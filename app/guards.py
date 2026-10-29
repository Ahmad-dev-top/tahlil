"""GuardrailsAI validators.

- ReadOnlySQL: generated SQL must be one read-only query over known tables, no file/network table functions.
- GroundedNumbers: every number in the final report must exist in the computed results (no hallucinated stats).
"""
from __future__ import annotations

import os
import re

# GuardrailsAI ships usage telemetry on by default; keep validation fully local.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from dataclasses import dataclass, field
from typing import Any, Iterable

import sqlglot
from sqlglot import exp
from guardrails import Guard, OnFailAction
from guardrails.validator_base import (
    FailResult,
    PassResult,
    ValidationResult,
    Validator,
    register_validator,
)

# DuckDB functions that can touch the filesystem/network or change state.
BLOCKED_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
    "read_json_objects", "read_text", "read_blob", "read_ndjson", "glob", "sniff_csv",
    "query_table", "query", "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan",
    "mysql_scan", "httpfs", "getenv", "current_setting", "duckdb_settings", "pragma",
}
WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Merge, exp.Set, exp.Use, exp.Copy, exp.Pragma,
)


@register_validator(name="tahlil/read_only_sql", data_type="string")
class ReadOnlySQL(Validator):
    """metadata: {"allowed_tables": [...]}"""

    def validate(self, value: Any, metadata: dict) -> ValidationResult:
        allowed = {t.lower() for t in metadata.get("allowed_tables", [])}
        try:
            statements = [s for s in sqlglot.parse(value, read="duckdb") if s is not None]
        except sqlglot.errors.ParseError as e:
            return FailResult(error_message=f"SQL does not parse: {str(e).splitlines()[0]}")
        if len(statements) != 1:
            return FailResult(error_message=f"Expected exactly 1 statement, got {len(statements)}.")
        tree = statements[0]
        if not isinstance(tree, exp.Query):
            return FailResult(error_message=f"Only SELECT queries are allowed (got {type(tree).__name__}).")
        for node in tree.walk():
            if isinstance(node, WRITE_NODES):
                return FailResult(error_message=f"Write/DDL operation not allowed: {type(node).__name__}.")
            if isinstance(node, exp.Func):
                fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
                if fname in BLOCKED_FUNCTIONS:
                    return FailResult(error_message=f"Function '{fname}' is not allowed (file/system access).")
        cte_names = {c.alias.lower() for c in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            if isinstance(table.this, exp.Func):  # table function in FROM, e.g. FROM read_csv(...)
                return FailResult(error_message="Table functions are not allowed in FROM.")
            name = table.name.lower()
            if name and name not in allowed and name not in cte_names:
                return FailResult(error_message=f"Unknown table '{table.name}'. Allowed: {sorted(allowed)}.")
        return PassResult()


# ---------- numeric grounding ----------

_NUM = re.compile(r"(?<![\w.])[-+]?\$?\d(?:[\d,]*\d)?(?:\.\d+)?\s*(?:%|[kKmMbB](?![a-zA-Z]))?")
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}
# YYYY-MM-DD, optionally with a time. Removed before numeric extraction so the
# year, month and day are not checked as standalone figures.
_ISO_DATE = re.compile(
    r"(?<!\d)\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"(?!\d)"
)


def _prepare_report(text: str) -> str:
    """Drop markdown markers the writer didn't mean as figures."""
    text = re.sub(r"^\s*(?:\d+[.)]|#+)\s", " ", text, flags=re.M)
    return re.sub(r"`[^`]*`", " ", text)


def cited_dates(text: str) -> list[str]:
    """ISO dates/datetimes written in the report, in order."""
    return [m.group(0) for m in _ISO_DATE.finditer(_prepare_report(text))]


