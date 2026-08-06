"""Tests for _scope_output_to_epic — reduces a full backlog down to one
epic's branch for the "push this to Redmine" action from a detail view.
Must always include the whole epic->stories->tasks branch, never a bare
story/task alone, or the pushed issue would end up orphaned in Redmine with
no epic parent."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from app.schemas.models import Epic, GenerationOutput, Story, Task  # noqa: E402


def _epic(id_):
    return Epic(id=id_, title=f"Epic {id_}", description="d", feature_area="General", priority="medium")


def _story(id_, epic_id):
    return Story(
        id=id_, title=f"Story {id_}", as_a="user", i_want="x", so_that="y",
        acceptance_criteria=["Given x, when y, then z"], feature_area="General",
        size="small", confidence="high", epic_id=epic_id,
    )


def _task(id_, story_id):
    return Task(
        id=id_, title=f"Task {id_}", description="d", definition_of_done="done",
        estimate_hours="1-2", dependencies=[], story_id=story_id, confidence="high",
    )


def _full_output():
    return GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[_epic("E1"), _epic("E2")],
        stories=[_story("S1", "E1"), _story("S2", "E1"), _story("S3", "E2")],
        tasks=[_task("T1", "S1"), _task("T2", "S2"), _task("T3", "S3")],
        gaps=[],
    )


def test_scopes_to_exactly_one_epic_and_its_branch():
    scoped = main._scope_output_to_epic(_full_output(), "E1")

    assert [e.id for e in scoped.epics] == ["E1"]
    assert {s.id for s in scoped.stories} == {"S1", "S2"}
    assert {t.id for t in scoped.tasks} == {"T1", "T2"}


def test_other_epics_stories_and_tasks_are_excluded():
    scoped = main._scope_output_to_epic(_full_output(), "E1")

    assert "E2" not in {e.id for e in scoped.epics}
    assert "S3" not in {s.id for s in scoped.stories}
    assert "T3" not in {t.id for t in scoped.tasks}


def test_unknown_epic_id_raises():
    with pytest.raises(ValueError, match="not found"):
        main._scope_output_to_epic(_full_output(), "E999")
