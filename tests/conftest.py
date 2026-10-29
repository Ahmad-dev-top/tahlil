import os
import tempfile
from pathlib import Path

# Must be set before `app` is imported: offline LLM, no Docker needed, throwaway data dir.
os.environ.update(
    LLM_MODE="fake",
    SANDBOX_MODE=os.environ.get("TEST_SANDBOX_MODE", "local"),
    DATA_DIR=tempfile.mkdtemp(prefix="tahlil-test-"),
    OTEL_SDK_DISABLED="true",
    ALLOW_SQLITE_CONNECTOR="true",
    CREWAI_DISABLE_TELEMETRY="true",
    ASKS_PER_MINUTE="1000",
)

import pytest  # noqa: E402

from app import db  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sales.csv"


@pytest.fixture(scope="session")
def dataset_id() -> str:
    ds, tables = db.create_dataset({"sales.csv": SAMPLE.read_bytes()})
    assert tables == ["sales"]
    return ds
