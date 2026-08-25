"""End-to-end integration test for main.py's _stream_pr_security_scan —
same direct-call + monkeypatch style as tests/test_bitbucket_review_orchestration.py,
exercising the real repo_intelligence/impact_graph/related_code/correlation/
baseline pipeline against a small on-disk fixture repo, with only the
Bitbucket network calls and the LLM provider mocked."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.services.security.pr_diff import PullRequestDiff, PullRequestInfo, parse_unified_diff  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


@pytest.fixture(autouse=True)
def _bitbucket_env(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")


class StubProvider:
    def __init__(self, raw_response):
        self._raw_response = raw_response
        self.calls = []

    def generate(self, system_prompt, user_message):
        self.calls.append((system_prompt, user_message))
        return self._raw_response


def _write_fixture_repo(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "controller.py").write_text(
        "from service import UserService\n\nclass UserController:\n"
        "    def __init__(self):\n        self.service = UserService()\n\n"
        "    def get_user(self, user_id):\n        return self.service.get_user(user_id)\n",
    )
    (destination / "service.py").write_text(
        "from repository import UserRepository\n\nclass UserService:\n"
        "    def __init__(self):\n        self.repository = UserRepository()\n\n"
        "    def get_user(self, user_id):\n        return self.repository.find_by_id(user_id)\n",
    )
    (destination / "repository.py").write_text(
        "class UserRepository:\n    def find_by_id(self, user_id):\n"
        '        conn.execute("SELECT * FROM users WHERE id = " + str(user_id))\n',
    )


_ADD_GET_USER_DIFF = (
    "diff --git a/controller.py b/controller.py\nindex 1..2 100644\n--- a/controller.py\n+++ b/controller.py\n"
    "@@ -3,3 +3,6 @@ class UserController:\n"
    "     def __init__(self):\n"
    "         self.service = UserService()\n \n"
    "+    def get_user(self, user_id):\n"
    "+        return self.service.get_user(user_id)\n+\n"
)

_LLM_FINDING = {
    "title": "Existing vulnerable retrieval newly exposed",
    "severity": "high", "confidence": "high",
    "changed_file": "controller.py", "changed_symbol": "UserController.get_user",
    "related_files": ["service.py", "repository.py"],
    "related_symbols": ["UserService.get_user", "UserRepository.find_by_id"],
    "execution_or_security_path": "UserController.get_user -> UserService.get_user -> UserRepository.find_by_id",
    "reason_for_pr_relevance": "The PR adds a new route reaching an existing unvalidated retrieval path.",
    "security_impact": "Any authenticated user can retrieve another user's record by id.",
    "recommendation": "Enforce ownership validation before retrieval.",
}


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def _fake_diff():
    files, truncated = parse_unified_diff(_ADD_GET_USER_DIFF)
    info = PullRequestInfo("42", "Add get_user endpoint", "adds retrieval", "feature/get-user", "main", "base-sha-123", "head-sha-456")
    return PullRequestDiff(info=info, files=files, truncated=truncated)


def _patch_pipeline(monkeypatch, *, provider, deterministic_findings=None):
    monkeypatch.setattr(main, "fetch_pull_request_diff", lambda config, pr_id: _fake_diff())

    def fake_snapshot(config, destination, branch=None, commit_sha=None, timeout_seconds=None, **kwargs):
        _write_fixture_repo(destination)
        return commit_sha or "head-sha-456"
    monkeypatch.setattr(main, "create_repository_snapshot", fake_snapshot)

    def fake_deterministic_scan(config, branch=None, commit_sha=None, *, source=None, commit=None):
        # PR scans call this with source=/commit= (reusing the snapshot
        # already fetched for the repository index) rather than branch=/
        # commit_sha= (which would fetch a fresh one) — assert that's what
        # actually happens, not just accept either shape silently.
        assert source is not None and commit is not None, "PR scan must reuse the already-fetched snapshot, not fetch a second one"
        findings = deterministic_findings if deterministic_findings is not None else [
            {"tool": "semgrep", "rule_id": "sqli", "file": "repository.py", "line": 3, "severity": "high",
             "comment": "SQL injection", "category": "injection", "fingerprint": "raw-fp-1"},
        ]
        yield "scanner_status", {"stage": "snapshot", "status": "completed", "commit": commit, "files": 3, "reused": True}
        yield "deterministic_complete", {"commit": commit, "snapshot_files": 3, "tools": [], "findings": findings, "partial": False}
    monkeypatch.setattr(main, "run_deterministic_scan", fake_deterministic_scan)

    monkeypatch.setattr(main, "get_provider", lambda: provider)


def test_full_pipeline_produces_existing_newly_exposed_finding(monkeypatch):
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    provider = StubProvider(json.dumps({
        "summary": "This PR adds a get_user endpoint to UserController that reaches an existing unvalidated retrieval path.",
        "findings": [_LLM_FINDING],
    }))
    _patch_pipeline(monkeypatch, provider=provider)

    events = _events(main._stream_pr_security_scan(project["id"], repo["id"], "ws", "slug", "42"))
    done = next(e for e in events if e["type"] == "done")

    assert done["changed_files"] == 1
    assert done["changed_symbols"] >= 1
    assert done["affected_files"] >= 2  # controller.py + service.py + repository.py reachable
    # changed_symbols/affected_files are just counts — regression for these
    # being bare numbers with no way to see what they actually counted.
    assert len(done["changed_symbols_detail"]) == done["changed_symbols"]
    assert any("get_user" == (seed["symbol"] or "") or "get_user" in (seed["symbol"] or "") for seed in done["changed_symbols_detail"])
    assert all({"file", "symbol", "change_status", "seed_type"} <= seed.keys() for seed in done["changed_symbols_detail"])
    assert len(done["affected_files_detail"]) == done["affected_files"]
    assert "controller.py" in done["affected_files_detail"]
    assert done["summary"] == "This PR adds a get_user endpoint to UserController that reaches an existing unvalidated retrieval path."
    assert done["summary_source"] == "llm"
    assert "EXISTING_NEWLY_EXPOSED" in done["findings_by_relation"]
    newly_exposed = [f for f in done["findings"] if f["relation_to_pr"] == "EXISTING_NEWLY_EXPOSED"]
    assert len(newly_exposed) >= 1
    assert any("UserController" in " -> ".join(f["affected_path"]) or "get_user" in " -> ".join(f["affected_path"]) for f in newly_exposed)

    # Persisted, retrievable via the DB layer directly.
    scan = database.get_security_scan(done["scan_id"])
    assert scan["status"] == "succeeded"
    assert scan["scan_type"] == "PULL_REQUEST"
    assert scan["pull_request_id"] == "42"
    assert scan["metadata"]["summary"] == done["summary"]
    findings = database.list_security_findings(done["scan_id"])
    assert len(findings) == len(done["findings"])


def test_llm_failure_still_persists_deterministic_findings(monkeypatch):
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    provider = StubProvider(raw_response=None)

    def broken_generate(system_prompt, user_message):
        raise RuntimeError("provider unreachable")
    provider.generate = broken_generate
    _patch_pipeline(monkeypatch, provider=provider)

    events = _events(main._stream_pr_security_scan(project["id"], repo["id"], "ws", "slug", "42"))
    done = next(e for e in events if e["type"] == "done")

    assert done["llm_review_status"] == "failed"
    # A manager still gets a plain-English summary even when the AI review
    # itself failed — built deterministically from the diff/seeds instead.
    assert done["summary_source"] == "fallback"
    assert done["summary"]
    assert "controller.py" in done["summary"] or "get_user" in done["summary"]
    scan = database.get_security_scan(done["scan_id"])
    assert scan["status"] == "succeeded"  # deterministic-only completion still succeeds
    assert scan["llm_review_status"] == "failed"
    assert len(done["findings"]) >= 1  # deterministic finding still made it through


def test_pr_fetch_failure_yields_error_and_does_not_crash(monkeypatch):
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")

    def fake_fetch(config, pr_id):
        raise RuntimeError("Bitbucket 404")
    monkeypatch.setattr(main, "fetch_pull_request_diff", fake_fetch)

    events = _events(main._stream_pr_security_scan(project["id"], repo["id"], "ws", "slug", "999"))
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)


def test_unrelated_findings_are_not_prominent_in_the_result(monkeypatch):
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    provider = StubProvider(json.dumps([]))
    unrelated = [{"tool": "semgrep", "rule_id": "x", "file": "totally_unrelated.py", "line": 1, "severity": "low", "comment": "n/a"}]
    _patch_pipeline(monkeypatch, provider=provider, deterministic_findings=unrelated)

    events = _events(main._stream_pr_security_scan(project["id"], repo["id"], "ws", "slug", "42"))
    done = next(e for e in events if e["type"] == "done")
    assert done["findings_by_relation"].get("UNRELATED", 0) == 0
    assert done["findings"] == []
