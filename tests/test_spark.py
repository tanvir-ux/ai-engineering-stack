"""PySpark pipeline tests. They start a real local Spark session (about 20-40 s in total)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from aistack.config import REPO_ROOT

pytestmark = pytest.mark.spark
pyspark = pytest.importorskip("pyspark")

from aistack.data.chunking import make_chunks, parse_document  # noqa: E402
from aistack.data.spark_pipeline import get_spark, run  # noqa: E402


@pytest.fixture(scope="module")
def spark() -> Iterator[Any]:
    s = get_spark()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def full_run(spark: Any, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("full")
    metrics = run(REPO_ROOT / "data" / "raw", base / "lake", base / "export", spark=spark)
    metrics["_base"] = base
    return metrics


def test_medallion_counts(full_run: dict[str, Any]) -> None:
    assert full_run["format"] == "delta"
    assert full_run["docs_ingested"] == full_run["docs_clean"] + full_run["docs_quarantined"]
    assert full_run["docs_clean"] == 28
    assert full_run["tickets_ingested"] == 306
    assert full_run["tickets_quarantined"] >= 1
    assert full_run["tickets_duplicates_removed"] == 4  # the generator plants 4 duplicate ids


def test_delta_transaction_log_exists(full_run: dict[str, Any]) -> None:
    log = full_run["_base"] / "lake" / "gold" / "chunks" / "_delta_log"
    assert any(log.glob("*.json"))


def test_spark_chunks_match_the_plain_python_chunker(full_run: dict[str, Any]) -> None:
    docs = [
        parse_document(p.read_text())
        for p in sorted((REPO_ROOT / "data" / "raw" / "docs").glob("*.md"))
    ]
    expected = {c["chunk_id"]: c["text"] for d in docs for c in make_chunks(d)}
    got = pd.read_parquet(full_run["_base"] / "export" / "chunks.parquet")
    assert dict(zip(got.chunk_id, got.text, strict=True)) == expected
    assert len(got) == full_run["chunks"]


def test_embeddings_are_unit_vectors_of_the_right_size(full_run: dict[str, Any]) -> None:
    got = pd.read_parquet(full_run["_base"] / "export" / "chunks.parquet")
    mat = np.stack(got.embedding.to_numpy())
    assert mat.shape == (len(got), full_run["embedding_dim"])
    norms = np.linalg.norm(mat, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_pipeline_is_reproducible_and_matches_committed_artifacts(
    full_run: dict[str, Any],
) -> None:
    new = pd.read_parquet(full_run["_base"] / "export" / "chunks.parquet").sort_values("chunk_id")
    old = pd.read_parquet(REPO_ROOT / "artifacts" / "gold" / "chunks.parquet").sort_values(
        "chunk_id"
    )
    assert list(new.chunk_id) == list(old.chunk_id)
    assert list(new.content_hash) == list(old.content_hash)
    assert np.allclose(np.stack(new.embedding.to_numpy()), np.stack(old.embedding.to_numpy()))


def test_ticket_stats_are_consistent(full_run: dict[str, Any]) -> None:
    stats = pd.read_csv(full_run["_base"] / "export" / "ticket_stats.csv")
    tickets = pd.read_parquet(full_run["_base"] / "export" / "tickets.parquet")
    assert int(stats["tickets"].sum()) == len(tickets) == full_run["tickets_clean"]


def test_bad_records_are_quarantined_not_dropped(spark: Any, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "docs").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "data" / "raw" / "docs" / "pub-001.md", raw / "docs")
    (raw / "docs" / "bad-class.md").write_text(
        "---\nid: bad-1\ntitle: Bad\nclassification: top-secret\ndepartment: x\n"
        "updated: 2026-01-01\n---\nBody text that should never reach the gold layer.\n"
    )
    (raw / "docs" / "empty.md").write_text(
        "---\nid: empty-1\ntitle: Empty\nclassification: public\ndepartment: x\n"
        "updated: 2026-01-01\n---\n\n"
    )
    shutil.copy(REPO_ROOT / "data" / "raw" / "tickets.csv", raw / "tickets.csv")
    metrics = run(raw, tmp_path / "lake", tmp_path / "export", spark=spark)
    assert metrics["docs_ingested"] == 3
    assert metrics["docs_clean"] == 1 and metrics["docs_quarantined"] == 2
    chunks = pd.read_parquet(tmp_path / "export" / "chunks.parquet")
    assert set(chunks.doc_id) == {"pub-001"}