def extract_numbers(text: str) -> list[tuple[str, float, float]]:
    """Returns (raw, value, rounding_tolerance). Percentages are converted to fractions
    (37.5% -> 0.375). The tolerance is half a unit of the last digit the writer used,
    so '45.15M' may stand for 45,151,248 but '42%' may not stand for 38.2%.
    Skips markdown list markers, headings, `code spans`, and ISO dates."""
    text = _ISO_DATE.sub(" ", _prepare_report(text))
    out = []
    for m in _NUM.finditer(text):
        raw = m.group(0).strip()
        s = raw.replace("$", "").replace(",", "").strip()
        scale = 1.0
        if s.endswith("%"):
            s, scale = s[:-1].strip(), 0.01
        elif s and s[-1].lower() in _SUFFIX:
            s, scale = s[:-1].strip(), _SUFFIX[s[-1].lower()]
        try:
            val = float(s)
        except ValueError:
            continue
        decimals = len(s.split(".")[1]) if "." in s else 0
        out.append((raw, val * scale, 0.5 * 10 ** -decimals * scale))
    return out


def _close(written: float, fact: float, tol: float, rel: float) -> bool:
    return abs(written - fact) <= max(tol, rel * abs(fact))


@register_validator(name="tahlil/grounded_numbers", data_type="string")
class GroundedNumbers(Validator):
    """metadata: {"facts": iterable of numbers the report may cite}.
    Small integers (<= ignore_below) are exempt: counts like 'top 3', 'Q2', '2 regions'."""

    def __init__(self, rel_tol: float = 0.001, ignore_below: float = 12, **kwargs):
        super().__init__(rel_tol=rel_tol, ignore_below=ignore_below, **kwargs)
        self.rel_tol = rel_tol
        self.ignore_below = ignore_below

    def validate(self, value: Any, metadata: dict) -> ValidationResult:
        facts = [float(f) for f in metadata.get("facts", []) if _finite(f)]
        allowed_dates = {_date_key(d) for d in metadata.get("dates", [])}
        missing_dates = [
            raw for raw in dict.fromkeys(cited_dates(str(value))) if _date_key(raw) not in allowed_dates
        ]
        ungrounded = []
        for raw, num, tol in extract_numbers(value):
            if abs(num) <= self.ignore_below and float(num).is_integer() and "%" not in raw:
                continue
            # a percentage may match a 0-1 fraction or a value already stored in percent units
            options = [(num, tol), (num * 100, tol * 100)] if "%" in raw else [(num, tol)]
            if not any(_close(n, f, t, self.rel_tol) for n, t in options for f in facts):
                ungrounded.append(raw)
        errors = []
        if missing_dates:
            errors.append(
                "Report cites dates not found in the results: " + ", ".join(missing_dates) + "."
            )
        if ungrounded:
            errors.append(
                "Report cites numbers not found in the computed results: "
                + ", ".join(dict.fromkeys(ungrounded))
                + ". Use only figures from the results, or remove them."
            )
        if errors:
            return FailResult(error_message=" ".join(errors))
        return PassResult()


def _date_key(value: Any) -> str:
    """Compare dates on YYYY-MM-DD, ignoring any time component."""
    return str(value).strip()[:10]


def _finite(x: Any) -> bool:
    try:
        f = float(x)
        return f == f and abs(f) != float("inf")
    except (TypeError, ValueError):
        return False


# ---------- guard runners ----------

@dataclass
class GuardOutcome:
    passed: bool
    errors: list[str] = field(default_factory=list)


def _run(guard: Guard, value: str, metadata: dict) -> GuardOutcome:
    outcome = guard.validate(value, metadata=metadata)
    errors = [
        s.failure_reason for s in (outcome.validation_summaries or []) if s.failure_reason
    ]
    return GuardOutcome(passed=bool(outcome.validation_passed), errors=errors)


_sql_guard = Guard(name="tahlil_sql").use(ReadOnlySQL(on_fail=OnFailAction.NOOP))
_report_guard = Guard(name="tahlil_report").use(GroundedNumbers(on_fail=OnFailAction.NOOP))


def check_sql(sql: str, allowed_tables: list[str]) -> GuardOutcome:
    return _run(_sql_guard, sql, {"allowed_tables": allowed_tables})


def check_report(report: str, facts: Iterable[float], dates: Iterable[Any] | None = None) -> GuardOutcome:
    return _run(_report_guard, report, {"facts": list(facts), "dates": list(dates or [])})
