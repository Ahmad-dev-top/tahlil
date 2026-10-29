"""HTTP API.

GET  /health
GET  /datasets                         list datasets
POST /datasets                         multipart CSV upload(s) (+ optional form field `name`)
POST /datasets/connect                 snapshot a Postgres/MySQL DB  {url, schema?, tables?, row_limit?, name?}
POST /datasets/{id}/refresh            re-import a DB dataset         {url, schema?, tables?, row_limit?}
GET  /datasets/{id}                    record + schema text
GET  /conversations?dataset_id=        list conversations
POST /conversations                    {dataset_id}
GET  /conversations/{id}               conversation + turns
POST /ask                              {dataset_id, question, conversation_id?} -> full result
POST /ask/stream                       same body -> Server-Sent Events: step* then result (or error)
GET  /charts/{ds}/{run}/{file}         chart PNG (unauthenticated: path holds ~88 bits of randomness)

Auth: if API_KEYS is set, every route except /health and /charts needs header `X-API-Key`.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Iterator

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db, graph, store
from .config import settings
from .connectors import ConnectorError, import_database

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

app = FastAPI(title="Tahlil — Autonomous Data Analyst", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                   allow_methods=["*"], allow_headers=["*"])


# ---------- auth & rate limiting ----------

def require_key(request: Request) -> str:
    """Returns the caller identity (API key, or client IP when auth is off)."""
    if not settings.api_keys:
        return request.client.host if request.client else "local"
    key = request.headers.get("x-api-key", "")
    if key not in settings.api_keys:
        raise HTTPException(401, "missing or invalid X-API-Key")
    return key


class RateLimiter:
    """Sliding one-minute window per caller. In-memory: fine for one API process;
    use Redis if you run several replicas."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, caller: str, per_minute: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[caller]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                raise HTTPException(429, f"rate limit: {per_minute} questions per minute",
                                    headers={"Retry-After": str(int(60 - (now - q[0])) + 1)})
            q.append(now)


limiter = RateLimiter()


def ask_limit(caller: str = Depends(require_key)) -> str:
    limiter.check(caller, settings.asks_per_minute)
    return caller


api = APIRouter(dependencies=[Depends(require_key)])


# ---------- models ----------

class AskRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=1000)
    conversation_id: str | None = None


class ConnectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    schema_name: str | None = Field(default=None, alias="schema")
    tables: list[str] | None = None
    row_limit: int | None = Field(default=None, ge=1, le=5_000_000)
    name: str | None = Field(default=None, max_length=120)

    model_config = {"populate_by_name": True}


class ConversationRequest(BaseModel):
    dataset_id: str


# ---------- helpers ----------

def _require_dataset(dataset_id: str) -> None:
    try:
        db.dataset_dir(dataset_id)
        db.list_tables(dataset_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "dataset not found")


def _resolve_conversation(req: AskRequest) -> list[dict]:
    """Validates the conversation and returns prompt history for it."""
    if not req.conversation_id:
        return []
    conv = store.get_conversation(req.conversation_id)
    if not conv or conv["dataset_id"] != req.dataset_id:
        raise HTTPException(404, "conversation not found for this dataset")
    return store.history_for_prompt(req.conversation_id)


def build_payload(dataset_id: str, question: str, state: dict) -> dict[str, Any]:
    rows = []
    if state.get("rows"):
        df = pd.DataFrame(state["rows"], columns=state["columns"])
        rows = json.loads(df.head(200).to_json(orient="records", date_format="iso"))
    run_id = state.get("run_id")
    trace = state.get("trace", [])
    return {
        "status": state.get("status"),
        "error": state.get("error"),
        "question": question,
        "plan": state.get("plan"),
        "sql": state.get("sql"),
        "row_count": state.get("row_count", 0),
        "columns": state.get("columns", []),
        "rows": rows,
        "stats": json.loads(json.dumps(state.get("stats", {}), default=str)),
        "charts": [f"/charts/{dataset_id}/{run_id}/{c}" for c in state.get("charts", [])],
        "report": state.get("report"),
        "verified": state.get("verified", False),
        "unverified_reason": None if state.get("verified") else state.get("report_feedback") or None,
        "trace": trace,
        "total_tokens": sum(int(step.get("tokens") or 0) for step in trace),
        "total_cost_usd": round(sum(float(step.get("cost_usd") or 0) for step in trace), 6),
    }


def _save_turn(req: AskRequest, payload: dict) -> None:
    if req.conversation_id:
        payload["turn_id"] = store.add_turn(req.conversation_id, payload)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------- routes ----------

@app.get("/health")
def health():
    return {"ok": True, "llm_mode": settings.llm_mode, "sandbox": settings.sandbox_mode,
            "auth": bool(settings.api_keys)}


@api.get("/datasets")
def list_datasets():
    return store.list_datasets()


