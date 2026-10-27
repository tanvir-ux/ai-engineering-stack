"""End-to-end evaluation: golden question -> full LangGraph workflow -> streamed answer.

    python -m aistack.eval.agent_eval                       # deterministic fake model (CI)
    AISTACK_LLM_MODE=gemini GEMINI_API_KEY=... python -m aistack.eval.agent_eval   # real model

With the default fake model the "answerer" is an extractive heuristic, so this measures the whole
pipeline (retrieval, access control, routing, streaming, citation plumbing) and NOT the quality of
a language model. Run it with a real provider key to measure one.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from aistack.agents.models import build_model
from aistack.agents.roles import Agents
from aistack.auth.idp import PERSONAS
from aistack.auth.policy import Principal
from aistack.config import REPO_ROOT, Settings, get_settings
from aistack.eval.rag_eval import load_golden
from aistack.mcp_tools.service import KnowledgeService
from aistack.orchestration.graph import Credentials, Deps, build_graph
from aistack.orchestration.tools import LocalToolGateway

ROLE_PERSONA = {
    "employee": "alice",
    "hr": "bob",
    "finance": "carol",
    "security": "dave",
    "contractor": "eve",
}


def principal(handle: str) -> Principal:
    p = PERSONAS[handle]
    return Principal(f"user:{handle}", p["email"], p["name"], tuple(p["roles"]))


async def evaluate(settings: Settings, golden: list[dict[str, Any]]) -> dict[str, Any]:
    svc = KnowledgeService.from_paths(settings.gold_chunks_path, settings.tickets_path)
    bundle = build_model(settings, fake_delay=0.0)
    graph = build_graph(Deps(Agents(bundle), LocalToolGateway(svc)), MemorySaver())
    correct = cited = 0
    lat: list[float] = []
    failures: list[dict[str, Any]] = []
    for i, q in enumerate(golden):
        p = principal(ROLE_PERSONA[q["role"]])
        cfg = {"configurable": {"thread_id": f"eval-{i}", "auth": Credentials(p, "eval")}}
        t0 = time.perf_counter()
        out = await graph.ainvoke({"question": q["question"], "user_sub": p.sub}, cfg)
        lat.append((time.perf_counter() - t0) * 1000)
        text = out["answer"].lower()
        ok = all(a.lower() in text for a in q["answer_contains"])
        cite = any(d in out.get("citations", []) for d in q["relevant_docs"])
        correct += ok
        cited += cite
        if not (ok and cite):
            failures.append({"id": q["id"], "question": q["question"], "answer": out["answer"]})
    lat.sort()
    n = len(golden)
    return {
        "model": bundle.name,
        "mode": bundle.mode,
        "questions": n,
        "answer_contains_all": round(correct / n, 3),
        "cites_relevant_doc": round(cited / n, 3),
        "p50_latency_ms": round(lat[n // 2], 1),
        "failures": failures,
    }


def render(report: dict[str, Any]) -> str:
    fails = "\n".join(f"- `{f['id']}` {f['question']}" for f in report["failures"]) or "- none"
    return f"""# End-to-end agent evaluation

Model: **{report["model"]}** ({report["mode"]}). Questions: {report["questions"]}.

| Metric | Value |
|---|---|
| Answer contains every expected fact | {report["answer_contains_all"]:.3f} |
| Cites a relevant document | {report["cites_relevant_doc"]:.3f} |
| p50 workflow latency (ms) | {report["p50_latency_ms"]} |

Failed questions:

{fails}

Reproduce: `python -m aistack.eval.agent_eval`. With the default deterministic model the answerer
is extractive, so this validates the pipeline, not language-model quality.
"""


def main() -> None:
    settings = get_settings()
    report = asyncio.run(evaluate(settings, load_golden()))
    Path(REPO_ROOT / "evals").mkdir(exist_ok=True)
    (REPO_ROOT / "evals" / "agent_report.json").write_text(json.dumps(report, indent=2) + "\n")
    (REPO_ROOT / "docs").mkdir(exist_ok=True)
    (REPO_ROOT / "docs" / "AGENT_EVAL.md").write_text(render(report))
    print(render(report))


if __name__ == "__main__":
    main()
