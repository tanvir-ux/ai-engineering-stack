from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from aistack.agents.models import build_model
from aistack.agents.roles import Agents
from aistack.auth.policy import Principal
from aistack.config import Settings
from aistack.mcp_tools.service import KnowledgeService
from aistack.orchestration.graph import Credentials, Deps, build_graph
from aistack.orchestration.tools import LocalToolGateway

ALICE = Principal("user:alice", "alice.nguyen@meridian.example", "Alice", ("employee",))
HUGO = Principal("user:hugo", "hugo.martin@meridian.example", "Hugo", ("employee",))
EVE = Principal("user:eve", "eve.contractor@meridian.example", "Eve", ("contractor",))


@pytest.fixture
def graph(service: KnowledgeService) -> Any:
    agents = Agents(build_model(Settings(llm_mode="fake")))
    return build_graph(Deps(agents, LocalToolGateway(service)), MemorySaver())


def cfg(p: Principal, thread: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread, "auth": Credentials(p, "t")}}


async def run(graph: Any, inp: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for mode, chunk in graph.astream(inp, config, stream_mode=["custom", "updates"]):
        if mode == "custom":
            events.append(chunk)
        elif "__interrupt__" in chunk:
            events.append({"type": "interrupt", "value": chunk["__interrupt__"][0].value})
    return events


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


async def test_rag_answer_streams_and_cites(graph: Any) -> None:
    ev = await run(
        graph,
        {"question": "How many days of annual leave do I get?", "user_sub": ALICE.sub},
        cfg(ALICE, "t1"),
    )
    assert kinds(ev)[:2] == ["retrieved", "plan"]
    assert kinds(ev).count("token") > 5
    text = "".join(e["text"] for e in ev if e["type"] == "token")
    assert "24 days" in text and "hr-001" in text
    state = (await graph.aget_state(cfg(ALICE, "t1"))).values
    assert state["answer"] == text and state["citations"] == ["hr-001"]


async def test_acl_withholds_restricted_documents(graph: Any) -> None:
    ev = await run(
        graph,
        {"question": "What salary range applies to Level 4?", "user_sub": ALICE.sub},
        cfg(ALICE, "t2"),
    )
    text = "".join(e["text"] for e in ev if e["type"] == "token")
    assert "76,000" not in text and "could not find" in text


async def test_write_tool_pauses_for_approval_then_runs(graph: Any) -> None:
    c = cfg(ALICE, "t3")
    ev = await run(
        graph,
        {
            "question": "Please create a ticket for a broken docking station P2",
            "user_sub": ALICE.sub,
        },
        c,
    )
    assert kinds(ev)[-1] == "interrupt"
    assert ev[-1]["value"]["tool"] == "create_ticket"
    assert "tool_result" not in kinds(ev)  # nothing ran yet
    snap = await graph.aget_state(c)
    assert snap.next == ("approval",)
    ev2 = await run(graph, Command(resume={"approved": True}), c)
    assert "tool_result" in kinds(ev2)
    text = "".join(e["text"] for e in ev2 if e["type"] == "token")
    assert "INC-9001" in text


async def test_declined_approval_does_not_run_tool(graph: Any, service: KnowledgeService) -> None:
    c = cfg(ALICE, "t4")
    await run(graph, {"question": "Open a ticket for printer jam", "user_sub": ALICE.sub}, c)
    ev = await run(graph, Command(resume={"approved": False}), c)
    assert "tool_result" not in kinds(ev)
    assert service.created == []
    assert "declined" in "".join(e["text"] for e in ev if e["type"] == "token")


async def test_policy_denies_before_asking_for_approval(graph: Any) -> None:
    ev = await run(
        graph,
        {"question": "Create a ticket for a new monitor", "user_sub": HUGO.sub},
        cfg(HUGO, "t5"),
    )
    assert "denied" in kinds(ev) and "interrupt" not in kinds(ev)
    assert "permission denied" in "".join(e["text"] for e in ev if e["type"] == "token")


async def test_read_tool_runs_without_approval(graph: Any) -> None:
    ev = await run(
        graph,
        {"question": "What is the status of my open tickets?", "user_sub": ALICE.sub},
        cfg(ALICE, "t6"),
    )
    assert "interrupt" not in kinds(ev) and "tool_result" in kinds(ev)
    assert "INC-" in "".join(e["text"] for e in ev if e["type"] == "token")


async def test_contractor_cannot_list_tickets(graph: Any) -> None:
    ev = await run(graph, {"question": "Show my tickets", "user_sub": EVE.sub}, cfg(EVE, "t7"))
    assert "denied" in kinds(ev)


async def test_token_is_not_persisted_in_checkpoints(graph: Any) -> None:
    c = cfg(ALICE, "t8")
    c["configurable"]["auth"] = Credentials(ALICE, "SECRET-BEARER-VALUE")
    await run(
        graph, {"question": "How many days of annual leave do I get?", "user_sub": ALICE.sub}, c
    )
    snap = await graph.aget_state(c)
    assert "SECRET-BEARER-VALUE" not in repr(snap.values)
    assert "SECRET-BEARER-VALUE" not in repr(snap.metadata)
