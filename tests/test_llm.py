from app import graph
from app.api import build_payload
from app.crew import _crew_usage, analyst_task_text, writer_task_text
from app.llm import CallUsage, FakeLLM, LiteLLM, strip_fences, temperature_kwargs


def test_temperature_kwarg_follows_setting(monkeypatch):
    assert temperature_kwargs("") == {}
    assert temperature_kwargs("0") == {"temperature": 0.0}

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        message = type("M", (), {"content": "ok"})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()

    import litellm
    monkeypatch.setattr(litellm, "completion", fake_completion)
    assert LiteLLM(model="anthropic/claude-sonnet-5-5").complete("planner", "sys", "user", {}) == "ok"
    assert "temperature" not in captured


def test_prompts_require_computed_comparisons_and_exact_citations(dataset_id):
    llm = FakeLLM({
        "planner": ["1. Sum revenue by region."],
        "sql": ["SELECT region, SUM(revenue_pkr) AS revenue FROM sales GROUP BY 1"],
        "analysis_code": ["import json\nprint(json.dumps({'share': 0.37, 'share_pct': 37.0}))"],
        "report": ["Punjab is well ahead of Sindh."],
    })
    state = graph.ask(dataset_id, "Which region brings the most revenue?", llm)
    assert state["status"] == "ok"
    analysis = next(system for role, system in llm.systems if role == "analysis_code")
    report = next(system for role, system in llm.systems if role == "report")
    for phrase in (
        "differences between the top items",
        "growth or change percent",
        "share of the total",
        "combined share of the top N",
        "ratios",
        "0-1 fraction",
        "rounded percentage",
        "pd.to_datetime",
        "Keep the sign",
    ):
        assert phrase in analysis
    for text in (report, analyst_task_text(), writer_task_text()):
        assert "copied exactly as shown" in text
        assert "RESULTS or STATS" in text
        assert "Punjab is well ahead of Sindh" in text
        assert "leading minus sign" in text
        assert "-10.87" in text
        assert "December 2025" not in text
        assert "calendar date" not in text


def test_strip_fences_keeps_the_query():
    query = "SELECT `revenue_pkr` FROM sales WHERE label = 'keep`me'"
    assert strip_fences(f"```sql\n{query}\n```") == query
    assert strip_fences(query + "\n```") == query  # closing fence only, the monthly-trend case
    assert strip_fences("```sql\n" + query) == query  # opening fence only
    assert strip_fences(f"  {query}\n") == query  # no fences, surrounding whitespace
    assert strip_fences(query) == query  # backticks inside stay intact
    monthly = "ORDER BY m.month;\n```"
    assert strip_fences(monthly) == "ORDER BY m.month;"


class _Metered(FakeLLM):
    def complete(self, role, system, user, ctx):
        text = super().complete(role, system, user, ctx)
        self.last_usage = CallUsage(tokens=5, cost_usd=0.001)
        return text


def test_fake_llm_usage_is_zero_and_payload_sums_real_usage(dataset_id):
    script = {
        "planner": ["1. Sum revenue by region."],
        "sql": ["SELECT region, SUM(revenue_pkr) AS revenue FROM sales GROUP BY 1"],
        "analysis_code": ["import json\nprint(json.dumps({'rows': len(df)}))"],
        "report": ["Punjab is well ahead of Sindh."],
    }
    state = graph.ask(dataset_id, "Which region brings the most revenue?", FakeLLM(script))
    payload = build_payload(dataset_id, state["question"], state)
    assert payload["total_tokens"] == 0
    assert payload["total_cost_usd"] == 0
    for step in state["trace"]:
        if step["step"] in {"plan", "write_sql", "analyze", "report"}:
            assert step["tokens"] == 0 and step["cost_usd"] == 0

    metered = graph.ask(dataset_id, "Which region brings the most revenue?", _Metered(script))
    paid = build_payload(dataset_id, metered["question"], metered)
    llm_steps = [s for s in metered["trace"] if s["step"] in {"plan", "write_sql", "analyze", "report"}]
    assert paid["total_tokens"] == 5 * len(llm_steps)
    assert paid["total_cost_usd"] == round(0.001 * len(llm_steps), 6)


def test_litellm_records_tokens_and_cost(monkeypatch):
    def fake_completion(**kwargs):
        usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})()
        message = type("M", (), {"content": "ok"})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice], "usage": usage, "model": kwargs["model"]})()

    import litellm
    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_k: 0.004)
    llm = LiteLLM(model="anthropic/claude-sonnet-5-5")
    assert llm.complete("planner", "sys", "user", {}) == "ok"
    assert llm.last_usage.tokens == 14
    assert llm.last_usage.cost_usd == 0.004


def test_crew_usage_reads_token_totals(monkeypatch):
    import litellm
    monkeypatch.setattr(litellm, "completion_cost", lambda **_k: 0.02)
    usage = type("U", (), {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140})()
    got = _crew_usage(type("R", (), {"token_usage": usage})(), object())
    assert got.tokens == 140
    assert got.cost_usd == 0.02
