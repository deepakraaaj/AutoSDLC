"""Tests for the project-scoped Security/VAPT endpoints (app/api/projects.py):
reading each repo's latest security_scan job, and triggering a new one.

Same stubbing style as tests/test_project_pull_requests.py."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.api.projects as projects_api  # noqa: E402
import app.services.database as database  # noqa: E402
import app.services.jobs as jobs  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _create_project(name="Smart Turf"):
    return client.post("/projects", json={"name": name}).json()


def _add_repo(project_id, workspace="acme", repo_slug="fits-service"):
    return client.post(f"/projects/{project_id}/repos", json={
        "workspace": workspace, "repo_slug": repo_slug, "verify": False,
    }).json()


def test_get_security_with_no_repos():
    project = _create_project()
    response = client.get(f"/projects/{project['id']}/security")
    assert response.status_code == 200
    assert response.json()["repos"] == []


def test_get_security_defaults_to_not_scanned():
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.get(f"/projects/{project['id']}/security")
    assert response.status_code == 200
    entry = response.json()["repos"][0]
    assert entry["repo_id"] == repo["id"]
    assert entry["scan"]["status"] == "not_scanned"
    assert entry["scan"]["findings"] == []


def test_get_security_reflects_completed_scan():
    project = _create_project()
    repo = _add_repo(project["id"])

    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('job-1', 'security_scan', 'succeeded', ?, ?, '2026-08-01', '2026-08-02')",
        (
            json.dumps({"repo_id": repo["id"], "label": "fits-service", "workspace": "acme", "repo_slug": "fits-service"}),
            json.dumps({"repo_id": repo["id"], "repo_label": "fits-service", "findings": [
                {"file": "a.py", "line": 3, "category": "secrets", "severity": "critical", "comment": "Hardcoded API key"},
                {"file": "b.py", "line": 9, "category": "input-validation", "severity": "low", "comment": "Unvalidated query param"},
            ]}),
        ),
    )
    conn.commit()
    conn.close()

    entry = client.get(f"/projects/{project['id']}/security").json()["repos"][0]
    assert entry["scan"]["status"] == "succeeded"
    assert entry["scan"]["job_id"] == "job-1"
    assert entry["scan"]["scanned_at"] == "2026-08-02"
    assert len(entry["scan"]["findings"]) == 2
    assert entry["scan"]["severity_counts"] == {"critical": 1, "high": 0, "medium": 0, "low": 1}


def test_get_security_404_for_missing_project():
    assert client.get("/projects/999999/security").status_code == 404


def test_trigger_scan_schedules_security_scan_job(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setitem(jobs._runners, "security_scan", lambda payload: iter(()))
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 202
    assert response.json()["kind"] == "security_scan"


def test_trigger_scan_404_for_repo_not_on_project(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    project_a = _create_project("A")
    project_b = _create_project("B")
    repo = _add_repo(project_b["id"])

    response = client.post(f"/projects/{project_a['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 404


def test_trigger_scan_400_without_bitbucket_configured(monkeypatch):
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 400
