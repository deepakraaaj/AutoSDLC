"""Regression tests for /estimate-tokens' two accuracy fixes: real
per-provider pricing (via LiteLLM's cost map) instead of one flat blended
guess, and an epic-count guess that respects EPIC_GENERATION_SYSTEM's actual
floor of 10 epics regardless of brief length, instead of scaling down for
short briefs (confirmed empirically wrong: a 48-word brief still produced
9 epics — see main.py's SECONDS_PER_CALL comment for the empirical basis)."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.database as database  # noqa: E402
from app.services.providers import estimate_call_cost_usd  # noqa: E402
import main  # noqa: E402


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


client = TestClient(main.app)


# ── estimate_call_cost_usd ──────────────────────────────────────────────

def test_estimate_call_cost_uses_real_pricing_for_known_model(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(database, "get_setting", lambda key, default=None: "groq" if key == "ai_provider" else default)

    cost = estimate_call_cost_usd(input_tokens=1000, output_tokens=500)

    assert cost is not None
    assert cost > 0
    # Sanity bound — real Groq pricing is well under $0.01 for 1500 tokens.
    assert cost < 0.01


def test_estimate_call_cost_scales_with_token_count(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(database, "get_setting", lambda key, default=None: "groq" if key == "ai_provider" else default)

    small = estimate_call_cost_usd(input_tokens=100, output_tokens=50)
    large = estimate_call_cost_usd(input_tokens=10000, output_tokens=5000)

    assert small is not None and large is not None
    assert large > small


def test_estimate_call_cost_returns_none_for_unknown_active_provider(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setattr(database, "get_setting", lambda key, default=None: "not-a-real-provider" if key == "ai_provider" else default)

    assert estimate_call_cost_usd(input_tokens=1000, output_tokens=500) is None


# ── /estimate-tokens: epic-count floor ──────────────────────────────────

def test_estimate_tokens_short_brief_still_assumes_the_ten_epic_floor(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "x")

    # A short brief (well under the old word_count // 50 threshold for
    # reaching even a handful of epics) — the prompt itself still targets a
    # minimum of 10 regardless, so estimated_calls must reflect that floor,
    # not scale down to almost nothing.
    res = client.post("/estimate-tokens", json={
        "text": "Build a small polling tool where a team creates polls and votes.",
        "clarification_answers": {},
    })
    assert res.status_code == 200
    data = res.json()
    # 10 epics floor -> phase1(1) + phase2(10) + phase3(10) + phase4(ceil(200/5)=40) = 61
    assert data["estimated_calls"] >= 60


def test_estimate_tokens_cost_is_positive_and_reasonable(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "x")

    res = client.post("/estimate-tokens", json={
        "text": "Build a small polling tool where a team creates polls and votes.",
        "clarification_answers": {},
    })
    data = res.json()
    assert data["cost_usd"] > 0
    assert data["cost_usd"] < 5  # sanity bound — this should be cents, not dollars
