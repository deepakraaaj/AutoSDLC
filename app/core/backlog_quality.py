"""Backlog post-processing helpers that improve generated hierarchy quality."""

from __future__ import annotations

from collections import defaultdict

from app.schemas.models import GenerationOutput
from app.services.metrics import score_single_story, score_single_task, QUALITY_PASS_THRESHOLD

# Below this, an individual dimension is flagged as a weak point worth a targeted fix.
# Deliberately the *same* number run_validation gates the trust level on
# (QUALITY_PASS_THRESHOLD), re-exported here rather than a separate local constant —
# a lower private cutoff used to let items sitting between the two thresholds (e.g.
# scoring 61% against a 70% pass bar but a 60% "weak" bar) escape ever being flagged,
# so they'd drag the aggregate down indefinitely with no way to target them.
WEAK_ITEM_THRESHOLD = QUALITY_PASS_THRESHOLD

_STORY_DIMENSION_LABELS = {
    "specificity": (
        "The actor/intent/rationale (as_a/i_want/so_that) is too generic or thin — name a specific "
        "actor (not just \"user\"), state a concrete intent in 8+ words, and explain the business "
        "value in so_that in 6+ words."
    ),
    "testability": (
        "Acceptance criteria are too few or not substantive — provide at least 3 independently "
        "verifiable, concrete acceptance criteria (6+ words each, naming an observable outcome)."
    ),
    "sizing": (
        "The size label (small/medium/large) doesn't match the acceptance-criteria count and "
        "description length — correct it, or split the story down if it's genuinely large."
    ),
    "edge_case": (
        "Acceptance criteria barely cover failure or edge conditions — add at least one criterion "
        "for an invalid input, validation failure, or boundary/error case."
    ),
}

_TASK_DIMENSION_LABELS = {
    "clarity": (
        "The description is too short or nearly identical to the title/definition of done — rewrite "
        "it with a precise, specific implementation description (15+ words) distinct from the "
        "definition of done."
    ),
    "definition_of_done": (
        "The definition of done is vague, generic, or duplicates the description — rewrite it with "
        "concrete, verifiable completion criteria (e.g. tests passing, reviewed, deployed)."
    ),
    "estimate": (
        "The estimate isn't a plausible numeric hour range — provide a realistic 'X-Y' hour estimate "
        "(e.g. '4-6') with 0 <= X < Y <= 80 and a spread of 40 hours or less."
    ),
}


def find_weak_items(
    output: GenerationOutput, max_items: int | None = 8, threshold: int = WEAK_ITEM_THRESHOLD
) -> list[dict]:
    """Find the specific stories/tasks dragging the Scorecard's quality scores down,
    worst first — using the exact same per-dimension rubric the Scorecard displays
    (score_single_story/score_single_task), rather than a separate heuristic.

    Task dependency scoring is deliberately excluded: that's already fixed
    deterministically by normalize_task_dependencies (the "repair dependencies"
    action), so it needs no AI call here.

    `threshold` is exposed rather than baked in so a caller can tighten or loosen it
    (e.g. a stricter re-check after a fix pass) — it defaults to WEAK_ITEM_THRESHOLD,
    the same bar run_validation gates the trust level on, so nothing sits in a dead
    zone between "counts as weak" and "counts as passing".

    Returns at most `max_items` items (worst worst-dimension score first); pass
    max_items=None to return every weak item uncapped — the UI diagnosis step
    (GET /weak-items) shows the whole set, grouped, so the user picks which ones to
    fix rather than trusting an arbitrary top-N cutoff. Each item carries enough to
    both explain the diagnosis to a user (weak_dimensions: name/score/reason per weak
    dimension, worst first) and drive one targeted _generate_content_change call
    (change_description, the same reasons joined into one instruction).
    """
    all_task_ids = {t.id for t in output.tasks}
    candidates: list[dict] = []

    for s in output.stories:
        scores = score_single_story(s)
        weak_dims = {dim: score for dim, score in scores.items() if score < threshold}
        if not weak_dims:
            continue
        weak_dimensions = [
            {"name": dim, "score": score, "reason": _STORY_DIMENSION_LABELS[dim]}
            for dim, score in sorted(weak_dims.items(), key=lambda kv: kv[1])
        ]
        candidates.append({
            "kind": "story",
            "id": s.id,
            "title": s.title,
            "weak_dimensions": weak_dimensions,
            "worst_score": min(weak_dims.values()),
            "change_description": (
                "Fix these specific quality issues without changing what the story is about: "
                + " ".join(d["reason"] for d in weak_dimensions)
            ),
        })

    for t in output.tasks:
        scores = score_single_task(t, all_task_ids)
        scores.pop("dependency", None)
        weak_dims = {dim: score for dim, score in scores.items() if score < threshold}
        if not weak_dims:
            continue
        weak_dimensions = [
            {"name": dim, "score": score, "reason": _TASK_DIMENSION_LABELS[dim]}
            for dim, score in sorted(weak_dims.items(), key=lambda kv: kv[1])
        ]
        candidates.append({
            "kind": "task",
            "id": t.id,
            "title": t.title,
            "weak_dimensions": weak_dimensions,
            "worst_score": min(weak_dims.values()),
            "change_description": (
                "Fix these specific quality issues without changing what the task is about: "
                + " ".join(d["reason"] for d in weak_dimensions)
            ),
        })

    candidates.sort(key=lambda c: c["worst_score"])
    return candidates if max_items is None else candidates[:max_items]


def normalize_task_dependencies(output: GenerationOutput) -> None:
    """Rewrite task dependencies into valid task IDs within each story.

    Many generation paths produce human-readable dependency text or leave
    dependencies implicit. The quality rubric expects concrete task IDs, so we
    normalize each story's tasks into a simple ordered chain:
    - first task has no dependencies
    - every later task depends on the immediately previous task in the same story
    """
    tasks_by_story: dict[str, list] = defaultdict(list)
    for task in output.tasks:
        if task.story_id:
            tasks_by_story[task.story_id].append(task)

    for story_tasks in tasks_by_story.values():
        previous_task_id: str | None = None
        for index, task in enumerate(story_tasks):
            if index == 0:
                task.dependencies = []
            else:
                task.dependencies = [previous_task_id] if previous_task_id else []
            previous_task_id = task.id
