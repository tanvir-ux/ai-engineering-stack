"""Pure-Python parsing and chunking helpers.

They are used by the PySpark job, the Databricks notebook and the Snowpark script, so all three
engines produce the same chunks.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

VALID_CLASSES = ("public", "internal", "finance", "hr", "security")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SENT = re.compile(r"(?<=[.!?])\s+")


def parse_document(raw: str) -> dict[str, str]:
    """Split a markdown file with simple `key: value` front matter. Raises ValueError if invalid."""
    m = _FRONT.match(raw.replace("\r\n", "\n"))
    if not m:
        raise ValueError("missing front matter")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = re.sub(r"^#\s+.*\n+", "", m.group(2).strip() + "\n", count=1).strip()
    body = re.sub(r"\s+", " ", body)
    for field in ("id", "title", "classification"):
        if not meta.get(field):
            raise ValueError(f"missing field {field}")
    if meta["classification"] not in VALID_CLASSES:
        raise ValueError(f"unknown classification {meta['classification']}")
    if not body:
        raise ValueError("empty body")
    return {**meta, "body": body}


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()[:16]


def chunk_text(body: str, *, max_words: int = 45, overlap_sentences: int = 1) -> list[str]:
    """Greedy sentence packing: each chunk holds up to `max_words` words and repeats the last
    `overlap_sentences` sentence(s) of the previous chunk, so a fact never straddles a boundary."""
    sentences = [s.strip() for s in _SENT.split(body) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for sent in sentences:
        words = sum(len(s.split()) for s in current) + len(sent.split())
        if current and words > max_words:
            chunks.append(" ".join(current))
            current = current[-overlap_sentences:] if overlap_sentences else []
        current.append(sent)
    if current and (not chunks or " ".join(current) != chunks[-1]):
        chunks.append(" ".join(current))
    return chunks


def make_chunks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, text in enumerate(chunk_text(doc["body"])):
        out.append(
            {
                "chunk_id": f"{doc['id']}#{i}",
                "doc_id": doc["id"],
                "chunk_index": i,
                "title": doc["title"],
                "classification": doc["classification"],
                "department": doc.get("department", ""),
                "text": text,
            }
        )
    return out
