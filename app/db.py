"""Datasets: uploaded CSVs are loaded into a per-dataset DuckDB file.
Queries always open that file READ-ONLY, so even a guard bypass cannot modify data."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from .config import settings

_SAFE_NAME = re.compile(r"[^a-z0-9_]")


def _table_name(filename: str) -> str:
    name = _SAFE_NAME.sub("_", Path(filename).stem.lower()).strip("_") or "data"
    return f"t_{name}" if name[0].isdigit() else name


def dataset_dir(dataset_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", dataset_id):
        raise ValueError("invalid dataset id")
    return settings.data_dir / dataset_id


def create_dataset(files: dict[str, bytes]) -> tuple[str, list[str]]:
    """files: {filename: csv_bytes}. Returns (dataset_id, table_names)."""
    dataset_id = uuid.uuid4().hex[:12]
    ddir = dataset_dir(dataset_id)
    ddir.mkdir(parents=True)
    tables = []
    con = duckdb.connect(str(ddir / "db.duckdb"))
    try:
        for fname, content in files.items():
            raw = ddir / f"{_table_name(fname)}.csv"
            raw.write_bytes(content)
            table = _table_name(fname)
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto(?)", [str(raw)])
            tables.append(table)
    finally:
        con.close()
    return dataset_id, tables


def create_dataset_from_frames(frames: dict[str, pd.DataFrame], dataset_id: str | None = None) -> tuple[str, list[str]]:
    """frames: {table_name: DataFrame}. Used by DB connectors. Passing an existing
    dataset_id rebuilds that dataset in place (refresh)."""
    dataset_id = dataset_id or uuid.uuid4().hex[:12]
    ddir = dataset_dir(dataset_id)
    ddir.mkdir(parents=True, exist_ok=True)
    tmp = ddir / "db.duckdb.tmp"
    tmp.unlink(missing_ok=True)
    tables = []
    con = duckdb.connect(str(tmp))
    try:
        for name, frame in frames.items():
            table = _table_name(name)
            con.register("incoming", frame)
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM incoming")
            con.unregister("incoming")
            tables.append(table)
    finally:
        con.close()
    tmp.replace(ddir / "db.duckdb")  # atomic swap so readers never see a half-built DB
    return dataset_id, tables


def _connect_ro(dataset_id: str) -> duckdb.DuckDBPyConnection:
    path = dataset_dir(dataset_id) / "db.duckdb"
    if not path.exists():
        raise FileNotFoundError(f"dataset {dataset_id} not found")
    return duckdb.connect(str(path), read_only=True)


def list_tables(dataset_id: str) -> list[str]:
    con = _connect_ro(dataset_id)
    try:
        return [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    finally:
        con.close()


def describe_schema(dataset_id: str, sample_rows: int = 3) -> str:
    """Compact schema text for prompts: columns, types, and a few sample rows per table."""
    con = _connect_ro(dataset_id)
    out = []
    try:
        for (table,) in con.execute("SHOW TABLES").fetchall():
            cols = con.execute(f"DESCRIBE {table}").fetchall()
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            out.append(f"TABLE {table} ({n} rows)")
            out += [f"  {c[0]}: {c[1]}" for c in cols]
            sample = con.execute(f"SELECT * FROM {table} LIMIT {sample_rows}").df()
            out.append("  sample:\n" + "\n".join("    " + l for l in sample.to_string(index=False).splitlines()))
    finally:
        con.close()
    return "\n".join(out)


def run_query(dataset_id: str, sql: str) -> pd.DataFrame:
    con = _connect_ro(dataset_id)
    try:
        return con.execute(f"SELECT * FROM ({sql.rstrip().rstrip(';')}) LIMIT {settings.max_result_rows}").df()
    finally:
        con.close()
