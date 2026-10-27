"""A deterministic, OpenAI-compatible fake model served through `httpx.MockTransport`.

The agents layer talks to a normal `AsyncOpenAI` client. In CI and in the recorded demo that
client's HTTP transport is this fake, so the *same* Agents SDK code path runs (request building,
JSON-schema structured output, SSE streaming) with no network, no API key and fully reproducible
output. It is rule-based: it plans from keywords and answers by extracting the best-matching
sentences from the retrieved context. It is a test double, not a language model, and the
README says so. Real providers plug in through `AISTACK_LLM_MODE` (see `models.py`).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx

from aistack.retrieval.embedding import tokenize

CREATE_RE = re.compile(r"\b(create|open|raise|file|log|submit)\b.*\bticket\b", re.I)
MY_TICKETS_RE = re.compile(r"\b(my|own)\b.*\btickets?\b|\bstatus of my\b", re.I)
STATS_RE = re.compile(
    r"\b(ticket (stats|statistics)|how many tickets|average resolution|"
    r"resolution time|ticket volume)\b",
    re.I,
)
CATEGORIES = ("access", "hardware", "network", "software")


def _section(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*?)(?=^\w[\w ]*:\s|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def plan_for(user_text: str) -> dict[str, Any]:
    q = _section(user_text, "Question")
    plan: dict[str, Any] = {
        "action": "answer",
        "tool": None,
        "title": None,
        "priority": None,
        "category": None,
        "status": None,
        "reason": "The question can be answered from documents.",
    }
    if CREATE_RE.search(q):
        title = re.sub(
            r"(?i)^(please\s+)?(can you\s+)?(create|open|raise|file|log|submit)\s+"
            r"(an?\s+)?(it\s+)?ticket\s*(for|about|to say|saying|:)?\s*",
            "",
            q,
        ).strip(" .?")
        prio = re.search(r"\bP([1-4])\b", q)
        title = re.sub(r"\s*\bP[1-4]\b\s*", " ", title).strip()
        plan.update(
            action="tool",
            tool="create_ticket",
            title=title or "IT request",
            priority=f"P{prio.group(1)}" if prio else "P3",
            reason="The user asked to create a ticket, which changes state.",
        )
    elif STATS_RE.search(q):
        cat = next((c for c in CATEGORIES if c in q.lower()), None)
        plan.update(
            action="tool",
            tool="ticket_stats",
            category=cat,
            reason="The user asked for ticket statistics.",
        )
    elif MY_TICKETS_RE.search(q):
        status = next((s for s in ("open", "closed", "resolved") if s in q.lower()), None)
        plan.update(
            action="tool",
            tool="list_my_tickets",
            status=status,
            reason="The user asked about their own tickets.",
        )
    return plan


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _relevant(question: str, entries: list[tuple[str, str]]) -> bool:
    """True if at least one context sentence shares a meaningful share of the question terms."""
    qtok = set(tokenize(question))
    if not qtok:
        return False
    best = max(
        (len(qtok & set(tokenize(s))) / len(qtok) for _, t in entries for s in _sentences(t)),
        default=0.0,
    )
    return best >= 0.25


def answer_for(user_text: str) -> str:
    q = _section(user_text, "Question")
    context = _section(user_text, "Context")
    tool_name = _section(user_text, "Tool")
    tool_raw = _section(user_text, "Tool result")
    if tool_name and tool_raw:
        return _answer_from_tool(tool_name, tool_raw)
    entries = re.findall(r"^\[([\w-]+)#?\d*\]\s*(.+)$", context, re.M)
    if not entries or not _relevant(q, entries[:3]):
        return (
            "I could not find anything about that in the documents you have access to. "
            "If you expect it to exist, ask the document owner for access."
        )
    qtok = set(tokenize(q))
    scored: list[tuple[float, str, str]] = []
    for doc_id, text in entries[:3]:
        for s in _sentences(text):
            overlap = len(qtok & set(tokenize(s)))
            scored.append((overlap / (len(qtok) or 1), doc_id, s))
    scored.sort(key=lambda t: -t[0])
    best = scored[0]
    picked = [best]
    for cand in scored[1:]:
        if cand[1] == best[1] and cand[0] >= max(0.3, best[0] * 0.6) and len(picked) < 2:
            picked.append(cand)
    cites = ", ".join(dict.fromkeys(f"[{p[1]}]" for p in picked))
    return " ".join(p[2] for p in picked) + f" Sources: {cites}"


def _answer_from_tool(name: str, raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return f"The {name} tool returned: {raw}"
    if isinstance(data, dict) and data.get("error"):
        return f"I could not complete that: {data['error']}."
    if isinstance(data, dict) and data.get("rejected"):
        return "Understood. I did not create the ticket because the approval was declined."
    if name == "create_ticket":
        return (
            f"Done. I created ticket {data['ticket_id']} ({data['priority']}): "
            f"{data['summary']}. Status: {data['status']}."
        )
    if name == "list_my_tickets":
        if not data:
            return "You have no matching tickets."
        items = "; ".join(
            f"{t['ticket_id']} ({t['status']}, {t['priority']}): {t['summary']}" for t in data[:5]
        )
        return f"You have {len(data)} recent ticket(s): {items}."
    if name == "ticket_stats":
        avg = data.get("avg_resolution_hours")
        pri = ", ".join(f"{k}: {v}" for k, v in data.get("by_priority", {}).items())
        return (
            f"For {data['category']} tickets there are {data['tickets']} in total, "
            f"{data['open_tickets']} still open, with an average resolution time of "
            f"{avg} hours. By priority: {pri}."
        )
    return f"Tool {name} returned {raw}"


def _completion(model: str, content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _chunk(model: str, delta: dict[str, Any], finish: str | None) -> bytes:
    body = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n".encode()


async def _sse(model: str, content: str, delay: float) -> AsyncIterator[bytes]:
    yield _chunk(model, {"role": "assistant", "content": ""}, None)
    for piece in re.findall(r"\S+\s*", content):
        if delay:
            await asyncio.sleep(delay)
        yield _chunk(model, {"content": piece}, None)
    yield _chunk(model, {}, "stop")
    yield b"data: [DONE]\n\n"


def make_transport(delay: float = 0.0) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body.get("model", "fake-model")
        messages = body.get("messages", [])
        system = next((m["content"] for m in messages if m["role"] in ("system", "developer")), "")
        system = system if isinstance(system, str) else json.dumps(system)
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        user = user if isinstance(user, str) else json.dumps(user)
        if "ROLE:planner" in system:
            content = json.dumps(plan_for(user))
        elif "ROLE:answerer" in system:
            content = answer_for(user)
        else:
            content = "Fake model: unknown role."
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(model, content, delay),
            )
        return httpx.Response(200, json=_completion(model, content))

    return httpx.MockTransport(handler)
