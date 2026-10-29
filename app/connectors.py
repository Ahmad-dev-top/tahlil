"""Database connectors: snapshot tables from Postgres / MySQL (or SQLite in dev) into a
DuckDB dataset. The agent then works on the snapshot, so it can never touch the source DB.

Why a snapshot instead of a live connection:
- the source DB never sees agent-written SQL (zero risk to production data)
- the same guards, read-only DuckDB and sandbox apply to every data source
- predictable cost: one bounded import, then fast local queries
Use a read-only DB user anyway (defence in depth)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from . import db
from .config import settings

# backend name -> extra connect args
_BACKENDS = {
    "postgresql": {"connect_timeout": 10, "options": "-c default_transaction_read_only=on"},
    "mysql": {"connect_timeout": 10},
    "mariadb": {"connect_timeout": 10},
    "sqlite": {},
}


class ConnectorError(ValueError):
    pass


@dataclass
class ImportResult:
    dataset_id: str
    tables: list[str]
    source_label: str  # URL with password removed, safe to store/show
    truncated: list[str] = field(default_factory=list)  # tables that hit the row limit


def _check_url(url: str):
    try:
        u = make_url(url)
    except ArgumentError as e:
        raise ConnectorError(f"Invalid database URL: {e}") from e
    backend = u.get_backend_name()
    if backend not in _BACKENDS:
        raise ConnectorError(f"Unsupported database '{backend}'. Use postgresql or mysql.")
    if backend == "sqlite" and not settings.allow_sqlite_connector:
        # SQLite URLs are file paths on the SERVER: never allow in production.
        raise ConnectorError("SQLite connections are disabled on this server.")
    allowed = settings.connector_allowed_hosts
    if backend != "sqlite" and allowed and (u.host or "").lower() not in allowed:
        raise ConnectorError(f"Host '{u.host}' is not in CONNECTOR_ALLOWED_HOSTS.")
    return u, backend


def _public_error(exc: BaseException, secret: str | None) -> str:
    """One line for the API. Never include the database password."""
    text = str(exc).splitlines()[0][:300]
    if secret:
        text = text.replace(secret, "***")
    return text


def _coerce_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Decimal and date columns arrive as object from some drivers. DuckDB would
    store those as VARCHAR, so convert them before the snapshot is written."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype != object:
            continue
        values = [v for v in out[col].tolist() if v is not None and not pd.isna(v)]
        if not values:
            continue
        if all(isinstance(v, Decimal) for v in values):
            out[col] = out[col].map(lambda v: float(v) if isinstance(v, Decimal) else pd.NA)
        elif all(isinstance(v, datetime) for v in values):
            out[col] = pd.to_datetime(out[col])
        elif all(isinstance(v, date) for v in values):
            out[col] = pd.to_datetime(out[col])
    return out


def import_database(url: str, schema: str | None = None, tables: list[str] | None = None,
                    row_limit: int | None = None, dataset_id: str | None = None) -> ImportResult:
    u, backend = _check_url(url)
    secret = u.password
    row_limit = row_limit or settings.connector_row_limit
    engine = create_engine(u, connect_args=_BACKENDS[backend], pool_pre_ping=True)
    try:
        try:
            available = inspect(engine).get_table_names(schema=schema)
        except Exception as e:
            raise ConnectorError(f"Could not connect: {_public_error(e, secret)}") from e
        if tables:
            missing = sorted(set(tables) - set(available))
            if missing:
                raise ConnectorError(f"Tables not found: {missing}")
            chosen = tables
        else:
            chosen = available
        if not chosen:
            raise ConnectorError("No tables found.")
        if len(chosen) > settings.connector_max_tables:
            raise ConnectorError(
                f"{len(chosen)} tables found; pick at most {settings.connector_max_tables} with 'tables'.")

        frames: dict[str, pd.DataFrame] = {}
        truncated = []
        with engine.connect() as conn:
            for name in chosen:
                table = Table(name, MetaData(), schema=schema, autoload_with=conn)
                df = _coerce_frame(pd.read_sql(select(table).limit(row_limit), conn))
                frames[name] = df
                if len(df) >= row_limit:
                    truncated.append(name)
    except ConnectorError:
        raise
    except Exception as e:
        raise ConnectorError(f"Could not connect: {_public_error(e, secret)}") from e
    finally:
        engine.dispose()

    ds_id, created = db.create_dataset_from_frames(frames, dataset_id=dataset_id)
    return ImportResult(ds_id, created, u.render_as_string(hide_password=True), truncated)
