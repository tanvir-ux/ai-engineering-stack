"""A local mock OpenID Connect provider for development, tests and the recorded demo.

It implements the parts of OIDC the app needs: discovery, JWKS, the authorization-code flow with
PKCE (S256) and RS256 access tokens. Users are fixed demo personas. It exists so the *relying
party* code (token verification, RBAC, tool permissions) is the real thing; point
`AISTACK_OIDC_ISSUER` at Auth0, Entra ID, Keycloak or Cognito and the same verifier works there.

This is a stand-in for a development environment. It is not an identity provider you should
expose to the internet: personas need no password.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse


def _persona(handle: str, name: str, *roles: str) -> dict[str, Any]:
    return {"email": f"{handle}@meridian.example", "name": name, "roles": list(roles)}


PERSONAS: dict[str, dict[str, Any]] = {
    "alice": _persona("alice.nguyen", "Alice Nguyen", "employee"),
    "bob": _persona("bob.fischer", "Bob Fischer", "employee", "hr"),
    "carol": _persona("carol.silva", "Carol Silva", "employee", "finance"),
    "dave": _persona("dave.okafor", "Dave Okafor", "employee", "security"),
    "eve": _persona("eve.contractor", "Eve (contractor)", "contractor"),
    "farid": _persona("farid.rahman", "Farid Rahman", "admin"),
    "hugo": _persona("hugo.martin", "Hugo Martin", "employee"),
}


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64u(hashlib.sha256(verifier.encode()).digest())


@dataclass
class _Code:
    persona: str
    client_id: str
    redirect_uri: str
    challenge: str
    nonce: str
    expires: float


class MockIdP:
    def __init__(
        self,
        issuer: str,
        audience: str,
        client_id: str = "aistack-web",
        redirect_prefixes: list[str] | None = None,
        token_ttl: int = 3600,
        key_file: str | Path | None = None,
    ) -> None:
        self.issuer, self.audience, self.client_id = issuer.rstrip("/"), audience, client_id
        self.redirect_prefixes = redirect_prefixes or ["http://localhost", "http://127.0.0.1"]
        self.token_ttl = token_ttl
        self._key = self._load_or_create_key(key_file)
        der = self._key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.kid = hashlib.sha256(der).hexdigest()[:12]
        self._codes: dict[str, _Code] = {}

    @staticmethod
    def _load_or_create_key(key_file: str | Path | None) -> rsa.RSAPrivateKey:
        """Optionally persist the dev signing key so restarts keep issued tokens valid."""
        path = Path(key_file) if key_file else None
        if path is not None and path.exists():
            loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(loaded, rsa.RSAPrivateKey):
                raise ValueError("idp key file must hold an RSA private key")
            return loaded
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            pem = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(pem)
        return key

    # -- keys / tokens -------------------------------------------------------------------
    def jwks(self) -> dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def private_pem(self) -> bytes:
        return self._key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def issue_token(self, persona: str, *, ttl: int | None = None, nonce: str = "") -> str:
        p = PERSONAS[persona]
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": f"user:{persona}",
            "email": p["email"],
            "name": p["name"],
            "roles": p["roles"],
            "iat": now,
            "exp": now + (self.token_ttl if ttl is None else ttl),
            "jti": secrets.token_hex(8),
        }
        if nonce:
            claims["nonce"] = nonce
        return jwt.encode(claims, self.private_pem(), algorithm="RS256", headers={"kid": self.kid})

    # -- authorization-code flow ---------------------------------------------------------
    def redirect_allowed(self, uri: str) -> bool:
        return any(uri.startswith(p) for p in self.redirect_prefixes)

    def create_code(
        self, persona: str, client_id: str, redirect_uri: str, challenge: str, nonce: str = ""
    ) -> str:
        code = secrets.token_urlsafe(24)
        self._codes[code] = _Code(
            persona, client_id, redirect_uri, challenge, nonce, time.time() + 300
        )
        return code

    def redeem(self, code: str, verifier: str, client_id: str, redirect_uri: str) -> dict[str, Any]:
        entry = self._codes.pop(code, None)  # single use
        if entry is None or entry.expires < time.time():
            raise ValueError("invalid_grant")
        if entry.client_id != client_id or entry.redirect_uri != redirect_uri:
            raise ValueError("invalid_grant")
        if not secrets.compare_digest(pkce_challenge(verifier), entry.challenge):
            raise ValueError("invalid_grant")
        token = self.issue_token(entry.persona, nonce=entry.nonce)
        return {"access_token": token, "token_type": "Bearer", "expires_in": self.token_ttl}


def build_router(idp: MockIdP) -> APIRouter:
    r = APIRouter(tags=["mock-idp"])

    @r.get("/.well-known/openid-configuration")
    def discovery() -> dict[str, Any]:
        base = idp.issuer
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    @r.get("/jwks.json")
    def jwks() -> dict[str, Any]:
        return idp.jwks()

    @r.get("/personas")
    def personas() -> list[dict[str, Any]]:
        return [{"id": k, **v} for k, v in PERSONAS.items()]

    @r.get("/authorize", response_model=None)
    def authorize(
        response_type: str = Query(...),
        client_id: str = Query(...),
        redirect_uri: str = Query(...),
        code_challenge: str = Query(...),
        code_challenge_method: str = Query("S256"),
        state: str = Query(""),
        nonce: str = Query(""),
        login_hint: str = Query(""),
    ) -> RedirectResponse | HTMLResponse:
        if response_type != "code" or code_challenge_method != "S256":
            raise HTTPException(400, "unsupported_request")
        if client_id != idp.client_id or not idp.redirect_allowed(redirect_uri):
            raise HTTPException(400, "invalid_client_or_redirect_uri")
        if login_hint in PERSONAS:
            code = idp.create_code(login_hint, client_id, redirect_uri, code_challenge, nonce)
            sep = "&" if "?" in redirect_uri else "?"
            q = urllib.parse.urlencode({"code": code, "state": state})
            return RedirectResponse(f"{redirect_uri}{sep}{q}", status_code=302)
        links = "".join(
            f'<li><a href="?{
                urllib.parse.urlencode(
                    {
                        "response_type": response_type,
                        "client_id": client_id,
                        "redirect_uri": redirect_uri,
                        "code_challenge": code_challenge,
                        "code_challenge_method": "S256",
                        "state": state,
                        "nonce": nonce,
                        "login_hint": k,
                    }
                )
            }">{p["name"]}</a> ({", ".join(p["roles"])})</li>'
            for k, p in PERSONAS.items()
        )
        return HTMLResponse(
            f"<h1>Mock identity provider</h1><p>Pick a demo persona:</p><ul>{links}</ul>"
        )

    @r.post("/token")
    def token(
        grant_type: str = Form(...),
        code: str = Form(...),
        code_verifier: str = Form(...),
        client_id: str = Form(...),
        redirect_uri: str = Form(...),
    ) -> dict[str, Any]:
        if grant_type != "authorization_code":
            raise HTTPException(400, "unsupported_grant_type")
        try:
            return idp.redeem(code, code_verifier, client_id, redirect_uri)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return r
