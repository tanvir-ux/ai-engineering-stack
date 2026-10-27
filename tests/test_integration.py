"""Full-stack tests: gateway -> LangGraph -> MCP server (real HTTP) -> data layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aistack.auth.idp import MockIdP
from aistack.config import Settings
from aistack.gateway.app import create_app
from tests.conftest import AUDIENCE, ISSUER
from tests.test_gateway import parse_sse


def _key_file(idp: MockIdP, tmp_path: Path) -> Path:
    path = tmp_path / "idp.pem"
    path.write_bytes(idp.private_pem())
    path.chmod(0o600)
    return path


def _settings(idp: MockIdP, tmp_path: Path, mcp_url: str) -> Settings:
    return Settings(
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        tool_transport="mcp",
        mcp_url=mcp_url,
        idp_key_file=str(_key_file(idp, tmp_path)),
        checkpoint_db=str(tmp_path / "graph.sqlite"),
    )


def _bearer(client: TestClient, persona: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.app.state.runtime.idp.issue_token(persona)}"}  # type: ignore[attr-defined]


def test_key_file_gives_stable_signing_identity(idp: MockIdP, tmp_path: Path) -> None:
    again = MockIdP(ISSUER, AUDIENCE, key_file=_key_file(idp, tmp_path))
    assert again.kid == idp.kid and again.jwks() == idp.jwks()
    fresh = MockIdP(ISSUER, AUDIENCE, key_file=tmp_path / "new.pem")
    assert (tmp_path / "new.pem").stat().st_mode & 0o777 == 0o600
    assert fresh.kid != idp.kid


def test_chat_runs_through_the_real_mcp_server(idp: MockIdP, tmp_path: Path, mcp_url: str) -> None:
    with TestClient(create_app(_settings(idp, tmp_path, mcp_url))) as c:
        ev = parse_sse(
            c.post(
                "/chat",
                json={"message": "What salary range applies to Level 4?"},
                headers=_bearer(c, "bob"),
            ).text
        )
        assert "76,000" in "".join(e.get("text", "") for e in ev)
        ev = parse_sse(
            c.post(
                "/chat",
                json={"message": "What salary range applies to Level 4?"},
                headers=_bearer(c, "alice"),
            ).text
        )
        assert "76,000" not in "".join(e.get("text", "") for e in ev)


def test_paused_run_survives_a_restart_and_keeps_token_out_of_the_db(
    idp: MockIdP, tmp_path: Path, mcp_url: str
) -> None:
    settings = _settings(idp, tmp_path, mcp_url)
    with TestClient(create_app(settings)) as c1:
        headers = _bearer(c1, "alice")
        token = headers["Authorization"].split()[1]
        ev = parse_sse(
            c1.post(
                "/chat",
                json={"message": "Create a ticket for a broken docking station P2"},
                headers=headers,
            ).text
        )
        assert ev[-1]["status"] == "awaiting_approval"
        thread_id = ev[0]["thread_id"]
    # the process "restarts": a brand-new app and a brand-new SQLite connection
    with TestClient(create_app(settings)) as c2:
        headers = _bearer(c2, "alice")
        state = c2.get(f"/threads/{thread_id}", headers=headers).json()
        assert state["waiting_for_approval"] is True
        ev2 = parse_sse(
            c2.post(
                "/approve", json={"thread_id": thread_id, "approved": True}, headers=headers
            ).text
        )
        text = "".join(e.get("text", "") for e in ev2)
        assert "INC-9001" in text and "P2" in text
        results: list[dict[str, Any]] = [e for e in ev2 if e["type"] == "tool_result"]
        assert json.dumps(results[0]["result"]).count("alice.nguyen@meridian.example") == 1
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("graph.sqlite*"))
    assert raw and token.encode() not in raw


def test_mcp_enforces_policy_even_if_the_gateway_were_bypassed(
    idp: MockIdP, tmp_path: Path, mcp_url: str
) -> None:
    # Hugo's per-user deny is enforced by the MCP server's own policy check.
    with TestClient(create_app(_settings(idp, tmp_path, mcp_url))) as c:
        ev = parse_sse(
            c.post(
                "/chat",
                json={"message": "Create a ticket for a monitor"},
                headers=_bearer(c, "hugo"),
            ).text
        )
        assert "denied" in [e["type"] for e in ev]
