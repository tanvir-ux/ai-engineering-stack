"""LangGraph workflow: retrieve -> plan -> (approval) -> tool -> answer.

    START -> retrieve -> plan -+-> answer -> END
                               |
                               +-> tool_gate -+-> approval (interrupt) -+-> tool_exec -> answer
                                              +-> tool_exec (read-only) |
                                              +-> answer (denied) <-----+ (declined)

* State is checkpointed (SQLite by default) after every node, so a paused run survives a restart.
* Write tools stop at `approval` using LangGraph's `interrupt`; the run resumes with
  `Command(resume={"approved": bool})`.
* Bearer tokens are never written into state. They travel in the per-invocation config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from aistack.agents.roles import Agents
from aistack.auth.policy import TOOL_PERMISSION, WRITE_TOOLS, Principal, can_use_tool
from aistack.observability.tracing import traced
from aistack.orchestration.tools import ToolError_, ToolGateway


class State(TypedDict, total=False):
    question: str
    user_sub: str
    context: list[dict[str, Any]]
    plan: dict[str, Any]
    tool: str | None
    tool_args: dict[str, Any]
    tool_result: Any
    approved: bool | None
    answer: str
    citations: list[str]


class Deps:
    def __init__(self, agents: Agents, tools: ToolGateway) -> None:
        self.agents = agents
        self.tools = tools


@dataclass(frozen=True)
class Credentials:
    """The caller's identity for one invocation.

    Passed through `config["configurable"]["auth"]`. LangGraph copies plain string values from
    `configurable` into checkpoint metadata, so the bearer token is deliberately wrapped in an
    object (and hidden from `repr`) to keep it out of persisted state.
    """

    principal: Principal
    token: str = field(repr=False)


def _who(config: RunnableConfig) -> tuple[Principal, str]:
    auth: Credentials = config["configurable"]["auth"]
    return auth.principal, auth.token


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    async def retrieve(state: State, config: RunnableConfig) -> State:
        principal, token = _who(config)
        writer = get_stream_writer()
        with traced("node.retrieve", user=principal.sub):
            try:
                hits = await deps.tools.call(
                    principal, token, "search_documents", {"query": state["question"], "k": 4}
                )
            except ToolError_ as exc:
                hits = []
                writer({"type": "warning", "message": f"retrieval failed: {exc}"})
        writer(
            {
                "type": "retrieved",
                "chunks": [
                    {
                        "chunk_id": h["chunk_id"],
                        "title": h["title"],
                        "classification": h["classification"],
                        "score": h["score"],
                    }
                    for h in hits
                ],
            }
        )
        return {"context": hits}

    async def plan(state: State, config: RunnableConfig) -> State:
        principal, _ = _who(config)
        writer = get_stream_writer()
        with traced("node.plan", user=principal.sub):
            available = sorted(t for t in TOOL_PERMISSION if can_use_tool(principal, t))
            p = await deps.agents.plan(state["question"], available)
        writer(
            {
                "type": "plan",
                "action": p.action,
                "tool": p.tool,
                "reason": p.reason,
                "arguments": p.tool_args(),
            }
        )
        return {
            "plan": p.model_dump(),
            "tool": p.tool,
            "tool_args": p.tool_args(),
            "approved": None,
        }

    def after_plan(state: State) -> Literal["tool_gate", "answer"]:
        return "tool_gate" if state.get("tool") else "answer"

    async def tool_gate(state: State, config: RunnableConfig) -> State:
        principal, _ = _who(config)
        writer = get_stream_writer()
        tool = state["tool"] or ""
        if not can_use_tool(principal, tool):
            msg = f"{principal.email} is not permitted to use {tool}"
            writer({"type": "denied", "tool": tool, "message": msg})
            return {"tool_result": {"error": f"permission denied: {msg}"}}
        return {}

    def after_gate(state: State) -> Literal["approval", "tool_exec", "answer"]:
        if state.get("tool_result"):
            return "answer"
        return "approval" if state["tool"] in WRITE_TOOLS else "tool_exec"

    async def approval(state: State) -> State:
        decision = interrupt(
            {
                "type": "approval_required",
                "tool": state["tool"],
                "arguments": state["tool_args"],
                "message": f"The assistant wants to run {state['tool']} with "
                f"{state['tool_args']}. Approve?",
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else False
        get_stream_writer()({"type": "approval", "approved": approved})
        return {"approved": approved, "tool_result": None if approved else {"rejected": True}}

    def after_approval(state: State) -> Literal["tool_exec", "answer"]:
        return "tool_exec" if state.get("approved") else "answer"

    async def tool_exec(state: State, config: RunnableConfig) -> State:
        principal, token = _who(config)
        writer = get_stream_writer()
        tool = state["tool"] or ""
        with traced("node.tool", user=principal.sub, tool=tool):
            try:
                result = await deps.tools.call(principal, token, tool, state["tool_args"])
            except ToolError_ as exc:
                result = {"error": str(exc)}
        writer({"type": "tool_result", "tool": tool, "result": result})
        return {"tool_result": result}

    async def answer(state: State, config: RunnableConfig) -> State:
        principal, _ = _who(config)
        writer = get_stream_writer()
        prompt = deps.agents.answer_prompt(
            state["question"],
            state.get("context", []),
            state.get("tool"),
            state.get("tool_result"),
        )
        parts: list[str] = []
        with traced("node.answer", user=principal.sub, model=deps.agents.bundle.name):
            async for delta in deps.agents.stream_answer(prompt):
                parts.append(delta)
                writer({"type": "token", "text": delta})
        text = "".join(parts)
        cites = sorted({c["doc_id"] for c in state.get("context", []) if c["doc_id"] in text})
        return {"answer": text, "citations": cites}

    g = StateGraph(State)
    for name, fn in [
        ("retrieve", retrieve),
        ("plan", plan),
        ("tool_gate", tool_gate),
        ("approval", approval),
        ("tool_exec", tool_exec),
        ("answer", answer),
    ]:
        g.add_node(name, fn)  # type: ignore[call-overload]
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "plan")
    g.add_conditional_edges("plan", after_plan)
    g.add_conditional_edges("tool_gate", after_gate)
    g.add_conditional_edges("approval", after_approval)
    g.add_edge("tool_exec", "answer")
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer)