@api.post("/datasets")
async def upload(files: list[UploadFile] = File(...), name: str | None = Form(default=None)):
    payload = {}
    for f in files:
        if not (f.filename or "").lower().endswith(".csv"):
            raise HTTPException(400, f"{f.filename}: only .csv files are supported")
        content = await f.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} exceeds 50 MB")
        payload[f.filename] = content
    try:
        dataset_id, tables = await run_in_threadpool(db.create_dataset, payload)
    except Exception as e:
        raise HTTPException(400, f"Could not load CSV: {e}") from e
    label = ", ".join(payload)
    record = store.add_dataset(dataset_id, name or label, "csv", label, tables)
    return {**record, "dataset_id": dataset_id, "schema": db.describe_schema(dataset_id)}


@api.post("/datasets/connect")
async def connect(req: ConnectRequest):
    try:
        res = await run_in_threadpool(import_database, req.url, req.schema_name, req.tables, req.row_limit)
    except ConnectorError as e:
        raise HTTPException(400, str(e)) from e
    record = store.add_dataset(res.dataset_id, req.name or res.source_label, "sql", res.source_label, res.tables)
    return {**record, "dataset_id": res.dataset_id, "truncated": res.truncated,
            "schema": db.describe_schema(res.dataset_id)}


@api.post("/datasets/{dataset_id}/refresh")
async def refresh(dataset_id: str, req: ConnectRequest):
    record = store.get_dataset(dataset_id)
    if not record:
        raise HTTPException(404, "dataset not found")
    if record["source"] != "sql":
        raise HTTPException(400, "only database datasets can be refreshed")
    try:
        res = await run_in_threadpool(import_database, req.url, req.schema_name, req.tables,
                                      req.row_limit, dataset_id)
    except ConnectorError as e:
        raise HTTPException(400, str(e)) from e
    record = store.add_dataset(dataset_id, record["name"], "sql", res.source_label, res.tables)
    return {**record, "dataset_id": dataset_id, "truncated": res.truncated}


@api.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    _require_dataset(dataset_id)
    record = store.get_dataset(dataset_id) or {"id": dataset_id, "tables": db.list_tables(dataset_id)}
    return {**record, "schema": db.describe_schema(dataset_id)}


@api.get("/conversations")
def list_conversations(dataset_id: str | None = None):
    return store.list_conversations(dataset_id)


@api.post("/conversations")
def create_conversation(req: ConversationRequest):
    _require_dataset(req.dataset_id)
    return store.create_conversation(req.dataset_id)


@api.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    conv = store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {**conv, "turns": store.list_turns(conversation_id)}


_PROVIDER_TYPES = (
    "badrequest", "authentication", "notfound", "ratelimit", "permission",
    "apiconnection", "internalserver", "serviceunavailable", "apierror",
)
_PROVIDER_TEXT = (
    "credit balance", "rate limit", "rate_limit", "model not found", "not_found_error",
    "authentication", "invalid api key", "api key", "overloaded",
)
_SECRET = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]+|req_[A-Za-z0-9]+|request_id[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]+",
    re.I,
)


def _is_provider_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    blob = f"{name} {exc}".lower()
    return any(part in name for part in _PROVIDER_TYPES) or any(part in blob for part in _PROVIDER_TEXT)


def _short_provider_message(exc: BaseException) -> str:
    raw = str(exc)
    match = re.search(r'"message"\s*:\s*"((?:\\.|[^"\\])*)"', raw)
    text = match.group(1) if match else raw.splitlines()[0]
    text = _SECRET.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t-:|,{}[]\"'")
    return (text[:180] or "the model provider returned an error")


@api.post("/ask", dependencies=[Depends(ask_limit)])
async def ask_endpoint(req: AskRequest):
    _require_dataset(req.dataset_id)
    history = _resolve_conversation(req)
    try:
        state = await run_in_threadpool(graph.ask, req.dataset_id, req.question, None, history)
    except Exception as e:
        if _is_provider_error(e):
            raise HTTPException(502, f"Model provider error: {_short_provider_message(e)}") from e
        raise
    payload = build_payload(req.dataset_id, req.question, state)
    _save_turn(req, payload)
    return payload


@api.post("/ask/stream", dependencies=[Depends(ask_limit)])
def ask_stream(req: AskRequest):
    _require_dataset(req.dataset_id)
    history = _resolve_conversation(req)

    def events() -> Iterator[str]:  # sync generator: Starlette runs it in a threadpool
        try:
            for kind, data in graph.stream(req.dataset_id, req.question, None, history):
                if kind == "step":
                    yield _sse("step", data)
                else:
                    payload = build_payload(req.dataset_id, req.question, data)
                    _save_turn(req, payload)
                    yield _sse("result", payload)
        except Exception as e:  # surface failures to the client instead of a dropped connection
            yield _sse("error", {"error": f"{type(e).__name__}: {str(e)[:300]}"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/charts/{dataset_id}/{run_id}/{filename}")
def chart(dataset_id: str, run_id: str, filename: str):
    if not (re.fullmatch(r"[a-f0-9]{10}", run_id) and re.fullmatch(r"chart_\d+\.png", filename)):
        raise HTTPException(400, "bad path")
    try:
        path = db.dataset_dir(dataset_id) / "runs" / run_id / filename
    except ValueError:
        raise HTTPException(400, "bad path")
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="image/png")


app.include_router(api)
