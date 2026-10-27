"""A transparent heuristic reranker.

It is deliberately simple and deterministic: it rewards chunks that cover more of the query's
distinct terms, that contain query bigrams verbatim, and whose title matches. A cross-encoder
(for example a hosted rerank API) can replace it behind the same `Reranker` protocol.
"""

from __future__ import annotations

from typing import Protocol

from aistack.retrieval.embedding import tokenize
from aistack.retrieval.types import Hit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]: ...


class HeuristicReranker:
    def __init__(
        self,
        w_fused: float = 0.5,
        w_cover: float = 0.35,
        w_bigram: float = 0.1,
        w_title: float = 0.05,
    ) -> None:
        self.w = (w_fused, w_cover, w_bigram, w_title)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return []
        q = tokenize(query)
        qset = set(q)
        qbi = set(zip(q, q[1:], strict=False))
        top = max(h.score for h in hits) or 1.0
        rescored: list[Hit] = []
        for h in hits:
            toks = tokenize(h.chunk.text)
            tset = set(toks)
            cover = len(qset & tset) / len(qset) if qset else 0.0
            bi = len(qbi & set(zip(toks, toks[1:], strict=False))) / len(qbi) if qbi else 0.0
            title = len(qset & set(tokenize(h.chunk.title))) / len(qset) if qset else 0.0
            score = (
                self.w[0] * h.score / top + self.w[1] * cover + self.w[2] * bi + self.w[3] * title
            )
            rescored.append(Hit(h.chunk, score, (*h.sources, "rerank")))
        return sorted(rescored, key=lambda x: x.score, reverse=True)
