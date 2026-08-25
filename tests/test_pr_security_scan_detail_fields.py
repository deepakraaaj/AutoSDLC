"""_pr_security_scan_result (app/api/projects.py) assembles the GET
.../security-scan/pr/{jobId} response from a job row's persisted result —
covers specifically that changed_symbols_detail/affected_files_detail (the
list backing the "Changed symbols"/"Affected files" stat counts) survive
that assembly, since test_pr_security_scan_orchestration.py only exercises
the SSE stream (_stream_pr_security_scan) directly, not this read-back
path."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.api.projects as projects_api  # noqa: E402
import app.services.database as database  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def test_pr_security_scan_result_carries_the_detail_lists_through():
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    scan = database.create_security_scan(
        scan_type="PULL_REQUEST", project_id=project["id"], repo_id=repo["id"], pull_request_id="42",
        base_commit_sha="base", head_commit_sha="head",
    )
    database.update_security_scan(scan["id"], status="succeeded", severity_counts={"critical": 0, "high": 0, "medium": 0, "low": 0})

    job = {
        "id": "job-1", "kind": "pr_security_scan", "status": "succeeded", "error": None, "updated_at": "2026-08-01",
        "result": {
            "scan_id": scan["id"],
            "changed_symbols": 1, "affected_files": 2,
            "changed_symbols_detail": [{"file": "controller.py", "symbol": "UserController.get_user", "change_status": "MODIFIED", "seed_type": "SYMBOL"}],
            "affected_files_detail": ["controller.py", "service.py"],
        },
    }

    response = projects_api._pr_security_scan_result(job)
    assert response["changed_symbols_detail"] == [{"file": "controller.py", "symbol": "UserController.get_user", "change_status": "MODIFIED", "seed_type": "SYMBOL"}]
    assert response["affected_files_detail"] == ["controller.py", "service.py"]


def test_pr_security_scan_result_defaults_detail_lists_for_older_scans():
    """A scan persisted before this field existed has no
    changed_symbols_detail/affected_files_detail in its job result — the
    response should default to an empty list, not KeyError or None (the
    frontend's "no detail available" fallback expects an array)."""
    project = database.create_project("P", "d", "PRJ")
    repo = database.add_project_repo(project["id"], "ws", "slug", label="r")
    scan = database.create_security_scan(
        scan_type="PULL_REQUEST", project_id=project["id"], repo_id=repo["id"], pull_request_id="42",
        base_commit_sha="base", head_commit_sha="head",
    )
    database.update_security_scan(scan["id"], status="succeeded", severity_counts={"critical": 0, "high": 0, "medium": 0, "low": 0})

    job = {
        "id": "job-1", "kind": "pr_security_scan", "status": "succeeded", "error": None, "updated_at": "2026-08-01",
        "result": {"scan_id": scan["id"], "changed_symbols": 1, "affected_files": 2},
    }

    response = projects_api._pr_security_scan_result(job)
    assert response["changed_symbols_detail"] == []
    assert response["affected_files_detail"] == []
