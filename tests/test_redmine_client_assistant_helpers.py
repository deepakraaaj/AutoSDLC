"""Unit tests for the redmine/client.py helpers added for the chat assistant: list_issues,
get_issue, list_issue_statuses, update_issue_fields, create_single_issue. Follows
tests/test_redmine_priority_mapping.py's convention of monkeypatching at the semantic function
layer; the two spots that talk to httpx directly (list_issues, list_issue_statuses, and the PUT
in update_issue_fields) get a minimal fake response instead of a real network call."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import redmine.client as redmine  # noqa: E402


class FakeResponse:
    def __init__(self, json_data, is_error=False):
        self._json_data = json_data
        self.is_error = is_error
        self.status_code = 422 if is_error else 200
        self.text = json.dumps(json_data)

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.is_error:
            raise RuntimeError("http error")


def test_list_issues_applies_filters_and_trims_fields(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse({"issues": [{
            "id": 42, "subject": "Bug", "status": {"name": "New"}, "priority": {"name": "High"},
            "assigned_to": {"name": "Sam"}, "tracker": {"name": "Task"},
            "project": {"id": 3, "name": "Website Redesign"}, "updated_on": "2026-08-01T00:00:00Z",
        }]})

    monkeypatch.setattr(redmine.httpx, "get", fake_get)
    monkeypatch.setattr(redmine, "get_tracker_id", lambda *a, **kw: "7")

    issues = redmine.list_issues("http://example.com", "key", project_id="3", tracker="Task", query_text="bug")

    assert captured["url"] == "http://example.com/issues.json"
    assert captured["params"]["project_id"] == "3"
    assert captured["params"]["tracker_id"] == "7"
    assert captured["params"]["subject"] == "~bug"
    assert issues == [{
        "id": 42, "subject": "Bug", "status": "New", "priority": "High", "assignee": "Sam",
        "tracker": "Task", "project": "Website Redesign", "project_id": 3,
        "updated_on": "2026-08-01T00:00:00Z", "url": "http://example.com/issues/42",
    }]


def test_list_issues_defaults_to_open_status(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["params"] = params
        return FakeResponse({"issues": []})

    monkeypatch.setattr(redmine.httpx, "get", fake_get)

    redmine.list_issues("http://example.com", "key")

    assert captured["params"]["status_id"] == "open"


def test_list_issues_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(redmine.httpx, "get", lambda *a, **kw: FakeResponse({"errors": ["bad request"]}, is_error=True))

    with pytest.raises(RuntimeError, match="Redmine issue search failed"):
        redmine.list_issues("http://example.com", "key")


def test_get_issue_formats_and_adds_description(monkeypatch):
    monkeypatch.setattr(redmine, "_get_issue", lambda *a, **kw: {
        "id": 42, "subject": "Bug", "status": {"name": "New"}, "priority": {"name": "High"},
        "assigned_to": {"name": "Sam"}, "tracker": {"name": "Task"},
        "project": {"id": 3, "name": "Website Redesign"}, "updated_on": "2026-08-01T00:00:00Z",
        "description": "It's broken.",
    })

    issue = redmine.get_issue("http://example.com", "key", 42)

    assert issue["id"] == 42
    assert issue["description"] == "It's broken."
    assert issue["url"] == "http://example.com/issues/42"


def test_list_issue_statuses_returns_list(monkeypatch):
    monkeypatch.setattr(redmine.httpx, "get", lambda *a, **kw: FakeResponse({"issue_statuses": [{"id": 1, "name": "New"}]}))
    assert redmine.list_issue_statuses("http://example.com", "key") == [{"id": 1, "name": "New"}]


def test_list_issue_statuses_returns_empty_list_on_error(monkeypatch):
    def fake_get(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(redmine.httpx, "get", fake_get)
    assert redmine.list_issue_statuses("http://example.com", "key") == []


def test_update_issue_fields_resolves_labels_and_puts(monkeypatch):
    monkeypatch.setattr(redmine, "list_issue_statuses", lambda *a: [{"id": 5, "name": "Closed"}])
    monkeypatch.setattr(redmine, "list_issue_priorities", lambda *a: [{"id": 4, "name": "Urgent"}])
    monkeypatch.setattr(redmine, "get_issue", lambda *a, **kw: {"id": 42, "status": "Closed", "priority": "Urgent"})
    captured = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse({})

    monkeypatch.setattr(redmine.httpx, "put", fake_put)

    result = redmine.update_issue_fields("http://example.com", "key", 42, status_label="closed", priority_label="Urgent")

    assert captured["url"] == "http://example.com/issues/42.json"
    assert captured["payload"]["issue"]["status_id"] == 5
    assert captured["payload"]["issue"]["priority_id"] == 4
    assert result == {"id": 42, "status": "Closed", "priority": "Urgent"}


def _capturing_put(captured):
    def fake_put(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return FakeResponse({})
    return fake_put


def test_update_issue_fields_accepts_numeric_assignee_id(monkeypatch):
    monkeypatch.setattr(redmine, "get_issue", lambda *a, **kw: {"id": 42})
    captured = {}
    monkeypatch.setattr(redmine.httpx, "put", _capturing_put(captured))

    redmine.update_issue_fields("http://example.com", "key", 42, assigned_to="9")

    assert captured["payload"]["issue"]["assigned_to_id"] == 9


def test_update_issue_fields_resolves_assignee_by_name(monkeypatch):
    monkeypatch.setattr(redmine, "get_issue", lambda *a, **kw: {"id": 42})
    monkeypatch.setattr(redmine, "find_user_id_by_name", lambda *a, **kw: 7)
    captured = {}
    monkeypatch.setattr(redmine.httpx, "put", _capturing_put(captured))

    redmine.update_issue_fields("http://example.com", "key", 42, assigned_to="Sam")

    assert captured["payload"]["issue"]["assigned_to_id"] == 7


def test_update_issue_fields_raises_for_unknown_status(monkeypatch):
    monkeypatch.setattr(redmine, "list_issue_statuses", lambda *a: [{"id": 1, "name": "New"}])
    with pytest.raises(ValueError, match="Unknown Redmine issue status"):
        redmine.update_issue_fields("http://example.com", "key", 42, status_label="Bogus")


def test_update_issue_fields_raises_when_no_fields_given():
    with pytest.raises(ValueError, match="No fields"):
        redmine.update_issue_fields("http://example.com", "key", 42)


def test_create_single_issue_resolves_ids_and_creates(monkeypatch):
    monkeypatch.setattr(redmine, "resolve_project_id", lambda *a: "3")
    monkeypatch.setattr(redmine, "get_tracker_id", lambda *a: "7")
    monkeypatch.setattr(redmine, "build_priority_id_map", lambda *a: {"critical": 5, "high": 4, "medium": 2, "low": 1})
    captured = {}
    monkeypatch.setattr(redmine, "_create_issue", lambda url, key, payload: captured.setdefault("payload", payload) or {"id": 99})
    monkeypatch.setattr(redmine, "get_issue", lambda *a, **kw: {"id": 99, "subject": "Fix it"})

    issue = redmine.create_single_issue("http://example.com", "key", "website-redesign", "Task", "Fix it", priority_label="high")

    assert captured["payload"]["issue"]["project_id"] == "3"
    assert captured["payload"]["issue"]["tracker_id"] == 7
    assert captured["payload"]["issue"]["priority_id"] == 4
    assert issue == {"id": 99, "subject": "Fix it"}


def test_create_single_issue_raises_for_unresolved_project(monkeypatch):
    monkeypatch.setattr(redmine, "resolve_project_id", lambda *a: "website-redesign")
    with pytest.raises(ValueError, match="not found"):
        redmine.create_single_issue("http://example.com", "key", "website-redesign", "Task", "Fix it")


def test_create_single_issue_raises_for_unknown_tracker(monkeypatch):
    monkeypatch.setattr(redmine, "resolve_project_id", lambda *a: "3")
    monkeypatch.setattr(redmine, "get_tracker_id", lambda *a: None)
    with pytest.raises(ValueError, match="tracker"):
        redmine.create_single_issue("http://example.com", "key", "website-redesign", "Bogus", "Fix it")
