"""Tests for the Project entity (app/api/projects.py, app/services/database.py):
CRUD, N repos per project, the optional "init the repo" connectivity check
on add, and default-repo resolution."""
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

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def test_create_and_get_project():
    response = client.post("/projects", json={"name": "REMP", "description": "Facility management"})
    assert response.status_code == 200
    project = response.json()
    assert project["name"] == "REMP"

    fetched = client.get(f"/projects/{project['id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["repos"] == []
    assert body["generations"] == []


def test_get_project_404_for_missing():
    assert client.get("/projects/999999").status_code == 404


def test_create_project_normalizes_ticket_prefix():
    project = client.post("/projects", json={"name": "REMP", "ticket_prefix": "remp"}).json()
    assert project["ticket_prefix"] == "REMP"


def test_update_project_partial_update():
    project = client.post("/projects", json={"name": "REMP", "description": "old"}).json()
    response = client.put(f"/projects/{project['id']}", json={"description": "new description"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "REMP"  # untouched
    assert body["description"] == "new description"


def test_update_project_404_for_missing():
    assert client.put("/projects/999999", json={"name": "x"}).status_code == 404


def test_delete_project_cascades_repos_and_settings_but_keeps_generations():
    project = client.post("/projects", json={"name": "REMP"}).json()
    database.add_project_repo(project["id"], "acme", "frontend")
    database.upsert_project_settings(project["id"], custom_instructions="keep me safe")
    gen_id = database.save_generation_with_backlog("brief text", _empty_output(), project_id=project["id"])

    response = client.delete(f"/projects/{project['id']}")
    assert response.status_code == 200
    assert client.get(f"/projects/{project['id']}").status_code == 404

    # The generation survives, just unlinked from the deleted project.
    assert database.get_generation_project_id(gen_id) is None


def test_delete_project_404_for_missing():
    assert client.delete("/projects/999999").status_code == 404


def test_list_projects_reports_repo_and_generation_counts(monkeypatch):
    project = client.post("/projects", json={"name": "REMP"}).json()
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"full_name": "acme/frontend"})
    client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "frontend"})

    listing = client.get("/projects").json()["projects"]
    row = next(p for p in listing if p["id"] == project["id"])
    assert row["repo_count"] == 1
    assert row["generation_count"] == 0


def test_add_repo_supports_n_repos_per_project(monkeypatch):
    project = client.post("/projects", json={"name": "REMP"}).json()
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"full_name": "ok"})

    client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "frontend", "label": "frontend"})
    client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "backend", "label": "backend"})

    detail = client.get(f"/projects/{project['id']}").json()
    assert len(detail["repos"]) == 2
    assert {r["label"] for r in detail["repos"]} == {"frontend", "backend"}


def test_add_repo_verify_success_sets_verified_at(monkeypatch):
    project = client.post("/projects", json={"name": "REMP"}).json()
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"full_name": "acme/frontend"})

    response = client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "frontend"})
    body = response.json()
    assert body["verification"]["ok"] is True
    assert body["verified_at"] is not None


def test_add_repo_verify_failure_still_creates_the_repo(monkeypatch):
    project = client.post("/projects", json={"name": "REMP"}).json()
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")

    def raise_error(config):
        raise RuntimeError("404 not found")

    monkeypatch.setattr(projects_api, "get_repo_metadata", raise_error)
    response = client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "typo-repo"})
    assert response.status_code == 201
    body = response.json()
    assert body["verification"]["ok"] is False
    assert body["verified_at"] is None

    # The repo still exists — a failed verification must not block linking it.
    detail = client.get(f"/projects/{project['id']}").json()
    assert len(detail["repos"]) == 1


def test_add_repo_without_verify_flag_skips_the_check(monkeypatch):
    project = client.post("/projects", json={"name": "REMP"}).json()

    def fail_if_called(config):
        raise AssertionError("should not verify")

    monkeypatch.setattr(projects_api, "get_repo_metadata", fail_if_called)
    response = client.post(f"/projects/{project['id']}/repos", json={"workspace": "acme", "repo_slug": "frontend", "verify": False})
    assert response.status_code == 201
    assert response.json()["verification"]["attempted"] is False


def test_update_repo_edits_fields_and_clears_verification():
    project = client.post("/projects", json={"name": "REMP"}).json()
    repo = database.add_project_repo(project["id"], "acme", "frontend")
    database.mark_repo_verified(repo["id"])

    response = client.put(
        f"/projects/{project['id']}/repos/{repo['id']}",
        json={"workspace": "kritilabs", "repo_slug": "mdm", "label": "backend"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["workspace"] == "kritilabs"
    assert updated["repo_slug"] == "mdm"
    assert updated["label"] == "backend"
    # Changing workspace/repo_slug invalidates the old verification.
    assert updated["verified_at"] is None


def test_delete_repo():
    project = client.post("/projects", json={"name": "REMP"}).json()
    repo = database.add_project_repo(project["id"], "acme", "frontend")
    response = client.delete(f"/projects/{project['id']}/repos/{repo['id']}")
    assert response.status_code == 200
    detail = client.get(f"/projects/{project['id']}").json()
    assert detail["repos"] == []


def test_project_sprint_plan_is_persisted_and_updated():
    project = client.post("/projects", json={"name": "REMP"}).json()
    payload = {
        "name": "Sprint 1", "objective": "Ship matching", "start_date": "2026-08-24",
        "end_date": "2026-09-06", "capacity_hours": 80, "story_ids": ["S-0001", "S-0002"], "status": "draft",
    }
    created = client.post(f"/projects/{project['id']}/sprints", json=payload)
    assert created.status_code == 201
    sprint = created.json()
    assert sprint["story_ids"] == ["S-0001", "S-0002"]

    payload.update({"capacity_hours": 64, "story_ids": ["S-0001"], "status": "approved"})
    updated = client.put(f"/projects/{project['id']}/sprints/{sprint['id']}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["capacity_hours"] == 64
    assert updated.json()["status"] == "approved"
    assert client.get(f"/projects/{project['id']}/sprints").json()["sprints"][0]["story_ids"] == ["S-0001"]

    deleted = client.delete(f"/projects/{project['id']}/sprints/{sprint['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/projects/{project['id']}/sprints").json()["sprints"] == []


def test_project_sprint_rejects_backwards_dates():
    project = client.post("/projects", json={"name": "REMP"}).json()
    response = client.post(f"/projects/{project['id']}/sprints", json={
        "name": "Bad sprint", "start_date": "2026-09-06", "end_date": "2026-08-24",
    })
    assert response.status_code == 400


def test_generate_stream_attaches_generation_to_project():
    project = client.post("/projects", json={"name": "REMP"}).json()
    gen_id = database.save_generation_with_backlog("brief text", _empty_output(), project_id=project["id"])
    assert database.get_generation_project_id(gen_id) == project["id"]

    detail = client.get(f"/projects/{project['id']}").json()
    assert any(g["id"] == gen_id for g in detail["generations"])


def _empty_output():
    from app.schemas.models import GenerationOutput
    return GenerationOutput(needs_clarification=False, clarifying_questions=[], epics=[], stories=[], tasks=[], gaps=[])
