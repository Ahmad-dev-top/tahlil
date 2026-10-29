"""App metadata in SQLite: datasets, conversations and turns.
(The data itself lives in per-dataset DuckDB files, see db.py.)"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings

_DB_PATH = settings.data_dir / "tahlil.sqlite"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,            -- csv | sql
    source_label TEXT,               -- filenames, or DB URL with password removed
    tables_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    title TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    question TEXT NOT NULL,
    status TEXT,
    sql TEXT,
    report TEXT,
    verified INTEGER,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_conv ON turns(conversation_id, created_at);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- datasets ----------

def add_dataset(dataset_id: str, name: str, source: str, source_label: str, tables: list[str]) -> dict:
    row = dict(id=dataset_id, name=name, source=source, source_label=source_label,
               tables_json=json.dumps(tables), created_at=time.time())
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO datasets VALUES (:id,:name,:source,:source_label,:tables_json,:created_at)", row)
    return _dataset_out(row)


def get_dataset(dataset_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    return _dataset_out(dict(r)) if r else None


def list_datasets() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM datasets ORDER BY created_at DESC").fetchall()
    return [_dataset_out(dict(r)) for r in rows]


def _dataset_out(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "source": r["source"], "source_label": r["source_label"],
            "tables": json.loads(r["tables_json"]), "created_at": r["created_at"]}


# ---------- conversations ----------

def create_conversation(dataset_id: str, title: str = "New analysis") -> dict:
    row = dict(id=_new_id(), dataset_id=dataset_id, title=title[:120], created_at=time.time())
    with _conn() as con:
        con.execute("INSERT INTO conversations VALUES (:id,:dataset_id,:title,:created_at)", row)
    return row


def get_conversation(conversation_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return dict(r) if r else None


def list_conversations(dataset_id: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM conversations", ()
    if dataset_id:
        q, args = q + " WHERE dataset_id=?", (dataset_id,)
    with _conn() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY created_at DESC", args).fetchall()]


def add_turn(conversation_id: str, payload: dict[str, Any]) -> str:
    turn_id = _new_id()
    with _conn() as con:
        con.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
            (turn_id, conversation_id, payload["question"], payload.get("status"), payload.get("sql"),
             payload.get("report"), int(bool(payload.get("verified"))), json.dumps(payload, default=str), time.time()),
        )
        # First question becomes the conversation title.
        n = con.execute("SELECT COUNT(*) FROM turns WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
        if n == 1:
            con.execute("UPDATE conversations SET title=? WHERE id=?", (payload["question"][:120], conversation_id))
    return turn_id


def list_turns(conversation_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT id, payload_json, created_at FROM turns WHERE conversation_id=? ORDER BY created_at",
                           (conversation_id,)).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"], **json.loads(r["payload_json"])} for r in rows]


def history_for_prompt(conversation_id: str, limit: int = 5) -> list[dict]:
    """Compact view of the last successful turns, fed to the planner and SQL writer."""
    with _conn() as con:
        rows = con.execute(
            "SELECT question, sql, report FROM turns WHERE conversation_id=? AND status='ok' "
            "ORDER BY created_at DESC LIMIT ?", (conversation_id, limit)).fetchall()
    return [{"question": r["question"], "sql": r["sql"], "answer": (r["report"] or "")[:400]} for r in reversed(rows)]
