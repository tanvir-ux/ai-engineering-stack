"""JWT verification for the resource servers (API gateway and MCP server).

Standards-based: RS256 only, signature checked against the issuer's JWKS, `iss`, `aud`, `exp`
and `sub` all required. Works with the bundled mock IdP and with any real OIDC provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from aistack.auth.policy import Principal


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired or not acceptable."""


JWKSSource = Callable[[], dict[str, Any]]


def http_jwks_source(url: str, timeout: float = 5.0) -> JWKSSource:
    def fetch() -> dict[str, Any]:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    return fetch


class JWTVerifier:
    def __init__(
        self, issuer: str, audience: str, jwks_source: JWKSSource, cache_seconds: int = 300
    ) -> None:
        self.issuer, self.audience = issuer.rstrip("/"), audience
        self._source = jwks_source
        self._cache_seconds = cache_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched = 0.0

    def _refresh(self) -> None:
        try:
            jwks = self._source()
        except Exception as exc:  # network or parse failure: fail closed
            raise AuthError("could not fetch signing keys") from exc
        self._keys = {k["kid"]: jwt.PyJWK(k) for k in jwks.get("keys", []) if "kid" in k}
        self._fetched = time.time()

    def _key_for(self, kid: str) -> jwt.PyJWK:
        if kid not in self._keys or time.time() - self._fetched > self._cache_seconds:
            self._refresh()
        if kid not in self._keys:
            raise AuthError("unknown signing key")
        return self._keys[kid]

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise AuthError("unsupported algorithm")
            key = self._key_for(str(header.get("kid", "")))
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=5,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid token") from exc
        roles = claims.get("roles", [])
        if not isinstance(roles, list):
            raise AuthError("invalid roles claim")
        return Principal(
            sub=str(claims["sub"]),
            email=str(claims.get("email", "")).lower(),
            name=str(claims.get("name", "")),
            roles=tuple(str(r) for r in roles),
        )


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing Authorization header")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise AuthError("expected a Bearer token")
    return value.strip()
