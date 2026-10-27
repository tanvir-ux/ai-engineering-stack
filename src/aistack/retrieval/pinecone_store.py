"""Pinecone adapter (managed vector DB). Optional: needs `PINECONE_API_KEY`.

The adapter talks to a Pinecone-style index object (`upsert`, `query`), so unit tests exercise it
with an in-memory fake and no network. It is not exercised against a live Pinecone project in CI.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from aistack.retrieval.embedding import Embedder
from aistack.retrieval.types import Chunk, Hit


class PineconeIndexLike(Protocol):
    def upsert(self, vectors: list[dict[str, Any]], namespace: str = "") -> Any: ...

    def query(
        self,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,  # noqa: A002
        include_metadata: bool = True,
        namespace: str = "",
    ) -> Any: ...


class PineconeStore:
    def __init__(self, index: PineconeIndexLike, embedder: Embedder, namespace: str = "docs"):
        self.index, self.embedder, self.namespace = index, embedder, namespace

    @classmethod
    def from_env(cls, api_key: str, index_name: str, embedder: Embedder) -> PineconeStore:
        from pinecone import Pinecone  # imported lazily: optional dependency

        return cls(Pinecone(api_key=api_key).Index(index_name), embedder)  # type: ignore[arg-type]

    def upsert(
        self, chunks: list[Chunk], vectors: NDArray[np.float32] | None = None, batch: int = 100
    ) -> int:
        vecs = vectors if vectors is not None else self.embedder.embed([c.text for c in chunks])
        records = [
            {
                "id": c.chunk_id,
                "values": [float(x) for x in v],
                "metadata": {
                    "doc_id": c.doc_id,
                    "title": c.title,
                    "classification": c.classification,
                    "department": c.department,
                    "text": c.text,
                },
            }
            for c, v in zip(chunks, vecs, strict=True)
        ]
        for i in range(0, len(records), batch):
            self.index.upsert(records[i : i + batch], namespace=self.namespace)
        return len(records)

    def search(self, query: str, k: int = 5, allowed_classes: set[str] | None = None) -> list[Hit]:
        flt = {"classification": {"$in": sorted(allowed_classes)}} if allowed_classes else None
        qv = [float(x) for x in self.embedder.embed([query])[0]]
        res = self.index.query(
            vector=qv, top_k=k, filter=flt, include_metadata=True, namespace=self.namespace
        )
        hits: list[Hit] = []
        for m in res["matches"]:
            md = m["metadata"]
            chunk = Chunk(
                m["id"],
                md["doc_id"],
                md["title"],
                md["classification"],
                md["department"],
                md["text"],
            )
            hits.append(Hit(chunk, float(m["score"]), ("pinecone",)))
        return hits
