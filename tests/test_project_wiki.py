"""Tests for the project/repo wiki endpoints (app/api/projects.py) and their
DB layer (project_wiki_pages / upsert_wiki_page / get_wiki_page /
list_wiki_pages in app/services/database.py).

Uses a minimal stub provider — same style as tests/test_code_review_job.py's
StubReviewProvider — since wiki generation is the other call site that goes
through AutoSDLCChatModel/LangChain rather than PhaseGenerator's plain
generate(), and the assertions here are about the endpoint/DB contract, not
prompt formatting."""
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
from app.services.providers import AllProvidersExhaustedError  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


class StubWikiProvider:
    """generate() returns a fixed wiki JSON object regardless of prompt
    content, so tests assert on the endpoint/DB contract rather than on
    exactly what got sent to the model."""

    def __init__(self, page=None, raise_error=None):
        self.calls = []
        self._page = page if page is not None else {
            "title": "Smart Turf",
            "summary": "A booking platform for turf facilities.",
            "sections": [{"heading": "What it does", "body": "Lets customers book turf slots online."}],
        }
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return json.dumps(self._page)


def _stub(monkeypatch, provider):
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)


def _create_project(name="Smart Turf", description="Turf booking"):
    return client.post("/projects", json={"name": name, "description": description}).json()


# ── Project wiki ─────────────────────────────────────────────────────────

def test_generate_project_wiki_with_no_generations(monkeypatch):
    """No backlog yet — the endpoint must still succeed, grounding the prompt
    in project name/description alone rather than erroring."""
    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    page = response.json()
    assert page["title"] == "Smart Turf"
    assert page["repo_id"] is None
    assert page["sections"][0]["heading"] == "What it does"

    # A manually supplied brief is optional; the prompt explicitly permits
    # generation from the project and linked repositories alone.
    _, user_message = provider.calls[0]
    assert "No project brief was supplied" in user_message


def test_generate_project_wiki_grounds_on_latest_generation_brief(monkeypatch):
    """Inserts a generation row directly via save_generation rather than
    running /generate-stream — no AI provider is involved in producing the
    backlog itself, only in the wiki call under test."""
    from app.schemas.models import GenerationOutput

    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    project = _create_project()

    brief = "Build a turf booking app with slot reservation and payments."
    output = GenerationOutput(needs_clarification=False, clarifying_questions=[], stories=[], tasks=[], gaps=[])
    database.save_generation(brief, output, project_id=project["id"])

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    _, user_message = provider.calls[0]
    assert "turf booking" in user_message.lower()


def test_generate_project_wiki_grounds_on_linked_repo_contents(monkeypatch):
    """A project-level 'Generate overview' with a linked repo must feed that
    repo's file listing/README into the prompt too, not just the brief —
    otherwise clicking Generate overview never actually looks at the repo."""
    import bitbucket.client as bb_client

    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        bb_client, "list_repo_files",
        lambda config, path="", ref="HEAD": [{"type": "commit_file", "path": "src/app.py"}],
    )
    monkeypatch.setattr(
        bb_client, "get_file_content",
        lambda config, path, ref="HEAD": "from fastapi import FastAPI",
    )
    # build_repo_context_block calls list_repo_files as a same-module name,
    # so patching it on bb_client is enough; _readme_content in projects.py
    # imported get_file_content by name, so that one needs patching there.
    monkeypatch.setattr(projects_api, "get_file_content", lambda config, path: "# fits-service\nA backend service.")
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    _, user_message = provider.calls[0]
    assert "src/app.py" in user_message
    assert "fits-service" in user_message.lower()


def test_generate_project_wiki_combines_all_linked_repositories_without_brief(monkeypatch):
    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        projects_api,
        "_collect_repo_wiki_material",
        lambda repo: {
            "label": repo["label"] or repo["repo_slug"],
            "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
            "context_block": f"architecture evidence from {repo['repo_slug']}",
            "readme_text": None,
        },
    )
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-ui", "label": "frontend", "verify": False,
    })
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "label": "backend", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/wiki/generate")

    assert response.status_code == 200
    _, user_message = provider.calls[0]
    assert "No project brief was supplied" in user_message
    assert "architecture evidence from fits-ui" in user_message
    assert "architecture evidence from fits-service" in user_message


def test_generate_project_wiki_404_for_missing_project(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    assert client.post("/projects/999999/wiki/generate").status_code == 404


def test_generate_project_wiki_maps_provider_exhaustion_to_503(monkeypatch):
    provider = StubWikiProvider(raise_error=AllProvidersExhaustedError("no provider available"))
    _stub(monkeypatch, provider)
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 503


def test_generate_project_wiki_502_on_malformed_model_response(monkeypatch):
    class RawProvider:
        def generate(self, system_prompt, user_message):
            return "not json"

    _stub(monkeypatch, RawProvider())
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 502


def test_get_project_wiki_round_trips_generated_page(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    generated = client.post(f"/projects/{project['id']}/wiki/generate").json()

    fetched = client.get(f"/projects/{project['id']}/wiki")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["project_id"] == project["id"]
    assert len(body["pages"]) == 1
    assert body["pages"][0]["id"] == generated["id"]
    assert body["pages"][0]["title"] == generated["title"]


def test_regenerating_project_wiki_overwrites_not_duplicates(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    first = client.post(f"/projects/{project['id']}/wiki/generate").json()

    _stub(monkeypatch, StubWikiProvider(page={
        "title": "Smart Turf v2", "summary": "Updated.", "sections": [],
    }))
    second = client.post(f"/projects/{project['id']}/wiki/generate").json()

    assert second["id"] == first["id"]
    assert second["title"] == "Smart Turf v2"
    pages = client.get(f"/projects/{project['id']}/wiki").json()["pages"]
    assert len(pages) == 1


def test_get_project_wiki_404_for_missing_project():
    assert client.get("/projects/999999/wiki").status_code == 404


# ── Repo wiki ────────────────────────────────────────────────────────────

def test_generate_repo_wiki_without_bitbucket_configured(monkeypatch):
    """No BITBUCKET_ACCESS_TOKEN in this test environment — the endpoint must
    degrade gracefully (empty repo context) rather than failing the request."""
    provider = StubWikiProvider(page={
        "title": "fits-service", "summary": "Backend service repo.", "sections": [],
    })
    _stub(monkeypatch, provider)
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    repo = client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    }).json()

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/wiki/generate")
    assert response.status_code == 200
    page = response.json()
    assert page["repo_id"] == repo["id"]
    assert page["title"] == "fits-service"


def test_generate_repo_wiki_404_for_repo_not_on_project(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project_a = _create_project("A")
    project_b = _create_project("B")
    repo = client.post(f"/projects/{project_b['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-ui", "verify": False,
    }).json()

    response = client.post(f"/projects/{project_a['id']}/repos/{repo['id']}/wiki/generate")
    assert response.status_code == 404


def test_wiki_page_deleted_when_project_deleted(monkeypatch):
    """Cascade via ON DELETE CASCADE on project_wiki_pages.project_id."""
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    client.post(f"/projects/{project['id']}/wiki/generate")

    client.delete(f"/projects/{project['id']}")
    assert database.get_wiki_page(project["id"]) is None
