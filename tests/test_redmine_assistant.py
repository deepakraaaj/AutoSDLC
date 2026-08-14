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


FAKE_HIERARCHY = {
    "generation_id": 1,
    "epics": [
        {
            "db_id": 10, "issue_id": None, "ai_id": "EP-0001", "title": "Security & Data Protection",
            "description": "Original epic description.", "feature_area": "Security", "priority": "high",
            "status": "planned", "redmine_id": None, "redmine_priority_name": None,
            "stories": [
                {
                    "db_id": 20, "issue_id": None, "ai_id": "US-0001", "title": "Login lockout",
                    "as_a": "user", "i_want": "my account locked after failed attempts",
                    "so_that": "brute force is prevented", "acceptance_criteria": ["Lock after 5 attempts"],
                    "feature_area": "Security", "size": "medium", "priority": "high", "confidence": "high",
                    "status": "planned", "redmine_id": None, "redmine_priority_name": None,
                    "tasks": [
                        {
                            "db_id": 30, "issue_id": None, "ai_id": "TASK-0001", "title": "Implement lockout logic",
                            "description": "Add a lockout counter.", "definition_of_done": "Locks after 5 tries",
                            "estimate_hours": "4", "dependencies": [], "confidence": "high", "priority": "high",
                            "status": "todo", "assignee": None, "redmine_id": None, "redmine_priority_name": None,
                            "test_cases": [],
                        },
                    ],
                },
            ],
        },
        {
            "db_id": 11, "issue_id": None, "ai_id": "EP-0002", "title": "Security Audit Logging",
            "description": "A second epic whose title also contains 'Security'.", "feature_area": "Security",
            "priority": "medium", "status": "planned", "redmine_id": None, "redmine_priority_name": None,
            "stories": [],
        },
    ],
}


def _provider_dispatching(router_payload: dict, change_fields: dict | None = None):
    """A FakeProvider whose response depends on which system prompt it's called with —
    change_request needs two distinct calls (the router, then _generate_content_change), unlike
    every other intent's single router call."""
    def generate(system_prompt, user_message):
        if system_prompt == main.CHANGE_REQUEST_SYSTEM:
            return json.dumps(change_fields or {})
        return json.dumps(router_payload)
    provider = FakeProvider()
    provider.generate = generate
    return provider


def test_change_request_with_no_generation_yet(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(router_payload={
        "intent": "change_request",
        "params": {"target_id": None, "target_hint": "the Security epic", "change_description": "clarify it"},
        "reply": "sure",
    }))
    res = client.post("/assistant/chat", json={"message": "update the Security epic", **REDMINE_FIELDS, "generation_id": None})
    assert res.status_code == 200
    assert "generate a backlog first" in res.json()["reply"].lower()


def test_change_request_resolves_by_id_requires_confirmation_then_confirms(monkeypatch):
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {"id": gen_id, "output": {"validation": {}}})
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gen_id: FAKE_HIERARCHY)
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(
        router_payload={
            "intent": "change_request",
            "params": {"target_id": "US-0001", "target_hint": None, "change_description": "mention lockout duration"},
            "reply": "sure",
        },
        change_fields={"acceptance_criteria": ["Lock after 5 attempts", "Lockout lasts 15 minutes"]},
    ))

    res = client.post("/assistant/chat", json={"message": "add lockout duration to US-0001", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is True
    pending_action = data["pending_action"]
    assert pending_action["intent"] == "change_request"
    assert pending_action["params"] == {
        "kind": "story", "db_id": 20,
        "fields": {"acceptance_criteria": ["Lock after 5 attempts", "Lockout lasts 15 minutes"]},
    }

    calls = []
    monkeypatch.setattr(main, "update_story_content", lambda story_id, fields: calls.append((story_id, fields)) or True)
    monkeypatch.setattr(main, "update_epic_content", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("wrong updater")))

    confirm_res = client.post("/assistant/chat", json={
        "message": "", **REDMINE_FIELDS, "generation_id": 1,
        "confirm": True, "pending_action": pending_action,
    })
    assert confirm_res.status_code == 200
    assert "updated the story" in confirm_res.json()["reply"].lower()
    assert calls == [(20, {"acceptance_criteria": ["Lock after 5 attempts", "Lockout lasts 15 minutes"]})]


def test_change_request_confirm_does_not_require_redmine_configured(monkeypatch):
    """Unlike create_issue/update_issue, change_request never touches Redmine — confirming one
    must work even with no Redmine connection saved."""
    monkeypatch.setattr(main, "update_epic_content", lambda epic_id, fields: True)

    res = client.post("/assistant/chat", json={
        "message": "", "redmine_url": "", "redmine_api_key": "", "redmine_project_id": "", "generation_id": 1,
        "confirm": True,
        "pending_action": {"intent": "change_request", "params": {"kind": "epic", "db_id": 10, "fields": {"title": "New title"}}},
    })
    assert res.status_code == 200
    assert "updated the epic" in res.json()["reply"].lower()


def test_change_request_resolves_by_hint_when_unambiguous(monkeypatch):
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {"id": gen_id, "output": {"validation": {}}})
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gen_id: FAKE_HIERARCHY)
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(
        router_payload={
            "intent": "change_request",
            "params": {"target_id": None, "target_hint": "the login lockout story", "change_description": "retitle it"},
            "reply": "sure",
        },
        change_fields={"title": "Account lockout after failed logins"},
    ))

    res = client.post("/assistant/chat", json={"message": "rename the login lockout story", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["pending_action"]["params"]["kind"] == "story"
    assert data["pending_action"]["params"]["db_id"] == 20


def test_change_request_ambiguous_hint_asks_which_one(monkeypatch):
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {"id": gen_id, "output": {"validation": {}}})
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gen_id: FAKE_HIERARCHY)
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(router_payload={
        "intent": "change_request",
        "params": {"target_id": None, "target_hint": "security", "change_description": "make it clearer"},
        "reply": "sure",
    }))

    res = client.post("/assistant/chat", json={"message": "update the security epic", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is False
    assert "EP-0001" in data["reply"] and "EP-0002" in data["reply"]


def test_change_request_unresolvable_hint_asks_for_id(monkeypatch):
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {"id": gen_id, "output": {"validation": {}}})
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gen_id: FAKE_HIERARCHY)
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(router_payload={
        "intent": "change_request",
        "params": {"target_id": None, "target_hint": "the payments epic", "change_description": "make it clearer"},
        "reply": "sure",
    }))

    res = client.post("/assistant/chat", json={"message": "update the payments epic", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is False
    assert "couldn't find" in data["reply"].lower()


def test_change_request_empty_diff_from_model_asks_to_be_more_specific(monkeypatch):
    monkeypatch.setattr(main, "get_generation", lambda gen_id: {"id": gen_id, "output": {"validation": {}}})
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gen_id: FAKE_HIERARCHY)
    monkeypatch.setattr(main, "get_provider", lambda: _provider_dispatching(
        router_payload={
            "intent": "change_request",
            "params": {"target_id": "EP-0001", "target_hint": None, "change_description": "make it better somehow"},
            "reply": "sure",
        },
        change_fields={},
    ))

    res = client.post("/assistant/chat", json={"message": "improve the security epic", **REDMINE_FIELDS, "generation_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["requires_confirmation"] is False
    assert "more specific" in data["reply"].lower()


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
