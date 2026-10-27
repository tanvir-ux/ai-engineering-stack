"""PySpark medallion pipeline: ingest -> clean -> chunk -> feature/embedding table.

Runs for real in Spark local mode and writes Delta tables (bronze, silver, gold) when
`delta-spark` is installed, plain Parquet otherwise. The gold chunk table is also exported as a
single Parquet file that the retrieval layer loads, so the pipeline output is what the app serves.

    python -m aistack.data.spark_pipeline --raw data/raw \
        --lakehouse lakehouse --export artifacts/gold
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from aistack.data.chunking import VALID_CLASSES, content_hash, make_chunks, parse_document
from aistack.retrieval.embedding import DIM, HashingEmbedder

try:  # Delta Lake is optional; Parquet is the fallback format.
    from delta import configure_spark_with_delta_pip

    HAVE_DELTA = True
except ImportError:  # pragma: no cover
    HAVE_DELTA = False

_PARSED = T.StructType(
    [
        T.StructField("id", T.StringType()),
        T.StructField("title", T.StringType()),
        T.StructField("classification", T.StringType()),
        T.StructField("department", T.StringType()),
        T.StructField("updated", T.StringType()),
        T.StructField("body", T.StringType()),
        T.StructField("error", T.StringType()),
    ]
)
_CHUNK = T.StructType(
    [
        T.StructField("chunk_id", T.StringType()),
        T.StructField("doc_id", T.StringType()),
        T.StructField("chunk_index", T.IntegerType()),
        T.StructField("title", T.StringType()),
        T.StructField("classification", T.StringType()),
        T.StructField("department", T.StringType()),
        T.StructField("text", T.StringType()),
    ]
)


def get_spark(
    app: str = "aistack", *, delta: bool = True, cores: int = 2, warehouse: str | None = None
) -> SparkSession:
    builder = (
        SparkSession.builder.master(f"local[{cores}]")
        .appName(app)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", warehouse or "spark-warehouse")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.default.parallelism", "4")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.databricks.delta.snapshotPartitions", "2")
        .config("spark.sql.execution.pythonUDF.arrow.enabled", "false")
        .config("spark.python.worker.reuse", "true")
    )
    if delta and HAVE_DELTA:
        builder = builder.config(
            "spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension"
        ).config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
    else:
        spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def _fmt(spark: SparkSession) -> str:
    return (
        "delta"
        if "DeltaSparkSessionExtension" in (spark.conf.get("spark.sql.extensions", "") or "")
        else "parquet"
    )


def _pdf(df: DataFrame) -> pd.DataFrame:
    out: pd.DataFrame = df.toPandas()  # type: ignore[assignment]
    return out


def _write(df: DataFrame, path: Path, fmt: str) -> None:
    writer = df.write.format(fmt).mode("overwrite")
    if fmt == "delta":
        writer = writer.option("overwriteSchema", "true")
    writer.save(str(path))


# ---------------------------------------------------------------------------------------------
# Stage 1: ingest (bronze)
# ---------------------------------------------------------------------------------------------
def ingest_docs(spark: SparkSession, raw_dir: Path) -> DataFrame:
    # `wholetext` reads each file as one row. No RDD API, so this also runs on serverless compute.
    df = (
        spark.read.format("text")
        .option("wholetext", True)
        .load(str(raw_dir / "docs" / "*.md"))
        .select(F.col("_metadata.file_path").alias("path"), F.col("value").alias("raw_text"))
    )
    return df.withColumn("source_file", F.regexp_extract("path", r"([^/]+)$", 1)).withColumn(
        "ingested_at", F.current_timestamp()
    )


def ingest_tickets(spark: SparkSession, raw_dir: Path) -> DataFrame:
    return (
        spark.read.option("header", True)
        .option("multiLine", False)
        .csv(str(raw_dir / "tickets.csv"))
        .withColumn("ingested_at", F.current_timestamp())
    )


# ---------------------------------------------------------------------------------------------
# Stage 2: clean (silver) with a quarantine table for rows that fail validation
# ---------------------------------------------------------------------------------------------
def clean_docs(bronze: DataFrame) -> tuple[DataFrame, DataFrame]:
    def _parse(raw: str | None) -> dict[str, Any]:
        try:
            doc = parse_document(raw or "")
            return {
                **{
                    k: doc.get(k, "")
                    for k in ("id", "title", "classification", "department", "updated", "body")
                },
                "error": None,
            }
        except ValueError as exc:
            return {
                "id": None,
                "title": None,
                "classification": None,
                "department": None,
                "updated": None,
                "body": None,
                "error": str(exc),
            }

    parse_udf = F.udf(_parse, _PARSED)
    hash_udf = F.udf(content_hash, T.StringType())
    parsed = bronze.withColumn("p", parse_udf("raw_text")).select(
        "source_file", "ingested_at", "p.*"
    )
    bad = parsed.where(F.col("error").isNotNull()).select("source_file", "error")
    good = parsed.where(F.col("error").isNull()).drop("error")
    good = good.withColumn("content_hash", hash_udf("body")).withColumn(
        "updated", F.to_date("updated")
    )
    # Deduplicate on content hash, keeping the most recently updated copy of each document.
    w = Window.partitionBy("content_hash").orderBy(F.col("updated").desc(), F.col("id").asc())
    silver = good.withColumn("rn", F.row_number().over(w)).where("rn = 1").drop("rn")
    silver = silver.withColumn("word_count", F.size(F.split("body", r"\s+")))
    return silver, bad


def clean_tickets(bronze: DataFrame) -> tuple[DataFrame, DataFrame]:
    typed = (
        bronze.withColumn("created_at", F.to_timestamp("created_at"))
        .withColumn("resolved_at", F.to_timestamp("resolved_at"))
        .withColumn("requester", F.lower(F.trim("requester")))
    )
    valid = (
        F.col("ticket_id").rlike(r"^INC-\d+$")
        & F.col("priority").isin("P1", "P2", "P3", "P4")
        & F.col("created_at").isNotNull()
    )
    valid = F.coalesce(valid, F.lit(False))
    bad = typed.where(~valid)
    good = typed.where(valid).dropDuplicates(["ticket_id"])
    return good, bad


# ---------------------------------------------------------------------------------------------
# Stage 3 and 4: chunk (silver) and feature/embedding table (gold)
# ---------------------------------------------------------------------------------------------
def chunk_docs(silver: DataFrame) -> DataFrame:
    def _chunks(id_: str, title: str, cls: str, dept: str, body: str) -> list[dict[str, Any]]:
        return make_chunks(
            {"id": id_, "title": title, "classification": cls, "department": dept, "body": body}
        )

    chunk_udf = F.udf(_chunks, T.ArrayType(_CHUNK))
    return (
        silver.withColumn(
            "c", F.explode(chunk_udf("id", "title", "classification", "department", "body"))
        )
        .select("c.*", "content_hash")
        .withColumn("word_count", F.size(F.split("text", r"\s+")))
    )


def embed_chunks(chunks: DataFrame) -> DataFrame:
    """Gold feature table: chunk text, metadata, simple features and the embedding vector."""
    embedder = HashingEmbedder(DIM)

    @F.pandas_udf(T.ArrayType(T.FloatType()))  # type: ignore[untyped-decorator,attr-defined]
    def embed(texts: pd.Series) -> pd.Series:
        vecs = embedder.embed([str(t) for t in texts])
        return pd.Series([v.tolist() for v in vecs])

    return (
        chunks.withColumn("embed_text", F.concat_ws(". ", "title", "text"))
        .withColumn("embedding", embed("embed_text"))
        .withColumn("embedding_model", F.lit(f"hashing-{DIM}"))
        .withColumn("has_numbers", F.col("text").rlike(r"\d"))
        .drop("embed_text")
    )


def ticket_stats(silver: DataFrame) -> DataFrame:
    hours = (F.unix_timestamp("resolved_at") - F.unix_timestamp("created_at")) / 3600.0
    return (
        silver.withColumn("resolution_hours", hours)
        .groupBy("category", "priority")
        .agg(
            F.count("*").alias("tickets"),
            F.round(F.avg("resolution_hours"), 2).alias("avg_resolution_hours"),
            F.sum(F.when(F.col("status").isin("open", "in_progress"), 1).otherwise(0)).alias(
                "open_tickets"
            ),
        )
        .orderBy("category", "priority")
    )


# ---------------------------------------------------------------------------------------------
# Orchestration of the whole job
# ---------------------------------------------------------------------------------------------
def run(
    raw: Path, lakehouse: Path, export: Path | None, spark: SparkSession | None = None
) -> dict[str, Any]:
    own = spark is None
    spark = spark or get_spark()
    fmt = _fmt(spark)
    if lakehouse.exists():
        shutil.rmtree(lakehouse)

    bronze_docs = ingest_docs(spark, raw)
    _write(bronze_docs, lakehouse / "bronze" / "docs", fmt)
    bronze_docs = spark.read.format(fmt).load(str(lakehouse / "bronze" / "docs"))
    silver_docs, quarantine_docs = clean_docs(bronze_docs)
    _write(silver_docs, lakehouse / "silver" / "docs", fmt)
    _write(quarantine_docs, lakehouse / "quarantine" / "docs", fmt)

    silver_docs = spark.read.format(fmt).load(str(lakehouse / "silver" / "docs"))
    silver_chunks = chunk_docs(silver_docs)
    _write(silver_chunks, lakehouse / "silver" / "chunks", fmt)
    gold = embed_chunks(spark.read.format(fmt).load(str(lakehouse / "silver" / "chunks")))
    _write(gold, lakehouse / "gold" / "chunks", fmt)

    bronze_t = ingest_tickets(spark, raw)
    _write(bronze_t, lakehouse / "bronze" / "tickets", fmt)
    silver_t, quarantine_t = clean_tickets(
        spark.read.format(fmt).load(str(lakehouse / "bronze" / "tickets"))
    )
    _write(silver_t, lakehouse / "silver" / "tickets", fmt)
    _write(quarantine_t, lakehouse / "quarantine" / "tickets", fmt)
    stats = ticket_stats(spark.read.format(fmt).load(str(lakehouse / "silver" / "tickets")))
    _write(stats, lakehouse / "gold" / "ticket_stats", fmt)

    gold_df = spark.read.format(fmt).load(str(lakehouse / "gold" / "chunks"))
    metrics: dict[str, Any] = {
        "format": fmt,
        "spark_version": spark.version,
        "docs_ingested": spark.read.format(fmt).load(str(lakehouse / "bronze" / "docs")).count(),
        "docs_clean": spark.read.format(fmt).load(str(lakehouse / "silver" / "docs")).count(),
        "docs_quarantined": spark.read.format(fmt)
        .load(str(lakehouse / "quarantine" / "docs"))
        .count(),
        "chunks": gold_df.count(),
        "embedding_dim": DIM,
        "tickets_ingested": spark.read.format(fmt)
        .load(str(lakehouse / "bronze" / "tickets"))
        .count(),
        "tickets_clean": spark.read.format(fmt).load(str(lakehouse / "silver" / "tickets")).count(),
        "tickets_quarantined": spark.read.format(fmt)
        .load(str(lakehouse / "quarantine" / "tickets"))
        .count(),
        "classifications": sorted(
            r[0]
            for r in gold_df.select("classification").distinct().collect()
            if r[0] in VALID_CLASSES
        ),
    }
    metrics["tickets_duplicates_removed"] = (
        metrics["tickets_ingested"] - metrics["tickets_clean"] - metrics["tickets_quarantined"]
    )
    if export is not None:
        export.mkdir(parents=True, exist_ok=True)
        _pdf(gold_df.orderBy("chunk_id")).to_parquet(export / "chunks.parquet", index=False)
        _pdf(
            spark.read.format(fmt).load(str(lakehouse / "silver" / "tickets")).orderBy("ticket_id")
        ).to_parquet(export / "tickets.parquet", index=False)
        _pdf(stats).to_csv(export / "ticket_stats.csv", index=False)
        (export / "pipeline_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    if own:
        spark.stop()
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--lakehouse", type=Path, default=Path("lakehouse"))
    ap.add_argument("--export", type=Path, default=Path("artifacts/gold"))
    ns = ap.parse_args()
    print(json.dumps(run(ns.raw, ns.lakehouse, ns.export), indent=2))


if __name__ == "__main__":
    main()
