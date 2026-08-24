"""Tests for bitbucket/client.py's push_backlog_to_bitbucket. Mirrors
tests/test_redmine_client_assistant_helpers.py's monkeypatch-httpx style;
mirrors push_to_redmine's created/skipped/warnings result-shape contract."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bitbucket.client as bb  # noqa: E402
from app.schemas.models import Epic, GenerationOutput  # noqa: E402


class FakeResponse:
    def __init__(self, json_data=None, is_error=False):
        self._json_data = json_data or {}
        self.is_error = is_error
        self.status_code = 422 if is_error else 201
        self.text = json.dumps(self._json_data)

    def json(self):
        return self._json_data


def _config():
    return bb.BitbucketConfig(base_url="https://api.bitbucket.org/2.0", workspace="acme", repo_slug="widgets", access_token="tok")


def _output():
    return GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="E1", title="Accounts", description="d", feature_area="Auth", priority="high")],
        stories=[], tasks=[], gaps=[],
    )


def test_push_raises_when_not_configured():
    import pytest
    unconfigured = bb.BitbucketConfig(base_url="", workspace="", repo_slug="", access_token="")
    with pytest.raises(ValueError, match="not configured"):
        bb.push_backlog_to_bitbucket(_output(), unconfigured)


def test_push_creates_new_issue(monkeypatch):
    ids = iter([101])
    monkeypatch.setattr(bb.httpx, "post", lambda *a, **kw: FakeResponse({"id": next(ids)}))
    result = bb.push_backlog_to_bitbucket(_output(), _config())
    assert len(result["created_issues"]) == 1
    created = result["created_issues"][0]
    assert created["ai_id"] == "E1"
    assert created["type"] == "epic"
    assert created["bitbucket_id"] == "101"
    assert created["status"] == "created"
    assert "skipped_issues" in result and result["skipped_issues"] == []


def test_push_skips_already_synced_item(monkeypatch):
    monkeypatch.setattr(bb.httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not create")))
    result = bb.push_backlog_to_bitbucket(_output(), _config(), existing_issue_ids={"epic": {"E1": "55"}})
    assert result["created_issues"] == []
    assert len(result["skipped_issues"]) == 1
    assert result["skipped_issues"][0]["bitbucket_id"] == "55"
    assert "Skipped 1" in result["warnings"][0]


def test_push_records_error_per_item_without_aborting(monkeypatch):
    monkeypatch.setattr(bb.httpx, "post", lambda *a, **kw: FakeResponse({"error": {"message": "boom"}}, is_error=True))
    result = bb.push_backlog_to_bitbucket(_output(), _config())
    assert len(result["created_issues"]) == 1
    assert "error" in result["created_issues"][0]
    assert "boom" in result["created_issues"][0]["error"]


def test_priority_map_covers_all_app_priority_labels():
    assert set(bb._BITBUCKET_PRIORITY_MAP.keys()) == {"critical", "high", "medium", "low"}
