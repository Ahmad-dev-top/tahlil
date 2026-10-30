"""Public-demo limits: daily budget, no outbound DB, upload caps, per-IP rate limit."""
import dataclasses
import threading
import time

from fastapi.testclient import TestClient

from app import api as api_module
from app import db, graph, store
from app.api import SAMPLE_DATASET_NAME, app, limiter, preload_sample_dataset
from app.llm import CallUsage, demo_llm

client = TestClient(app)
TINY = b"a\n1\n"


def _demo(**changes):
    return dataclasses.replace(api_module.settings, public_demo=True, **changes)


def _clear_usage():
    with store._conn() as con:
        con.execute("DELETE FROM usage")


def test_daily_budget_uses_fakellm_cost(monkeypatch, dataset_id):
    monkeypatch.setattr(api_module, "settings", _demo(daily_cost_limit_usd=0.001))
    _clear_usage()
    limiter._hits.clear()

    def costly():
        llm = demo_llm()
        original = llm.complete

        def complete(*args, **kwargs):
            text = original(*args, **kwargs)
            llm.last_usage = CallUsage(tokens=4, cost_usd=0.01)
            return text

        llm.complete = complete
        return llm

    monkeypatch.setattr(graph, "get_llm", costly)
    body = {"dataset_id": dataset_id, "question": "What is the total revenue?"}
    first = client.post("/ask", json=body)
    assert first.status_code == 200
    assert first.json()["total_cost_usd"] >= 0.01
    second = client.post("/ask", json=body)
    assert second.status_code == 429
    assert second.json()["detail"] == "Daily demo budget reached, try again tomorrow"
    streamed = client.post("/ask/stream", json=body)
    assert streamed.status_code == 429
    assert streamed.json()["detail"] == "Daily demo budget reached, try again tomorrow"
    _clear_usage()


def test_daily_budget_counts_only_the_utc_day(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo(daily_cost_limit_usd=1))
    _clear_usage()
    start = api_module._utc_day_start()
    with store._conn() as con:
        con.execute("INSERT INTO usage (created_at, cost_usd) VALUES (?, ?)", (start - 10, 50))
        con.execute("INSERT INTO usage (created_at, cost_usd) VALUES (?, ?)", (start + 1, 0.25))
    assert store.cost_since(start) == 0.25
    _clear_usage()


def test_health_reports_public_demo(monkeypatch):
    assert client.get("/health").json()["public_demo"] is False
    monkeypatch.setattr(api_module, "settings", _demo())
    assert client.get("/health").json()["public_demo"] is True


def test_public_demo_rejects_connect_and_refresh(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo())
    body = {"url": "postgresql://user:secret@db.example/sales"}
    assert client.post("/datasets/connect", json=body).status_code == 403
    assert client.post("/datasets/not-a-real-id/refresh", json=body).status_code == 403


def test_public_demo_upload_limits(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo())
    files = [("files", (f"{i}.csv", TINY, "text/csv")) for i in range(4)]
    assert client.post("/datasets", files=files).status_code == 400
    big = ("files", ("big.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv"))
    assert client.post("/datasets", files=[big]).status_code == 413


def test_sample_dataset_is_preloaded_once():
    first = preload_sample_dataset()
    assert first
    assert preload_sample_dataset() is None
    names = [d["name"] for d in store.list_datasets()]
    assert names.count(SAMPLE_DATASET_NAME) == 1


def test_public_demo_rate_limit_is_per_forwarded_ip(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo(
        asks_per_minute=1, api_keys=frozenset({"shared"}), trusted_proxies=frozenset({"testclient"}),
    ))
    limiter._hits.clear()
    body = {"dataset_id": "ffffffffffff", "question": "hello there"}

    def post(ip):
        return client.post("/ask", json=body, headers={"X-API-Key": "shared", "X-Forwarded-For": ip}).status_code

    assert post("203.0.113.5") == 404
    assert post("203.0.113.5") == 429
    assert post("203.0.113.9") == 404
    limiter._hits.clear()


_OK_STATE = {
    "status": "ok", "error": None, "plan": "p", "sql": "select 1", "row_count": 0,
    "columns": [], "rows": [], "stats": {}, "charts": [], "report": "1",
    "verified": True, "trace": [], "run_id": None,
}


def test_ask_returns_503_when_the_queue_times_out(monkeypatch, dataset_id):
    monkeypatch.setattr(api_module, "settings", dataclasses.replace(
        api_module.settings, max_concurrent_asks=1, queue_timeout_s=0.4,
    ))
    api_module.gate.reset()
    entered = threading.Event()
    release = threading.Event()

    def slow_ask(*_args, **_kwargs):
        demo_llm().complete("planner", "system", "user", {})  # FakeLLM, then hold the only slot
        entered.set()
        release.wait(5)
        return dict(_OK_STATE)

    monkeypatch.setattr(graph, "ask", slow_ask)
    body = {"dataset_id": dataset_id, "question": "What is the total revenue?"}
    results: dict = {}

    def first():
        results["first"] = client.post("/ask", json=body).status_code

    def second():
        assert entered.wait(5)
        results["second"] = client.post("/ask", json=body)

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    threads[1].join(5)
    assert results["second"].status_code == 503
    assert results["second"].json()["detail"] == "Demo is busy, try again in a minute"
    release.set()
    threads[0].join(5)
    assert results["first"] == 200
    api_module.gate.reset()


