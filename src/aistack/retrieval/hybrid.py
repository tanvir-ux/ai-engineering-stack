"""Hybrid retrieval: BM25 + dense (FAISS) fused with reciprocal rank fusion, then reranked.

Access control is applied *inside* the search (before ranking), so a document a caller may not
read can never appear in results or influence scores returned to them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import faiss  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from numpy.typing import NDArray

from aistack.retrieval.bm25 import BM25
from aistack.retrieval.embedding import Embedder, HashingEmbedder
from aistack.retrieval.rerank import HeuristicReranker, Reranker
from aistack.retrieval.types import Chunk, Hit

RRF_K = 60


def load_gold(path: Path) -> tuple[list[Chunk], NDArray[np.float32]]:
    df = pd.read_parquet(path)
    chunks = [
        Chunk(r.chunk_id, r.doc_id, r.title, r.classification, r.department, r.text)
        for r in df.itertuples()
    ]
    vecs = np.array(df["embedding"].tolist(), dtype=np.float32)
    return chunks, vecs


def rrf(rankings: Iterable[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


class HybridIndex:
    def __init__(
        self,
        chunks: list[Chunk],
        vectors: NDArray[np.float32],
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.chunks = chunks
        self.embedder = embedder or HashingEmbedder(vectors.shape[1])
        self.reranker = reranker or HeuristicReranker()
        self._bm25 = BM25([c.text + " " + c.title for c in chunks])
        self._faiss = faiss.IndexFlatIP(vectors.shape[1])
        self._faiss.add(np.ascontiguousarray(vectors))
        self._vectors = vectors

    @classmethod
    def from_gold(cls, path: Path, **kw: Any) -> HybridIndex:
        chunks, vecs = load_gold(path)
        return cls(chunks, vecs, **kw)

    def _allowed(self, classes: set[str] | None) -> list[int]:
        return [
            i for i, c in enumerate(self.chunks) if classes is None or c.classification in classes
        ]

    def search(
        self,
        query: str,
        k: int = 5,
        allowed_classes: set[str] | None = None,
        mode: str = "hybrid",
        rerank: bool = True,
        pool: int = 20,
    ) -> list[Hit]:
        """mode: bm25 | dense | hybrid."""
        allowed = self._allowed(allowed_classes)
        if not allowed:
            return []
        rankings: list[list[int]] = []
        if mode in ("bm25", "hybrid"):
            s = self._bm25.scores(query)
            order = sorted(allowed, key=lambda i: s[i], reverse=True)
            rankings.append([i for i in order if s[i] > 0][:pool])
        if mode in ("dense", "hybrid"):
            qv = self.embedder.embed([query])[0]
            sims = self._vectors[allowed] @ qv
            order_local = np.argsort(-sims)[:pool]
            rankings.append([allowed[j] for j in order_local if sims[j] > 0])
        fused = rrf(rankings)
        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:pool]
        label = (mode,) if mode != "hybrid" else ("bm25", "dense")
        hits = [Hit(self.chunks[i], score, label) for i, score in ranked]
        if rerank:
            hits = self.reranker.rerank(query, hits)
        return hits[:k]
