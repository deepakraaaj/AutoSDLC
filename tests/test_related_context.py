"""Tests for app/services/related_context.py — the SQL-backed replacement
for the old Neo4j knowledge graph. Same job (let generation know what
already exists elsewhere), backed by a plain query over the existing
epics/generations tables instead of a separate graph database."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.related_context as related_context  # noqa: E402
import app.services.database as database  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _create_generation(project_name: str) -> int:
    from datetime import datetime, timezone
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO generations (created_at, project_name, input_text, output_json) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), project_name, "brief text", "{}"),
    )
    conn.commit()
    gen_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()
    return gen_id


def _add_epic(gen_id: int, title: str, feature_area: str) -> None:
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO epics (issue_id, generation_id, ai_id, title, description, feature_area, priority, status, created_at) "
        "VALUES (?, ?, ?, ?, '', ?, 'high', 'planned', datetime('now'))",
        (f"E-{gen_id}-{title}", gen_id, "E1", title, feature_area),
    )
    conn.commit()
    conn.close()


def test_extract_keywords_filters_stopwords_and_short_words():
    text = "Build a project management tool with user accounts and billing systems"
    keywords = related_context._extract_keywords(text)
    assert "system" not in keywords  # in _STOPWORDS
    assert all(len(w) >= 5 for w in keywords)


def test_query_related_context_returns_empty_without_keywords():
    assert related_context.query_related_context("a to it") == []  # no words >= 5 chars


def test_query_related_context_returns_empty_with_no_matches():
    gen_id = _create_generation("Unrelated Project")
    _add_epic(gen_id, "Completely different topic entirely", "Misc")
    assert related_context.query_related_context("Build a billing and invoicing platform") == []


def test_query_related_context_finds_matching_epics_across_projects():
    gen_id = _create_generation("Corporate Card Reconciliation")
    _add_epic(gen_id, "Billing Reconciliation", "Billing")

    results = related_context.query_related_context("Build a billing and invoicing platform")
    assert len(results) == 1
    assert results[0]["project_name"] == "Corporate Card Reconciliation"
    assert results[0]["title"] == "Billing Reconciliation"
    assert results[0]["generation_id"] == gen_id


def test_query_related_context_excludes_current_generation():
    gen_id = _create_generation("Billing Platform")
    _add_epic(gen_id, "Billing Reconciliation", "Billing")

    results = related_context.query_related_context("Build a billing and invoicing platform", exclude_generation_id=gen_id)
    assert results == []


def test_query_related_context_respects_limit():
    for i in range(5):
        gen_id = _create_generation(f"Billing Project {i}")
        _add_epic(gen_id, "Billing Reconciliation", "Billing")

    results = related_context.query_related_context("Build a billing and invoicing platform", limit=2)
    assert len(results) == 2


def test_query_related_context_degrades_to_empty_on_db_error(monkeypatch):
    def raise_error():
        raise RuntimeError("db locked")

    monkeypatch.setattr(related_context, "get_connection", raise_error)
    assert related_context.query_related_context("Build a billing and invoicing platform") == []
