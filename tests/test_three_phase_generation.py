"""Tests for the 4-phase AI generation pipeline (_three_phase_generate in
main.py) — epics -> stories -> tasks -> test cases. This is the actual
money-path of the app and, before this file, had zero automated coverage;
every bug we hit in it during development was caught by hand."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fake_provider import FakeProvider  # noqa: E402
import main  # noqa: E402
from app.schemas.models import GenerationOutput  # noqa: E402


def _empty_output():
    return GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[],
        stories=[],
        tasks=[],
        gaps=[],
        metrics=None,
    )


def _run(provider, text="Build a small SaaS product for managing team tasks."):
    output = _empty_output()
    events = list(main._three_phase_generate(text, provider, output))
    return output, events


def _parsed_events(events, event_type):
    """Decode the 'data: {...}\\n\\n' SSE lines into dicts, filtered by type."""
    out = []
    for e in events:
        if not e.startswith("data: "):
            continue
        payload = json.loads(e[len("data: "):])
        if payload.get("type") == event_type:
            out.append(payload)
    return out


def test_happy_path_links_epics_stories_tasks_and_tests():
    provider = FakeProvider()
    output, events = _run(provider)

    assert len(output.epics) == 2
    assert len(output.stories) == 4  # 2 stories/epic x 2 epics
    assert len(output.tasks) == 8  # 2 tasks/story x 4 stories

    # Every story links back to a real epic.
    epic_ids = {e.id for e in output.epics}
    for story in output.stories:
        assert story.epic_id in epic_ids

    # Every task links back to a real story.
    story_ids = {s.id for s in output.stories}
    for task in output.tasks:
        assert task.story_id in story_ids

    # Every task got test cases, correctly ID-namespaced under the task.
    for task in output.tasks:
        assert len(task.test_cases) == 1
        assert task.test_cases[0].id == f"{task.id}-T1"

    # No error events anywhere in a clean run.
    assert not any('"type": "error"' in e for e in events)


def test_epics_stories_tasks_stream_live_as_they_are_generated():
    """The frontend builds a live backlog view from these events instead of
    waiting for the final 'done' payload — each one must appear as soon as
    the corresponding item exists, not just be reflected in the final output."""
    provider = FakeProvider()
    output, events = _run(provider)

    epic_events = _parsed_events(events, "epic")
    story_events = _parsed_events(events, "story")
    task_events = _parsed_events(events, "task")

    assert [e["epic"]["id"] for e in epic_events] == [e.id for e in output.epics]
    assert [e["story"]["id"] for e in story_events] == [s.id for s in output.stories]

    # Every task streams once on creation (Phase 3) and again once test cases
    # land on it (Phase 4) — so each task id appears twice, and the second
    # copy actually carries the test cases.
    task_ids_seen = [e["task"]["id"] for e in task_events]
    for task in output.tasks:
        assert task_ids_seen.count(task.id) == 2

    updated_task_events = {e["task"]["id"]: e["task"] for e in task_events}
    for task in output.tasks:
        assert len(updated_task_events[task.id]["test_cases"]) == len(task.test_cases)


def test_task_with_invalid_story_id_is_rejected_not_silently_kept():
    epics = json.dumps([
        {"title": "Accounts", "description": "User accounts.", "feature_area": "Accounts", "priority": "high"},
    ])
    stories = json.dumps([
        {"title": "Sign up", "as_a": "new visitor", "i_want": "to create an account", "so_that": "I can use the product",
         "acceptance_criteria": ["Given valid input, when submitted, then account is created"], "size": "small", "priority": "high"},
    ])
    provider = FakeProvider(epics=epics, stories=stories)

    # Monkeypatch the task phase response after stories are known: we need
    # the real assigned story id (S1) plus one bogus id that must be dropped.
    original_tasks = provider._tasks

    def tasks_with_one_bad_id(user_message):
        return json.dumps([
            {"story_id": "S1", "title": "Legit task", "description": "Do the real thing, end to end.",
             "definition_of_done": "Works and is tested.", "estimate_hours": "2-4", "dependencies": [], "priority": "high"},
            {"story_id": "S999", "title": "Orphaned task", "description": "References a story that doesn't exist.",
             "definition_of_done": "N/A", "estimate_hours": "2-4", "dependencies": [], "priority": "high"},
        ])

    provider._tasks = tasks_with_one_bad_id
    output, _ = _run(provider)

    assert len(output.stories) == 1
    assert len(output.tasks) == 1  # the S999 task must be rejected
    assert output.tasks[0].story_id == "S1"


def test_phase1_empty_epics_yields_error_and_stops_pipeline():
    provider = FakeProvider(epics="[]")
    output, events = _run(provider)

    assert output.epics == []
    assert output.stories == []
    assert output.tasks == []
    assert any('"type": "error"' in e for e in events)
    # Only Phase 1 should have been called — nothing downstream.
    assert len(provider.calls) == 1


def test_phase1_all_epics_missing_required_fields_yields_error():
    # Title/description missing entirely -> every epic gets skipped as invalid.
    provider = FakeProvider(epics=json.dumps([{"feature_area": "X"}]))
    output, events = _run(provider)

    assert output.epics == []
    assert any('"type": "error"' in e for e in events)


def test_phase2_retries_once_then_succeeds():
    # First call for the epic returns nothing; second (retry) succeeds.
    story_queue = ["[]", json.dumps([
        {"title": "Sign up", "as_a": "new visitor", "i_want": "to create an account", "so_that": "I can use the product",
         "acceptance_criteria": ["Given valid input, when submitted, then account is created"], "size": "small", "priority": "high"},
    ])]
    provider = FakeProvider(epics=json.dumps([
        {"title": "Accounts", "description": "User accounts.", "feature_area": "Accounts", "priority": "high"},
    ]), story_queue=story_queue)

    output, _ = _run(provider)

    assert len(output.stories) == 1
    story_calls = [c for c in provider.calls if "writing user stories" in c[0]]
    assert len(story_calls) == 2  # confirms the retry actually happened


def test_test_case_generation_is_skipped_gracefully_when_tasks_exist_but_response_is_malformed():
    provider = FakeProvider()
    # Make the test-generation phase return unparseable garbage on both attempts.
    provider._tests = lambda user_message: "not json"
    output, events = _run(provider)

    # Pipeline should still complete with tasks, just no test cases attached.
    assert len(output.tasks) > 0
    assert all(t.test_cases == [] for t in output.tasks)
