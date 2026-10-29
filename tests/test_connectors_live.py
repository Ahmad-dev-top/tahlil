"""Live Postgres and MySQL snapshot tests. Skipped unless TAHLIL_LIVE_DB=1.

Start the servers and load them with: python scripts/seed_dbs.py
"""
from __future__ import annotations

import os

import duckdb
import pytest

from app import db, graph
from app.connectors import import_database
from app.llm import FakeLLM

pytestmark = pytest.mark.skipif(
    os.getenv("TAHLIL_LIVE_DB") != "1",
    reason="set TAHLIL_LIVE_DB=1 to import from the seeded Postgres and MySQL servers",
)

SECRET = "ro-secret"
PG_URL = f"postgresql+psycopg://readonly:{SECRET}@127.0.0.1:5432/sales"
MY_URL = f"mysql+pymysql://readonly:{SECRET}@127.0.0.1:3306/shop"


def _types(dataset_id: str, table: str) -> dict[str, str]:
    con = duckdb.connect(str(db.dataset_dir(dataset_id) / "db.duckdb"), read_only=True)
    try:
        rows = con.execute(f"DESCRIBE {table}").fetchall()
    finally:
        con.close()
    return {name: typ.upper() for name, typ, *_rest in rows}


def _assert_snapshot_types(dataset_id: str, table: str) -> None:
    types = _types(dataset_id, table)
    for col in ("unit_price_pkr", "revenue_pkr"):
        assert "VARCHAR" not in types[col]
        assert any(token in types[col] for token in ("DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL"))
    assert any(token in types["order_date"] for token in ("DATE", "TIMESTAMP"))


def _ask(dataset_id: str, table: str) -> None:
    llm = FakeLLM({
        "planner": ["1. Sum revenue by region."],
        "sql": [f"SELECT region, SUM(revenue_pkr) AS revenue FROM {table} GROUP BY 1"],
        "analysis_code": ["import json\nprint(json.dumps({'rows': int(len(df))}))"],
        "report": ["Done."],
    })
    state = graph.ask(dataset_id, "Revenue by region", llm)
    assert state["status"] == "ok"


def _import_checks(url: str, all_tables: list[str], one: str) -> None:
    everything = import_database(url)
    assert sorted(everything.tables) == sorted(all_tables)
    assert SECRET not in everything.source_label

    selected = import_database(url, tables=[one])
    assert selected.tables == [one]
    assert SECRET not in selected.source_label

    limited = import_database(url, tables=[one], row_limit=100)
    assert limited.truncated == [one]
    _assert_snapshot_types(limited.dataset_id, one)
    _ask(limited.dataset_id, one)


def test_postgres_public_and_analytics_schema():
    _import_checks(PG_URL, ["sales"], "sales")
    analytics = import_database(PG_URL, schema="analytics")
    assert analytics.tables == ["sales_2025"]
    assert SECRET not in analytics.source_label
    _assert_snapshot_types(analytics.dataset_id, "sales_2025")
    _ask(analytics.dataset_id, "sales_2025")


def test_mysql_shop_sales():
    _import_checks(MY_URL, ["sales"], "sales")
