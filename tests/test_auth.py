from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aistack.auth.idp import MockIdP, build_router, pkce_challenge
from aistack.auth.verifier import AuthError, JWTVerifier, bearer_token
from tests.conftest import AUDIENCE, ISSUER

VERIFIER = "v" * 50
REDIRECT = "http://localhost:5173/callback"


def _client(idp: MockIdP) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(idp), prefix="/idp")
    return TestClient(app, follow_redirects=False)


def test_discovery_and_jwks(idp: MockIdP) -> None:
    c = _client(idp)
    disc = c.get("/idp/.well-known/openid-configuration").json()
    assert disc["issuer"] == ISSUER
    assert "S256" in disc["code_challenge_methods_supported"]
    assert c.get("/idp/jwks.json").json()["keys"][0]["alg"] == "RS256"


def _login(c: TestClient, persona: str = "alice") -> str:
    r = c.get(
        "/idp/authorize",
        params={
            "response_type": "code",
            "client_id": "aistack-web",
            "redirect_uri": REDIRECT,
            "code_challenge": pkce_challenge(VERIFIER),
            "state": "xyz",
            "login_hint": persona,
        },
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(REDIRECT) and "state=xyz" in loc
    return loc.split("code=")[1].split("&")[0]


def _token(c: TestClient, code: str, verifier: str = VERIFIER) -> Any:
    return c.post(
        "/idp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "aistack-web",
            "redirect_uri": REDIRECT,
        },
    )


def test_full_pkce_flow_yields_verifiable_token(idp: MockIdP, verifier: JWTVerifier) -> None:
    c = _client(idp)
    r = _token(c, _login(c, "bob"))
    assert r.status_code == 200
    p = verifier.verify(r.json()["access_token"])
    assert p.email == "bob.fischer@meridian.example"
    assert p.roles == ("employee", "hr")
    assert "hr" in p.classes


def test_code_is_single_use(idp: MockIdP) -> None:
    c = _client(idp)
    code = _login(c)
    assert _token(c, code).status_code == 200
    assert _token(c, code).status_code == 400


def test_wrong_pkce_verifier_is_rejected(idp: MockIdP) -> None:
    c = _client(idp)
    assert _token(c, _login(c), verifier="w" * 50).status_code == 400


def test_open_redirect_is_rejected(idp: MockIdP) -> None:
    c = _client(idp)
    r = c.get(
        "/idp/authorize",
        params={
            "response_type": "code",
            "client_id": "aistack-web",
            "redirect_uri": "https://evil.example/cb",
            "code_challenge": "x",
            "login_hint": "alice",
        },
    )
    assert r.status_code == 400


def test_expired_token_rejected(idp: MockIdP, verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError, match="expired"):
        verifier.verify(idp.issue_token("alice", ttl=-60))


def test_wrong_audience_rejected(idp: MockIdP) -> None:
    other = JWTVerifier(ISSUER, "someone-else", idp.jwks)
    with pytest.raises(AuthError):
        other.verify(idp.issue_token("alice"))


def test_wrong_issuer_rejected(idp: MockIdP) -> None:
    other = JWTVerifier("http://evil.example/idp", AUDIENCE, idp.jwks)
    with pytest.raises(AuthError):
        other.verify(idp.issue_token("alice"))


def test_token_signed_by_another_key_rejected(idp: MockIdP, verifier: JWTVerifier) -> None:
    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "x",
            "iat": now,
            "exp": now + 60,
            "roles": ["admin"],
        },
        rogue,
        algorithm="RS256",
        headers={"kid": idp.kid},
    )
    with pytest.raises(AuthError):
        verifier.verify(forged)


def test_alg_none_and_hs256_rejected(verifier: JWTVerifier) -> None:
    none_tok = jwt.encode({"sub": "x"}, key="", algorithm="none")
    with pytest.raises(AuthError):
        verifier.verify(none_tok)
    hs = jwt.encode({"sub": "x"}, key="k" * 40, algorithm="HS256")
    with pytest.raises(AuthError):
        verifier.verify(hs)


def test_unknown_kid_rejected(idp: MockIdP, verifier: JWTVerifier) -> None:
    now = int(time.time())
    tok = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "iat": now, "exp": now + 60},
        idp.private_pem(),
        algorithm="RS256",
        headers={"kid": "nope"},
    )
    with pytest.raises(AuthError, match="unknown signing key"):
        verifier.verify(tok)


def test_jwks_failure_fails_closed(idp: MockIdP) -> None:
    def boom() -> dict[str, Any]:
        raise RuntimeError("down")

    with pytest.raises(AuthError):
        JWTVerifier(ISSUER, AUDIENCE, boom).verify(idp.issue_token("alice"))


def test_bearer_parsing() -> None:
    assert bearer_token("Bearer abc") == "abc"
    for bad in (None, "", "Basic abc", "Bearer "):
        with pytest.raises(AuthError):
            bearer_token(bad)
