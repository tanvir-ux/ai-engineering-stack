from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastmcp.server.auth.providers.jwt import JWTVerifier as MCPJWTVerifier

from aistack.auth.idp import MockIdP
from aistack.auth.verifier import JWTVerifier
from aistack.config import get_settings
from aistack.mcp_tools.server import build_server
from aistack.mcp_tools.service import KnowledgeService

ISSUER = "http://testserver/idp"
AUDIENCE = "aistack-api"


@pytest.fixture(scope="session")
def idp() -> MockIdP:
    return MockIdP(ISSUER, AUDIENCE)


@pytest.fixture(scope="session")
def verifier(idp: MockIdP) -> JWTVerifier:
    return JWTVerifier(ISSUER, AUDIENCE, idp.jwks)


@pytest.fixture
def service() -> KnowledgeService:
    s = get_settings()
    return KnowledgeService.from_paths(s.gold_chunks_path, s.tickets_path)


@pytest.fixture
def mcp_url(idp: MockIdP, service: KnowledgeService) -> Iterator[str]:
    from cryptography.hazmat.primitives import serialization

    pub = idp._key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    auth = MCPJWTVerifier(public_key=pub.decode(), issuer=ISSUER, audience=AUDIENCE)
    server = build_server(service, auth=auth)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = server.http_app(transport="http")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    srv.should_exit = True
    th.join(timeout=5)
