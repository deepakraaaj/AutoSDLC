"""Tests for the full-content-edit endpoints (title/description/acceptance
criteria/etc — not just status/priority/assignee) and the priority
endpoints, which existed in the DB layer from a prior session but were
never wired to a route until now. Isolated from the real dev database via a
tmp_path monkeypatch, same as tests/test_step_generation.py."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fake_provider import FakeProvider  # noqa: E402
import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.utils import rate_limit  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


def _parsed_events(res, event_type=None):
    out = []
    for line in res.text.split("\n"):
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: "):])
        if event_type is None or payload.get("type") == event_type:
            out.append(payload)
    return out


@pytest.fixture
def seeded_ids(monkeypatch):
    """Runs a full one-click generation through the real endpoint (fake
    provider) and returns the DB ids of the first epic/story/task, via
    GET /hierarchy/{id} — exactly what the frontend does before editing."""
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    res = client.post("/generate-stream", json={"text": "Build a small SaaS product for managing team tasks."})
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    gen_id = done[0]["output"]["generation_id"]

    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    epic = hierarchy["epics"][0]
    story = epic["stories"][0]
    task = story["tasks"][0]
    return {"gen_id": gen_id, "epic_id": epic["db_id"], "story_id": story["db_id"], "task_id": task["db_id"]}


def test_one_click_generate_stream_done_event_carries_project_name(monkeypatch):
    """The Backlog view has no other way to show which project it's looking at —
    GenerationOutput itself has no project_name field (it's a DB/history concept),
    so the one-click /generate-stream 'done' event has to carry it explicitly, the
    same as every step-by-step phase's 'done' event does."""
    from app.services.database import extract_project_name
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    brief_text = "Build a small SaaS product for managing team tasks."

    res = client.post("/generate-stream", json={"text": brief_text})
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    assert done[0]["output"]["project_name"] == extract_project_name(brief_text)


# ── Content editing ─────────────────────────────────────────────────────

def test_update_epic_content_persists_and_returns_updated_fields(seeded_ids):
    res = client.patch(f"/epics/{seeded_ids['epic_id']}", json={"title": "Renamed Epic", "description": "New description"})
    assert res.status_code == 200
    body = res.json()
    assert body["updated"] is True
    assert body["title"] == "Renamed Epic"
    assert body["description"] == "New description"

    hierarchy = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    epic = next(e for e in hierarchy["epics"] if e["db_id"] == seeded_ids["epic_id"])
    assert epic["title"] == "Renamed Epic"
    assert epic["description"] == "New description"


def test_update_epic_content_partial_update_leaves_other_fields_alone(seeded_ids):
    before = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    epic_before = next(e for e in before["epics"] if e["db_id"] == seeded_ids["epic_id"])

    res = client.patch(f"/epics/{seeded_ids['epic_id']}", json={"title": "Only Title Changed"})
    assert res.status_code == 200

    after = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    epic_after = next(e for e in after["epics"] if e["db_id"] == seeded_ids["epic_id"])
    assert epic_after["title"] == "Only Title Changed"
    assert epic_after["description"] == epic_before["description"]


def test_update_epic_content_not_found_returns_404():
    res = client.patch("/epics/999999", json={"title": "Nope"})
    assert res.status_code == 404


def test_update_story_content_round_trips_acceptance_criteria_list(seeded_ids):
    new_ac = ["Given X, when Y, then Z", "Given A, when B, then C"]
    res = client.patch(f"/stories/{seeded_ids['story_id']}", json={
        "title": "Renamed Story",
        "so_that": "I get real value",
        "acceptance_criteria": new_ac,
    })
    assert res.status_code == 200
    assert res.json()["acceptance_criteria"] == new_ac

    hierarchy = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    story = next(s for e in hierarchy["epics"] for s in e["stories"] if s["db_id"] == seeded_ids["story_id"])
    assert story["title"] == "Renamed Story"
    assert story["so_that"] == "I get real value"
    assert story["acceptance_criteria"] == new_ac


def test_story_edit_is_canonical_for_history_export_and_redmine(seeded_ids, monkeypatch):
    """A visible edit must be the same content every downstream consumer sees.

    This guards the former split-brain persistence bug where hierarchy read the
    normalized row but History, Excel, scoring, and Redmine read stale output_json.
    """
    new_title = "Canonical edited story"
    new_ac = ["Given an approved file, when ingestion completes, then every valid row is staged"]
    res = client.patch(f"/stories/{seeded_ids['story_id']}", json={
        "title": new_title,
        "acceptance_criteria": new_ac,
    })
    assert res.status_code == 200

    history_output = client.get(f"/history/{seeded_ids['gen_id']}").json()["output"]
    history_story = next(s for s in history_output["stories"] if s["title"] == new_title)
    assert history_story["acceptance_criteria"] == new_ac

    exported = {}
    monkeypatch.setattr(main, "validate_backlog_depth", lambda output: [])
    def capture_export(output):
        exported["output"] = output
        return b"xlsx"
    monkeypatch.setattr(main, "generate_excel", capture_export)
    export_res = client.get(f"/export-excel/{seeded_ids['gen_id']}")
    assert export_res.status_code == 200
    assert any(s.title == new_title and s.acceptance_criteria == new_ac for s in exported["output"].stories)

    published = {}
    monkeypatch.setattr(main, "_run_redmine_trust_gate", lambda output: None)
    monkeypatch.setattr(main, "validate_redmine_url", lambda url: url)
    def capture_publish(output, config, existing=None):
        published["output"] = output
        return {"created_issues": []}
    monkeypatch.setattr(main, "push_to_redmine", capture_publish)
    push_res = client.post("/push-to-redmine", json={
        "generation_id": seeded_ids["gen_id"],
        "redmine_url": "https://redmine.example.test",
        "redmine_api_key": "test-key",
        "redmine_project_id": "demo",
    })
    assert push_res.status_code == 200
    assert any(s.title == new_title and s.acceptance_criteria == new_ac for s in published["output"].stories)


def test_update_task_content_round_trips_dependencies_list(seeded_ids):
    new_deps = ["Some other task must be done first"]
    res = client.patch(f"/tasks/{seeded_ids['task_id']}", json={
        "description": "Updated description",
        "definition_of_done": "Updated DoD",
        "dependencies": new_deps,
    })
    assert res.status_code == 200
    assert res.json()["dependencies"] == new_deps

    hierarchy = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    task = next(t for e in hierarchy["epics"] for s in e["stories"] for t in s["tasks"] if t["db_id"] == seeded_ids["task_id"])
    assert task["description"] == "Updated description"
    assert task["definition_of_done"] == "Updated DoD"
    assert task["dependencies"] == new_deps


def test_update_story_content_not_found_returns_404():
    res = client.patch("/stories/999999", json={"title": "Nope"})
    assert res.status_code == 404


def test_update_task_content_not_found_returns_404():
    res = client.patch("/tasks/999999", json={"title": "Nope"})
    assert res.status_code == 404


def test_update_content_with_empty_body_is_a_noop_but_still_404s_on_bad_id(seeded_ids):
    res = client.patch(f"/epics/{seeded_ids['epic_id']}", json={})
    assert res.status_code == 200
    assert res.json()["updated"] is True

    res = client.patch("/epics/999999", json={})
    assert res.status_code == 404


# ── Priority editing (previously unwired) ───────────────────────────────

def test_update_epic_priority(seeded_ids):
    res = client.patch(f"/epics/{seeded_ids['epic_id']}/priority", json={"priority": "critical"})
    assert res.status_code == 200
    assert res.json()["priority"] == "critical"

    hierarchy = client.get(f"/hierarchy/{seeded_ids['gen_id']}").json()
    epic = next(e for e in hierarchy["epics"] if e["db_id"] == seeded_ids["epic_id"])
    assert epic["priority"] == "critical"


def test_update_story_priority(seeded_ids):
    res = client.patch(f"/stories/{seeded_ids['story_id']}/priority", json={"priority": "low"})
    assert res.status_code == 200
    assert res.json()["priority"] == "low"


def test_update_task_priority(seeded_ids):
    res = client.patch(f"/tasks/{seeded_ids['task_id']}/priority", json={"priority": "high"})
    assert res.status_code == 200
    assert res.json()["priority"] == "high"


def test_update_priority_invalid_value_returns_422():
    res = client.patch("/epics/1/priority", json={"priority": "not-a-real-priority"})
    assert res.status_code == 422  # pydantic Literal validation, before the handler even runs


def test_update_priority_not_found_returns_404():
    res = client.patch("/tasks/999999/priority", json={"priority": "high"})
    assert res.status_code == 404
