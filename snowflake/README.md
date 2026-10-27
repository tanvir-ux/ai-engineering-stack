# Snowflake

> **Status: parsed and tested offline, not executed.** The SQL has not been run in a Snowflake account. What is checked in CI: every file in [`sql/`](sql) parses with `sqlglot` (Snowflake dialect); the dbt models render and their results are compared with the PySpark gold table by running them in DuckDB; the role-to-classification map in the governance script matches `src/aistack/auth/policy.py`; and the Python loader runs against a fake Snowpark session. See `tests/test_snowflake.py` (12 tests).

## Files

| File | Purpose |
| --- | --- |
| `sql/00_setup.sql` | Warehouse, database and schemas |
| `sql/01_stage_and_load.sql` | Internal stage and Parquet load of the gold files |
| `sql/02_vector_table.sql` | A table with a native `VECTOR(FLOAT, 384)` column |
| `sql/03_governance.sql` | A row access policy: a role only sees chunks of classifications it was granted. This is the same rule the app enforces |
| `sql/04_search.sql` | Cosine search in SQL, filtered before ranking |
| `dbt/` | Staging and mart models for ticket statistics, with schema tests |
| `../src/aistack/data/snowflake_pipeline.py` | Python loader and parameterised search (values are bound, never concatenated) |

## How to run it yourself

A Snowflake trial account works.

```bash
# 1. Create the objects, then upload the gold files
snow sql -f snowflake/sql/00_setup.sql
snow sql -q "PUT file://artifacts/gold/chunks.parquet  @MERIDIAN.RAW.GOLD_STAGE AUTO_COMPRESS=FALSE"
snow sql -q "PUT file://artifacts/gold/tickets.parquet @MERIDIAN.RAW.GOLD_STAGE AUTO_COMPRESS=FALSE"
snow sql -f snowflake/sql/01_stage_and_load.sql
snow sql -f snowflake/sql/02_vector_table.sql
snow sql -f snowflake/sql/03_governance.sql

# 2. dbt (credentials from the environment, never from a file in the repo)
cp snowflake/dbt/profiles.yml.example ~/.dbt/profiles.yml
export SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...
cd snowflake/dbt && dbt build
```

Role names in the scripts are placeholders (`MERIDIAN_*`). If a statement fails on a live account, that is new information, because this path has not yet been run.
