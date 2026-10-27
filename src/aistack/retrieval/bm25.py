"""A small, dependency-free BM25 (Okapi) index."""

from __future__ import annotations

import math
from collections import Counter

from aistack.retrieval.embedding import tokenize


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._tf = [Counter(tokenize(d)) for d in docs]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out: list[float] = []
        for tf, length in zip(self._tf, self._len, strict=True):
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * length / (self._avg or 1.0))
                    s += self._idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out.append(s)
        return out
