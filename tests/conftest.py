from __future__ import annotations

import pytest

from aistack.auth.idp import MockIdP
from aistack.auth.verifier import JWTVerifier
from aistack.config import get_settings
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
