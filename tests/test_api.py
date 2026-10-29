from fastapi.testclient import TestClient

from app.api import app
from tests.conftest import SAMPLE

client = TestClient(app)


def test_upload_and_ask_offline_demo():
    r = client.post("/datasets", files={"files": ("sales.csv", SAMPLE.read_bytes(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tables"] == ["sales"] and "revenue_pkr" in body["schema"]

    r = client.post("/ask", json={"dataset_id": body["dataset_id"], "question": "Show me the data"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ok" and out["verified"] is True
    assert out["row_count"] == 20 and len(out["rows"]) == 20
    assert out["sql"].startswith("SELECT * FROM sales")


def test_provider_error_is_502(monkeypatch):
    uploaded = client.post("/datasets", files={"files": ("sales.csv", SAMPLE.read_bytes(), "text/csv")})
    dataset_id = uploaded.json()["dataset_id"]

    def boom(*_args, **_kwargs):
        raise RuntimeError(
            'BadRequestError: {"message":"Your credit balance is too low '
            'request_id req_011CgWe8N6xpLnpxUcDaZFLR sk-ant-api03-secret"}'
        )

    monkeypatch.setattr("app.graph.ask", boom)
    response = client.post("/ask", json={"dataset_id": dataset_id, "question": "Which region leads?"})
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail.startswith("Model provider error:")
    assert "credit balance" in detail
    assert "req_" not in detail
    assert "sk-ant" not in detail


def test_rejects_non_csv_and_bad_ids():
    r = client.post("/datasets", files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert client.post("/ask", json={"dataset_id": "../../etc", "question": "hello"}).status_code == 404
    assert client.get("/charts/abcdefabcdef/../../x/chart_1.png").status_code in (400, 404)
