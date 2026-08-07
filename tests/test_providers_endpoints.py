"""Regression tests for this session's provider-settings work:
UsageTracker's proactive rpm throttle + persisted daily (tpd/rpd) counters,
and the GET /providers / POST /providers/select endpoints. Isolated from the
real local dev database (app/services/database.DB_PATH) via a tmp_path
monkeypatch — without it, these tests would write real "ai_provider"
settings into whichever DB a locally-run `uvicorn main:app` also uses."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.database as database  # noqa: E402
from app.services.providers import UsageTracker  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    yield


# ── UsageTracker ─────────────────────────────────────────────────────────

def test_acquire_allows_calls_up_to_rpm_without_blocking():
    tracker = UsageTracker("test-provider", rpm=3, tpm=None, tpd=None)
    # All 3 should return immediately — well under the limit.
    for _ in range(3):
        tracker.acquire()
    status = tracker.status()
    assert status["requests"]["used"] == 3
    assert status["requests"]["limit"] == 3


def test_record_success_tracks_tpm_when_configured():
    tracker = UsageTracker("test-provider", rpm=25, tpm=10000, tpd=None)
    tracker.record_success(150)
    tracker.record_success(50)
    status = tracker.status()
    assert status["tokens"]["used"] == 200
    assert status["tokens"]["window"] == "minute"


def test_record_success_persists_tpd_across_tracker_instances():
    # Two separate UsageTracker instances for the same provider_id (as would
    # happen across a container restart) must see the same daily total —
    # that's the whole point of persisting it, not just an in-memory count.
    tracker_a = UsageTracker("shared-id", rpm=5, tpm=None, tpd=1_000_000)
    tracker_a.record_success(500)
    tracker_b = UsageTracker("shared-id", rpm=5, tpm=None, tpd=1_000_000)
    tracker_b.record_success(250)

    assert tracker_a.status()["tokens"]["used"] == 750
    assert tracker_b.status()["tokens"]["used"] == 750


def test_record_success_persists_rpd_as_request_count_not_tokens():
    tracker = UsageTracker("rpd-provider", rpm=15, tpm=250_000, tpd=None, rpd=500)
    tracker.record_success(9999)  # token count is irrelevant to rpd
    tracker.record_success(1)
    status = tracker.status()
    assert status["requests"]["used"] == 2
    assert status["requests"]["limit"] == 500
    assert status["requests"]["window"] == "day"


def test_record_error_surfaces_in_status_until_next_success():
    tracker = UsageTracker("err-provider", rpm=5, tpm=None, tpd=None)
    tracker.record_error("boom")
    assert tracker.status()["last_error"] == "boom"
    tracker.record_success(10)
    assert tracker.status()["last_error"] is None


def test_status_before_any_live_probe_reports_not_live():
    tracker = UsageTracker("never-probed", rpm=5, tpm=None, tpd=None)
    status = tracker.status()
    assert status["live"] is False
    assert status["checked_at"] is None


def test_set_live_with_numeric_data_overrides_self_tracked_estimate():
    tracker = UsageTracker("live-provider", rpm=5, tpm=None, tpd=None)
    tracker.record_success(10)  # self-tracked: 0 requests counted (tpm not set)
    tracker.set_live({"requests": {"used": 4, "limit": 5, "window": "minute"}})
    status = tracker.status()
    assert status["live"] is True
    assert status["requests"] == {"used": 4, "limit": 5, "window": "minute"}


def test_set_live_with_empty_dict_still_counts_as_a_completed_check():
    # Gemini-shaped case: probe succeeded but the provider returns no
    # numeric quota headers. Must be distinguishable from "never checked".
    tracker = UsageTracker("no-numbers-provider", rpm=5, tpm=None, tpd=None)
    tracker.set_live({})
    status = tracker.status()
    assert status["live"] is True
    assert status["no_live_numbers"] is True


# ── /providers endpoints ─────────────────────────────────────────────────

client = TestClient(__import__("main").app)


def test_get_providers_lists_all_three_ui_providers():
    res = client.get("/providers")
    assert res.status_code == 200
    data = res.json()
    ids = {p["id"] for p in data["providers"]}
    assert ids == {"groq", "cerebras", "gemini"}


def test_select_provider_persists_and_reflects_in_active(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("CEREBRAS_API_KEY", "x")

    res = client.post("/providers/select", json={"provider": "cerebras"})
    assert res.status_code == 200
    assert res.json()["active"] == "cerebras"

    # Persisted, not just returned — a fresh GET must agree.
    res2 = client.get("/providers")
    assert res2.json()["active"] == "cerebras"


def test_select_unknown_provider_returns_400():
    res = client.post("/providers/select", json={"provider": "not-a-real-provider"})
    assert res.status_code == 400


def test_select_unconfigured_provider_returns_400(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res = client.post("/providers/select", json={"provider": "gemini"})
    assert res.status_code == 400
