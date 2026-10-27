from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from aistack.agents.fake_llm import answer_for, make_transport, plan_for
from aistack.agents.models import build_model
from aistack.agents.roles import Agents
from aistack.config import Settings


@pytest.fixture
def agents() -> Agents:
    return Agents(build_model(Settings(llm_mode="fake"), fake_delay=0.0))


def test_plan_rules() -> None:
    assert plan_for("Question: Please create a ticket for a broken docking station P2")["tool"] == (
        "create_ticket"
    )
    p = plan_for("Question: Open a ticket: VPN keeps dropping, priority P1")
    assert p["priority"] == "P1" and "P1" not in p["title"]
    assert plan_for("Question: show my tickets")["tool"] == "list_my_tickets"
    assert plan_for("Question: ticket stats for network")["tool"] == "ticket_stats"
    assert plan_for("Question: How many days of leave?")["action"] == "answer"


async def test_planner_returns_structured_output(agents: Agents) -> None:
    plan = await agents.plan("Create a ticket for a broken monitor P3", ["create_ticket"])
    assert plan.action == "tool" and plan.tool == "create_ticket" and plan.priority == "P3"
    assert plan.tool_args()["title"].startswith("Broken monitor")


async def test_streamed_answer_arrives_in_many_chunks(agents: Agents) -> None:
    ctx = [{"chunk_id": "hr-001#0", "text": "Employees receive 24 days of paid leave per year."}]
    prompt = agents.answer_prompt("How many days of leave do I get?", ctx, None, None)
    deltas = [d async for d in agents.stream_answer(prompt)]
    assert len(deltas) > 3 and "24 days" in "".join(deltas) and "[hr-001]" in "".join(deltas)


def test_answer_says_so_when_context_is_irrelevant() -> None:
    prompt = (
        "Question: What is the CEO's favourite colour?\n"
        "Context:\n[pub-001#0] The company operates 41 warehouses.\n"
    )
    assert "could not find" in answer_for(prompt)


def test_tool_error_is_reported_not_hidden() -> None:
    prompt = 'Question: x\nTool: create_ticket\nTool result: {"error": "permission denied"}'
    assert "permission denied" in answer_for(prompt)


async def test_fake_transport_makes_no_network_calls() -> None:
    async with httpx.AsyncClient(transport=make_transport(0.0)) as client:
        body = {
            "model": "m",
            "messages": [
                {"role": "system", "content": "ROLE:answerer"},
                {"role": "user", "content": "Question: hi"},
            ],
        }
        r = await client.post("http://fake-llm.invalid/v1/chat/completions", json=body)
    assert r.status_code == 200 and json.loads(r.text)["choices"][0]["message"]["content"]


def test_real_providers_demand_keys() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_model(Settings(llm_mode="openai", openai_api_key=""))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_model(Settings(llm_mode="gemini", gemini_api_key=""))


def test_real_provider_builds_with_a_key_without_calling_it() -> None:
    b = build_model(Settings(llm_mode="gemini", gemini_api_key="x"))
    assert b.mode == "gemini" and "gemini" in b.name
