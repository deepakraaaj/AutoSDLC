"""Integration tests for the multi-chapter wiki endpoints (app/api/projects.py:
get_project_chapter_wiki_endpoint / generate_project_chapter_wiki_endpoint /
the chapter_wiki_generation job runner) — same TestClient/StubProvider style
as tests/test_project_wiki.py."""
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

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AUTOSDLC_ARTIFACT_ROOT", str(tmp_path / "wiki_artifacts"))
    database.init_db()


class StubChapterProvider:
    """Same fixed-response generate() contract as test_project_wiki.py's
    StubWikiProvider — one call per top-level chapter, all returning the
    same well-formed leaf chapter JSON. Grounding validation only requires
    the evidence entries to be citation-SHAPED and the source material to
    contain some real citation somewhere (see wiki_generator._grounding_violations'
    early-return guard) — it doesn't cross-check the specific string
    against the material, so one fixed response works for any chapter."""

    def __init__(self):
        self.calls = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return json.dumps({
            "title": "A chapter", "summary": "Covers part of the product.",
            "sections": [{"heading": "What it does", "body": "Business capability described here.", "evidence": ["app.py:1"]}],
        })


def _stub(monkeypatch, provider):
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)


def _create_project(name="Chapter Wiki Project"):
    return client.post("/projects", json={"name": name, "description": "d"}).json()


def _link_repo_with_fastapi_routes(monkeypatch, project_id):
    """Same fake-snapshot monkeypatch pattern as test_project_wiki.py's
    test_generate_project_wiki_grounds_on_linked_repo_contents, but with
    enough api_route symbols (>= MIN_SEEDS_FOR_CHAPTERING) to actually
    trigger clustering rather than the small-repo fallback."""
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"mainbranch": {"name": "main", "target": {"hash": "abc123"}}})

    def fake_snapshot(config, destination, branch=None, timeout_seconds=None, **kwargs):
        target = destination / "app.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n\n"
            "@app.get('/a')\nasync def a():\n    pass\n\n"
            "@app.get('/b')\nasync def b():\n    pass\n\n"
            "@app.get('/c')\nasync def c():\n    pass\n"
        )
        return "abc123"

    monkeypatch.setattr(projects_api, "create_repository_snapshot", fake_snapshot)
    return client.post(f"/projects/{project_id}/repos", json={"workspace": "acme", "repo_slug": "widgets", "verify": False}).json()


# ── GET before any build ─────────────────────────────────────────────────

def test_get_chapter_wiki_404_before_any_build():
    project = _create_project()
    response = client.get(f"/projects/{project['id']}/wiki-chapters")
    assert response.status_code == 404


def test_get_chapter_wiki_404_for_missing_project():
    response = client.get("/projects/999999/wiki-chapters")
    assert response.status_code == 404


# ── generate: gating ─────────────────────────────────────────────────────

def test_generate_chapter_wiki_404_for_missing_project():
    response = client.post("/projects/999999/wiki-chapters/generate")
    assert response.status_code == 404


def test_generate_chapter_wiki_403_when_not_enabled(monkeypatch):
    provider = StubChapterProvider()
    _stub(monkeypatch, provider)
    project = _create_project()
    response = client.post(f"/projects/{project['id']}/wiki-chapters/generate")
    assert response.status_code == 403
    assert provider.calls == []  # never even tried — gated before any repo work


def test_generate_chapter_wiki_502_when_no_repos_linked(monkeypatch):
    provider = StubChapterProvider()
    _stub(monkeypatch, provider)
    project = _create_project()
    client.put(f"/projects/{project['id']}/settings", json={"chapter_wiki_enabled": True})
    response = client.post(f"/projects/{project['id']}/wiki-chapters/generate")
    assert response.status_code == 502


# ── generate: full flow ──────────────────────────────────────────────────

def test_generate_chapter_wiki_full_flow_builds_and_persists_chapters(monkeypatch):
    provider = StubChapterProvider()
    _stub(monkeypatch, provider)
    project = _create_project()
    client.put(f"/projects/{project['id']}/settings", json={"chapter_wiki_enabled": True})
    _link_repo_with_fastapi_routes(monkeypatch, project["id"])

    response = client.post(f"/projects/{project['id']}/wiki-chapters/generate")
    assert response.status_code == 200
    chapter_set = response.json()
    assert chapter_set["chapters"]
    top_level = [c for c in chapter_set["chapters"] if c["parent_id"] is None]
    assert top_level
    # Every top-level chapter got its own LLM call and its content narrated.
    for chapter in top_level:
        assert chapter["title"] is not None
        assert chapter["sections"]
        assert chapter["sections"][0]["evidence"] == ["app.py:1"]
    assert len(provider.calls) == len(top_level)

    # GET now returns the same persisted tree.
    fetched = client.get(f"/projects/{project['id']}/wiki-chapters").json()
    assert fetched["id"] == chapter_set["id"]
    assert len(fetched["chapters"]) == len(chapter_set["chapters"])


def test_regenerate_chapter_wiki_supersedes_previous_set(monkeypatch):
    provider = StubChapterProvider()
    _stub(monkeypatch, provider)
    project = _create_project()
    client.put(f"/projects/{project['id']}/settings", json={"chapter_wiki_enabled": True})
    _link_repo_with_fastapi_routes(monkeypatch, project["id"])

    first = client.post(f"/projects/{project['id']}/wiki-chapters/generate").json()
    second = client.post(f"/projects/{project['id']}/wiki-chapters/generate").json()
    assert first["id"] != second["id"]
    assert client.get(f"/projects/{project['id']}/wiki-chapters").json()["id"] == second["id"]
