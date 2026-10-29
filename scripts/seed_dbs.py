"""Load sample_data/sales.csv into local Postgres and MySQL for connector tests.

Postgres (superuser postgres/postgres, database sales):
  public.sales
  analytics.sales_2025
MySQL (root/root, database shop):
  shop.sales

Both get a SELECT-only user readonly / ro-secret.
Prices are NUMERIC(12,2) and order_date is DATE.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import pymysql
import psycopg

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "sample_data" / "sales.csv"

PG = dict(host="127.0.0.1", port=5432, user="postgres", password="postgres", dbname="sales")
MY = dict(host="127.0.0.1", port=3306, user="root", password="root", database="shop")
RO_PASSWORD = "ro-secret"

COLUMNS = (
    "order_id", "order_date", "region", "channel", "category", "product",
    "units", "unit_price_pkr", "revenue_pkr",
)

PG_DDL = """
CREATE TABLE {table} (
    order_id VARCHAR(32) PRIMARY KEY,
    order_date DATE NOT NULL,
    region VARCHAR(64) NOT NULL,
    channel VARCHAR(64) NOT NULL,
    category VARCHAR(64) NOT NULL,
    product VARCHAR(64) NOT NULL,
    units INTEGER NOT NULL,
    unit_price_pkr NUMERIC(12, 2) NOT NULL,
    revenue_pkr NUMERIC(12, 2) NOT NULL
)
"""

MY_DDL = """
CREATE TABLE sales (
    order_id VARCHAR(32) PRIMARY KEY,
    order_date DATE NOT NULL,
    region VARCHAR(64) NOT NULL,
    channel VARCHAR(64) NOT NULL,
    category VARCHAR(64) NOT NULL,
    product VARCHAR(64) NOT NULL,
    units INTEGER NOT NULL,
    unit_price_pkr DECIMAL(12, 2) NOT NULL,
    revenue_pkr DECIMAL(12, 2) NOT NULL
) ENGINE=InnoDB
"""


def _rows() -> list[tuple]:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return [
            (
                r["order_id"], r["order_date"], r["region"], r["channel"], r["category"],
                r["product"], int(r["units"]), r["unit_price_pkr"], r["revenue_pkr"],
            )
            for r in csv.DictReader(f)
        ]


def _wait(connect, label: str, attempts: int = 60):
    last = None
    for _ in range(attempts):
        try:
            conn = connect()
            conn.close()
            return
        except Exception as e:  # servers print a few lines while they boot
            last = e
            time.sleep(2)
    raise RuntimeError(f"{label} did not accept connections: {last}") from last


def seed_postgres(rows: list[tuple]) -> None:
    _wait(lambda: psycopg.connect(**PG), "Postgres")
    with psycopg.connect(**PG, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        for table in ("public.sales", "analytics.sales_2025"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(PG_DDL.format(table=table))
        with conn.cursor() as cur:
            for table in ("public.sales", "analytics.sales_2025"):
                cur.executemany(
                    f"INSERT INTO {table} ({', '.join(COLUMNS)}) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )
        conn.execute(
            f"""
            DO $$ BEGIN
              CREATE ROLE readonly LOGIN PASSWORD '{RO_PASSWORD}';
            EXCEPTION WHEN duplicate_object THEN
              ALTER ROLE readonly WITH LOGIN PASSWORD '{RO_PASSWORD}';
            END $$;
            """
        )
        conn.execute("GRANT CONNECT ON DATABASE sales TO readonly")
        conn.execute("GRANT USAGE ON SCHEMA public, analytics TO readonly")
        conn.execute("GRANT SELECT ON public.sales, analytics.sales_2025 TO readonly")
    print(f"postgres: {len(rows)} rows in public.sales and analytics.sales_2025")


def seed_mysql(rows: list[tuple]) -> None:
    def connect():
        return pymysql.connect(**MY)

    _wait(connect, "MySQL")
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE DATABASE IF NOT EXISTS shop")
            cur.execute("USE shop")
            cur.execute("DROP TABLE IF EXISTS sales")
            cur.execute(MY_DDL)
            cur.executemany(
                f"INSERT INTO sales ({', '.join(COLUMNS)}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
            cur.execute(f"CREATE USER IF NOT EXISTS 'readonly'@'%' IDENTIFIED BY '{RO_PASSWORD}'")
            cur.execute(f"ALTER USER 'readonly'@'%' IDENTIFIED BY '{RO_PASSWORD}'")
            cur.execute("GRANT SELECT ON shop.* TO 'readonly'@'%'")
            cur.execute("FLUSH PRIVILEGES")
        conn.commit()
    finally:
        conn.close()
    print(f"mysql: {len(rows)} rows in shop.sales")


def main() -> None:
    rows = _rows()
    seed_postgres(rows)
    seed_mysql(rows)


if __name__ == "__main__":
    main()
