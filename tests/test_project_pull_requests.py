"""Tests for the project-scoped Pull Requests endpoints (app/api/projects.py):
listing a project's open PRs merged with 'bitbucket_review' job status, and
triggering a review against one of the project's N repos.

Same stubbing style as tests/test_project_wiki.py: functions imported by
name into app/api/projects.py get patched there, not on bitbucket.client,
so the endpoint's own reference is the one that changes."""
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


def _fake_pr(pr_id, title="Fix the thing"):
    return {
        "id": pr_id,
        "title": title,
        "author": {"display_name": "Ada"},
        "source": {"branch": {"name": "feature/x"}},
        "destination": {"branch": {"name": "main"}},
        "state": "OPEN",
        "created_on": "2026-08-01T00:00:00Z",
        "updated_on": "2026-08-02T00:00:00Z",
        "links": {"html": {"href": "https://bitbucket.org/acme/fits-service/pull-requests/1"}},
    }


def test_list_pull_requests_without_bitbucket_configured(monkeypatch):
    """No BITBUCKET_ACCESS_TOKEN — the repo entry degrades gracefully with an
    error rather than failing the whole request."""
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    _add_repo(project["id"])

    response = client.get(f"/projects/{project['id']}/pull-requests")
    assert response.status_code == 200
    body = response.json()
    assert len(body["repos"]) == 1
    assert body["repos"][0]["pull_requests"] == []
    assert "not configured" in body["repos"][0]["error"]


def test_list_pull_requests_merges_review_status(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "list_pull_requests", lambda config, states=None: [_fake_pr(1)])
    project = _create_project()
    repo = _add_repo(project["id"])

    # No review job yet — PR should surface as not_reviewed.
    body = client.get(f"/projects/{project['id']}/pull-requests").json()
    pr = body["repos"][0]["pull_requests"][0]
    assert pr["id"] == 1
    assert pr["title"] == "Fix the thing"
    assert pr["review"]["status"] == "not_reviewed"
    assert pr["review"]["findings_count"] == 0

    # Insert a completed review job for this exact repo/PR directly via the
    # DB layer, mirroring what _bitbucket_review_job_runner would persist.
    import json
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('job-1', 'bitbucket_review', 'succeeded', ?, ?, '2026-08-01', '2026-08-01')",
        (
            json.dumps({"repo_full_name": "acme/fits-service", "pr_id": 1}),
            json.dumps({
                "pr_id": 1, "repo_full_name": "acme/fits-service",
                "summary": "Added input validation and removed an unused import.",
                "findings": [
                    {"file": "a.py", "line": 3, "severity": "blocking", "comment": "SQL injection"},
                    {"file": "b.py", "line": 9, "severity": "minor", "comment": "Unused import"},
                ],
                "files_reviewed": ["a.py", "b.py", "c.py"],
                "token_usage": {"ai_calls": 1, "prompt_tokens": 4200, "completion_tokens": 180, "total_tokens": 4380, "cost_usd": 0.00015},
            }),
        ),
    )
    conn.commit()
    conn.close()

    body = client.get(f"/projects/{project['id']}/pull-requests").json()
    pr = body["repos"][0]["pull_requests"][0]
    assert pr["review"]["status"] == "succeeded"
    assert pr["review"]["job_id"] == "job-1"
    assert pr["review"]["reviewed_at"] == "2026-08-01"
    assert pr["review"]["findings_count"] == 2
    assert pr["review"]["severity_counts"] == {"blocking": 1, "important": 0, "minor": 1}
    # Full findings, not just the count/severity tally — the frontend shows
    # these so "Reviewed" isn't an opaque badge with nothing behind it.
    assert pr["review"]["findings"] == [
        {"file": "a.py", "line": 3, "severity": "blocking", "comment": "SQL injection"},
        {"file": "b.py", "line": 9, "severity": "minor", "comment": "Unused import"},
    ]
    assert pr["review"]["files_reviewed"] == ["a.py", "b.py", "c.py"]
    assert pr["review"]["summary"] == "Added input validation and removed an unused import."
    assert pr["review"]["token_usage"] == {"ai_calls": 1, "prompt_tokens": 4200, "completion_tokens": 180, "total_tokens": 4380, "cost_usd": 0.00015}


