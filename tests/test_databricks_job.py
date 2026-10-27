"""The Databricks job logic, executed on LOCAL Spark. Not run against a live workspace."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aistack.config import REPO_ROOT

pytestmark = pytest.mark.spark
pytest.importorskip("pyspark")

from aistack.data.databricks_job import (  # noqa: E402
    check_quality,
    local_namer,
    run_tables,
    uc_namer,
)
from aistack.data.spark_pipeline import get_spark  # noqa: E402


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    wh = tmp_path_factory.mktemp("warehouse")
    s = get_spark(warehouse=str(wh))
    yield s
    s.stop()


def test_job_writes_managed_delta_tables(spark: Any, tmp_path: Path) -> None:
    spark.sql("CREATE DATABASE IF NOT EXISTS default")
    m = run_tables(spark, REPO_ROOT / "data" / "raw", local_namer)
    assert m["docs_clean"] == 28 and m["chunks"] == 65
    assert spark.table("gold_chunks").count() == 65
    detail = spark.sql("DESCRIBE DETAIL gold_chunks").collect()[0]
    assert detail["format"] == "delta"
    check_quality(m)


def test_quality_gate_fails_loudly() -> None:
    good = {
        "docs_ingested": 10, "docs_clean": 10, "docs_quarantined": 0, "chunks": 20,
        "tickets_ingested": 100, "tickets_clean": 99, "tickets_quarantined": 1,
    }  # fmt: skip
    check_quality(good)
    with pytest.raises(RuntimeError, match="no documents"):
        check_quality({**good, "docs_clean": 0})
    with pytest.raises(RuntimeError, match="quarantined"):
        check_quality({**good, "tickets_quarantined": 50})


def test_unity_catalog_names_reject_injection() -> None:
    assert uc_namer("main", "meridian")("gold", "chunks") == "main.meridian.gold_chunks"
    with pytest.raises(ValueError):
        uc_namer("main; DROP TABLE x", "meridian")
