from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from rule_based_generator import (  # noqa: E402
    StorySpec,
    TaskSpec,
    _build_story,
    generate_rule_based_output,
    looks_like_structured_brief,
)
from metrics import compute_metrics  # noqa: E402


def test_detects_structured_brief():
    text = Path(ROOT.parent / "AUTOSDLC_PROJECT_BRIEF.md").read_text(encoding="utf-8")
    assert looks_like_structured_brief(text) is True


def test_generates_rule_based_backlog_from_brief():
    text = Path(ROOT.parent / "AUTOSDLC_PROJECT_BRIEF.md").read_text(encoding="utf-8")
    output = generate_rule_based_output(text)

    assert output.needs_clarification is False
    assert output.clarifying_questions == []
    assert len(output.epics) >= 5
    assert len(output.stories) >= 15
    assert len(output.tasks) >= 30
    assert output.gaps == []

    for story in output.stories:
        assert len(story.acceptance_criteria) >= 3

    for task in output.tasks:
        assert task.dependencies

    metrics = compute_metrics(output)
    assert metrics.story_metrics.overall >= 70
    assert metrics.task_metrics.overall >= 70


def test_task_inherits_story_priority_when_unspecified():
    story_spec = StorySpec(
        title="Priority inheritance",
        as_a="delivery lead",
        i_want="generated tasks to keep story urgency",
        so_that="Redmine priorities stay aligned",
        acceptance_criteria=["Tasks inherit the story priority when not set explicitly."],
        feature_area="Tracking",
        size="small",
        priority="critical",
        tasks=[
            TaskSpec(
                title="Carry story priority into generated task",
                description="Build a task without an explicit task-level priority.",
                definition_of_done="The generated task priority matches the parent story priority.",
                estimate_hours="1-2",
                dependencies=["A parent story exists."],
            )
        ],
    )

    story, tasks = _build_story(story_spec, "E1", "S1", [0])

    assert story.priority == "critical"
    assert len(tasks) == 1
    assert tasks[0].priority == "critical"