def test_list_pull_requests_404_for_missing_project():
    assert client.get("/projects/999999/pull-requests").status_code == 404


def test_publish_review_requires_confirmation_and_is_idempotent(monkeypatch):
    import json

    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    project = _create_project()
    repo = _add_repo(project["id"])
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('publish-job', 'bitbucket_review', 'succeeded', ?, ?, '2026-08-01', '2026-08-01')",
        (json.dumps({"repo_full_name": "acme/fits-service", "pr_id": 7}), json.dumps({
            "summary": "Validated endpoint handling.",
            "findings": [{"file": "api.js", "line": 4, "severity": "important", "verification": "confirmed", "comment": "Wrong route."}],
        })),
    )
    conn.commit()
    conn.close()

    url = f"/projects/{project['id']}/repos/{repo['id']}/pull-requests/7/review/publish"
    assert client.post(url, json={"confirm": False}).status_code == 400

    posted = []
    monkeypatch.setattr(projects_api, "post_pr_comment", lambda config, pr_id, body: posted.append(body) or {"id": 99})
    first = client.post(url, json={"confirm": True})
    second = client.post(url, json={"confirm": True})

    assert first.status_code == 200 and first.json()["already_published"] is False
    assert second.status_code == 200 and second.json()["already_published"] is True
    assert len(posted) == 1
    assert "Wrong route" in posted[0]


def test_list_pull_requests_fetches_n_repos_concurrently_and_preserves_order(monkeypatch):
    """Repos are now fetched on a thread pool (app/api/projects.py) rather
    than one after another — the response must still list them in the same
    order as project['repos'], and one repo's failure must not affect
    another's, regardless of which thread happens to finish first."""
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")

    def fake_list_pull_requests(config, states=None):
        if config.repo_slug == "flaky-repo":
            raise RuntimeError("Bitbucket PR listing failed (503): timeout")
        return [_fake_pr(1, title=f"PR on {config.repo_slug}")]

    monkeypatch.setattr(projects_api, "list_pull_requests", fake_list_pull_requests)
    project = _create_project()
    repo_a = _add_repo(project["id"], workspace="acme", repo_slug="repo-a")
    repo_b = _add_repo(project["id"], workspace="acme", repo_slug="flaky-repo")
    repo_c = _add_repo(project["id"], workspace="acme", repo_slug="repo-c")

    body = client.get(f"/projects/{project['id']}/pull-requests").json()
    repos = body["repos"]
    assert [r["repo_id"] for r in repos] == [repo_a["id"], repo_b["id"], repo_c["id"]]
    assert repos[0]["error"] is None and repos[0]["pull_requests"][0]["title"] == "PR on repo-a"
    assert repos[1]["error"] is not None and repos[1]["pull_requests"] == []
    assert repos[2]["error"] is None and repos[2]["pull_requests"][0]["title"] == "PR on repo-c"


def test_list_pull_requests_surfaces_repo_fetch_error(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")

    def _boom(config, states=None):
        raise RuntimeError("Bitbucket PR listing failed (403): forbidden")

    monkeypatch.setattr(projects_api, "list_pull_requests", _boom)
    project = _create_project()
    _add_repo(project["id"])

    response = client.get(f"/projects/{project['id']}/pull-requests")
    assert response.status_code == 200
    assert "forbidden" in response.json()["repos"][0]["error"]


def test_trigger_review_schedules_bitbucket_review_job(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    # Stub out the real runner so the background job doesn't hit the network
    # during the test — same intent as test_project_wiki.py's provider stub,
    # just one layer further down since this endpoint only schedules a job.
    monkeypatch.setitem(jobs._runners, "bitbucket_review", lambda payload: iter(()))
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/pull-requests/7/review")
    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "bitbucket_review"


def test_trigger_review_404_for_repo_not_on_project(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    project_a = _create_project("A")
    project_b = _create_project("B")
    repo = _add_repo(project_b["id"])

    response = client.post(f"/projects/{project_a['id']}/repos/{repo['id']}/pull-requests/7/review")
    assert response.status_code == 404


def test_trigger_review_400_without_bitbucket_configured(monkeypatch):
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/pull-requests/7/review")
    assert response.status_code == 400
