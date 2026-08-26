"""Tests for app/services/wiki_chapters.py — Pass 0 of the multi-chapter
wiki pipeline (cross-repo edge resolution + deterministic chapter
clustering). Per the approved plan's testing strategy, this is the
highest-value test investment: Pass 0 is fully deterministic, so every case
here asserts an exact expected result, not a content-quality judgment."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.database as database  # noqa: E402
from app.services.repo_intelligence import index_repository, symbol_id  # noqa: E402
from app.services.wiki_chapters import (  # noqa: E402
    MIN_SEEDS_FOR_CHAPTERING,
    build_chapter_set,
    cluster_repo_chapters,
    global_symbol_id,
    normalize_path_template,
    resolve_cross_repo_edges,
    route_from_symbol,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


# ── normalize_path_template ─────────────────────────────────────────────

def test_normalize_path_template_collapses_placeholder_styles():
    assert normalize_path_template("/projects/{id}/wiki") == normalize_path_template("/projects/${id}/wiki")
    assert normalize_path_template("/projects/:id/wiki") == normalize_path_template("/projects/{id}/wiki")


def test_normalize_path_template_strips_query_string():
    assert normalize_path_template("/things?limit=10") == ("things",)


def test_normalize_path_template_differs_on_real_segment_difference():
    assert normalize_path_template("/projects/{id}") != normalize_path_template("/projects/{id}/wiki")
    assert normalize_path_template("/projects/{id}") != normalize_path_template("/projects/{id}/other")


# ── route_from_symbol ────────────────────────────────────────────────────

def test_route_from_symbol_handles_python_decorator_shape(tmp_path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n@app.post('/things/{id}')\nasync def update_thing():\n    pass\n"
    )
    index = index_repository(tmp_path, "rev")
    route = next(s for s in index.symbols if s.kind == "api_route")
    assert route_from_symbol(route) == ("POST", "/things/{id}")


def test_route_from_symbol_handles_js_shape(tmp_path):
    (tmp_path / "server.ts").write_text("router.get('/health', health)\n")
    index = index_repository(tmp_path, "rev")
    route = next(s for s in index.symbols if s.kind == "api_route")
    assert route_from_symbol(route) == ("GET", "/health")


# ── resolve_cross_repo_edges ─────────────────────────────────────────────

def test_resolve_cross_repo_edges_matches_frontend_call_to_backend_route(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "client.ts").write_text(
        "export function generateWiki(id) {\n  return postJSON(`/projects/${id}/wiki/generate-job`, {})\n}\n"
    )
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.post('/projects/{project_id}/wiki/generate-job')\nasync def generate_wiki():\n    pass\n"
    )
    frontend_index = index_repository(frontend_dir, "rev-fe")
    backend_index = index_repository(backend_dir, "rev-be")

    edges = resolve_cross_repo_edges({1: frontend_index, 2: backend_index})

    assert len(edges) == 1
    edge = edges[0]
    assert edge.kind == "cross_repo_calls"
    assert edge.method == "POST"
    assert edge.source_repo_id == 1
    assert edge.target_repo_id == 2
    assert edge.source_path == "client.ts"
    assert edge.target_path == "app.py"


def test_resolve_cross_repo_edges_rejects_different_method(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "client.ts").write_text("getJSON('/things')\n")
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "server.ts").write_text("router.delete('/things', handler)\n")

    edges = resolve_cross_repo_edges({
        1: index_repository(frontend_dir, "rev-fe"),
        2: index_repository(backend_dir, "rev-be"),
    })
    assert edges == []


def test_resolve_cross_repo_edges_rejects_different_segment_count(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "client.ts").write_text("getJSON('/projects/${id}')\n")
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "server.ts").write_text("router.get('/projects/:id/wiki', handler)\n")

    edges = resolve_cross_repo_edges({
        1: index_repository(frontend_dir, "rev-fe"),
        2: index_repository(backend_dir, "rev-be"),
    })
    assert edges == []


def test_resolve_cross_repo_edges_ignores_same_repo_pairs(tmp_path):
    """A route and a call site that happen to match, but live in the SAME
    repo, are not reported as a cross-repo edge — that's already the
    intra-repo resolver's job (repo_intelligence.py's resolve_relations).
    Only the genuine cross-repo pair should be reported here."""
    same_repo_dir = tmp_path / "monolith"
    same_repo_dir.mkdir()
    (same_repo_dir / "app.ts").write_text("getJSON('/things')\nrouter.get('/things', handler)\n")

    other_frontend_dir = tmp_path / "frontend"
    other_frontend_dir.mkdir()
    (other_frontend_dir / "client.ts").write_text("getJSON('/widgets')\n")

    monolith_index = index_repository(same_repo_dir, "rev-mono")
    frontend_index = index_repository(other_frontend_dir, "rev-fe")

    edges = resolve_cross_repo_edges({1: monolith_index, 2: frontend_index})
    # /widgets has no matching route anywhere, so the only possible match is
    # /things — but its call site and route are both inside repo 1, so it
    # must NOT be reported (repo_id 1 -> repo_id 1 is excluded by design).
    assert edges == []


def test_global_symbol_id_is_repo_qualified(tmp_path):
    (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
    index = index_repository(tmp_path, "rev")
    sym = index.symbols[0]
    assert global_symbol_id(1, sym) == f"1::{symbol_id(sym)}"
    assert global_symbol_id(2, sym) == f"2::{symbol_id(sym)}"
    assert global_symbol_id(1, sym) != global_symbol_id(2, sym)


# ── cluster_repo_chapters ────────────────────────────────────────────────

def test_cluster_repo_chapters_falls_back_to_empty_for_small_repo(tmp_path):
    (tmp_path / "app.py").write_text("class Thing:\n    pass\n")
    index = index_repository(tmp_path, "rev")
    seeds = [s for s in index.symbols if s.kind in {"api_route", "class", "data_model"}]
    assert len(seeds) < MIN_SEEDS_FOR_CHAPTERING
    assert cluster_repo_chapters(1, index) == []


def test_cluster_repo_chapters_covers_every_seed_symbol(tmp_path):
    """Structural completeness check, not a content judgment: every
    api_route/class/data_model symbol must appear inside SOME chapter's
    subtree (member_symbol_ids), whether via a seed's own neighborhood or
    the "Other" catch-all — this is what actually fixes the completeness
    gap the discarded capability_areas field in the flat pipeline tried and
    failed to guarantee."""
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\n\n"
        "class Widget(BaseModel):\n    name: str\n\n"
        "class Gadget(BaseModel):\n    name: str\n\n"
        "@app.get('/widgets')\nasync def list_widgets():\n    pass\n\n"
        "@app.get('/gadgets')\nasync def list_gadgets():\n    pass\n\n"
        "@app.get('/reports')\nasync def list_reports():\n    pass\n"
    )
    index = index_repository(tmp_path, "rev")
    seeds = [s for s in index.symbols if s.kind in {"api_route", "class", "data_model"}]
    assert len(seeds) >= MIN_SEEDS_FOR_CHAPTERING

    chapters = cluster_repo_chapters(1, index)
    assert chapters  # real chapters were produced

    all_seed_local_ids = {symbol_id(s) for s in seeds}
    covered: set[str] = set()

    def walk(node):
        covered.update(node.member_symbol_ids)
        for child in node.children:
            walk(child)

    for chapter in chapters:
        walk(chapter)

    assert all_seed_local_ids <= covered


def test_cluster_repo_chapters_is_deterministic(tmp_path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/a')\nasync def a():\n    pass\n\n"
        "@app.get('/b')\nasync def b():\n    pass\n\n"
        "@app.get('/c')\nasync def c():\n    pass\n"
    )
    index = index_repository(tmp_path, "rev")
    first = cluster_repo_chapters(1, index)
    second = cluster_repo_chapters(1, index)
    first_shapes = [(c.seed_symbol_ids, [g.seed_symbol_ids for g in c.children]) for c in first]
    second_shapes = [(c.seed_symbol_ids, [g.seed_symbol_ids for g in c.children]) for c in second]
    assert first_shapes == second_shapes


# ── build_chapter_set (full Pass 0 integration, persisted) ──────────────

def test_build_chapter_set_persists_a_queryable_chapter_tree(tmp_path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/a')\nasync def a():\n    pass\n\n"
        "@app.get('/b')\nasync def b():\n    pass\n\n"
        "@app.get('/c')\nasync def c():\n    pass\n"
    )
    index = index_repository(tmp_path, "rev")

    project = database.create_project("Test Project")
    repo = database.add_project_repo(project["id"], "acme", "widgets")
    chapter_set_id = build_chapter_set(project["id"], {repo["id"]: index})

    stored = database.get_current_chapter_set(project["id"])
    assert stored is not None
    assert stored["id"] == chapter_set_id
    assert stored["chapters"]
    # Skeleton rows: title/summary/sections are unset until Pass 1 runs.
    assert all(c["title"] is None for c in stored["chapters"])
    assert all(c["sections"] == [] for c in stored["chapters"])


def test_build_chapter_set_records_cross_repo_edges(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "client.ts").write_text("getJSON('/things')\n")
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "server.ts").write_text("router.get('/things', handler)\n")

    project = database.create_project("Cross Repo Project")
    build_chapter_set(project["id"], {
        1: index_repository(frontend_dir, "rev-fe"),
        2: index_repository(backend_dir, "rev-be"),
    })

    stored = database.get_current_chapter_set(project["id"])
    assert len(stored["cross_repo_edges"]) == 1
    assert stored["cross_repo_edges"][0]["method"] == "GET"


def test_build_chapter_set_only_current_set_is_returned(tmp_path):
    """A second build for the same project supersedes the first — is_current
    flips, get_current_chapter_set only ever returns the latest."""
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/a')\nasync def a():\n    pass\n\n"
        "@app.get('/b')\nasync def b():\n    pass\n\n"
        "@app.get('/c')\nasync def c():\n    pass\n"
    )
    index = index_repository(tmp_path, "rev")
    project = database.create_project("Rebuild Project")
    repo = database.add_project_repo(project["id"], "acme", "widgets")

    first_id = build_chapter_set(project["id"], {repo["id"]: index})
    second_id = build_chapter_set(project["id"], {repo["id"]: index})

    assert first_id != second_id
    stored = database.get_current_chapter_set(project["id"])
    assert stored["id"] == second_id
