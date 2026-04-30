from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from rule_based_generator import generate_rule_based_output, looks_like_structured_brief  # noqa: E402
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
