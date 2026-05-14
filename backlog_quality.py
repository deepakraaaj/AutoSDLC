"""Backlog post-processing helpers that improve generated hierarchy quality."""

from __future__ import annotations

from collections import defaultdict

from schemas import GenerationOutput


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
