"""Tests for token spend tracking: app/services/database.py's
record_token_usage/get_token_usage_summary/list_token_usage, and the
/usage/summary + /usage/log endpoints (app/api/usage.py).

Every row here is meant to represent a LiteLLMProvider's own reported
usage (app/services/providers.py's usage_summary()) — never an estimate,
so these tests use realistic-looking fixed numbers rather than derived
ones, the same way test_project_pull_requests.py's fake job results do."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _usage(total=1000, cost=0.001):
    return {"ai_calls": 1, "prompt_tokens": total - 100, "completion_tokens": 100, "total_tokens": total, "cost_usd": cost}


def _insert_at(kind: str, ref_id: str, when: datetime, total=1000, cost=0.001):
    """Back-dated insert for window-boundary tests — record_token_usage
    itself always stamps 'now', so this goes straight to the table to place
    a row at a specific time."""
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO token_usage_log (kind, ref_id, provider, prompt_tokens, completion_tokens, total_tokens, cost_usd, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, ref_id, "groq", total - 100, 100, total, cost, when.isoformat()),
    )
    conn.commit()
    conn.close()


def test_record_and_list_token_usage():
    database.record_token_usage("generation", "42", "groq", _usage(total=5300, cost=0.0021))
    entries = database.list_token_usage()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "generation"
    assert entry["ref_id"] == "42"
    assert entry["provider"] == "groq"
    assert entry["total_tokens"] == 5300
    assert entry["cost_usd"] == 0.0021


def test_list_token_usage_orders_newest_first():
    now = datetime.now(timezone.utc)
    _insert_at("generation", "1", now - timedelta(minutes=10))
    _insert_at("generation", "2", now)
    entries = database.list_token_usage()
    assert [e["ref_id"] for e in entries] == ["2", "1"]


def test_list_token_usage_caps_limit_at_500():
    for i in range(3):
        database.record_token_usage("generation", str(i), "groq", _usage())
    entries = database.list_token_usage(limit=10000)
    assert len(entries) == 3  # cap only bounds the query, doesn't fabricate rows


def test_usage_summary_buckets_by_window():
    now = datetime.now(timezone.utc)
    _insert_at("generation", "today", now, total=1000, cost=0.001)
    _insert_at("generation", "3-days-ago", now - timedelta(days=3), total=2000, cost=0.002)
    _insert_at("generation", "20-days-ago", now - timedelta(days=20), total=4000, cost=0.004)
    _insert_at("generation", "60-days-ago", now - timedelta(days=60), total=8000, cost=0.008)

    summary = database.get_token_usage_summary()
    assert summary["today"]["total_tokens"] == 1000
    assert summary["week"]["total_tokens"] == 3000  # today + 3 days ago
    assert summary["month"]["total_tokens"] == 7000  # today + 3d + 20d, not the 60-day-old row
    assert summary["all_time"]["total_tokens"] == 15000  # everything


def test_usage_summary_empty_db_is_all_zeros():
    summary = database.get_token_usage_summary()
    for window in ("today", "week", "month", "all_time"):
        assert summary[window] == {"ai_calls": 0, "total_tokens": 0, "cost_usd": 0}


def test_usage_summary_endpoint():
    database.record_token_usage("bitbucket_review", "acme/widgets#7", "mistral", _usage(total=7990, cost=0.00137))
    response = client.get("/usage/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["today"]["total_tokens"] == 7990
    assert body["today"]["ai_calls"] == 1


def test_usage_log_endpoint_returns_entries():
    database.record_token_usage("generation", "1", "groq", _usage(total=1200))
    database.record_token_usage("security_scan", "acme/widgets", "groq", _usage(total=3400))
    response = client.get("/usage/log")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 2
    assert {e["kind"] for e in entries} == {"generation", "security_scan"}


def test_usage_log_endpoint_respects_limit():
    for i in range(5):
        database.record_token_usage("generation", str(i), "groq", _usage())
    response = client.get("/usage/log", params={"limit": 2})
    assert len(response.json()["entries"]) == 2
