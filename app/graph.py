"""The agent: a LangGraph state machine.

load_schema -> plan -> write_sql -> guard_sql --fail--> write_sql (retry with validator feedback)
                                       |pass
                                    run_sql --db error--> write_sql
                                       |ok
                                    analyze (code in Docker sandbox; non-fatal on failure)
                                       |
                                    report (CrewAI crew) -> guard_report --fail--> report (retry)
                                                                 |pass
                                                                END
"""
from __future__ import annotations

import math
import re
import time
import uuid
from datetime import date, datetime
from typing import Any, Iterator, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph

from . import db, prompts
from .config import settings
from .crew import write_report
from .guards import check_report, check_sql
from .llm import LLM, get_llm, strip_fences
from .sandbox import run_analysis


class AgentState(TypedDict, total=False):
    dataset_id: str
    question: str
    history: list[dict]  # previous turns of this conversation (question, sql, answer)
    run_id: str
    tables: list[str]
    schema: str
    plan: str
    sql: str
    sql_attempts: int
    sql_feedback: str
    rows: list[dict]
    columns: list[str]
    row_count: int
    stats: dict
    charts: list[str]
    analysis_error: str
    report: str
    report_attempts: int
    report_feedback: str
    verified: bool
    status: str  # ok | failed
    error: str
    trace: list[dict]


def _log(state: AgentState, step: str, **info: Any) -> list[dict]:
    return [*state.get("trace", []), {"step": step, **info}]


def _usage_fields(llm: LLM) -> dict[str, int | float]:
    """Tokens and cost of the LLM call that just finished. Missing usage is zero."""
    usage = getattr(llm, "last_usage", None)
    return {
        "tokens": int(getattr(usage, "tokens", 0) or 0),
        "cost_usd": float(getattr(usage, "cost_usd", 0.0) or 0.0),
    }


def _flatten_numbers(obj: Any) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)] if math.isfinite(obj) else []
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _flatten_numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _flatten_numbers(v)]
    return []


def grounding_facts(df: pd.DataFrame, stats: dict) -> list[float]:
    """Numbers the report is allowed to cite: result cells, simple column aggregates,
    row shares of each column total, row count, and sandbox-computed stats."""
    facts = [float(len(df))] + _flatten_numbers(stats)
    num = df.select_dtypes("number")
    facts += [float(v) for v in num.to_numpy().ravel() if pd.notna(v)]
    for col in num.columns:
        s = num[col].dropna()
        if s.empty:
            continue
        facts += [s.sum(), s.mean(), s.median(), s.min(), s.max()]
        if len(s) <= 500 and s.sum():
            facts += list(s / s.sum())
    # dates/years in text columns are fine to cite too
    for col in df.columns.difference(num.columns):
        facts += [float(x) for x in pd.to_numeric(df[col].astype(str).str.extract(r"(\d{4})")[0], errors="coerce").dropna()]
    return [float(f) for f in facts if math.isfinite(float(f))]


_CELL_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def result_dates(df: pd.DataFrame) -> list[str]:
    """YYYY-MM-DD values present in the result rows. The report may cite these."""
    found: list[str] = []
    for col in df.columns:
        for value in df[col].dropna():
            if isinstance(value, (pd.Timestamp, datetime, date)):
                found.append(pd.Timestamp(value).strftime("%Y-%m-%d"))
                continue
            match = _CELL_DATE.match(str(value).strip())
            if match:
                found.append(match.group(1))
    return found


def _history_block(state: AgentState) -> str:
    turns = state.get("history") or []
    if not turns:
        return ""
    lines = ["CONVERSATION SO FAR (oldest first). The new question may refer back to these:"]
    for i, t in enumerate(turns, 1):
        lines.append(f"[{i}] Q: {t['question']}\n    SQL: {t.get('sql') or '-'}\n    Answer: {t.get('answer') or '-'}")
    return "\n".join(lines) + "\n\n"


