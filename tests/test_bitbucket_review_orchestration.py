"""Regression test for main.py's _stream_bitbucket_review: it must scope its
BitbucketConfig from the repo_full_name it's given, not silently fall back
to the single global BITBUCKET_WORKSPACE/BITBUCKET_REPO_SLUG env repo.

Bug this guards: a project with N linked repos triggering a review on any
repo other than the one named by the env vars 404'd, because the config
used to always resolve to the env repo regardless of which repo's PR was
actually being reviewed."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    # _stream_bitbucket_review now writes a token_usage_log row on a
    # successful review (record_token_usage) — isolate so that doesn't land
    # in the real dev database this suite otherwise never touches.
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture(autouse=True)
def _bitbucket_env(monkeypatch):
    # Global env deliberately points at a *different* repo than the one
    # under test below — if the bug regresses, the fetch calls will observe
    # this repo instead of the one repo_full_name names.
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "kritilabs")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "mdm")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")


def test_stream_bitbucket_review_scopes_config_to_repo_full_name(monkeypatch):
    seen_configs = []

    def fake_get_pull_request(config, pr_id):
        seen_configs.append((config.workspace, config.repo_slug))
        return {"id": pr_id}

    def fake_get_pull_request_diff(config, pr_id):
        seen_configs.append((config.workspace, config.repo_slug))
        return "diff --git a/x b/x"

    monkeypatch.setattr(main, "get_pull_request", fake_get_pull_request)
    monkeypatch.setattr(main, "get_pull_request_diff", fake_get_pull_request_diff)
    monkeypatch.setattr(main, "get_provider", lambda: object())
    monkeypatch.setattr(main, "run_code_review", lambda repo, pr_id, diff, provider: iter(()))

    list(main._stream_bitbucket_review("kritilabs/fits-service", 42))

    assert seen_configs == [("kritilabs", "fits-service"), ("kritilabs", "fits-service")]


def test_stream_bitbucket_review_falls_back_to_env_repo_when_full_name_missing_slash(monkeypatch):
    """A malformed/empty repo_full_name shouldn't crash — falls back to
    whatever the env config resolves to, same graceful-degradation contract
    as everywhere else BitbucketConfig is built."""
    seen_configs = []
    monkeypatch.setattr(main, "get_pull_request", lambda config, pr_id: seen_configs.append((config.workspace, config.repo_slug)))
    monkeypatch.setattr(main, "get_pull_request_diff", lambda config, pr_id: "diff")
    monkeypatch.setattr(main, "get_provider", lambda: object())
    monkeypatch.setattr(main, "run_code_review", lambda repo, pr_id, diff, provider: iter(()))

    list(main._stream_bitbucket_review("", 1))

    assert seen_configs == [("kritilabs", "mdm")]


def test_stream_bitbucket_review_posts_findings_against_the_scoped_repo(monkeypatch):
    posted = []
    monkeypatch.setattr(main, "get_pull_request", lambda config, pr_id: {"id": pr_id})
    monkeypatch.setattr(main, "get_pull_request_diff", lambda config, pr_id: "diff")
    monkeypatch.setattr(main, "get_provider", lambda: object())

    def fake_run_code_review(repo_full_name, pr_id, diff, provider):
        yield main._sse("finding", {"finding": {"file": "a.py", "line": 1, "severity": "minor", "comment": "nit"}})
        yield main._sse("done", {"pr_id": pr_id, "repo_full_name": repo_full_name, "findings": [
            {"file": "a.py", "line": 1, "severity": "minor", "comment": "nit"},
        ]})

    def fake_post_pr_comment(config, pr_id, body, inline=None):
        posted.append((config.workspace, config.repo_slug, pr_id))

    monkeypatch.setattr(main, "run_code_review", fake_run_code_review)
    monkeypatch.setattr(main, "post_pr_comment", fake_post_pr_comment)

    events = _events(main._stream_bitbucket_review("kritilabs/fits-ui", 7))

    assert any(e["type"] == "finding" for e in events)
    assert posted == [("kritilabs", "fits-ui", 7)]


class _StubUsageProvider:
    """A minimal stand-in for LiteLLMProvider's usage_summary() contract —
    only what _stream_bitbucket_review actually reads (hasattr check +
    call), not a full AIProvider."""

    def usage_summary(self):
        return {"ai_calls": 1, "prompt_tokens": 5000, "completion_tokens": 300, "total_tokens": 5300, "cost_usd": 0.00021}


def test_stream_bitbucket_review_attaches_real_token_usage_to_done_event(monkeypatch):
    """provider is fresh per review (get_provider() inside
    _stream_bitbucket_review, not shared across calls), so its
    usage_summary() after run_code_review finishes is exactly this one
    review's real token spend — not an estimate."""
    monkeypatch.setattr(main, "get_pull_request", lambda config, pr_id: {"id": pr_id})
    monkeypatch.setattr(main, "get_pull_request_diff", lambda config, pr_id: "diff")
    monkeypatch.setattr(main, "get_provider", lambda: _StubUsageProvider())
    monkeypatch.setattr(main, "post_pr_comment", lambda *a, **kw: None)

    def fake_run_code_review(repo_full_name, pr_id, diff, provider):
        yield main._sse("done", {"pr_id": pr_id, "repo_full_name": repo_full_name, "findings": [], "summary": "x", "files_reviewed": []})

    monkeypatch.setattr(main, "run_code_review", fake_run_code_review)

    events = _events(main._stream_bitbucket_review("kritilabs/fits-ui", 7))
    done = [e for e in events if e["type"] == "done"][0]
    assert done["token_usage"] == {"ai_calls": 1, "prompt_tokens": 5000, "completion_tokens": 300, "total_tokens": 5300, "cost_usd": 0.00021}


