"""Retrieval evaluation against the golden set.

    python -m aistack.eval.rag_eval            # writes evals/report.json and docs/EVAL_REPORT.md

Every number in the report comes from this script. Nothing is hand-edited.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from aistack.auth.policy import classes_for
from aistack.config import REPO_ROOT, get_settings
from aistack.retrieval.hybrid import HybridIndex

CONFIGS: list[tuple[str, str, bool]] = [
    ("bm25", "bm25", False),
    ("dense (hashing embeddings)", "dense", False),
    ("hybrid (RRF)", "hybrid", False),
    ("hybrid (RRF) + rerank", "hybrid", True),
]


def load_golden(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or REPO_ROOT / "evals" / "golden.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def evaluate(index: HybridIndex, golden: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for label, mode, rerank in CONFIGS:
        h1 = h3 = h5 = 0
        rr = 0.0
        ans3 = 0
        lat: list[float] = []
        for q in golden:
            classes = set(classes_for([q["role"]]))
            t0 = time.perf_counter()
            hits = index.search(
                q["question"], k=k, allowed_classes=classes, mode=mode, rerank=rerank
            )
            lat.append((time.perf_counter() - t0) * 1000)
            docs = [h.chunk.doc_id for h in hits]
            rel = set(q["relevant_docs"])
            rank = next((i + 1 for i, d in enumerate(docs) if d in rel), None)
            h1 += rank == 1
            h3 += rank is not None and rank <= 3
            h5 += rank is not None and rank <= 5
            rr += 1 / rank if rank else 0.0
            ctx = " ".join(h.chunk.text for h in hits[:3]).lower()
            ans3 += all(a.lower() in ctx for a in q["answer_contains"])
        n = len(golden)
        results[label] = {
            "hit@1": round(h1 / n, 3),
            "hit@3": round(h3 / n, 3),
            "hit@5": round(h5 / n, 3),
            "mrr": round(rr / n, 3),
            "answer_in_top3_context": round(ans3 / n, 3),
            "latency_ms_p50": round(statistics.median(lat), 3),
        }
    return results


def acl_check(index: HybridIndex, golden: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask every golden question as the *lowest* role and as each role; count forbidden results."""
    leaks = 0
    probes = 0
    blocked_correctly = 0
    blocked_total = 0
    for q in golden:
        for role in ("contractor", "employee", "hr", "finance", "security"):
            allowed = set(classes_for([role]))
            hits = index.search(q["question"], k=5, allowed_classes=allowed)
            probes += 1
            leaks += sum(h.chunk.classification not in allowed for h in hits)
            doc_class = next(
                c.classification for c in index.chunks if c.doc_id == q["relevant_docs"][0]
            )
            if doc_class not in allowed:
                blocked_total += 1
                blocked_correctly += all(h.chunk.doc_id not in q["relevant_docs"] for h in hits)
    return {
        "probes": probes,
        "forbidden_results_returned": leaks,
        "restricted_probes": blocked_total,
        "restricted_probes_correctly_withheld": blocked_correctly,
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval evaluation report",
        "",
        f"Golden set: **{report['golden_questions']} questions** over "
        f"**{report['chunks']} chunks** "
        f"from {report['documents']} synthetic documents (`evals/golden.jsonl`). "
        "Each question names the document that holds the answer. "
        "Questions are asked as a role that is allowed to read that document.",
        "",
        "Reproduce: `make eval`",
        "",
        "| Retriever | hit@1 | hit@3 | hit@5 | MRR | answer text in top-3 context "
        "| p50 latency (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in report["retrieval"].items():
        lines.append(
            f"| {name} | {m['hit@1']:.3f} | {m['hit@3']:.3f} | {m['hit@5']:.3f} | {m['mrr']:.3f} "
            f"| {m['answer_in_top3_context']:.3f} | {m['latency_ms_p50']:.2f} |"
        )
    a = report["acl"]
    lines += [
        "",
        "## Access-control check",
        "",
        f"Every golden question was asked as each of 5 roles ({a['probes']} searches). "
        f"Forbidden chunks returned: **{a['forbidden_results_returned']}**. "
        f"Questions whose answer lives in a document the role may not read: "
        f"{a['restricted_probes']}, of which the document was correctly withheld in "
        f"**{a['restricted_probes_correctly_withheld']}**.",
        "",
        "## Notes and limits",
        "",
        "- The default embedder is a feature-hashing embedder (lexical, no neural model), "
        'so "dense" here is a lexical vector baseline. Swap in real embeddings '
        "(`OpenAIEmbedder`) to compare.",
        "- The golden set is small and synthetic. Treat the numbers as a regression gate and a "
        "demonstration of the method, not as a general benchmark.",
        "- The reranker is a transparent heuristic, not a cross-encoder.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    index = HybridIndex.from_gold(get_settings().gold_chunks_path)
    golden = load_golden()
    report = {
        "golden_questions": len(golden),
        "chunks": len(index.chunks),
        "documents": len({c.doc_id for c in index.chunks}),
        "retrieval": evaluate(index, golden),
        "acl": acl_check(index, golden),
    }
    (REPO_ROOT / "evals").mkdir(exist_ok=True)
    (REPO_ROOT / "evals" / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (REPO_ROOT / "docs").mkdir(exist_ok=True)
    (REPO_ROOT / "docs" / "EVAL_REPORT.md").write_text(to_markdown(report))
    print(to_markdown(report))


if __name__ == "__main__":
    main()
