"""Tests for step-by-step generation: the four phase functions extracted out
of _three_phase_generate (main.py), and the /generate-epics ->
/generate-stories/{id} -> /generate-tasks/{id} -> /generate-test-cases/{id}
endpoint chain built on top of them. Isolated from the real dev database via
a tmp_path monkeypatch, same as tests/test_providers_endpoints.py."""
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
from app.schemas.models import GenerationOutput  # noqa: E402
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


def _empty_output():
    return GenerationOutput(
        needs_clarification=False, clarifying_questions=[], epics=[], stories=[], tasks=[], gaps=[], metrics=None,
    )


def _parsed_events(res, event_type=None):
    out = []
    for line in res.text.split("\n"):
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: "):])
        if event_type is None or payload.get("type") == event_type:
            out.append(payload)
    return out


# ── Extracted phase functions behave the same as before the refactor ───────

def test_extracted_phases_compose_to_the_same_result_as_three_phase_generate():
    """The old _three_phase_generate test suite (tests/test_three_phase_generation.py)
    already covers each phase's behavior in detail — this just confirms the
    extraction didn't change what _three_phase_generate itself produces."""
    provider = FakeProvider()
    output = _empty_output()
    events = list(main._three_phase_generate("Build a small SaaS product.", provider, output))

    assert len(output.epics) == 2
    assert len(output.stories) == 4
    assert len(output.tasks) == 8
    assert all(t.test_cases for t in output.tasks)
    assert not any('"type": "error"' in e for e in events)


def test_generate_stories_phase_continues_id_numbering_when_resumed():
    """Simulates what the /generate-stories/{id} endpoint does: start from an
    output that already has epics (from a prior /generate-epics call) and
    confirm new story IDs continue rather than restart at S1."""
    provider = FakeProvider()
    output = _empty_output()
    list(main._generate_epics_phase("Build a small SaaS product.", provider, output))
    assert len(output.epics) == 2

    # Pretend one story already exists (as if a previous partial run saved it).
    from app.schemas.models import Story
    output.stories.append(Story(
        id="S1", title="Existing", as_a="x", i_want="y", so_that="z",
        acceptance_criteria=["ok"], feature_area="General", size="small",
        confidence="high", epic_id=output.epics[0].id,
    ))

    list(main._generate_stories_phase("Build a small SaaS product.", provider, output))
    new_ids = [s.id for s in output.stories if s.id != "S1"]
    assert "S1" not in new_ids  # no collision
    assert all(int(sid[1:]) > 1 for sid in new_ids)


# ── Endpoint chain: /generate-epics -> stories -> tasks -> test-cases ──────

def test_full_step_by_step_chain_matches_one_click_shape(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    res = client.post("/generate-epics", json={"text": "Build a small SaaS product for managing team tasks."})
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    assert done[0]["phase"] == "epics"
    gen_id = done[0]["output"]["generation_id"]
    assert len(done[0]["output"]["epics"]) == 2

    res = client.post(f"/generate-stories/{gen_id}")
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    assert done[0]["phase"] == "stories"
    assert len(done[0]["output"]["stories"]) == 4

    res = client.post(f"/generate-tasks/{gen_id}")
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    assert done[0]["phase"] == "tasks"
    assert len(done[0]["output"]["tasks"]) == 8

    res = client.post(f"/generate-test-cases/{gen_id}")
    assert res.status_code == 200
    done = _parsed_events(res, "done")
    assert len(done) == 1
    assert done[0]["phase"] == "tests"
    final_output = done[0]["output"]
    assert all(t["test_cases"] for t in final_output["tasks"])
    assert final_output["metrics"] is not None
    assert final_output["validation"] is not None

    # DB ends up with exactly the rows a one-click run would have produced —
    # no double-inserts from resuming across 4 separate requests.
    history = client.get(f"/history/{gen_id}")
    assert history.status_code == 200
    saved = history.json()["output"]
    assert len(saved["epics"]) == 2
    assert len(saved["stories"]) == 4
    assert len(saved["tasks"]) == 8
    assert all(t["test_cases"] for t in saved["tasks"])

    hierarchy = client.get(f"/hierarchy/{gen_id}")
    assert hierarchy.status_code == 200
    hdata = hierarchy.json()
    assert len(hdata["epics"]) == 2
    assert sum(len(e["stories"]) for e in hdata["epics"]) == 4
    assert sum(len(s["tasks"]) for e in hdata["epics"] for s in e["stories"]) == 8


def test_generate_stories_without_prior_epics_yields_error(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    # A generation with no epics saved (simulate by asking for a generation id
    # that doesn't exist at all).
    res = client.post("/generate-stories/999999")
    assert res.status_code == 200
    errors = _parsed_events(res, "error")
    assert len(errors) == 1
    assert "not found" in errors[0]["error"]["message"].lower()


def test_generate_tasks_before_stories_yields_error(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    res = client.post("/generate-epics", json={"text": "Build a small SaaS product."})
    gen_id = _parsed_events(res, "done")[0]["output"]["generation_id"]

    res = client.post(f"/generate-tasks/{gen_id}")
    errors = _parsed_events(res, "error")
    assert len(errors) == 1
    assert "generate stories first" in errors[0]["error"]["message"].lower()
