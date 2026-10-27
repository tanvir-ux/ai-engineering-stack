# Databricks notebook source
# MAGIC %md
# MAGIC # Meridian gold tables
# MAGIC Quick sanity checks after the `build_tables` task. Not executed against a live workspace
# MAGIC by the author of this repo.

# COMMAND ----------

dbutils.widgets.text("catalog", "main")  # type: ignore[name-defined]  # noqa: F821
dbutils.widgets.text("schema", "meridian")  # type: ignore[name-defined]  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # type: ignore[name-defined]  # noqa: F821
schema = dbutils.widgets.get("schema")  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

chunks = spark.table(f"{catalog}.{schema}.gold_chunks")  # type: ignore[name-defined]  # noqa: F821
display(chunks.groupBy("classification").count())  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

stats = spark.table(f"{catalog}.{schema}.gold_ticket_stats")  # type: ignore[name-defined]  # noqa: F821
display(stats.limit(20))  # type: ignore[name-defined]  # noqa: F821
