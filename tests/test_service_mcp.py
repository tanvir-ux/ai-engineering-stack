from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier as MCPJWTVerifier

from aistack.auth.idp import MockIdP
from aistack.auth.policy import Principal
from aistack.mcp_tools.server import build_server
from aistack.mcp_tools.service import KnowledgeService, NotFound, PermissionDenied
from tests.conftest import AUDIENCE, ISSUER

ALICE = Principal("a", "alice.nguyen@meridian.example", "Alice", ("employee",))
BOB = Principal("b", "bob.fischer@meridian.example", "Bob", ("employee", "hr"))
EVE = Principal("e", "eve.contractor@meridian.example", "Eve", ("contractor",))
HUGO = Principal("h", "hugo.martin@meridian.example", "Hugo", ("employee",))
FARID = Principal("f", "farid.rahman@meridian.example", "Farid", ("admin",))


def test_search_respects_classes(service: KnowledgeService) -> None:
    alice = service.search_documents(ALICE, "salary bands level 4")
    assert "hr-004" not in {h["doc_id"] for h in alice}
    bob = service.search_documents(BOB, "salary bands level 4")
    assert bob[0]["doc_id"] == "hr-004"


def test_get_document_hides_existence(service: KnowledgeService) -> None:
    assert service.get_document(ALICE, "hr-001")["classification"] == "internal"
    with pytest.raises(NotFound):
        service.get_document(ALICE, "hr-004")
    with pytest.raises(NotFound):
        service.get_document(ALICE, "does-not-exist")


def test_tickets_are_scoped_to_the_caller(service: KnowledgeService) -> None:
    mine = service.list_my_tickets(ALICE)
    assert mine and len(mine) <= 10
    assert all(t["ticket_id"].startswith("INC-") for t in mine)
    with pytest.raises(PermissionDenied):
        service.list_my_tickets(EVE)


def test_stats_need_permission(service: KnowledgeService) -> None:
    with pytest.raises(PermissionDenied):
        service.ticket_stats(ALICE)
    stats = service.ticket_stats(FARID, "network")
    assert stats["category"] == "network" and stats["tickets"] > 0


def test_create_ticket_rules(service: KnowledgeService) -> None:
    t = service.create_ticket(ALICE, "Docking station not charging", "P3")
    assert t["ticket_id"] == "INC-9001" and t["requester"] == ALICE.email
    assert any(x["ticket_id"] == "INC-9001" for x in service.list_my_tickets(ALICE))
    with pytest.raises(PermissionDenied):
        service.create_ticket(HUGO, "Per-user override denies this")
    with pytest.raises(PermissionDenied):
        service.create_ticket(EVE, "contractors are read-only")
    with pytest.raises(ValueError):
        service.create_ticket(ALICE, "ok title", "P9")
    with pytest.raises(ValueError):
        service.create_ticket(ALICE, "x")


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


async def _call(url: str, token: str | None, tool: str, args: dict[str, Any]) -> Any:
    async with Client(url, auth=token) as c:
        res = await c.call_tool(tool, args)
        return res.data


async def test_mcp_requires_a_token(mcp_url: str) -> None:
    r = httpx.post(mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, timeout=5)
    assert r.status_code == 401


async def test_mcp_lists_tools_and_enforces_identity(mcp_url: str, idp: MockIdP) -> None:
    async with Client(mcp_url, auth=idp.issue_token("alice")) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {
        "search_documents",
        "get_document",
        "list_my_tickets",
        "ticket_stats",
        "create_ticket",
    }
    rows = await _call(
        mcp_url,
        idp.issue_token("bob"),
        "search_documents",
        {"query": "salary bands level 4", "k": 2},
    )
    assert rows[0]["doc_id"] == "hr-004"
    rows = await _call(
        mcp_url,
        idp.issue_token("alice"),
        "search_documents",
        {"query": "salary bands level 4", "k": 3},
    )
    assert "hr-004" not in {r["doc_id"] for r in rows}


async def test_mcp_permission_denied_is_a_tool_error(mcp_url: str, idp: MockIdP) -> None:
    with pytest.raises(ToolError, match="permission denied"):
        await _call(
            mcp_url, idp.issue_token("hugo"), "create_ticket", {"title": "blocked by policy"}
        )
    with pytest.raises(ToolError):
        await _call(mcp_url, idp.issue_token("alice"), "ticket_stats", {})


async def test_mcp_rejects_expired_token(mcp_url: str, idp: MockIdP) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        await _call(mcp_url, idp.issue_token("alice", ttl=-60), "search_documents", {"query": "x"})
