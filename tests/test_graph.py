"""End-to-end runs of the LangGraph agent with a scripted LLM (no API key, local sandbox)."""
from pathlib import Path

from app.config import settings
from app.graph import ask
from app.llm import FakeLLM

GOOD_SQL = "SELECT region, SUM(revenue_pkr) AS revenue FROM sales GROUP BY region ORDER BY revenue DESC"

ANALYSIS = """
total = float(df['revenue'].sum())
top = df.iloc[0]
plt.figure(figsize=(7, 4))
plt.bar(df['region'], df['revenue'] / 1e6)
plt.ylabel('Revenue (PKR M)'); plt.title('Revenue by region')
plt.savefig(f"{OUT_DIR}/chart_1.png", dpi=100, bbox_inches='tight')
print(json.dumps({'total_revenue': total, 'top_region': top['region'],
                  'top_revenue': float(top['revenue']), 'top_share': float(top['revenue']) / total}))
"""


def grounded_report(ctx):
    s = ctx["stats"]
    return (f"## Answer\n{s['top_region']} is the top region with PKR {s['top_revenue']:,.0f} "
            f"({s['top_share']:.1%} of PKR {s['total_revenue']:,.0f}).")


def script(**overrides):
    base = {
        "planner": ["1. Sum revenue by region.\n2. Bar chart."],
        "sql": [GOOD_SQL],
        "analysis_code": [ANALYSIS],
        "report": [grounded_report],
    }
    base.update(overrides)
    return FakeLLM(base)


def steps(state):
    return [t["step"] for t in state["trace"]]


def test_happy_path(dataset_id):
    state = ask(dataset_id, "Which region brings the most revenue?", script())
    assert state["status"] == "ok" and state["verified"]
    assert state["row_count"] == 5
    assert state["rows"][0]["region"] == "Punjab"
    assert state["stats"]["top_region"] == "Punjab"
    chart = settings.data_dir / dataset_id / "runs" / state["run_id"] / state["charts"][0]
    assert chart.exists() and chart.stat().st_size > 1000
    assert steps(state) == ["load_schema", "plan", "write_sql", "guard_sql", "run_sql",
                            "analyze", "report", "guard_report", "finish"]
    assert all(isinstance(t.get("duration_ms"), int) for t in state["trace"])
    analyze = next(t for t in state["trace"] if t["step"] == "analyze")
    assert isinstance(analyze["llm_ms"], int) and isinstance(analyze["sandbox_ms"], int)
    report = next(t for t in state["trace"] if t["step"] == "report")
    assert isinstance(report["llm_ms"], int)


def test_unsafe_sql_is_rejected_then_corrected(dataset_id):
    llm = script(sql=["DROP TABLE sales", GOOD_SQL])
    state = ask(dataset_id, "Revenue by region?", llm)
    assert state["status"] == "ok" and state["sql"] == GOOD_SQL
    guard_events = [t for t in state["trace"] if t["step"] == "guard_sql"]
    assert [g["passed"] for g in guard_events] == [False, True]
    # the validator's reason was fed back to the model on the retry
    retry_prompt = [u for r, u in llm.calls if r == "sql"][1]
    assert "Only SELECT queries are allowed" in retry_prompt


def test_database_error_is_fed_back(dataset_id):
    bad = "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region"  # no such column
    state = ask(dataset_id, "Revenue by region?", script(sql=[bad, GOOD_SQL]))
    assert state["status"] == "ok"
    run_events = [t for t in state["trace"] if t["step"] == "run_sql"]
    assert run_events[0]["ok"] is False and "revenue" in run_events[0]["error"]


def test_gives_up_after_max_attempts(dataset_id):
    state = ask(dataset_id, "Delete everything", script(sql=["DELETE FROM sales"]))
    assert state["status"] == "failed"
    assert state["sql_attempts"] == settings.max_sql_attempts
    assert "report" not in state


def test_hallucinated_report_is_rewritten(dataset_id):
    fake = "## Answer\nPunjab leads with PKR 99,999,999, growing 42% year on year."
    llm = script(report=[fake, grounded_report])
    state = ask(dataset_id, "Top region?", llm)
    assert state["verified"] and state["report_attempts"] == 2
    retry_prompt = [u for r, u in llm.calls if r == "report"][1]
    assert "99,999,999" in retry_prompt and "42%" in retry_prompt


def test_unfixable_report_is_flagged_not_hidden(dataset_id):
    state = ask(dataset_id, "Top region?", script(report=["Revenue was PKR 123,456,789."]))
    assert state["status"] == "ok" and state["verified"] is False
    assert "123,456,789" in state["report_feedback"]


def test_crashing_analysis_is_non_fatal(dataset_id):
    def report(ctx):
        return f"The query returned {ctx['row_count']} rows."
    state = ask(dataset_id, "Revenue by region?",
                script(analysis_code=["raise ValueError('boom')"], report=[report]))
    assert state["status"] == "ok" and state["charts"] == []
    assert "boom" in state["analysis_error"]


def test_sandbox_cannot_write_to_dataset(dataset_id):
    """Even local mode runs the code in a separate process against a CSV copy, not the DB."""
    code = "import os\nprint(json.dumps({'cwd_has_db': os.path.exists('db.duckdb')}))"
    state = ask(dataset_id, "x", script(analysis_code=[code], report=[lambda c: "ok"]))
    assert state["stats"] == {"cwd_has_db": False}
    assert Path(settings.data_dir / dataset_id / "db.duckdb").exists()
