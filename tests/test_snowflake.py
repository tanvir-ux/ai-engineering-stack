"""Snowflake layer: SQL syntax (sqlglot), dbt models rendered and EXECUTED locally in DuckDB,
and the Snowpark helpers against a recording fake session. Nothing here touches a live account."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb
import jinja2
import numpy as np
import pandas as pd
import pytest
import sqlglot
from sqlglot import exp

from aistack.auth.policy import ROLE_CLASSES
from aistack.config import REPO_ROOT
from aistack.data.snowflake_pipeline import SnowflakeStore, load_gold, search_sql
from aistack.retrieval.embedding import HashingEmbedder

SQL_FILES = sorted((REPO_ROOT / "snowflake" / "sql").glob("*.sql"))
DBT = REPO_ROOT / "snowflake" / "dbt" / "models"
# sqlglot does not know Cortex Search DDL or row access policies for every statement type; those
# statements are checked structurally below instead of being parsed.
UNPARSED = ("CREATE OR REPLACE CORTEX SEARCH SERVICE", "CREATE OR REPLACE ROW ACCESS POLICY")


def _statements(text: str) -> list[str]:
    text = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_sql_files_parse_as_snowflake(path: Path) -> None:
    stmts = _statements(path.read_text())
    assert stmts
    for s in stmts:
        if s.startswith(UNPARSED) or s.startswith(("PUT ", "ALTER TABLE CHUNKS ADD ROW")):
            continue
        parsed = sqlglot.parse_one(s, read="snowflake")
        assert parsed is not None, s


def test_cortex_and_policy_statements_are_present() -> None:
    search = (REPO_ROOT / "snowflake/sql/04_search.sql").read_text()
    assert "CREATE OR REPLACE CORTEX SEARCH SERVICE" in search and "TARGET_LAG" in search
    assert "VECTOR_COSINE_SIMILARITY" in search
    gov = (REPO_ROOT / "snowflake/sql/03_governance.sql").read_text()
    assert "ROW ACCESS POLICY CHUNK_ACL" in gov and "IS_ROLE_IN_SESSION" in gov


def test_snowflake_acl_table_matches_application_policy() -> None:
    gov = (REPO_ROOT / "snowflake/sql/03_governance.sql").read_text()
    pairs = set(re.findall(r"\('MERIDIAN_([A-Z]+)', '([a-z]+)'\)", gov))
    expected = {(r.upper(), c) for r, classes in ROLE_CLASSES.items() for c in classes}
    assert pairs == expected


def _render(name: str, refs: dict[str, str]) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    tpl = env.from_string((DBT / name).read_text())
    return tpl.render(
        source=lambda _src, table: table,
        ref=lambda model: refs[model],
    )


def test_dbt_models_render_and_parse() -> None:
    stg = _render("staging/stg_tickets.sql", {})
    mart = _render("marts/ticket_stats.sql", {"stg_tickets": "stg_tickets"})
    for sql in (stg, mart):
        tree = sqlglot.parse_one(sql, read="snowflake")
        assert tree.find(exp.Select)


def test_dbt_ticket_stats_equals_pyspark_gold_table() -> None:
    """Run the Snowflake-dialect dbt SQL in DuckDB over the real gold tickets and compare it with
    the PySpark `ticket_stats` output. Same rows, same numbers, two engines."""
    gold = REPO_ROOT / "artifacts" / "gold"
    con = duckdb.connect()
    con.execute(f"CREATE TABLE tickets AS SELECT * FROM read_parquet('{gold / 'tickets.parquet'}')")
    stg = _render("staging/stg_tickets.sql", {})
    mart = _render("marts/ticket_stats.sql", {"stg_tickets": "stg_tickets"})
    # DuckDB has no REGEXP_LIKE full-match semantics identical to Snowflake, so transpile.
    duck_stg = sqlglot.transpile(stg, read="snowflake", write="duckdb")[0]
    duck_mart = sqlglot.transpile(mart, read="snowflake", write="duckdb")[0]
    con.execute(f"CREATE VIEW stg_tickets AS {duck_stg}")
    got = con.execute(duck_mart).df()
    want = pd.read_csv(gold / "ticket_stats.csv")
    got = got.sort_values(["category", "priority"]).reset_index(drop=True)
    want = want.sort_values(["category", "priority"]).reset_index(drop=True)
    assert len(got) == len(want)
    assert got["tickets"].tolist() == want["tickets"].tolist()
    assert got["open_tickets"].tolist() == want["open_tickets"].tolist()
    np.testing.assert_allclose(
        got["avg_resolution_hours"].astype(float), want["avg_resolution_hours"], atol=0.011
    )


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def collect(self) -> list[dict[str, Any]]:
        return self._rows


class FakeSession:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.queries: list[tuple[str, list[Any] | None]] = []
        self.written: dict[str, pd.DataFrame] = {}
        self.rows = rows or []

    def sql(self, query: str, params: list[Any] | None = None) -> _Rows:
        self.queries.append((query, params))
        return _Rows(self.rows)

    def write_pandas(self, df: pd.DataFrame, table_name: str, **kwargs: Any) -> None:
        self.written[table_name] = df


def test_search_sql_is_parameterised_and_parses() -> None:
    q = search_sql(2)
    assert q.count("?") == 4 and "'" not in q
    sqlglot.parse_one(q, read="snowflake")
    with pytest.raises(ValueError):
        search_sql(0)


def test_store_binds_parameters_and_fails_closed() -> None:
    row = {
        "CHUNK_ID": "a#0", "DOC_ID": "a", "TITLE": "t", "CLASSIFICATION": "hr",
        "DEPARTMENT": "d", "TEXT": "x", "SCORE": 0.5,
    }  # fmt: skip
    sess = FakeSession([row])
    store = SnowflakeStore(sess, HashingEmbedder())
    hits = store.search("vacation", k=3, allowed_classes={"public", "hr"})
    assert hits[0].chunk.chunk_id == "a#0" and hits[0].sources == ("snowflake",)
    _, params = sess.queries[0]
    assert params is not None and len(json.loads(params[0])) == 384
    assert params[1:] == ["hr", "public", 3]
    assert store.search("x", allowed_classes=set()) == []
    assert len(sess.queries) == 1  # the empty set never reached Snowflake
    with pytest.raises(ValueError):
        store.search("x")


def test_load_gold_writes_both_tables() -> None:
    sess = FakeSession()
    out = load_gold(sess, REPO_ROOT / "artifacts" / "gold")
    assert out == {"chunks": 65, "tickets": 300}
    assert {"CHUNKS_LOAD", "TICKETS"} <= set(sess.written)
    assert "EMBEDDING" in sess.written["CHUNKS_LOAD"].columns
    assert isinstance(sess.written["CHUNKS_LOAD"]["EMBEDDING"].iloc[0], list)
    assert "INSERT OVERWRITE INTO CHUNKS" in sess.queries[0][0]
