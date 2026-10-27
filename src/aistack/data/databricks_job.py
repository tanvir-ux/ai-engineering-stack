"""The same medallion pipeline, writing managed Delta tables (Unity Catalog) instead of paths.

This is the entry point of the Databricks job (`aistack-lakehouse`, see `databricks/`). The stage
functions are the ones in `spark_pipeline`, so the logic that runs on a Databricks cluster is the
logic the local tests execute. Only the *table naming* differs:

* on Databricks:  `<catalog>.<schema>.<layer>_<name>`
* in local tests: `<layer>_<name>` in the default Spark catalog

Nothing in this module has been run against a live Databricks workspace. The table-writing path is
exercised locally by `tests/test_databricks_job.py`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession

from aistack.data.spark_pipeline import (
    chunk_docs,
    clean_docs,
    clean_tickets,
    embed_chunks,
    ingest_docs,
    ingest_tickets,
    ticket_stats,
)

Namer = Callable[[str, str], str]


def uc_namer(catalog: str, schema: str) -> Namer:
    for part in (catalog, schema):
        if not part.replace("_", "").isalnum():
            raise ValueError(f"unsafe identifier: {part!r}")
    return lambda layer, name: f"{catalog}.{schema}.{layer}_{name}"


def local_namer(layer: str, name: str) -> str:
    return f"{layer}_{name}"


def _save(df: DataFrame, table: str) -> DataFrame:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    return df.sparkSession.table(table)


def run_tables(spark: SparkSession, raw: Path | str, name: Namer) -> dict[str, Any]:
    raw = Path(str(raw))
    bronze_docs = _save(ingest_docs(spark, raw), name("bronze", "docs"))
    silver_docs, bad_docs = clean_docs(bronze_docs)
    silver_docs = _save(silver_docs, name("silver", "docs"))
    _save(bad_docs, name("quarantine", "docs"))
    silver_chunks = _save(chunk_docs(silver_docs), name("silver", "chunks"))
    gold = _save(embed_chunks(silver_chunks), name("gold", "chunks"))

    bronze_t = _save(ingest_tickets(spark, raw), name("bronze", "tickets"))
    silver_t, bad_t = clean_tickets(bronze_t)
    silver_t = _save(silver_t, name("silver", "tickets"))
    _save(bad_t, name("quarantine", "tickets"))
    _save(ticket_stats(silver_t), name("gold", "ticket_stats"))

    t = spark.table
    return {
        "docs_ingested": t(name("bronze", "docs")).count(),
        "docs_clean": silver_docs.count(),
        "docs_quarantined": t(name("quarantine", "docs")).count(),
        "chunks": gold.count(),
        "tickets_ingested": bronze_t.count(),
        "tickets_clean": silver_t.count(),
        "tickets_quarantined": t(name("quarantine", "tickets")).count(),
    }


def check_quality(m: dict[str, Any], max_quarantine_ratio: float = 0.2) -> None:
    """Fail the job (and so the Databricks run) if the data looks wrong."""
    if m["docs_clean"] == 0 or m["chunks"] == 0:
        raise RuntimeError(f"pipeline produced no documents or chunks: {m}")
    for kind in ("docs", "tickets"):
        ratio = m[f"{kind}_quarantined"] / max(1, m[f"{kind}_ingested"])
        if ratio > max_quarantine_ratio:
            raise RuntimeError(f"{kind}: {ratio:.0%} of rows quarantined, limit is 20%")


def main() -> None:
    ap = argparse.ArgumentParser(description="Meridian lakehouse job")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--raw", required=True, help="e.g. /Volumes/<catalog>/<schema>/raw")
    ns = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()
    metrics = run_tables(spark, ns.raw, uc_namer(ns.catalog, ns.schema))
    check_quality(metrics)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
