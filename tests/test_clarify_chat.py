"""Tests for the /clarify-chat endpoint and the round-cap logic that
guarantees the clarify loop always terminates. Uses a monkeypatched provider
so no real network/LLM calls happen."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fake_provider import FakeProvider  # noqa: E402
import main  # noqa: E402
from app.utils import rate_limit  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The limiter is in-process/module-level state; clear it between tests
    # so one test's calls don't trip another's rate limit.
    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


def test_clarify_chat_returns_questions_when_model_says_unclear(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(provider, "generate", lambda system_prompt, user_message: json.dumps({
        "needs_clarification": True,
        "questions": [{"question": "Who is this for?", "why_it_matters": "Shapes the whole feature set."}],
    }))
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    res = client.post("/clarify-chat", json={"text": "Build a social app", "qa_history": []})
    assert res.status_code == 200
    data = res.json()
    assert data["needs_clarification"] is True
    assert data["round"] == 1
    assert data["questions"][0]["question"] == "Who is this for?"


def test_clarify_chat_reports_ready_when_model_says_clear(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(provider, "generate", lambda system_prompt, user_message: json.dumps({
        "needs_clarification": False, "questions": [],
    }))
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    res = client.post("/clarify-chat", json={"text": "Build a food delivery app for small restaurants with menus, cart, and online payment.", "qa_history": []})
    assert res.status_code == 200
    assert res.json()["needs_clarification"] is False


def test_clarify_chat_forces_ready_once_round_cap_is_exceeded(monkeypatch):
    provider = FakeProvider()
    calls = []

    def always_wants_more(system_prompt, user_message):
        calls.append(1)
        return json.dumps({"needs_clarification": True, "questions": [{"question": "More?", "why_it_matters": "x"}]})

    monkeypatch.setattr(provider, "generate", always_wants_more)
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    # qa_history already has MAX_CLARIFY_ROUNDS entries -> round_number exceeds the cap.
    qa_history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(main.MAX_CLARIFY_ROUNDS)]
    res = client.post("/clarify-chat", json={"text": "Build a social app", "qa_history": qa_history})

    assert res.status_code == 200
    data = res.json()
    assert data["needs_clarification"] is False
    assert data["questions"] == []
    assert len(calls) == 0  # capped before even calling the provider


def test_clarify_chat_forces_ready_when_model_wants_more_on_the_last_allowed_round(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(provider, "generate", lambda system_prompt, user_message: json.dumps({
        "needs_clarification": True, "questions": [{"question": "More?", "why_it_matters": "x"}],
    }))
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    # qa_history has (MAX_CLARIFY_ROUNDS - 1) entries -> this call IS round MAX_CLARIFY_ROUNDS,
    # still within the cap, but the model asking for more must be overridden.
    qa_history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(main.MAX_CLARIFY_ROUNDS - 1)]
    res = client.post("/clarify-chat", json={"text": "Build a social app", "qa_history": qa_history})

    data = res.json()
    assert data["round"] == main.MAX_CLARIFY_ROUNDS
    assert data["needs_clarification"] is False  # forced, despite the model wanting more


def test_clarify_chat_checks_structured_brief_context_with_provider(monkeypatch):
    text = Path(ROOT / "docs" / "AUTOSDLC_PROJECT_BRIEF.md").read_text(encoding="utf-8")

    provider = FakeProvider()
    monkeypatch.setattr(provider, "generate", lambda *_: json.dumps({
        "needs_clarification": False,
        "questions": [],
    }))

    monkeypatch.setattr(main, "get_provider", lambda: provider)
    res = client.post("/clarify-chat", json={"text": text, "qa_history": []})

    assert res.status_code == 200
    assert res.json()["needs_clarification"] is False


def test_clarify_chat_rejects_empty_text():
    res = client.post("/clarify-chat", json={"text": "   ", "qa_history": []})
    assert res.status_code == 400


def test_clarify_chat_rate_limit_returns_429_after_limit_exceeded(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(provider, "generate", lambda system_prompt, user_message: json.dumps({
        "needs_clarification": False, "questions": [],
    }))
    monkeypatch.setattr(main, "get_provider", lambda: provider)
    monkeypatch.setattr(rate_limit, "CLARIFY_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(main, "CLARIFY_LIMIT_PER_MINUTE", 2)

    for _ in range(2):
        res = client.post("/clarify-chat", json={"text": "Build a social app", "qa_history": []})
        assert res.status_code == 200

    res = client.post("/clarify-chat", json={"text": "Build a social app", "qa_history": []})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "RATE_LIMIT_ERROR"
