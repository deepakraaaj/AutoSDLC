"""BITBUCKET_ALLOW_WRITES is the app's hard kill switch on writing to
Bitbucket — bitbucket/client.py's _require_writes_allowed, checked inside
post_pr_comment/create_bitbucket_issue/push_backlog_to_bitbucket themselves
(the lowest layer every write path funnels through), not just at each
endpoint. Unset/anything but exactly "true" means blocked, no exceptions —
this file locks that default in and proves no HTTP call is even attempted
when it's off."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bitbucket.client as bb  # noqa: E402
from app.schemas.models import Epic, GenerationOutput  # noqa: E402


def _config():
    return bb.BitbucketConfig(base_url="https://api.bitbucket.org/2.0", workspace="acme", repo_slug="widgets", access_token="tok")


def _boom(*a, **kw):
    """Any httpx call reaching here means the kill switch failed to block
    the request before it went out — fail loudly rather than let a fake
    response quietly mask that."""
    raise AssertionError("HTTP request was attempted despite BITBUCKET_ALLOW_WRITES being off")


@pytest.fixture(autouse=True)
def _writes_unset(monkeypatch):
    monkeypatch.delenv("BITBUCKET_ALLOW_WRITES", raising=False)
    monkeypatch.setattr(bb.httpx, "post", _boom)


def test_writes_allowed_is_false_by_default():
    assert bb.writes_allowed() is False


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "", "truer", "nottrue"])
def test_writes_allowed_is_false_for_anything_but_true(monkeypatch, value):
    monkeypatch.setenv("BITBUCKET_ALLOW_WRITES", value)
    assert bb.writes_allowed() is False


@pytest.mark.parametrize("value", ["true", "True", "TRUE", " true", "true "])
def test_writes_allowed_accepts_true_case_and_whitespace_insensitively(monkeypatch, value):
    monkeypatch.setenv("BITBUCKET_ALLOW_WRITES", value)
    assert bb.writes_allowed() is True


def test_post_pr_comment_blocked_by_default():
    with pytest.raises(bb.BitbucketWritesDisabledError, match="BITBUCKET_ALLOW_WRITES"):
        bb.post_pr_comment(_config(), 42, "some review comment")


def test_create_bitbucket_issue_blocked_by_default():
    with pytest.raises(bb.BitbucketWritesDisabledError, match="BITBUCKET_ALLOW_WRITES"):
        bb.create_bitbucket_issue(_config(), title="New issue")


def test_push_backlog_to_bitbucket_blocked_by_default():
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="E1", title="Accounts", description="d", feature_area="Auth", priority="high")],
        stories=[], tasks=[], gaps=[],
    )
    with pytest.raises(bb.BitbucketWritesDisabledError, match="BITBUCKET_ALLOW_WRITES"):
        bb.push_backlog_to_bitbucket(output, _config())


def test_writes_work_once_explicitly_enabled(monkeypatch):
    """Confirms the switch actually flips both ways — not just permanently
    blocked regardless of the env var, which would be its own bug."""
    monkeypatch.setenv("BITBUCKET_ALLOW_WRITES", "true")

    class FakeResponse:
        is_error = False
        text = "{}"

        def json(self):
            return {"id": 1}

    monkeypatch.setattr(bb.httpx, "post", lambda *a, **kw: FakeResponse())
    comment = bb.post_pr_comment(_config(), 42, "some review comment")
    assert comment == {"id": 1}
