# Databricks

> **Status: validated offline, not executed.** The bundle passes `databricks bundle validate` against a local stub of the workspace API (`python scripts/validate_bundle.py`, also run in CI). I have not deployed it to a Databricks workspace or run the job there. The same transformation code does run locally on PySpark and Delta (see the Spark tests).

## What it deploys

[`databricks.yml`](databricks.yml) and [`resources/lakehouse.yml`](resources/lakehouse.yml) define, under Unity Catalog:

- a schema (`meridian`, or `meridian_dev` for the dev target) and a volume `raw` for landing files;
- a job, `meridian-lakehouse-refresh`, on serverless compute, with two tasks: `build_tables` (a Python wheel task that runs `aistack-lakehouse`) and `explore_gold` (a notebook with sanity checks). The schedule is defined but **paused**.

The job reads the synthetic documents and tickets, cleans them (bad records go to a quarantine table), removes duplicates, chunks the text, embeds it and writes bronze, silver and gold Delta tables. The logic lives in [`src/aistack/data/`](../src/aistack/data). A small table-namer maps the same job to local Delta paths or to `catalog.schema.table` names, which is why the local tests cover the Databricks code path.

## How to run it yourself

You need a Databricks workspace (the free edition is enough for serverless) and the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html).

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com
cd databricks
databricks bundle validate -t dev
databricks bundle deploy -t dev           # builds the wheel with `uv build`, creates the schema, volume and job
databricks fs cp -r ../data/raw dbfs:/Volumes/main/meridian_dev/raw   # upload the synthetic inputs
databricks bundle run lakehouse_refresh -t dev
```

Credentials come from your CLI profile. None are stored in this repository. If something fails on a live workspace, that is new information: please open an issue with the error, because this path has not yet been run.
