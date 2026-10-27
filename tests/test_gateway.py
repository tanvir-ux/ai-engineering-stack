from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from aistack.config import Settings
from aistack.gateway.app import create_app
from aistack.gateway.ratelimit import RateLimiter
from aistack.mcp_tools.service import KnowledgeService


def parse_sse(text: str) -> list[dict[str, Any]]:
    out = []
    for block in text.strip().split("\n\n"):
        data = [ln[6:] for ln in block.splitlines() if ln.startswith("data: ")]
        if data:
            out.append(json.loads(data[0]))
    return out


def make_client(limit: int = 100) -> Iterator[TestClient]:
    settings = Settings(
        oidc_issuer="http://testserver/idp", tool_transport="local", rate_limit_per_minute=limit
    )
    app = create_app(settings, checkpointer=MemorySaver())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from make_client()


def auth(client: TestClient, persona: str) -> dict[str, str]:
    idp = client.app.state.runtime.idp  # type: ignore[attr-defined]
    return {"Authorization": f"Bearer {idp.issue_token(persona)}"}


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["ready"] is True


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/me").status_code == 401
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    r = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_me_reflects_roles(client: TestClient) -> None:
    me = client.get("/me", headers=auth(client, "bob")).json()
    assert "hr" in me["document_classes"] and "ticket_stats" not in me["tools"]
    eve = client.get("/me", headers=auth(client, "eve")).json()
    assert eve["document_classes"] == ["public"] and eve["tools"] == [
        "get_document",
        "search_documents",
    ]


def test_request_id_and_trace_headers(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "req-12345678"})
    assert r.headers["x-request-id"] == "req-12345678"
    r2 = client.get("/health", headers={"X-Request-ID": "bad id!"})
    assert r2.headers["x-request-id"] != "bad id!"
    assert len(r.headers["x-trace-id"]) == 32


def test_traceparent_is_continued(client: TestClient) -> None:
    tid = "4bf92f3577b34da6a3ce929d0e0e4736"
    r = client.get("/health", headers={"traceparent": f"00-{tid}-00f067aa0ba902b7-01"})
    assert r.headers["x-trace-id"] == tid


def test_chat_streams_events(client: TestClient) -> None:
    r = client.post(
        "/chat",
        json={"message": "How many days of annual leave do I get?"},
        headers=auth(client, "alice"),
    )
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = parse_sse(r.text)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "start" and kinds[-1] == "done" and "token" in kinds
    assert ev[-1]["status"] == "completed"
    assert "24 days" in "".join(e.get("text", "") for e in ev)


def test_approval_flow_end_to_end(client: TestClient) -> None:
    h = auth(client, "alice")
    ev = parse_sse(
        client.post(
            "/chat", json={"message": "Create a ticket for a broken monitor P3"}, headers=h
        ).text
    )
    assert ev[-1] == {"type": "done", "status": "awaiting_approval"}
    tid = ev[0]["thread_id"]
    assert any(e["type"] == "approval_required" for e in ev)
    assert client.get(f"/threads/{tid}", headers=h).json()["waiting_for_approval"] is True
    ev2 = parse_sse(
        client.post("/approve", json={"thread_id": tid, "approved": True}, headers=h).text
    )
    assert "INC-9001" in "".join(e.get("text", "") for e in ev2)
    assert ev2[-1]["status"] == "completed"
    # a finished thread cannot be approved again
    again = client.post("/approve", json={"thread_id": tid, "approved": True}, headers=h)
    assert again.status_code == 409


def test_other_users_cannot_see_or_approve_my_thread(client: TestClient) -> None:
    ev = parse_sse(
        client.post(
            "/chat",
            json={"message": "Create a ticket for a broken monitor"},
            headers=auth(client, "alice"),
        ).text
    )
    tid = ev[0]["thread_id"]
    mallory = auth(client, "carol")
    assert client.get(f"/threads/{tid}", headers=mallory).status_code == 404
    r = client.post("/approve", json={"thread_id": tid, "approved": True}, headers=mallory)
    assert r.status_code == 404
    assert client.get(f"/threads/{tid}", headers=auth(client, "alice")).json()[
        "waiting_for_approval"
    ]


def test_denied_tool_never_asks_for_approval(client: TestClient) -> None:
    ev = parse_sse(
        client.post(
            "/chat", json={"message": "Create a ticket for a monitor"}, headers=auth(client, "hugo")
        ).text
    )
    kinds = [e["type"] for e in ev]
    assert "denied" in kinds and "approval_required" not in kinds


def test_validation(client: TestClient) -> None:
    h = auth(client, "alice")
    assert client.post("/chat", json={"message": ""}, headers=h).status_code == 422
    assert client.post("/chat", json={"message": "x" * 3000}, headers=h).status_code == 422


def test_rate_limit_is_per_user() -> None:
    for c in make_client(limit=3):
        h = auth(c, "alice")
        codes = [c.get("/me", headers=h).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        assert c.get("/me", headers=h).headers["retry-after"].isdigit()
        assert c.get("/me", headers=auth(c, "bob")).status_code == 200


def test_rate_limiter_window() -> None:
    rl = RateLimiter(2, 10)
    assert rl.check("k", 0) == 0 and rl.check("k", 1) == 0
    assert rl.check("k", 2) > 0
    assert rl.check("k", 10.5) == 0


def test_oidc_discovery_served_by_gateway(client: TestClient) -> None:
    d = client.get("/idp/.well-known/openid-configuration").json()
    assert d["jwks_uri"].endswith("/idp/jwks.json")


def test_service_is_real(client: TestClient) -> None:
    assert isinstance(client.app.state.runtime.tools.service, KnowledgeService)  # type: ignore[attr-defined]
