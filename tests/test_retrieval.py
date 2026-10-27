from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from aistack.config import get_settings
from aistack.data.chunking import chunk_text, content_hash, make_chunks, parse_document
from aistack.retrieval.bm25 import BM25
from aistack.retrieval.embedding import HashingEmbedder
from aistack.retrieval.hybrid import HybridIndex, rrf
from aistack.retrieval.pinecone_store import PineconeStore
from aistack.retrieval.types import Chunk


@pytest.fixture(scope="module")
def index() -> HybridIndex:
    return HybridIndex.from_gold(get_settings().gold_chunks_path)


def test_embedder_is_deterministic_and_normalised() -> None:
    e = HashingEmbedder()
    a, b = e.embed(["annual leave days"])[0], e.embed(["annual leave days"])[0]
    assert np.allclose(a, b)
    assert abs(float(np.linalg.norm(a)) - 1.0) < 1e-5
    assert e.embed([]).shape == (0, e.dim)


def test_bm25_ranks_matching_doc_first() -> None:
    bm = BM25(["cats like fish", "dogs like bones", "birds fly south"])
    s = bm.scores("fish")
    assert s[0] > s[1] and s[0] > s[2]


def test_rrf_rewards_agreement() -> None:
    fused = rrf([[1, 2, 3], [2, 1, 4]])
    assert fused[1] == fused[2] > fused[3]
    assert fused[4] < fused[3] or fused[4] == fused[3]


def test_search_finds_known_fact(index: HybridIndex) -> None:
    hits = index.search(
        "How many days of annual leave do I get?", k=3, allowed_classes={"internal"}
    )
    assert hits[0].chunk.doc_id == "hr-001"


def test_acl_filters_before_ranking(index: HybridIndex) -> None:
    q = "What salary range applies to Level 4?"
    open_hits = index.search(q, k=5, allowed_classes={"public", "internal"})
    assert all(h.chunk.classification in {"public", "internal"} for h in open_hits)
    assert "hr-004" not in {h.chunk.doc_id for h in open_hits}
    hr_hits = index.search(q, k=3, allowed_classes={"public", "internal", "hr"})
    assert hr_hits[0].chunk.doc_id == "hr-004"


def test_no_allowed_classes_returns_nothing(index: HybridIndex) -> None:
    assert index.search("anything", allowed_classes=set()) == []


def test_all_modes_return_results(index: HybridIndex) -> None:
    for mode in ("bm25", "dense", "hybrid"):
        assert index.search("password length", mode=mode, k=2)


def test_chunking_and_parsing() -> None:
    raw = (
        "---\nid: x-1\ntitle: T\nclassification: internal\ndepartment: d\n"
        "updated: 2026-01-01\n---\n# T\n\n"
        + " ".join(f"Sentence number {i} is here." for i in range(40))
    )
    doc = parse_document(raw)
    chunks = make_chunks(doc)
    assert len(chunks) > 1
    assert all(len(c["text"].split()) <= 60 for c in chunks)
    assert content_hash("a") == content_hash("a") != content_hash("b")
    assert chunk_text("") == []


def test_parse_rejects_bad_classification() -> None:
    with pytest.raises(ValueError):
        parse_document("---\nid: a\ntitle: t\nclassification: top-secret\ndepartment: d\n---\nbody")
    with pytest.raises(ValueError):
        parse_document("no front matter")


class FakePinecone:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.last_filter: dict[str, Any] | None = None

    def upsert(self, vectors: list[dict[str, Any]], namespace: str = "") -> None:
        for v in vectors:
            self.rows[v["id"]] = v

    def query(
        self,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,  # noqa: A002
        include_metadata: bool = True,
        namespace: str = "",
    ) -> dict[str, Any]:
        self.last_filter = filter
        allowed = set(filter["classification"]["$in"]) if filter else None
        q = np.array(vector)
        scored = [
            (float(np.dot(q, np.array(r["values"]))), r)
            for r in self.rows.values()
            if allowed is None or r["metadata"]["classification"] in allowed
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        return {
            "matches": [
                {"id": r["id"], "score": s, "metadata": r["metadata"]} for s, r in scored[:top_k]
            ]
        }


def test_pinecone_adapter_roundtrip_and_acl_filter(index: HybridIndex) -> None:
    fake = FakePinecone()
    store = PineconeStore(fake, HashingEmbedder())
    assert store.upsert(index.chunks, batch=20) == len(index.chunks)
    hits = store.search("password characters multi-factor", k=3, allowed_classes={"internal"})
    assert "it-001" in {h.chunk.doc_id for h in hits}
    assert fake.last_filter == {"classification": {"$in": ["internal"]}}
    assert all(h.chunk.classification == "internal" for h in hits)
    chunk = Chunk("a#0", "a", "t", "hr", "d", "x")
    assert store.upsert([chunk]) == 1
