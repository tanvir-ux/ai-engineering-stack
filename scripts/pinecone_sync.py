"""Load the gold chunks into a Pinecone index and run one filtered query.

    PINECONE_API_KEY=... python scripts/pinecone_sync.py --query "salary bands" \
        --classes public internal

NOT executed against a live Pinecone project (no key was available when this was built).
The adapter itself is unit-tested against an in-memory fake. Create the index first, with
dimension 384 and the cosine metric. Requires `pip install -e ".[pinecone]"`.
"""

from __future__ import annotations

import argparse
import os

from aistack.config import get_settings
from aistack.retrieval.embedding import HashingEmbedder
from aistack.retrieval.hybrid import load_gold
from aistack.retrieval.pinecone_store import PineconeStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="How many days of paid holiday do I get?")
    ap.add_argument("--classes", nargs="*", default=["public", "internal"])
    ns = ap.parse_args()
    s = get_settings()
    key = os.environ.get("PINECONE_API_KEY", "") or s.pinecone_api_key
    if not key:
        raise SystemExit("set PINECONE_API_KEY")
    store = PineconeStore.from_env(key, s.pinecone_index, HashingEmbedder())
    chunks, vecs = load_gold(s.gold_chunks_path)
    print(f"upserted {store.upsert(chunks, vecs)} chunks")
    for h in store.search(ns.query, k=3, allowed_classes=set(ns.classes)):
        print(f"{h.score:.3f}  {h.chunk.classification:9}  {h.chunk.title}")


if __name__ == "__main__":
    main()
