"""Embedders behind one small interface.

`HashingEmbedder` is a deterministic, dependency-free feature-hashing embedder over word unigrams
and bigrams. It is **not** a neural model: it captures lexical overlap only. It is the default so
that the whole stack, including the PySpark pipeline and CI, runs offline with reproducible
numbers. `OpenAIEmbedder` plugs a real embedding model in through environment keys.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
        "my",
        "we",
        "our",
        "do",
        "does",
        "can",
    ]
)


def tokenize(text: str, *, drop_stop: bool = True) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    return [t for t in toks if not (drop_stop and t in _STOP)]


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> NDArray[np.float32]: ...


def _bucket(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


class HashingEmbedder:
    """Signed feature hashing of unigrams (weight 1) and bigrams (weight 0.5), L2 normalised."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed_one(self, text: str) -> NDArray[np.float32]:
        vec = np.zeros(self.dim, dtype=np.float32)
        toks = tokenize(text)
        for tok in toks:
            idx, sign = _bucket(tok, self.dim)
            vec[idx] += sign
        for a, b in zip(toks, toks[1:], strict=False):
            idx, sign = _bucket(f"{a}_{b}", self.dim)
            vec[idx] += 0.5 * sign
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self.embed_one(t) for t in texts]).astype(np.float32)


class OpenAIEmbedder:
    """Real embeddings through the OpenAI API (`OPENAI_API_KEY`). Not exercised in CI."""

    def __init__(self, model: str = "text-embedding-3-small", api_key: str = "") -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key or None)
        self._model = model
        self.dim = 1536

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        arr = np.array([d.embedding for d in resp.data], dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return (arr / np.where(norms == 0, 1, norms)).astype(np.float32)
