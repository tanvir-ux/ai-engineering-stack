"""Snowflake side of the data layer: load the gold files and run vector search with Snowpark.

Status: unit-tested against a recording fake session (no network). NOT executed against a live
Snowflake account. The SQL it relies on lives in `snowflake/sql/` and is syntax-checked
with sqlglot.

Credentials are read from `SNOWFLAKE_*` environment variables by `connect()`, never from files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from aistack.retrieval.embedding import Embedder
from aistack.retrieval.types import Chunk, Hit

SQL_DIR = Path(__file__).resolve().parents[3] / "snowflake" / "sql"
EMBED_DIM = 384


class SessionLike(Protocol):
    """The slice of `snowflake.snowpark.Session` this module uses."""

    def sql(self, query: str, params: list[Any] | None = ...) -> Any: ...

    def write_pandas(self, df: pd.DataFrame, table_name: str, **kwargs: Any) -> Any: ...


def connect() -> SessionLike:  # pragma: no cover - needs a live account
    from snowflake.snowpark import Session  # optional dependency: `pip install .[snowflake]`

    cfg = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "password": os.environ["SNOWFLAKE_PASSWORD"],
        "role": os.environ.get("SNOWFLAKE_ROLE", "MERIDIAN_COPILOT"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "MERIDIAN_WH"),
        "database": "MERIDIAN",
        "schema": "RAW",
    }
    return Session.builder.configs(cfg).create()  # type: ignore[no-any-return]


def load_gold(session: SessionLike, gold_dir: Path) -> dict[str, int]:
    """Load chunks and tickets Parquet files with `write_pandas` (an alternative to PUT + COPY)."""
    chunks = pd.read_parquet(gold_dir / "chunks.parquet")
    chunks["embedding"] = chunks["embedding"].map(lambda v: [float(x) for x in v])
    session.write_pandas(
        chunks.rename(columns=str.upper), "CHUNKS_LOAD", auto_create_table=False, overwrite=True
    )
    session.sql("INSERT OVERWRITE INTO CHUNKS " + _CHUNKS_SELECT).collect()
    tickets = pd.read_parquet(gold_dir / "tickets.parquet").rename(columns=str.upper)
    session.write_pandas(tickets, "TICKETS", auto_create_table=False, overwrite=True)
    return {"chunks": len(chunks), "tickets": len(tickets)}


# Only the integer EMBED_DIM constant is interpolated, so B608 is a false positive.
_CHUNKS_SELECT = (
    "SELECT CHUNK_ID, DOC_ID, TITLE, CLASSIFICATION, DEPARTMENT, TEXT, "  # nosec B608
    f"EMBEDDING::VECTOR(FLOAT, {EMBED_DIM}), EMBEDDING_MODEL FROM CHUNKS_LOAD"
)


def search_sql(n_classes: int) -> str:
    """Cosine search restricted to the caller's classifications (bound parameters only)."""
    if n_classes < 1:
        raise ValueError("at least one readable classification is required")
    marks = ", ".join("?" for _ in range(n_classes))
    # Only "?" placeholders and an integer constant are interpolated (B608 false positive).
    return (
        "SELECT CHUNK_ID, DOC_ID, TITLE, CLASSIFICATION, DEPARTMENT, TEXT, "  # nosec B608
        "VECTOR_COSINE_SIMILARITY("
        f"EMBEDDING, PARSE_JSON(?)::ARRAY::VECTOR(FLOAT, {EMBED_DIM})) AS SCORE "
        f"FROM MERIDIAN.RAW.CHUNKS WHERE CLASSIFICATION IN ({marks}) "
        "ORDER BY SCORE DESC LIMIT ?"
    )


class SnowflakeStore:
    """Vector search in Snowflake. The row access policy (`03_governance.sql`) also applies."""

    def __init__(self, session: SessionLike, embedder: Embedder) -> None:
        self.session, self.embedder = session, embedder

    def search(self, query: str, k: int = 5, allowed_classes: set[str] | None = None) -> list[Hit]:
        if allowed_classes is not None and not allowed_classes:
            return []
        if allowed_classes is None:
            raise ValueError("allowed_classes is required for Snowflake search")
        vec = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
        params: list[Any] = [json.dumps([float(x) for x in vec]), *sorted(allowed_classes), int(k)]
        rows = self.session.sql(search_sql(len(allowed_classes)), params=params).collect()
        hits: list[Hit] = []
        for r in rows:
            d = r.as_dict() if hasattr(r, "as_dict") else dict(r)
            chunk = Chunk(
                d["CHUNK_ID"], d["DOC_ID"], d["TITLE"], d["CLASSIFICATION"],
                d["DEPARTMENT"], d["TEXT"],
            )  # fmt: skip
            hits.append(Hit(chunk, float(d["SCORE"]), ("snowflake",)))
        return hits
