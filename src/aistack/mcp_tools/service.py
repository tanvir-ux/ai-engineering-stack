"""Data-layer tools as plain Python. The MCP server is a thin, authenticated wrapper around this.

Every method takes the caller's `Principal` and enforces policy itself (document classes, ticket
ownership, tool permission), so the checks hold no matter which transport calls them.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pandas as pd

from aistack.auth.policy import Principal, can_use_tool
from aistack.retrieval.hybrid import HybridIndex


class PermissionDenied(Exception):
    pass


class NotFound(Exception):
    pass


class KnowledgeService:
    def __init__(self, index: HybridIndex, tickets: pd.DataFrame) -> None:
        self.index = index
        self.tickets = tickets
        self.created: list[dict[str, Any]] = []
        self._ids = itertools.count(9001)

    @classmethod
    def from_paths(cls, chunks: Path, tickets: Path) -> KnowledgeService:
        return cls(HybridIndex.from_gold(chunks), pd.read_parquet(tickets))

    def _require(self, who: Principal, tool: str) -> None:
        if not can_use_tool(who, tool):
            raise PermissionDenied(f"{who.email or who.sub} may not use {tool}")

    def search_documents(self, who: Principal, query: str, k: int = 4) -> list[dict[str, Any]]:
        self._require(who, "search_documents")
        hits = self.index.search(query, k=max(1, min(k, 10)), allowed_classes=set(who.classes))
        return [h.to_dict() for h in hits]

    def get_document(self, who: Principal, doc_id: str) -> dict[str, Any]:
        self._require(who, "get_document")
        chunks = [c for c in self.index.chunks if c.doc_id == doc_id]
        if not chunks:
            raise NotFound(f"no document {doc_id}")
        if chunks[0].classification not in who.classes:
            # Same message as a missing document: do not reveal that it exists.
            raise NotFound(f"no document {doc_id}")
        return {
            "doc_id": doc_id,
            "title": chunks[0].title,
            "classification": chunks[0].classification,
            "text": " ".join(c.text for c in chunks),
        }

    def list_my_tickets(self, who: Principal, status: str | None = None) -> list[dict[str, Any]]:
        self._require(who, "list_my_tickets")
        df = self.tickets[self.tickets["requester"] == who.email]
        if status:
            df = df[df["status"] == status]
        rows = df.sort_values("created_at", ascending=False).head(10)
        out = [
            {
                "ticket_id": r.ticket_id,
                "category": r.category,
                "priority": r.priority,
                "status": r.status,
                "summary": r.summary,
            }
            for r in rows.itertuples()
        ]
        out += [t for t in self.created if t["requester"] == who.email]
        return out

    def ticket_stats(self, who: Principal, category: str | None = None) -> dict[str, Any]:
        self._require(who, "ticket_stats")
        df = self.tickets if not category else self.tickets[self.tickets["category"] == category]
        done = df.dropna(subset=["resolved_at"])
        hours = (done["resolved_at"] - done["created_at"]).dt.total_seconds() / 3600
        return {
            "category": category or "all",
            "tickets": int(len(df)),
            "open_tickets": int(df["resolved_at"].isna().sum()),
            "avg_resolution_hours": round(float(hours.mean()), 1) if len(hours) else None,
            "by_priority": {
                k: int(v) for k, v in df["priority"].value_counts().sort_index().items()
            },
        }

    def create_ticket(self, who: Principal, title: str, priority: str = "P3") -> dict[str, Any]:
        self._require(who, "create_ticket")
        if priority not in {"P1", "P2", "P3", "P4"}:
            raise ValueError("priority must be P1, P2, P3 or P4")
        if not 3 <= len(title.strip()) <= 140:
            raise ValueError("title must be 3 to 140 characters")
        ticket = {
            "ticket_id": f"INC-{next(self._ids)}",
            "requester": who.email,
            "priority": priority,
            "status": "open",
            "summary": title.strip(),
        }
        self.created.append(ticket)
        return ticket
