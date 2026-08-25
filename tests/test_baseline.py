"""Same DB-isolation convention as tests/test_project_security.py:
monkeypatch database.DB_PATH to a per-test sqlite file."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.database as database  # noqa: E402
from app.services.security import baseline  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def test_exact_base_commit_baseline_wins():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")

    exact = database.create_security_scan(scan_type="FULL_REPOSITORY", project_id=project["id"], repo_id=repo["id"], branch="main", commit_sha="base-sha")
    database.update_security_scan(exact["id"], status="succeeded")
    stale = database.create_security_scan(scan_type="FULL_REPOSITORY", project_id=project["id"], repo_id=repo["id"], branch="main", commit_sha="older-sha")
    database.update_security_scan(stale["id"], status="succeeded")

    selection = baseline.select_baseline(repo["id"], base_commit_sha="base-sha", destination_branch="main")
    assert selection.scan_id == exact["id"]
    assert selection.source == baseline.SOURCE_EXACT_BASE_COMMIT
    assert selection.confidence == baseline.CONFIDENCE_HIGH


def test_falls_back_to_destination_branch_latest():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    branch_scan = database.create_security_scan(scan_type="FULL_REPOSITORY", project_id=project["id"], repo_id=repo["id"], branch="main", commit_sha="some-other-sha")
    database.update_security_scan(branch_scan["id"], status="succeeded")

    selection = baseline.select_baseline(repo["id"], base_commit_sha="not-scanned-sha", destination_branch="main")
    assert selection.scan_id == branch_scan["id"]
    assert selection.source == baseline.SOURCE_DESTINATION_BRANCH_LATEST
    assert selection.confidence == baseline.CONFIDENCE_MEDIUM


def test_no_reliable_baseline_returns_none_source():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")

    selection = baseline.select_baseline(repo["id"], base_commit_sha="nope", destination_branch="unscanned-branch")
    assert selection.scan_id is None
    assert selection.source == baseline.SOURCE_NONE
    assert selection.confidence == baseline.CONFIDENCE_NONE


def test_never_uses_a_different_branchs_scan_as_fallback():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    other_branch_scan = database.create_security_scan(scan_type="FULL_REPOSITORY", project_id=project["id"], repo_id=repo["id"], branch="unrelated-feature", commit_sha="x")
    database.update_security_scan(other_branch_scan["id"], status="succeeded")

    selection = baseline.select_baseline(repo["id"], base_commit_sha="nope", destination_branch="main")
    assert selection.scan_id is None
    assert selection.source == baseline.SOURCE_NONE


def test_classify_against_baseline_new_existing_unknown():
    assert baseline.classify_against_baseline("fp1", None) == baseline.STATE_UNKNOWN
    assert baseline.classify_against_baseline("fp1", {"fp1", "fp2"}) == baseline.STATE_EXISTING
    assert baseline.classify_against_baseline("fp3", {"fp1", "fp2"}) == baseline.STATE_NEW


def test_baseline_fingerprints_loaded_from_scan_findings():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    scan = database.create_security_scan(scan_type="FULL_REPOSITORY", project_id=project["id"], repo_id=repo["id"], branch="main", commit_sha="base-sha")
    database.update_security_scan(scan["id"], status="succeeded")
    database.save_security_findings(scan["id"], [{"fingerprint": "fp-a"}, {"fingerprint": "fp-b"}])

    selection = baseline.select_baseline(repo["id"], base_commit_sha="base-sha", destination_branch="main")
    fps = baseline.baseline_fingerprints(selection)
    assert fps == {"fp-a", "fp-b"}


def test_resolved_fingerprints_are_baseline_minus_current():
    assert baseline.resolved_fingerprints({"a", "b", "c"}, {"a"}) == {"b", "c"}
    assert baseline.resolved_fingerprints(None, {"a"}) == set()
