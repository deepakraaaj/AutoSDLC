"""Tests for the 'brief from repository' endpoint (app/api/projects.py) —
automates prompts/EXTRACT_FROM_REPO.md's manual copy/paste workflow by
generating a backlog-ready brief straight from a project's linked repos.

Uses the same stub-provider style as tests/test_project_wiki.py — this call
site (app/services/repo_brief.py) goes through AutoSDLCChatModel/LangChain
like wiki generation, not PhaseGenerator's plain generate()."""
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
from app.services.providers import AllProvidersExhaustedError  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


class StubBriefProvider:
    def __init__(self, text="# Project: Smart Turf\n\n## Summary\nA turf booking platform.", raise_error=None):
        self.calls = []
        self._text = text
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return self._text


def _stub(monkeypatch, provider):
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)


def _create_project(name="Smart Turf", description="Turf booking"):
    return client.post("/projects", json={"name": name, "description": description}).json()


def test_brief_from_repo_requires_a_linked_repo(monkeypatch):
    _stub(monkeypatch, StubBriefProvider())
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/brief/from-repo", json={})
    assert response.status_code == 400


def test_brief_from_repo_404_for_missing_project(monkeypatch):
    _stub(monkeypatch, StubBriefProvider())
    response = client.post("/projects/999999/brief/from-repo", json={})
    assert response.status_code == 404


def test_brief_from_repo_grounds_on_linked_repositories(monkeypatch):
    """Reuses _collect_repo_wiki_material the same way wiki generation does —
    stub it directly rather than Bitbucket itself, matching
    test_project_wiki.py's test_generate_project_wiki_combines_all_linked_repositories_without_brief."""
    provider = StubBriefProvider()
    _stub(monkeypatch, provider)
    monkeypatch.setattr(
        projects_api,
        "_collect_repo_wiki_material",
        lambda repo, project_id=None: {
            "label": repo["label"] or repo["repo_slug"],
            "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
            "context_block": f"architecture evidence from {repo['repo_slug']}",
            "readme_text": None,
        },
    )
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "label": "backend", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/brief/from-repo", json={"existing_brief": "Focus on payments first."})
    assert response.status_code == 200
    body = response.json()
    assert body["brief_text"].startswith("# Project:")
    assert body["repos_used"] == ["backend"]

    _, user_message = provider.calls[0]
    assert "architecture evidence from fits-service" in user_message
    assert "Focus on payments first." in user_message


def test_brief_from_repo_maps_provider_exhaustion_to_503(monkeypatch):
    provider = StubBriefProvider(raise_error=AllProvidersExhaustedError("no provider available"))
    _stub(monkeypatch, provider)
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/brief/from-repo", json={})
    assert response.status_code == 503


def test_brief_from_repo_502_on_empty_model_response(monkeypatch):
    provider = StubBriefProvider(text="   ")
    _stub(monkeypatch, provider)
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/brief/from-repo", json={})
    assert response.status_code == 502
