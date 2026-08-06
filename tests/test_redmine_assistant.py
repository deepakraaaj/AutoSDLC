"""Tests for /assistant/chat — the Redmine chat assistant's router+dispatch endpoint.
Mirrors tests/test_clarify_chat.py's conventions (TestClient, monkeypatched provider, rate
limiter reset). Redmine calls are monkeypatched at the main.* import site so no network happens
and so tests can assert the model's guesses are never trusted for real data, only for routing."""
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

REDMINE_FIELDS = {
    "redmine_url": "https://redmine.example.com",
    "redmine_api_key": "secret-key",
    "redmine_project_id": "website-redesign",
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


def _provider_returning(payload: dict):
    provider = FakeProvider()
    provider.generate = lambda system_prompt, user_message: json.dumps(payload)
    return provider


def test_rejects_empty_message():
    res = client.post("/assistant/chat", json={"message": "   ", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 400


def test_list_issues_returns_real_data_not_model_text(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "list_issues",
        "params": {"project": "website-redesign", "status": "open"},
        "reply": "this text should be overridden by real data",
    }))
    fake_issues = [
        {"id": 42, "subject": "Checkout button broken", "status": "New", "priority": "High",
         "assignee": None, "tracker": "Task", "project": "Website Redesign", "project_id": 1,
         "updated_on": "2026-08-01T00:00:00Z", "url": "https://redmine.example.com/issues/42"},
    ]
    monkeypatch.setattr(main, "list_issues", lambda *a, **kw: fake_issues)

    res = client.post("/assistant/chat", json={"message": "what's open?", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    data = res.json()
    assert data["issues"] == fake_issues
    assert "42" in data["reply"]
    assert "Checkout button broken" in data["reply"]


def test_list_issues_without_redmine_configured_asks_to_connect(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "list_issues", "params": {}, "reply": "sure",
    }))
    called = []
    monkeypatch.setattr(main, "list_issues", lambda *a, **kw: called.append(1))

    res = client.post("/assistant/chat", json={
        "message": "what's open?", "redmine_url": "", "redmine_api_key": "", "redmine_project_id": "",
        "generation_id": None,
    })
    assert res.status_code == 200
    assert called == []
    assert "connect" in res.json()["reply"].lower()


def test_get_issue_returns_real_issue(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "get_issue", "params": {"issue_id": 42}, "reply": "checking",
    }))
    fake_issue = {"id": 42, "subject": "Checkout button broken", "status": "New", "priority": "High",
                  "assignee": "Sam", "tracker": "Task", "project": "Website Redesign", "project_id": 1,
                  "updated_on": "2026-08-01T00:00:00Z", "url": "https://redmine.example.com/issues/42",
                  "description": "It's broken."}
    monkeypatch.setattr(main, "get_issue", lambda *a, **kw: fake_issue)

    res = client.post("/assistant/chat", json={"message": "what about #42", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    data = res.json()
    assert data["issue"] == fake_issue
    assert "Sam" in data["reply"]


def test_create_issue_requires_confirmation_and_does_not_call_redmine(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "create_issue",
        "params": {"project": "website-redesign", "tracker": "Task", "subject": "Fix checkout button",
                    "description": "", "priority": "high"},
        "reply": "About to create it",
    }))

    def _exploding_create(*a, **kw):
        raise AssertionError("create_single_issue must not run before confirmation")

    monkeypatch.setattr(main, "create_single_issue", _exploding_create)

    res = client.post("/assistant/chat", json={"message": "log a bug for the checkout button", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is True
    assert data["pending_action"]["intent"] == "create_issue"
    assert data["pending_action"]["params"]["subject"] == "Fix checkout button"


def test_confirm_create_issue_calls_redmine_and_returns_created_issue(monkeypatch):
    fake_created = {"id": 99, "subject": "Fix checkout button", "status": "New", "priority": "High",
                     "assignee": None, "tracker": "Task", "project": "Website Redesign", "project_id": 1,
                     "updated_on": "2026-08-01T00:00:00Z", "url": "https://redmine.example.com/issues/99",
                     "description": ""}
    calls = []
    monkeypatch.setattr(main, "create_single_issue", lambda *a, **kw: calls.append(kw) or fake_created)

    res = client.post("/assistant/chat", json={
        "message": "", **REDMINE_FIELDS, "generation_id": None,
        "confirm": True,
        "pending_action": {"intent": "create_issue", "params": {
            "project": "website-redesign", "tracker": "Task", "subject": "Fix checkout button",
            "description": "", "priority": "high",
        }},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["issue"] == fake_created
    assert "99" in data["reply"]
    assert len(calls) == 1


def test_confirm_is_ignored_if_pending_action_missing():
    # confirm=True with no pending_action falls through to normal routing, which requires a
    # non-empty message.
    res = client.post("/assistant/chat", json={"message": "  ", **REDMINE_FIELDS, "generation_id": None, "confirm": True})
    assert res.status_code == 400


def test_update_issue_requires_confirmation_then_confirm(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "update_issue", "params": {"issue_id": 42, "status": "Closed"}, "reply": "sure",
    }))

    res = client.post("/assistant/chat", json={"message": "close #42", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is True
    pending_action = data["pending_action"]

    fake_updated = {"id": 42, "subject": "Checkout button broken", "status": "Closed", "priority": "High",
                     "assignee": None, "tracker": "Task", "project": "Website Redesign", "project_id": 1,
                     "updated_on": "2026-08-01T00:00:00Z", "url": "https://redmine.example.com/issues/42"}
    monkeypatch.setattr(main, "update_issue_fields", lambda *a, **kw: fake_updated)

    confirm_res = client.post("/assistant/chat", json={
        "message": "", **REDMINE_FIELDS, "generation_id": None,
        "confirm": True, "pending_action": pending_action,
    })
    assert confirm_res.status_code == 200
    assert confirm_res.json()["issue"] == fake_updated


def test_generate_backlog_triggers_generation_without_touching_redmine(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "generate_backlog",
        "params": {"brief_text": "Build a food delivery app for small restaurants."},
        "reply": "Starting now",
    }))
    for name in ("list_issues", "get_issue", "create_single_issue", "update_issue_fields"):
        monkeypatch.setattr(main, name, lambda *a, **kw: (_ for _ in ()).throw(AssertionError(f"{name} must not be called")))

    res = client.post("/assistant/chat", json={
        "message": "build me a backlog for a food delivery app",
        "redmine_url": "", "redmine_api_key": "", "redmine_project_id": "", "generation_id": None,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "trigger_generation"
    assert "food delivery" in data["generation_text"]


def test_push_backlog_blocked_when_backlog_not_trust_gate_passed(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "push_backlog", "params": {}, "reply": "pushing",
    }))
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {
        "id": gen_id, "output": {"validation": {"trust_level": "review"}},
    })

    res = client.post("/assistant/chat", json={"message": "push that to redmine", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "none"
    assert "trust gate" in data["reply"].lower()


def test_push_backlog_allowed_when_trusted_and_configured(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "push_backlog", "params": {}, "reply": "pushing",
    }))
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {
        "id": gen_id, "output": {"validation": {"trust_level": "trusted"}},
    })

    res = client.post("/assistant/chat", json={"message": "push that to redmine", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    assert res.json()["action"] == "trigger_push"


def test_malformed_router_response_falls_back_to_chitchat(monkeypatch):
    provider = FakeProvider()
    provider.generate = lambda system_prompt, user_message: "not valid json"
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    res = client.post("/assistant/chat", json={"message": "hello", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "none"
    assert data["requires_confirmation"] is False


def test_rate_limit_returns_429_after_limit_exceeded(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_returning({
        "intent": "chitchat", "params": {}, "reply": "hi",
    }))
    monkeypatch.setattr(rate_limit, "ASSISTANT_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(main, "ASSISTANT_LIMIT_PER_MINUTE", 2)

    for _ in range(2):
        res = client.post("/assistant/chat", json={"message": "hi", **REDMINE_FIELDS, "generation_id": None})
        assert res.status_code == 200

    res = client.post("/assistant/chat", json={"message": "hi", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "RATE_LIMIT_ERROR"
