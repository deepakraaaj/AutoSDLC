"""Tests for app/services/metrics.py — the quality scoring and validation
gate shown in the UI as the trust level (trusted/review/low). Pure functions,
deterministic, and central to what the app tells users to trust — but had no
dedicated test coverage before this file."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas.models import (  # noqa: E402
    Epic, Story, Task, Gap, GenerationOutput, OverallMetrics, StoryMetrics, TaskMetrics,
)
from app.services.metrics import score_stories, score_tasks, compute_metrics, run_validation  # noqa: E402


def _output(epics=None, stories=None, tasks=None, gaps=None):
    return GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=epics or [],
        stories=stories or [],
        tasks=tasks or [],
        gaps=gaps or [],
        metrics=None,
    )


def _story(**overrides):
    defaults = dict(
        id="S1", title="Story", as_a="user", i_want="do a thing", so_that="benefit",
        acceptance_criteria=[], feature_area="General", size="medium", confidence="high", epic_id="E1",
    )
    defaults.update(overrides)
    return Story(**defaults)


def _task(**overrides):
    defaults = dict(
        id="T1", title="Task", description="Do the thing.", definition_of_done="Done.",
        estimate_hours="4-6", dependencies=[], confidence="high", story_id="S1",
    )
    defaults.update(overrides)
    return Task(**defaults)


# ── score_stories ────────────────────────────────────────────────────────

def test_score_stories_empty_list_returns_all_zero():
    metrics = score_stories(_output())
    assert metrics.overall == 0
    assert metrics.specificity_score == 0


def test_score_stories_rewards_specific_actor_over_generic_user():
    generic = _story(as_a="user", i_want="log in", so_that="see stuff")
    specific = _story(
        as_a="returning premium subscriber",
        i_want="log in using my saved credentials on this device",
        so_that="I can pick up right where I left off without re-entering anything",
    )
    generic_score = score_stories(_output(stories=[generic])).specificity_score
    specific_score = score_stories(_output(stories=[specific])).specificity_score
    assert specific_score > generic_score
    assert generic_score <= 40  # "user" alone is blocklisted regardless of other content


def test_score_stories_testability_rewards_substantive_binary_acceptance_criteria():
    weak = _story(acceptance_criteria=["works"])
    strong = _story(acceptance_criteria=[
        "Given a valid email and password, when the form is submitted, then the account should be created",
        "Given an already-registered email, when submitted, then an error message should be displayed",
        "Given an empty password field, when submitted, then a validation error should be shown",
    ])
    weak_score = score_stories(_output(stories=[weak])).testability_score
    strong_score = score_stories(_output(stories=[strong])).testability_score
    assert strong_score > weak_score
    assert strong_score >= 70


def test_score_stories_sizing_flags_mismatched_label():
    # "small" but with far more ACs than a half-day story should realistically have.
    mismatched = _story(size="small", acceptance_criteria=[f"Criterion number {i} should hold true" for i in range(10)])
    consistent = _story(size="small", acceptance_criteria=["Criterion one should hold true"])
    mismatched_score = score_stories(_output(stories=[mismatched])).sizing_score
    consistent_score = score_stories(_output(stories=[consistent])).sizing_score
    assert consistent_score > mismatched_score


def test_score_stories_edge_case_score_rewards_edge_case_language():
    no_edge_cases = _story(acceptance_criteria=[
        "Given the form is submitted, then the record should be saved",
        "Given the form is submitted, then a confirmation should be shown",
    ])
    with_edge_cases = _story(acceptance_criteria=[
        "Given an invalid input, when submitted, then an error should be shown",
        "Given a duplicate entry, when submitted, then a conflict message should be displayed",
    ])
    assert (
        score_stories(_output(stories=[with_edge_cases])).edge_case_score
        > score_stories(_output(stories=[no_edge_cases])).edge_case_score
    )


# ── score_tasks ──────────────────────────────────────────────────────────

def test_score_tasks_empty_list_returns_all_zero():
    metrics = score_tasks(_output(), all_task_ids=set())
    assert metrics.overall == 0


def test_score_tasks_penalizes_definition_of_done_that_is_a_copy_of_description():
    desc = "Implement the login endpoint and its validation logic end to end."
    copy_paste = _task(description=desc, definition_of_done=desc)
    real_dod = _task(description=desc, definition_of_done="Endpoint returns 200 with a JWT and is covered by tests.")
    copy_score = score_tasks(_output(tasks=[copy_paste]), all_task_ids={"T1"}).clarity_score
    real_score = score_tasks(_output(tasks=[real_dod]), all_task_ids={"T1"}).clarity_score
    assert real_score > copy_score


def test_score_tasks_estimate_scoring_valid_vs_implausible_vs_inverted():
    valid = _task(id="T1", estimate_hours="4-6")
    implausible = _task(id="T2", estimate_hours="5-500")
    inverted = _task(id="T3", estimate_hours="10-4")
    non_numeric = _task(id="T4", estimate_hours="a few days")

    all_ids = {"T1", "T2", "T3", "T4"}
    valid_score = score_tasks(_output(tasks=[valid]), all_ids).estimate_score
    implausible_score = score_tasks(_output(tasks=[implausible]), all_ids).estimate_score
    inverted_score = score_tasks(_output(tasks=[inverted]), all_ids).estimate_score
    non_numeric_score = score_tasks(_output(tasks=[non_numeric]), all_ids).estimate_score

    assert valid_score > implausible_score > inverted_score > non_numeric_score


def test_score_tasks_dependency_scoring_valid_vs_orphaned():
    valid_dep = _task(id="T1", dependencies=["T2"])
    orphaned_dep = _task(id="T3", dependencies=["T999"])
    no_dep = _task(id="T4", dependencies=[])

    all_ids = {"T1", "T2", "T3", "T4"}
    valid_score = score_tasks(_output(tasks=[valid_dep]), all_ids).dependency_score
    orphaned_score = score_tasks(_output(tasks=[orphaned_dep]), all_ids).dependency_score
    no_dep_score = score_tasks(_output(tasks=[no_dep]), all_ids).dependency_score

    assert valid_score > orphaned_score
    assert no_dep_score > orphaned_score  # no dependency beats a broken one


# ── compute_metrics: coverage_score ─────────────────────────────────────

def test_compute_metrics_coverage_requires_two_linked_tasks_and_substantive_acs():
    good_ac = ["Given valid input, when submitted, then the record should be created"]
    well_covered = _story(id="S1", epic_id="E1", confidence="high", acceptance_criteria=good_ac)
    under_covered = _story(id="S2", epic_id="E1", confidence="high", acceptance_criteria=good_ac)

    tasks = [
        _task(id="T1", story_id="S1"),
        _task(id="T2", story_id="S1"),  # S1 has 2 tasks -> covered
        _task(id="T3", story_id="S2"),  # S2 has only 1 task -> not covered
    ]
    output = _output(stories=[well_covered, under_covered], tasks=tasks)
    metrics = compute_metrics(output)
    assert metrics.coverage_score == 50  # 1 of 2 stories well covered


def test_compute_metrics_coverage_zero_when_epic_id_missing():
    story = _story(id="S1", epic_id=None, acceptance_criteria=["Given valid input, when submitted, then it should work"])
    tasks = [_task(id="T1", story_id="S1"), _task(id="T2", story_id="S1")]
    metrics = compute_metrics(_output(stories=[story], tasks=tasks))
    assert metrics.coverage_score == 0


def test_compute_metrics_input_quality_low_when_blocking_gap_present():
    metrics = compute_metrics(_output(gaps=[Gap(description="No auth strategy defined", severity="blocking")]))
    assert metrics.input_quality == "low"


def test_compute_metrics_input_quality_high_with_no_gaps():
    story = _story(acceptance_criteria=["Given valid input, when submitted, then it should work correctly"])
    tasks = [_task(id="T1", story_id="S1"), _task(id="T2", story_id="S1")]
    metrics = compute_metrics(_output(stories=[story], tasks=tasks, gaps=[]))
    assert metrics.input_quality == "high"


# ── run_validation: trust level thresholds ──────────────────────────────

def _metrics(coverage=80, story=80, task=80, gaps=0, quality="high"):
    return OverallMetrics(
        coverage_score=coverage,
        gap_count=gaps,
        input_quality=quality,
        story_metrics=StoryMetrics(specificity_score=story, testability_score=story, sizing_score=story, edge_case_score=story, overall=story),
        task_metrics=TaskMetrics(clarity_score=task, definition_of_done_score=task, estimate_score=task, dependency_score=task, overall=task),
        confidence_summary="test",
    )


def test_run_validation_all_checks_pass_is_trusted():
    result = run_validation(_metrics())
    assert result.trust_level == "trusted"
    assert all(c.passed for c in result.checks)


def test_run_validation_mixed_results_is_review():
    # Coverage and gaps fail, the rest pass -> 3 of 5 pass -> review.
    result = run_validation(_metrics(coverage=40, gaps=10))
    assert result.trust_level == "review"


def test_run_validation_mostly_failing_is_low():
    result = run_validation(_metrics(coverage=10, story=10, task=10, gaps=10, quality="low"))
    assert result.trust_level == "low"
    assert all(not c.passed for c in result.checks)
