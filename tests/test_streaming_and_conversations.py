import json

from fastapi.testclient import TestClient

from app import graph, store
from app.api import app
from app.llm import FakeLLM
from tests.conftest import SAMPLE

client = TestClient(app)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def upload() -> str:
    r = client.post("/datasets", files={"files": ("sales.csv", SAMPLE.read_bytes(), "text/csv")},
                    data={"name": "Sales 2025"})
    assert r.status_code == 200, r.text
    return r.json()["dataset_id"]


def test_upload_is_registered():
    ds = upload()
    listed = {d["id"]: d for d in client.get("/datasets").json()}
    assert listed[ds]["name"] == "Sales 2025" and listed[ds]["tables"] == ["sales"]
    detail = client.get(f"/datasets/{ds}").json()
    assert "revenue_pkr" in detail["schema"]


def test_stream_emits_steps_then_result():
    ds = upload()
    r = client.post("/ask/stream", json={"dataset_id": ds, "question": "Show me the data"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[-1] == "result" and set(kinds[:-1]) == {"step"}
    steps = [d["step"] for k, d in events if k == "step"]
    assert steps == ["load_schema", "plan", "write_sql", "guard_sql", "run_sql",
                     "analyze", "report", "guard_report", "finish"]
    result = events[-1][1]
    assert result["status"] == "ok" and result["row_count"] == 20
    assert [t["step"] for t in result["trace"]] == steps


def test_stream_reports_errors_as_events(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model unavailable")
        yield  # pragma: no cover
    monkeypatch.setattr(graph, "stream", boom)
    ds = upload()
    events = parse_sse(client.post("/ask/stream", json={"dataset_id": ds, "question": "hello"}).text)
    assert events == [("error", {"error": "RuntimeError: model unavailable"})]


def test_conversation_turns_are_saved_and_titled():
    ds = upload()
    conv = client.post("/conversations", json={"dataset_id": ds}).json()
    for q in ["Show me the data", "Now only Punjab"]:
        r = client.post("/ask", json={"dataset_id": ds, "question": q, "conversation_id": conv["id"]})
        assert r.status_code == 200 and r.json()["turn_id"]
    detail = client.get(f"/conversations/{conv['id']}").json()
    assert detail["title"] == "Show me the data"
    assert [t["question"] for t in detail["turns"]] == ["Show me the data", "Now only Punjab"]
    assert detail["turns"][0]["sql"].startswith("SELECT")
    assert [c["id"] for c in client.get(f"/conversations?dataset_id={ds}").json()] == [conv["id"]]
    hist = store.history_for_prompt(conv["id"])
    assert len(hist) == 2 and hist[0]["question"] == "Show me the data"


def test_conversation_must_match_dataset():
    ds1, ds2 = upload(), upload()
    conv = client.post("/conversations", json={"dataset_id": ds1}).json()
    r = client.post("/ask", json={"dataset_id": ds2, "question": "hello", "conversation_id": conv["id"]})
    assert r.status_code == 404


def test_history_reaches_planner_and_sql_writer(dataset_id):
    llm = FakeLLM({
        "planner": ["1. Filter."],
        "sql": ["SELECT region, SUM(revenue_pkr) AS revenue FROM sales WHERE region = 'Punjab' GROUP BY 1"],
        "analysis_code": ["print(json.dumps({}))"],
        "report": [lambda c: "Done."],
    })
    history = [{"question": "Revenue by region?", "sql": "SELECT region, SUM(revenue_pkr) FROM sales GROUP BY 1",
                "answer": "Punjab leads."}]
    state = graph.ask(dataset_id, "Now only Punjab", llm, history)
    assert state["status"] == "ok"
    for role in ("planner", "sql"):
        prompt = next(u for r, u in llm.calls if r == role)
        assert "CONVERSATION SO FAR" in prompt and "Revenue by region?" in prompt
