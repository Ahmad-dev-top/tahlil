import dataclasses
import sqlite3

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app import connectors
from app.api import app, limiter
from app.connectors import ConnectorError, import_database
from tests.conftest import SAMPLE

client = TestClient(app)


@pytest.fixture()
def source_db(tmp_path):
    """A small 'production' database to import from."""
    path = tmp_path / "shop.db"
    con = sqlite3.connect(path)
    pd.read_csv(SAMPLE).to_sql("orders", con, index=False)
    pd.DataFrame({"region": ["Punjab", "Sindh"], "manager": ["Ali", "Sara"]}).to_sql("regions", con, index=False)
    con.close()
    return f"sqlite:///{path}"


def test_import_all_tables(source_db):
    res = import_database(source_db)
    assert sorted(res.tables) == ["orders", "regions"] and res.truncated == []


def test_import_selected_tables_with_row_limit(source_db):
    res = import_database(source_db, tables=["orders"], row_limit=100)
    assert res.tables == ["orders"] and res.truncated == ["orders"]


def test_refresh_rebuilds_in_place(source_db):
    first = import_database(source_db, tables=["regions"])
    again = import_database(source_db, tables=["orders"], dataset_id=first.dataset_id)
    assert again.dataset_id == first.dataset_id and again.tables == ["orders"]


@pytest.mark.parametrize("url,msg", [
    ("not a url", "Invalid database URL"),
    ("mssql+pyodbc://u:p@host/db", "Unsupported database"),
])
def test_bad_urls_rejected(url, msg):
    with pytest.raises(ConnectorError, match=msg):
        import_database(url)


def test_missing_table_rejected(source_db):
    with pytest.raises(ConnectorError, match="Tables not found"):
        import_database(source_db, tables=["nope"])


def test_sqlite_blocked_unless_enabled(source_db, monkeypatch):
    monkeypatch.setattr(connectors, "settings", dataclasses.replace(connectors.settings, allow_sqlite_connector=False))
    with pytest.raises(ConnectorError, match="disabled"):
        import_database(source_db)


def test_host_allow_list(monkeypatch):
    monkeypatch.setattr(connectors, "settings", dataclasses.replace(
        connectors.settings, connector_allowed_hosts=frozenset({"db.internal"})))
    with pytest.raises(ConnectorError, match="not in CONNECTOR_ALLOWED_HOSTS"):
        import_database("postgresql://u:p@evil.example.com/db")


def test_connect_endpoint_then_ask(source_db):
    r = client.post("/datasets/connect", json={"url": source_db, "tables": ["orders"], "name": "Shop DB"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "sql" and body["tables"] == ["orders"]
    r = client.post("/ask", json={"dataset_id": body["dataset_id"], "question": "Show me the data"})
    assert r.json()["status"] == "ok"
    r = client.post(f"/datasets/{body['dataset_id']}/refresh", json={"url": source_db, "tables": ["regions"]})
    assert r.status_code == 200 and r.json()["tables"] == ["regions"]


def test_decimal_and_date_columns_are_coerced():
    from datetime import date
    from decimal import Decimal
    df = pd.DataFrame({
        "unit_price_pkr": [Decimal("10.50"), Decimal("2.00")],
        "order_date": [date(2025, 1, 1), date(2025, 2, 1)],
        "region": ["Punjab", "Sindh"],
    })
    out = connectors._coerce_frame(df)
    assert str(out["unit_price_pkr"].dtype).startswith("float")
    assert "datetime" in str(out["order_date"].dtype)
    assert out["region"].tolist() == ["Punjab", "Sindh"]


def test_connection_error_hides_password():
    text = connectors._public_error(RuntimeError("login failed for secret-pw"), "secret-pw")
    assert "secret-pw" not in text and "***" in text


def test_password_never_stored(source_db, monkeypatch):
    def fake_import(url, *a, **k):
        return connectors.ImportResult("abcdef123456", ["t"], "postgresql://admin:***@db/x")
    monkeypatch.setattr(api_module, "import_database", fake_import)
    monkeypatch.setattr(api_module.db, "describe_schema", lambda ds: "")
    r = client.post("/datasets/connect", json={"url": "postgresql://admin:s3cret@db/x"})
    assert "s3cret" not in r.text


def test_api_key_required_when_configured(monkeypatch):
    monkeypatch.setattr(api_module, "settings", dataclasses.replace(api_module.settings, api_keys=frozenset({"k1"})))
    assert client.get("/health").status_code == 200           # public
    assert client.get("/datasets").status_code == 401
    assert client.get("/datasets", headers={"X-API-Key": "bad"}).status_code == 401
    assert client.get("/datasets", headers={"X-API-Key": "k1"}).status_code == 200


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(api_module, "settings", dataclasses.replace(api_module.settings, asks_per_minute=2))
    limiter._hits.clear()
    body = {"dataset_id": "ffffffffffff", "question": "hello"}  # 404 after the limiter, still counts
    codes = [client.post("/ask", json=body).status_code for _ in range(3)]
    assert codes == [404, 404, 429]
    limiter._hits.clear()
