"""Tests for per-project settings: app/services/database.py's
get_project_settings/upsert_project_settings, the GET/PUT
/projects/{id}/settings endpoints, and main.py's
_bitbucket_config_for_project / _maybe_auto_push_bitbucket helpers.

Project is now a first-class entity (app/api/projects.py) — settings key
off project_id, not generation_id (a generation optionally belongs to a
project via generations.project_id)."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.schemas.models import GenerationOutput, ValidationResult  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _create_project() -> int:
    return database.create_project("Test Project")["id"]


def _create_generation(project_id: int | None = None) -> int:
    from datetime import datetime, timezone
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO generations (created_at, project_name, input_text, output_json, project_id) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), "Test Project", "brief text", "{}", project_id),
    )
    conn.commit()
    gen_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()
    return gen_id


def test_init_db_migrates_old_generation_id_keyed_project_settings(tmp_path, monkeypatch):
    """Regression: project_settings shipped earlier this session keyed by
    generation_id, before Project existed. CREATE TABLE IF NOT EXISTS is a
    no-op against that shape (confirmed live — the real dev DB hit exactly
    this: 'no such column: project_id' on the first genuine settings save).
    init_db() must detect and migrate it, not silently leave it stale."""
    db_path = tmp_path / "old_schema.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    conn = database.get_connection()
    conn.execute("""
        CREATE TABLE project_settings (
            generation_id INTEGER PRIMARY KEY,
            bitbucket_workspace TEXT,
            bitbucket_repo_slug TEXT,
            custom_instructions TEXT,
            auto_push_bitbucket INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    database.init_db()  # must not raise, and must leave the new project_id-keyed shape behind

    project_id = database.create_project("Migrated Project")["id"]
    result = database.upsert_project_settings(project_id, custom_instructions="works now")
    assert result["custom_instructions"] == "works now"


def test_get_project_settings_returns_defaults_when_unset():
    project_id = _create_project()
    settings = database.get_project_settings(project_id)
    assert settings == {
        "project_id": project_id, "custom_instructions": None, "auto_push_bitbucket": False,
        "default_redmine_project_id": None,
    }


def test_upsert_project_settings_partial_update_preserves_other_fields():
    project_id = _create_project()
    database.upsert_project_settings(project_id, custom_instructions="Use snake_case.")
    database.upsert_project_settings(project_id, auto_push_bitbucket=True)
    settings = database.get_project_settings(project_id)
    assert settings["custom_instructions"] == "Use snake_case."
    assert settings["auto_push_bitbucket"] is True


def test_upsert_project_settings_ignores_unknown_fields():
    project_id = _create_project()
    result = database.upsert_project_settings(project_id, not_a_real_field="x", auto_push_bitbucket=True)
    assert "not_a_real_field" not in result
    assert result["auto_push_bitbucket"] is True


def test_get_settings_endpoint_404s_for_missing_project():
    response = client.get("/projects/999999/settings")
    assert response.status_code == 404


def test_put_settings_endpoint_round_trips():
    project_id = _create_project()
    response = client.put(f"/projects/{project_id}/settings", json={
        "custom_instructions": "Always write GWT acceptance criteria.", "auto_push_bitbucket": True,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["custom_instructions"] == "Always write GWT acceptance criteria."
    assert body["auto_push_bitbucket"] is True

    read_back = client.get(f"/projects/{project_id}/settings")
    assert read_back.json() == body


def test_bitbucket_config_for_project_uses_first_linked_repo(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "env-workspace")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "env-repo")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    project_id = _create_project()

    # No repos linked yet — falls back to env.
    config = main._bitbucket_config_for_project(project_id)
    assert config.workspace == "env-workspace"
    assert config.repo_slug == "env-repo"

    database.add_project_repo(project_id, "project-workspace", "project-repo")
    config = main._bitbucket_config_for_project(project_id)
    assert config.workspace == "project-workspace"
    assert config.repo_slug == "project-repo"


def test_bitbucket_config_for_project_none_returns_env_config(monkeypatch):
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "env-workspace")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "env-repo")
    config = main._bitbucket_config_for_project(None)
    assert config.workspace == "env-workspace"
    assert config.repo_slug == "env-repo"


def _output(trust_level: str | None) -> GenerationOutput:
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[], epics=[], stories=[], tasks=[], gaps=[],
    )
    if trust_level:
        output.validation = ValidationResult(trust_level=trust_level, checks=[], recommendation="")
    return output


def test_maybe_auto_push_noops_when_not_trusted():
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    database.upsert_project_settings(project_id, auto_push_bitbucket=True)
    assert main._maybe_auto_push_bitbucket(gen_id, _output("review")) is None
    assert main._maybe_auto_push_bitbucket(gen_id, _output(None)) is None


def test_maybe_auto_push_noops_when_toggle_off():
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    assert main._maybe_auto_push_bitbucket(gen_id, _output("trusted")) is None


def test_maybe_auto_push_noops_when_generation_has_no_project():
    gen_id = _create_generation(project_id=None)
    assert main._maybe_auto_push_bitbucket(gen_id, _output("trusted")) is None


def test_maybe_auto_push_calls_push_when_trusted_and_enabled(monkeypatch):
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    database.upsert_project_settings(project_id, auto_push_bitbucket=True)
    monkeypatch.setattr(
        main, "_bitbucket_config_for_project",
        lambda pid, repo_id=None: type("Cfg", (), {"is_configured": lambda self: True, "workspace": "acme", "repo_slug": "widgets"})(),
    )
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gid: None)
    captured = {}

    def fake_push(output, config, existing=None):
        captured["called"] = True
        return {"created_issues": []}

    monkeypatch.setattr(main, "push_backlog_to_bitbucket", fake_push)
    result = main._maybe_auto_push_bitbucket(gen_id, _output("trusted"))
    assert result == {"created_issues": []}
    assert captured["called"] is True


def test_maybe_auto_push_swallows_push_failure(monkeypatch):
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    database.upsert_project_settings(project_id, auto_push_bitbucket=True)
    monkeypatch.setattr(
        main, "_bitbucket_config_for_project",
        lambda pid, repo_id=None: type("Cfg", (), {"is_configured": lambda self: True, "workspace": "acme", "repo_slug": "widgets"})(),
    )
    monkeypatch.setattr(main, "get_generation_hierarchy", lambda gid: None)

    def raise_error(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(main, "push_backlog_to_bitbucket", raise_error)
    # Must not raise — a push failure can't be allowed to fail the phase that triggered it.
    assert main._maybe_auto_push_bitbucket(gen_id, _output("trusted")) is None