def test_stream_bitbucket_review_omits_token_usage_when_provider_cant_report_it(monkeypatch):
    monkeypatch.setattr(main, "get_pull_request", lambda config, pr_id: {"id": pr_id})
    monkeypatch.setattr(main, "get_pull_request_diff", lambda config, pr_id: "diff")
    monkeypatch.setattr(main, "get_provider", lambda: object())  # no usage_summary attribute

    def fake_run_code_review(repo_full_name, pr_id, diff, provider):
        yield main._sse("done", {"pr_id": pr_id, "repo_full_name": repo_full_name, "findings": [], "summary": "x", "files_reviewed": []})

    monkeypatch.setattr(main, "run_code_review", fake_run_code_review)

    events = _events(main._stream_bitbucket_review("kritilabs/fits-ui", 7))
    done = [e for e in events if e["type"] == "done"][0]
    assert "token_usage" not in done


def test_stream_bitbucket_review_persists_token_usage_to_the_log(monkeypatch):
    monkeypatch.setattr(main, "get_pull_request", lambda config, pr_id: {"id": pr_id})
    monkeypatch.setattr(main, "get_pull_request_diff", lambda config, pr_id: "diff")
    monkeypatch.setattr(main, "get_provider", lambda: _StubUsageProvider())
    monkeypatch.setattr(main, "post_pr_comment", lambda *a, **kw: None)

    def fake_run_code_review(repo_full_name, pr_id, diff, provider):
        yield main._sse("done", {"pr_id": pr_id, "repo_full_name": repo_full_name, "findings": [], "summary": "x", "files_reviewed": []})

    monkeypatch.setattr(main, "run_code_review", fake_run_code_review)

    list(main._stream_bitbucket_review("kritilabs/fits-ui", 7))

    entries = database.list_token_usage()
    assert len(entries) == 1
    assert entries[0]["kind"] == "bitbucket_review"
    assert entries[0]["ref_id"] == "kritilabs/fits-ui#7"
    assert entries[0]["total_tokens"] == 5300
