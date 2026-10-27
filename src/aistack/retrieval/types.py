"""Shared retrieval types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    classification: str
    department: str
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self.chunk)
        out["score"] = round(self.score, 4)
        out["sources"] = list(self.sources)
        return out
