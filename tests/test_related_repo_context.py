"""Tests for app/services/related_repo_context.py: the diff-aware related-repo
grep used by a PR code review's "Related repository" section.

Covers what matters for this module's contract:
1. It finds real content matches for diff-derived terms (getDayEnd,
   maxDateTime — the running example from the AutoSDLC PR #62 case this
   module was built for) via a local grep, not a per-file API fetch.
2. It degrades gracefully (empty string) on no terms, no config, or a
   failed sync — this must never raise into the PR review it feeds.
3. The clone is persistent: a repo already cloned is fetched, not
   re-cloned, on later calls; evict_repo_cache removes it on unlink.
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.related_repo_context as related_repo_context  # noqa: E402
from app.services.related_repo_context import _grep, _repo_dir, build_related_repo_context_block, evict_repo_cache  # noqa: E402
from bitbucket.client import BitbucketConfig  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    # Every test gets its own cache root so persistent-clone tests never
    # touch (or get confused by) a real clone from another test run.
    monkeypatch.setattr(related_repo_context, "CACHE_DIR", tmp_path / "related_repo_cache")


def _config():
    config = BitbucketConfig.from_env()
    config.workspace = "ws"
    config.repo_slug = "repo"
    return config


def test_grep_finds_term_matches_with_context_lines(tmp_path):
    backend_file = tmp_path / "src" / "utils" / "dateHelpers.ts"
    backend_file.parent.mkdir(parents=True)
    backend_file.write_text(
        "\n".join(
            [
                "export function getDayEnd(m) {",
                "  return m.endOf('day');",
                "}",
                "",
                "export function maxDateTime() {",
                "  return getDayEnd(moment()).valueOf();",
                "}",
            ]
        )
    )

    matches = _grep(tmp_path, ["getDayEnd", "maxDateTime"], max_files=6)

    assert len(matches) == 1
    path, snippet = matches[0]
    assert path == "src/utils/dateHelpers.ts"
    assert "getDayEnd" in snippet
    # Line numbers are 1-indexed and present so the LLM can cite a real line.
    assert "1: export function getDayEnd" in snippet


def test_grep_skips_ignored_directories(tmp_path):
    ignored = tmp_path / "node_modules" / "pkg" / "index.js"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("getDayEnd()")

    matches = _grep(tmp_path, ["getDayEnd"], max_files=6)

    assert matches == []


def test_grep_returns_empty_for_no_terms(tmp_path):
    (tmp_path / "file.py").write_text("def getDayEnd(): pass")
    assert _grep(tmp_path, [], max_files=6) == []


def test_build_related_repo_context_block_empty_without_terms():
    assert build_related_repo_context_block(_config(), [], label="backend") == ""


def test_build_related_repo_context_block_empty_when_not_configured():
    config = BitbucketConfig.from_env()
    config.workspace = ""
    config.repo_slug = ""
    assert build_related_repo_context_block(config, ["getDayEnd"], label="backend") == ""


def test_build_related_repo_context_block_degrades_on_sync_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("clone failed")

    monkeypatch.setattr(related_repo_context, "_sync_repo", _boom)

    result = build_related_repo_context_block(_config(), ["getDayEnd"], label="backend")

    assert result == ""


def test_sync_repo_clones_once_then_fetches_on_later_calls(monkeypatch):
    """The persistence contract: a repo already on disk must be fetched,
    never re-cloned — that's the entire reason this module keeps a
    permanent working clone instead of a TTL cache or a fresh clone per
    review."""
    calls: list[list[str]] = []

    def _fake_run(command, *, cwd, env):
        calls.append(command)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if command[:2] == ["git", "clone"]:
            # Simulate a real clone landing on disk so the second call sees
            # an existing .git directory and takes the fetch path.
            Path(cwd, command[-1]).mkdir(parents=True, exist_ok=True)
            (Path(cwd, command[-1]) / ".git").mkdir()
        return _Result()

    monkeypatch.setattr(related_repo_context, "_run", _fake_run)
    monkeypatch.setattr(related_repo_context, "_clone_url", lambda config: "https://example.invalid/repo.git")
    monkeypatch.setattr(related_repo_context, "_git_environment", lambda config, home: {})

    config = _config()
    related_repo_context._sync_repo(config, None)
    related_repo_context._sync_repo(config, None)

    clone_calls = [c for c in calls if c[:2] == ["git", "clone"]]
    fetch_calls = [c for c in calls if c[:2] == ["git", "fetch"]]
    assert len(clone_calls) == 1
    assert len(fetch_calls) == 1


def test_evict_repo_cache_removes_the_clone(tmp_path):
    config = _config()
    repo_dir = _repo_dir(config.workspace, config.repo_slug)
    repo_dir.mkdir(parents=True)
    (repo_dir / "marker.txt").write_text("present")

    evict_repo_cache(config.workspace, config.repo_slug)

    assert not repo_dir.exists()


def test_evict_repo_cache_is_a_noop_when_nothing_cached():
    # Must not raise just because the repo was never cloned in the first
    # place (e.g. a repo linked and then unlinked before any review ran).
    evict_repo_cache("never", "cloned")