def test_stream_sends_queued_then_runs(monkeypatch, dataset_id):
    monkeypatch.setattr(api_module, "settings", dataclasses.replace(
        api_module.settings, max_concurrent_asks=1, queue_timeout_s=5,
    ))
    api_module.gate.reset()
    entered = threading.Event()
    release = threading.Event()

    def slow_ask(*_args, **_kwargs):
        demo_llm().complete("planner", "system", "user", {})
        entered.set()
        release.wait(5)
        return dict(_OK_STATE)

    def instant_stream(*_args, **_kwargs):
        yield "step", {"step": "plan"}
        yield "result", dict(_OK_STATE)

    monkeypatch.setattr(graph, "ask", slow_ask)
    monkeypatch.setattr(graph, "stream", instant_stream)
    body = {"dataset_id": dataset_id, "question": "What is the total revenue?"}
    holder = threading.Thread(target=lambda: client.post("/ask", json=body))
    holder.start()
    assert entered.wait(5)
    saw: list[str] = []
    with client.stream("POST", "/ask/stream", json=body) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if "queued" in line:
                saw.append("queued")
                release.set()
            if line.startswith("event: result"):
                saw.append("result")
                break
    holder.join(5)
    assert saw == ["queued", "result"]
    api_module.gate.reset()


def test_stream_timeout_reports_busy(monkeypatch, dataset_id):
    monkeypatch.setattr(api_module, "settings", dataclasses.replace(
        api_module.settings, max_concurrent_asks=1, queue_timeout_s=0.4,
    ))
    api_module.gate.reset()
    entered = threading.Event()
    release = threading.Event()

    def slow_ask(*_args, **_kwargs):
        demo_llm().complete("planner", "system", "user", {})
        entered.set()
        release.wait(5)
        return dict(_OK_STATE)

    monkeypatch.setattr(graph, "ask", slow_ask)
    body = {"dataset_id": dataset_id, "question": "What is the total revenue?"}
    holder = threading.Thread(target=lambda: client.post("/ask", json=body))
    holder.start()
    assert entered.wait(5)
    with client.stream("POST", "/ask/stream", json=body) as response:
        body_text = "".join(response.iter_text())
    assert "queued" in body_text
    assert "Demo is busy, try again in a minute" in body_text
    release.set()
    holder.join(5)
    api_module.gate.reset()


def test_retention_deletes_old_uploads_and_keeps_the_sample(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo(demo_retention_hours=24))
    created_sample = False
    sample_id = "ab" * 6
    if not any(d["name"] == SAMPLE_DATASET_NAME for d in store.list_datasets()):
        store.add_dataset(sample_id, SAMPLE_DATASET_NAME, "csv", "sales.csv", ["sales"])
        created_sample = True
    else:
        sample_id = next(d["id"] for d in store.list_datasets() if d["name"] == SAMPLE_DATASET_NAME)
    with store._conn() as con:
        con.execute("UPDATE datasets SET created_at=? WHERE id=?", (time.time() - 48 * 3600, sample_id))

    old_id, _ = db.create_dataset({"old.csv": b"a\n1\n"})
    store.add_dataset(old_id, "old.csv", "csv", "old.csv", ["old"])
    with store._conn() as con:
        con.execute("UPDATE datasets SET created_at=? WHERE id=?", (time.time() - 48 * 3600, old_id))
    store.create_conversation(old_id, "old chat")
    chart = db.dataset_dir(old_id) / "runs" / "abc1234567"
    chart.mkdir(parents=True)
    (chart / "chart_1.png").write_bytes(b"png")

    fresh_id, _ = db.create_dataset({"new.csv": b"a\n1\n"})
    store.add_dataset(fresh_id, "new.csv", "csv", "new.csv", ["new"])

    try:
        assert api_module.purge_demo_uploads() == 1
        assert store.get_dataset(old_id) is None
        assert store.list_conversations(old_id) == []
        assert not db.dataset_dir(old_id).exists()
        assert store.get_dataset(fresh_id) is not None
        assert store.get_dataset(sample_id) is not None
        monkeypatch.setattr(api_module, "settings", dataclasses.replace(api_module.settings, public_demo=False))
        assert api_module.purge_demo_uploads() == 0
        assert store.get_dataset(fresh_id) is not None
    finally:
        store.delete_dataset(fresh_id)
        if created_sample:
            store.delete_dataset(sample_id)


def test_forwarded_for_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setattr(api_module, "settings", _demo(
        asks_per_minute=1, api_keys=frozenset({"shared"}), trusted_proxies=frozenset(),
    ))
    limiter._hits.clear()
    body = {"dataset_id": "ffffffffffff", "question": "hello there"}

    def post(ip):
        return client.post("/ask", json=body, headers={"X-API-Key": "shared", "X-Forwarded-For": ip}).status_code

    assert post("203.0.113.5") == 404
    assert post("198.51.100.8") == 429
    limiter._hits.clear()
