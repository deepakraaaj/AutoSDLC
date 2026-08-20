from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.services.jobs import configure_runner  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    yield
    configure_runner("generation", main._generation_job_runner)


def _wait(job_id: str, terminal=("succeeded", "failed", "cancelled")) -> dict:
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in terminal:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_generation_job_persists_progress_and_result():
    def runner(payload):
        yield "status", {"message": f"Working on {payload['text']}"}
        yield "done", {"output": {"generation_id": 42}}

    configure_runner("generation", runner)
    response = client.post("/jobs/generations", json={"text": "demo"})
    assert response.status_code == 202
    job = _wait(response.json()["id"])
    assert job["status"] == "succeeded"
    assert job["result"]["output"]["generation_id"] == 42

    events = client.get(f"/jobs/{job['id']}/events").json()["events"]
    assert [event["type"] for event in events] == ["status", "done"]
    assert events[0]["seq"] < events[1]["seq"]


def test_failed_job_retains_error_and_event():
    def runner(_payload):
        yield "error", {"error": {"message": "provider exhausted"}}

    configure_runner("generation", runner)
    job_id = client.post("/jobs/generations", json={"text": "demo"}).json()["id"]
    job = _wait(job_id)
    assert job["status"] == "failed"
    assert "provider exhausted" in job["error"]
    assert client.get(f"/jobs/{job_id}/events").json()["events"][0]["type"] == "error"


def test_job_can_be_cancelled_cooperatively():
    def runner(_payload):
        for index in range(50):
            time.sleep(0.005)
            yield "progress", {"index": index}

    configure_runner("generation", runner)
    job_id = client.post("/jobs/generations", json={"text": "demo"}).json()["id"]
    assert client.delete(f"/jobs/{job_id}").status_code == 200
    assert _wait(job_id)["status"] == "cancelled"


def test_database_records_current_schema_version():
    conn = database.get_connection()
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    conn.close()
    assert database.SCHEMA_VERSION in versions
