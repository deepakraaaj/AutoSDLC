"""A task's generated QA test cases must end up in the Redmine task issue's
description — otherwise they only ever exist in this app's own UI, which
defeats the point of generating them (a QA tester/PM reads issues in
Redmine, not this app's live view). Regression test for that gap."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import redmine.client as redmine  # noqa: E402
from app.schemas.models import GenerationOutput, Task, TestCase  # noqa: E402


def _push_single_task(task: Task, monkeypatch) -> str:
    """Runs push_to_redmine for one task and returns the description Redmine
    would have received, without making any real HTTP calls."""
    monkeypatch.setattr(redmine, "resolve_project_id", lambda *_: "42")
    monkeypatch.setattr(redmine, "build_priority_id_map", lambda *_: {"critical": 5, "high": 4, "medium": 2, "low": 1})
    monkeypatch.setattr(redmine, "get_tracker_id", lambda *_: "7")
    monkeypatch.setattr(redmine, "_get_project_enabled_tracker_ids", lambda *_: {7})
    monkeypatch.setattr(redmine, "get_custom_field_id_map", lambda *_: {})
    monkeypatch.setattr(redmine, "get_project_subject_prefix_counters", lambda *_: {"E": 0, "S": 0, "T": 0})

    captured_payloads = []

    def fake_create_issue(_url, _key, payload):
        captured_payloads.append(payload)
        return {"id": 1, "priority": {"id": 2, "name": "Normal"}}

    monkeypatch.setattr(redmine, "_create_issue", fake_create_issue)
    monkeypatch.setattr(redmine, "_get_issue", lambda *_: {"id": 1, "priority": {"id": 2, "name": "Normal"}})

    output = GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[],
        stories=[],
        tasks=[task],
        gaps=[],
    )
    redmine.push_to_redmine(
        output,
        redmine.RedmineConfig(url="http://example.com", api_key="api-key", project_id="demo"),
    )
    return captured_payloads[0]["issue"]["description"]


def test_test_cases_appear_in_task_description(monkeypatch):
    task = Task(
        id="T1",
        title="Add close-poll button",
        description="Implement the close action.",
        definition_of_done="Closing a poll hides the vote form.",
        estimate_hours="2-3",
        dependencies=[],
        confidence="high",
        test_cases=[
            TestCase(
                id="T1-T1",
                title="Close poll happy path",
                test_type="functional",
                description="Verifies closing a poll works.",
                preconditions="An open poll exists.",
                steps=["Open the poll.", "Click Close."],
                expected_result="The poll status shows Closed.",
            ),
        ],
    )

    description = _push_single_task(task, monkeypatch)

    assert "*Test Cases:*" in description
    assert "T1-T1: Close poll happy path" in description
    assert "functional" in description
    assert "# Open the poll." in description
    assert "# Click Close." in description
    assert "The poll status shows Closed." in description
    # Never a code-shaped field — see the TestCase model's docstring for why.
    assert "test_code" not in description
    assert "assertion" not in description


def test_no_test_cases_section_when_task_has_none(monkeypatch):
    task = Task(
        id="T1",
        title="Add close-poll button",
        description="Implement the close action.",
        definition_of_done="Closing a poll hides the vote form.",
        estimate_hours="2-3",
        dependencies=[],
        confidence="high",
    )

    description = _push_single_task(task, monkeypatch)

    assert "*Test Cases:*" not in description