def build_graph(llm: LLM | None = None):
    llm = llm or get_llm()

    def load_schema(state: AgentState) -> AgentState:
        tables = db.list_tables(state["dataset_id"])
        schema = db.describe_schema(state["dataset_id"])
        return {"tables": tables, "schema": schema, "sql_attempts": 0, "report_attempts": 0,
                "run_id": state.get("run_id") or uuid.uuid4().hex[:10],
                "trace": _log(state, "load_schema", tables=tables)}

    def plan(state: AgentState) -> AgentState:
        out = llm.complete("planner", prompts.PLANNER,
                           f"{_history_block(state)}QUESTION: {state['question']}\n\nSCHEMA:\n{state['schema']}", dict(state))
        return {"plan": out.strip(), "trace": _log(state, "plan", **_usage_fields(llm))}

    def write_sql(state: AgentState) -> AgentState:
        user = f"{_history_block(state)}QUESTION: {state['question']}\n\nPLAN:\n{state['plan']}\n\nSCHEMA:\n{state['schema']}"
        if state.get("sql_feedback"):
            user += f"\n\nYOUR PREVIOUS QUERY:\n{state['sql']}\nWAS REJECTED: {state['sql_feedback']}\nWrite a corrected query."
        sql = strip_fences(llm.complete("sql", prompts.SQL_WRITER.format(tables=", ".join(state["tables"])), user, dict(state)))
        attempts = state.get("sql_attempts", 0) + 1
        return {"sql": sql, "sql_attempts": attempts,
                "trace": _log(state, "write_sql", attempt=attempts, sql=sql, **_usage_fields(llm))}

    def guard_sql(state: AgentState) -> AgentState:
        outcome = check_sql(state["sql"], state["tables"])
        info: dict[str, Any] = {"passed": outcome.passed, "errors": outcome.errors}
        if not outcome.passed:
            info["sql"] = state.get("sql", "")
        return {"sql_feedback": "" if outcome.passed else "; ".join(outcome.errors),
                "trace": _log(state, "guard_sql", **info)}

    def run_sql(state: AgentState) -> AgentState:
        try:
            df = db.run_query(state["dataset_id"], state["sql"])
        except Exception as e:  # syntax/semantic DB errors go back to the SQL writer
            msg = f"Database error: {str(e).splitlines()[0][:300]}"
            return {"sql_feedback": msg, "trace": _log(state, "run_sql", ok=False, error=msg)}
        return {"rows": df.to_dict(orient="records"), "columns": list(df.columns), "row_count": len(df),
                "sql_feedback": "", "trace": _log(state, "run_sql", ok=True, rows=len(df))}

    def analyze(state: AgentState) -> AgentState:
        df = pd.DataFrame(state["rows"], columns=state["columns"])
        preview = df.head(30).to_string(index=False)
        user = f"QUESTION: {state['question']}\nPLAN:\n{state['plan']}\n\ndf columns/dtypes:\n{df.dtypes.to_string()}\n\ndf head:\n{preview}"
        out_dir = settings.data_dir / state["dataset_id"] / "runs" / state["run_id"]
        error = ""
        tokens = 0
        cost = 0.0
        llm_ms = 0
        sandbox_ms = 0
        for attempt in (1, 2):
            t_llm = time.perf_counter()
            code = strip_fences(llm.complete("analysis_code", prompts.ANALYSIS_CODE, user, dict(state)))
            llm_ms += int((time.perf_counter() - t_llm) * 1000)
            spent = _usage_fields(llm)
            tokens += int(spent["tokens"])
            cost += float(spent["cost_usd"])
            t_box = time.perf_counter()
            res = run_analysis(code, df, out_dir)
            sandbox_ms += int((time.perf_counter() - t_box) * 1000)
            if res.ok:
                return {"stats": res.stats, "charts": [p.name for p in res.charts], "analysis_error": "",
                        "trace": _log(state, "analyze", ok=True, attempt=attempt, charts=len(res.charts),
                                      tokens=tokens, cost_usd=cost, llm_ms=llm_ms, sandbox_ms=sandbox_ms)}
            error = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "unknown error"
            user += f"\n\nYOUR PREVIOUS CODE FAILED:\n{code}\nERROR: {error}\nFix it."
        # Non-fatal: the report can still be written from the SQL result alone.
        return {"stats": {}, "charts": [], "analysis_error": error,
                "trace": _log(state, "analyze", ok=False, error=error, tokens=tokens, cost_usd=cost,
                              llm_ms=llm_ms, sandbox_ms=sandbox_ms)}

    def report(state: AgentState) -> AgentState:
        df = pd.DataFrame(state["rows"], columns=state["columns"])
        ctx = {**state, "result_preview": df.head(50).to_string(index=False),
               "stats": state.get("stats", {}), "feedback": state.get("report_feedback", "")}
        text = write_report(ctx, llm)
        attempts = state.get("report_attempts", 0) + 1
        split = getattr(write_report, "last_split", {})
        return {"report": text, "report_attempts": attempts,
                "trace": _log(state, "report", attempt=attempts, **split, **_usage_fields(llm))}

    def guard_report(state: AgentState) -> AgentState:
        df = pd.DataFrame(state["rows"], columns=state["columns"])
        outcome = check_report(state["report"], grounding_facts(df, state.get("stats", {})), result_dates(df))
        return {"verified": outcome.passed, "report_feedback": "; ".join(outcome.errors),
                "trace": _log(state, "guard_report", passed=outcome.passed, errors=outcome.errors)}

    def fail(state: AgentState) -> AgentState:
        return {"status": "failed",
                "error": f"Could not produce a valid query after {state['sql_attempts']} attempts: {state.get('sql_feedback')}",
                "trace": _log(state, "fail")}

    def finish(state: AgentState) -> AgentState:
        return {"status": "ok", "trace": _log(state, "finish", verified=state.get("verified", False))}

    # --- routing ---
    def after_sql_check(state: AgentState) -> str:
        if not state.get("sql_feedback"):
            return "pass"
        return "retry" if state["sql_attempts"] < settings.max_sql_attempts else "give_up"

    def after_report_check(state: AgentState) -> str:
        if state.get("verified") or state["report_attempts"] >= settings.max_report_attempts:
            return "done"
        return "retry"

    def _timed(fn):
        def wrapped(state: AgentState) -> AgentState:
            started = time.perf_counter()
            out = fn(state)
            trace = out.get("trace")
            if trace:
                trace[-1]["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return out
        return wrapped

    g = StateGraph(AgentState)
    for name, fn in [("load_schema", load_schema), ("plan", plan), ("write_sql", write_sql),
                     ("guard_sql", guard_sql), ("run_sql", run_sql), ("analyze", analyze),
                     ("report", report), ("guard_report", guard_report), ("fail", fail), ("finish", finish)]:
        g.add_node(name, _timed(fn))

    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "plan")
    g.add_edge("plan", "write_sql")
    g.add_edge("write_sql", "guard_sql")
    g.add_conditional_edges("guard_sql", after_sql_check, {"pass": "run_sql", "retry": "write_sql", "give_up": "fail"})
    g.add_conditional_edges("run_sql", after_sql_check, {"pass": "analyze", "retry": "write_sql", "give_up": "fail"})
    g.add_edge("analyze", "report")
    g.add_edge("report", "guard_report")
    g.add_conditional_edges("guard_report", after_report_check, {"retry": "report", "done": "finish"})
    g.add_edge("fail", END)
    g.add_edge("finish", END)
    return g.compile()


def _initial(dataset_id: str, question: str, history: list[dict] | None) -> AgentState:
    return {"dataset_id": dataset_id, "question": question, "history": history or []}


_CONFIG = {"recursion_limit": 40}


def ask(dataset_id: str, question: str, llm: LLM | None = None, history: list[dict] | None = None) -> AgentState:
    return build_graph(llm).invoke(_initial(dataset_id, question, history), _CONFIG)


def stream(dataset_id: str, question: str, llm: LLM | None = None,
           history: list[dict] | None = None) -> Iterator[tuple[str, Any]]:
    """Yields ("step", trace_entry) as each graph node finishes, then ("final", state)."""
    state: dict = _initial(dataset_id, question, history)
    sent = 0
    for update in build_graph(llm).stream(state, _CONFIG, stream_mode="updates"):
        for _node, delta in update.items():
            if not delta:
                continue
            state.update(delta)
            trace = state.get("trace", [])
            for entry in trace[sent:]:
                yield "step", entry
            sent = len(trace)
    yield "final", state
