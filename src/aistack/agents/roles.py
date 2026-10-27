"""The two agents, built on the OpenAI Agents SDK: a planner and an answerer."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from agents import Agent, ModelSettings, Runner
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel

from aistack.agents.models import ModelBundle

ToolName = Literal[
    "search_documents", "get_document", "list_my_tickets", "ticket_stats", "create_ticket"
]

PLANNER_INSTRUCTIONS = (
    "ROLE:planner\n"
    "You decide whether answering needs a tool. Documents are already retrieved. Use a tool only "
    "when the user asks about their tickets, ticket statistics, or asks to create a ticket. "
    "Reply with the structured plan."
)
ANSWER_INSTRUCTIONS = (
    "ROLE:answerer\n"
    "Answer the question using only the retrieved context or the tool result. Be concise. Cite "
    "document ids in square brackets. If the context does not contain the answer, say so."
)


class Plan(BaseModel):
    action: Literal["answer", "tool"]
    tool: ToolName | None = None
    title: str | None = None
    priority: str | None = None
    category: str | None = None
    status: str | None = None
    reason: str = ""

    def tool_args(self) -> dict[str, Any]:
        if self.tool == "create_ticket":
            return {"title": self.title or "IT request", "priority": self.priority or "P3"}
        if self.tool == "ticket_stats":
            return {"category": self.category} if self.category else {}
        if self.tool == "list_my_tickets":
            return {"status": self.status} if self.status else {}
        return {}


class Agents:
    def __init__(self, bundle: ModelBundle) -> None:
        self.bundle = bundle
        self.planner: Agent[Any] = Agent(
            name="planner",
            instructions=PLANNER_INSTRUCTIONS,
            model=bundle.model,
            output_type=Plan,
            model_settings=ModelSettings(temperature=0),
        )
        self.answerer: Agent[Any] = Agent(
            name="answerer",
            instructions=ANSWER_INSTRUCTIONS,
            model=bundle.model,
            model_settings=ModelSettings(temperature=0),
        )

    async def plan(self, question: str, available_tools: list[str]) -> Plan:
        prompt = f"Question: {question}\nAvailable tools: {', '.join(available_tools)}\n"
        result = await Runner.run(self.planner, prompt)
        out = result.final_output
        return out if isinstance(out, Plan) else Plan.model_validate(out)

    @staticmethod
    def answer_prompt(
        question: str, context: list[dict[str, Any]], tool: str | None, tool_result: Any
    ) -> str:
        ctx = "\n".join(f"[{c['chunk_id']}] {c['text']}" for c in context)
        prompt = f"Question: {question}\nContext:\n{ctx}\n"
        if tool:
            prompt += f"Tool: {tool}\nTool result: {json.dumps(tool_result, default=str)}\n"
        return prompt

    async def stream_answer(self, prompt: str) -> AsyncIterator[str]:
        run = Runner.run_streamed(self.answerer, prompt)
        async for event in run.stream_events():
            if event.type == "raw_response_event" and isinstance(
                event.data, ResponseTextDeltaEvent
            ):
                yield event.data.delta
