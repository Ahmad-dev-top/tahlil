"""Accuracy evals: run the agent on questions with known answers and score it.

    python -m evals.run                      # live model from .env / environment
    python -m evals.run --model openai/gpt-4o-mini
    python -m evals.run --label A --no-crewai
    python -m evals.run --questions evals/holdout.json
    python -m evals.run --fake               # harness self-test, no API key (should score 100%)
    python -m evals.run --min-accuracy 0.8   # non-zero exit below threshold (for CI)

A numeric question passes when the agent's result table contains the reference answer:
every reference number (±0.5%, or ×100 for shares shown as percentages) and every
reference text value must appear in the agent's rows. Extra rows/columns are fine.

An unanswerable question passes when the run status is ok, the report is verified,
and the report says the data cannot answer it.

Results are written to evals/results/<timestamp>-<label>-<model>.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

_UNANSWERABLE_PHRASES = (
    "not available",
    "does not contain",
    "doesn't contain",
    "no data",
    "cannot",
    "can't",
    "not included",
    "no column",
)


def _numbers(df) -> list[float]:
    vals = []
    for col in df.select_dtypes("number").columns:
        vals += [float(v) for v in df[col].dropna() if math.isfinite(float(v))]
    return vals


def _texts(df) -> set[str]:
    out = set()
    for col in df.select_dtypes(include=["object", "string"]).columns:
        out |= {str(v).strip().lower() for v in df[col].dropna()}
    return out


def score(agent_df, ref_df, rel_tol: float = 0.005) -> tuple[bool, str]:
    if agent_df is None or agent_df.empty:
        return False, "agent returned no rows"
    have = _numbers(agent_df)
    for v in _numbers(ref_df):
        if not any(math.isclose(h, v, rel_tol=rel_tol, abs_tol=1e-6) or
                   math.isclose(h, v * 100, rel_tol=rel_tol) for h in have):
            return False, f"missing number {v:,.4g}"
    missing = _texts(ref_df) - _texts(agent_df)
    if missing:
        return False, f"missing values {sorted(missing)[:5]}"
    return True, "ok"


def score_unanswerable(status, verified, report: str | None) -> tuple[bool, str]:
    """Pass when the agent finishes, grounds the report, and says the data cannot answer."""
    if status != "ok":
        return False, f"status {status or 'missing'}"
    if not verified:
        return False, "not verified"
    text = (report or "").lower()
    if not any(phrase in text for phrase in _UNANSWERABLE_PHRASES):
        return False, "report does not say the data cannot answer the question"
    return True, "ok"


def score_question(kind: str, agent_df, ref_df, state: dict, error: str | None) -> tuple[bool, str]:
    if error:
        return False, error
    if kind == "unanswerable":
        return score_unanswerable(state.get("status"), bool(state.get("verified")), state.get("report"))
    return score(agent_df, ref_df)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def _step_rows(trace: list[dict]) -> list[dict]:
    rows = []
    for step in trace:
        row = {
            "step": step.get("step"),
            "duration_ms": step.get("duration_ms"),
            "attempt": step.get("attempt"),
        }
        for key in ("llm_ms", "sandbox_ms", "analyst_ms", "writer_ms"):
            if step.get(key) is not None:
                row[key] = step[key]
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fake", action="store_true", help="scripted model that answers with the reference SQL")
    p.add_argument("--model", help="override LLM_MODEL")
    p.add_argument("--label", help="name stored in the result file")
    p.add_argument("--no-crewai", action="store_true", help="single LLM call for the report")
    p.add_argument("--questions", help="question file (default: evals/questions.json)")
    p.add_argument("--only", nargs="*", help="question ids to run")
    p.add_argument("--min-accuracy", type=float, default=0.0)
    p.add_argument("--out", default=str(HERE / "results"))
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from dotenv import load_dotenv
    # A leftover shell env must not override .env for a paid run.
    for key in ("LLM_MODE", "LLM_MODEL", "LLM_TEMPERATURE", "USE_CREWAI", "SANDBOX_MODE", "DEMO_DELAY_S"):
        os.environ.pop(key, None)
    load_dotenv(ROOT / ".env")
    os.environ["LLM_MODE"] = "fake" if args.fake else "live"
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.no_crewai:
        os.environ["USE_CREWAI"] = "false"
    if not args.fake:
        os.environ["SANDBOX_MODE"] = "docker"

    import pandas as pd  # imported after env is set so app.config picks it up

    from app import db
    from app.config import settings
    from app.graph import ask
    from app.llm import FakeLLM, get_llm

    question_path = Path(args.questions) if args.questions else HERE / "questions.json"
    if not question_path.is_absolute():
        question_path = ROOT / question_path
    questions = json.loads(question_path.read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]

    ds, _ = db.create_dataset({"sales.csv": (ROOT / "sample_data" / "sales.csv").read_bytes()})

    results = []
    for q in questions:
        kind = q.get("kind", "numeric")
        ref = db.run_query(ds, q["reference_sql"]) if kind != "unanswerable" else None
        if args.fake:
            if kind == "unanswerable":
                report = "The data does not contain the information needed to answer this."
                sql = "SELECT 1 AS note"
            else:
                report = lambda c: f"The query returned {c['row_count']} rows."
                sql = q["reference_sql"]
            llm = FakeLLM({
                "planner": ["1. Answer directly."],
                "sql": [sql],
                "analysis_code": ["print(json.dumps({}))"],
                "report": [report],
            })
        else:
            llm = get_llm()

        t0 = time.time()
        try:
            state = ask(ds, q["question"], llm)
            error = state.get("error")
        except Exception as e:  # count crashes as failures, keep going
            state, error = {}, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        elapsed = time.time() - t0

        agent_df = pd.DataFrame(state["rows"], columns=state["columns"]) if state.get("rows") else None
        passed, reason = score_question(kind, agent_df, ref, state, error)
        trace = state.get("trace") or []
        tokens = sum(int(step.get("tokens") or 0) for step in trace)
        cost = round(sum(float(step.get("cost_usd") or 0) for step in trace), 6)
        results.append({
            "id": q["id"], "kind": kind, "question": q["question"], "passed": passed, "reason": reason,
            "verified": bool(state.get("verified")), "sql": state.get("sql"),
            "sql_attempts": state.get("sql_attempts"), "report_attempts": state.get("report_attempts"),
            "seconds": round(elapsed, 2), "total_tokens": tokens, "total_cost_usd": cost,
            "steps": _step_rows(trace),
        })
        mark = "PASS" if passed else "FAIL"
        print(
            f"[{mark}] {q['id']:<26} {elapsed:6.1f}s  verified={results[-1]['verified']!s:<5}  "
            f"sql={state.get('sql_attempts')} report={state.get('report_attempts')}  "
            f"${cost:.4f}  {reason}"
        )

    n = len(results)
    seconds = [r["seconds"] for r in results]
    costs = [r["total_cost_usd"] for r in results]
    acc = sum(r["passed"] for r in results) / n if n else 0.0
    verified = sum(r["verified"] for r in results) / n if n else 0.0
    first_try = sum(r.get("report_attempts") == 1 for r in results) / n if n else 0.0
    buckets: dict[str, list[int]] = defaultdict(list)
    for row in results:
        for step in row["steps"]:
            if isinstance(step.get("duration_ms"), int):
                buckets[step["step"]].append(step["duration_ms"])
    step_median_ms = {name: int(median(vals)) for name, vals in buckets.items()}
    summary = {
        "label": args.label,
        "model": "fake" if args.fake else settings.llm_model,
        "crewai": not args.no_crewai and settings.use_crewai,
        "n": n,
        "accuracy": acc,
        "verified_rate": verified,
        "first_try_report_rate": first_try,
        "avg_seconds": round(sum(seconds) / n, 2) if n else 0.0,
        "p50_seconds": round(_percentile(seconds, 0.50), 2),
        "p90_seconds": round(_percentile(seconds, 0.90), 2),
        "avg_cost_usd": round(sum(costs) / n, 6) if n else 0.0,
        "total_cost_usd": round(sum(costs), 6),
        "step_median_ms": step_median_ms,
        "results": results,
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model_slug = summary["model"].replace("/", "_")
    label = args.label or "run"
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-{model_slug}.json"
    path.write_text(json.dumps(summary, indent=2, default=str))
    print(
        f"\naccuracy {acc:.0%} · verified {verified:.0%} · first-try report {first_try:.0%} · "
        f"p50 {summary['p50_seconds']:.1f}s · p90 {summary['p90_seconds']:.1f}s · "
        f"avg ${summary['avg_cost_usd']:.4f} · total ${summary['total_cost_usd']:.4f} · {path}"
    )
    if step_median_ms:
        ordered = "  ".join(f"{name} {ms}ms" for name, ms in step_median_ms.items())
        print(f"step medians: {ordered}")
    return 0 if acc >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
