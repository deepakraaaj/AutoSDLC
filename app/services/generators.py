"""OOP generation pipeline: one class per phase (Epics -> Stories -> Tasks ->
Test Cases), chained by GenerationPipeline. Mirrors the AIProvider ABC
pattern (app/services/providers.py:13-20) — a single abstract method
subclasses implement, each holding its own state via __init__.

Extracted from main.py's former _generate_*_phase functions — the logic
itself is unchanged, just reorganized so each phase is a proper object
instead of a free function, and the four objects are explicitly
"interconnected" via GenerationPipeline.run_all, the one place a phase's
output becomes the next phase's input (via the shared, mutated
GenerationOutput)."""
import json
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

from app.core.rule_based_generator import MIN_STORIES_PER_EPIC, MIN_TASKS_PER_STORY
from app.schemas.models import Epic, GenerationOutput, Story, Task, TestCase
from app.services.prompt import (
    EPIC_GENERATION_SYSTEM,
    STORY_GENERATION_SYSTEM,
    TASK_GENERATION_SYSTEM,
    TEST_GENERATION_SYSTEM,
    build_epic_generation_message,
    build_story_generation_message,
    build_task_generation_message,
    build_test_generation_message,
)
from app.services.providers import AllProvidersExhaustedError
from app.utils.error_handler import GenerationError, log_debug, log_error, log_info, log_warning, safe_exc
from app.utils.sse import sse
from app.utils.text_parsing import clean_raw

# How many AI calls run concurrently within a phase (one call per epic in
# Stories/Tasks, one per task batch in Test Cases). These are independent,
# network-bound requests — running them one at a time makes wall-clock time
# scale linearly with backlog depth. Provider instances hold no mutable
# per-call state (app/services/providers.py), so concurrent generate() calls
# on the same instance are safe. Also read by main.py's /estimate-tokens to
# predict the real call count instead of guessing at a different number.
EPIC_CONCURRENCY = int(os.getenv("EPIC_CONCURRENCY", "5"))

# How many tasks go into one Test Case batch call. Providers cap completions
# at ~8000 tokens; a whole epic's tasks in one call comfortably exceeds
# that and gets truncated mid-JSON. Also read by main.py's /estimate-tokens.
TASKS_PER_TEST_BATCH = 5


def _parse_json_array(raw: str) -> list:
    """Parse a JSON array from raw text, handling markdown fences."""
    cleaned = clean_raw(raw)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return []


def _next_id_counters(output: GenerationOutput) -> tuple[int, int, int]:
    """Next ID number for each type (epic, story, task) — 0 on a fresh
    output, or the highest existing E</S</T<n> when resuming a step-by-step
    generation."""
    epic_max = max(
        (int(e.id[1:]) for e in output.epics if e.id.startswith("E") and e.id[1:].isdigit()),
        default=0,
    )
    story_max = max(
        (int(s.id[1:]) for s in output.stories if s.id.startswith("S") and s.id[1:].isdigit()),
        default=0,
    )
    task_max = max(
        (int(t.id[1:]) for t in output.tasks if t.id.startswith("T") and t.id[1:].isdigit()),
        default=0,
    )
    return epic_max, story_max, task_max


class PhaseGenerator(ABC):
    """One stage of the Epics -> Stories -> Tasks -> Test Cases pipeline.
    Mirrors AIProvider (app/services/providers.py:13-20) — one abstract
    method, subclasses hold whatever state they need via __init__."""

    name: str

    def __init__(self, provider):
        self.provider = provider

    @abstractmethod
    def run(self, text: str, output: GenerationOutput) -> Iterator[str]:
        """Mutates `output` in place, yields SSE-framed strings."""
        ...


class EpicGenerator(PhaseGenerator):
    """Phase 1: Epic Generation. Populates output.epics in-place."""

    name = "epics"

    def run(self, text: str, output: GenerationOutput) -> Iterator[str]:
        yield sse("status", {"step": "generating", "message": "Identifying all feature areas and epics…"})
        try:
            raw = self.provider.generate(EPIC_GENERATION_SYSTEM, build_epic_generation_message(text))
            log_debug("Phase1", f"AI response received: {len(raw)} chars")
            epics_data = _parse_json_array(raw)
            if not epics_data:
                error = GenerationError(
                    message="Epic generation returned empty. Check your brief or provider configuration.",
                    phase="Epic Generation",
                    user_action="Add more detail to your brief — include specific features, users, and goals."
                )
                yield sse("error", error.to_dict())
                return

            valid_epics = 0
            for i, e in enumerate(epics_data, start=1):
                if not isinstance(e, dict):
                    log_debug("Phase1", f"Skipping item {i}: not a dict")
                    continue
                title = e.get("title", "").strip()
                description = e.get("description", "").strip()

                if not title or not description:
                    log_debug("Phase1", f"Skipping item {i}: missing title or description")
                    continue

                valid_epics += 1
                output.epics.append(Epic(
                    id=f"E{valid_epics}",
                    title=title,
                    description=description,
                    feature_area=e.get("feature_area", "General").strip(),
                    priority=e.get("priority", "medium"),
                    status="planned",
                ))
                log_debug("Phase1", f"Added epic E{valid_epics}: {title}")
                # Stream the epic to the client as soon as it exists, rather than
                # only the final "N valid epics" count — the UI builds a live
                # backlog view from these instead of a blank progress bar.
                yield sse("epic", {"epic": output.epics[-1].model_dump()})

            if not output.epics:
                error = GenerationError(
                    message="All epics were invalid (missing title/description).",
                    phase="Epic Validation",
                    user_action="Check your brief has valid section headings and descriptions."
                )
                yield sse("error", error.to_dict())
                return

            log_info("Phase1", f"Successfully generated {len(output.epics)} epics")
            yield sse("status", {"step": "generating", "message": f"Found {len(output.epics)} valid epics. Generating stories…"})
        except AllProvidersExhaustedError as e:
            error = GenerationError(
                message=str(e),
                phase="Epic Generation",
                user_action="Wait a few minutes for rate limits to reset, or switch providers in AI Provider settings."
            )
            log_error("Phase1", "All configured providers exhausted", exception=e)
            yield sse("error", error.to_dict())
            return
        except Exception as e:
            error = GenerationError(
                message=f"Epic generation failed: {safe_exc(e)}",
                phase="Epic Generation"
            )
            log_error("Phase1", str(error.message), exception=e)
            yield sse("error", error.to_dict())
            return


class StoryGenerator(PhaseGenerator):
    """Phase 2: Story Generation per Epic (concurrent across epics).
    Populates output.stories in-place. Story IDs continue from whatever's
    already in `output` — 0 on a fresh generation, or the highest existing
    S<n> when resuming a step-by-step generation."""

    name = "stories"

    def run(self, text: str, output: GenerationOutput) -> Iterator[str]:
        _, story_counter, _ = _next_id_counters(output)
        epics_done = 0
        exhaustion_warned = False
        yield sse("status", {"step": "generating", "message": f"Generating stories for {len(output.epics)} epics…"})
        with ThreadPoolExecutor(max_workers=EPIC_CONCURRENCY) as executor:
            futures = {executor.submit(self._fetch_for_epic, text, epic): epic for epic in output.epics}
            for future in as_completed(futures):
                epic = futures[future]
                stories_data, error = future.result()
                epics_done += 1

                if error:
                    if isinstance(error, AllProvidersExhaustedError):
                        # The circuit breaker in LiteLLMProvider means every other
                        # concurrent epic is about to hit this exact same error —
                        # say it once clearly instead of repeating it per epic.
                        if not exhaustion_warned:
                            exhaustion_warned = True
                            yield sse("status", {"message": f"⚠️ {error}"})
                        log_warning("Phase2", f"Story generation for epic {epic.id} skipped — providers exhausted")
                    else:
                        yield sse("status", {"message": f"Story generation for {epic.title} failed after retry, continuing… ({epics_done}/{len(output.epics)} epics)"})
                    continue
                if not stories_data:
                    yield sse("status", {"message": f"Story generation for {epic.title} returned empty after retry, skipping… ({epics_done}/{len(output.epics)} epics)"})
                    continue

                for s in stories_data:
                    if not isinstance(s, dict):
                        continue
                    story_counter += 1
                    output.stories.append(Story(
                        id=f"S{story_counter}",
                        title=s.get("title", ""),
                        as_a=s.get("as_a", ""),
                        i_want=s.get("i_want", ""),
                        so_that=s.get("so_that", ""),
                        acceptance_criteria=s.get("acceptance_criteria", []),
                        feature_area=epic.feature_area,
                        size=s.get("size", "medium"),
                        confidence="high",
                        epic_id=epic.id,
                        priority=s.get("priority", epic.priority),
                        status="planned",
                    ))
                    yield sse("story", {"story": output.stories[-1].model_dump()})
                log_info("Phase2", f"Added {len(stories_data)} stories for epic {epic.id}")
                yield sse("status", {"step": "generating", "message": f"Stories ready for {epic.title} ({epics_done}/{len(output.epics)} epics)…"})

        yield sse("status", {"step": "generating", "message": f"Generated {len(output.stories)} stories."})

    def _fetch_for_epic(self, text: str, epic: Epic) -> tuple[list, Exception | None]:
        """Runs in a thread pool. Does the AI call and JSON parsing only;
        never touches `output` or yields SSE (that stays on the generator
        thread once results come back via as_completed)."""
        last_error = None
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_story_generation_message(text, epic.title, epic.description, MIN_STORIES_PER_EPIC)
                log_debug("Phase2", f"Generating stories for epic {epic.id} (attempt {attempt+1})")
                raw = self.provider.generate(STORY_GENERATION_SYSTEM.format(n=MIN_STORIES_PER_EPIC), prompt_msg)
                log_debug("Phase2", f"AI response received for {epic.title}")
                stories_data = _parse_json_array(raw)
                if stories_data:
                    return stories_data, None
                log_debug("Phase2", f"Empty stories list for epic {epic.id} - will retry" if attempt == 0 else f"Empty stories after retry for epic {epic.id}")
            except Exception as e:
                log_error("Phase2", f"Failed to generate stories for epic {epic.id}", exception=e)
                last_error = e
        return [], last_error


class TaskGenerator(PhaseGenerator):
    """Phase 3: Task Generation per Epic (batching stories, concurrent
    across epics). Populates output.tasks in-place. Task IDs continue from
    whatever's already in `output`, same as story IDs above."""

    name = "tasks"

    def run(self, text: str, output: GenerationOutput) -> Iterator[str]:
        _, _, task_counter = _next_id_counters(output)
        epics_with_stories = []
        for epic in output.epics:
            epic_stories = [s for s in output.stories if s.epic_id == epic.id]
            if not epic_stories:
                log_debug("Phase3", f"No stories for epic {epic.id}, skipping tasks")
                continue
            epics_with_stories.append((epic, epic_stories))

        if epics_with_stories:
            epics_done = 0
            exhaustion_warned = False
            yield sse("status", {"step": "generating", "message": f"Generating tasks for {len(epics_with_stories)} epics…"})
            with ThreadPoolExecutor(max_workers=EPIC_CONCURRENCY) as executor:
                futures = {
                    executor.submit(self._fetch_for_epic, text, epic, epic_stories): (epic, epic_stories)
                    for epic, epic_stories in epics_with_stories
                }
                for future in as_completed(futures):
                    epic, epic_stories = futures[future]
                    tasks_data, error = future.result()
                    epics_done += 1

                    if error:
                        if isinstance(error, AllProvidersExhaustedError):
                            if not exhaustion_warned:
                                exhaustion_warned = True
                                yield sse("status", {"message": f"⚠️ {error}"})
                            log_warning("Phase3", f"Task generation for epic {epic.id} skipped — providers exhausted")
                        else:
                            yield sse("status", {"message": f"Task generation for {epic.title} failed after retry, continuing… ({epics_done}/{len(epics_with_stories)} epics)"})
                        continue
                    if not tasks_data:
                        log_warning("Phase3", f"No tasks generated for epic {epic.id} after retry")
                        yield sse("warning", {"message": f"⚠️ Task generation for {epic.title} returned empty after retry, skipping…"})
                        continue

                    valid_story_ids = {s.id for s in epic_stories}
                    added_count = 0
                    rejected_count = 0
                    for t in tasks_data:
                        if not isinstance(t, dict):
                            continue
                        sid = t.get("story_id")
                        if sid not in valid_story_ids:
                            log_debug("Phase3", f"Task rejected: invalid story_id '{sid}' (valid: {valid_story_ids})")
                            rejected_count += 1
                            continue
                        task_counter += 1
                        added_count += 1
                        output.tasks.append(Task(
                            id=f"T{task_counter}",
                            title=t.get("title", ""),
                            description=t.get("description", ""),
                            definition_of_done=t.get("definition_of_done", ""),
                            estimate_hours=t.get("estimate_hours", ""),
                            dependencies=t.get("dependencies", []),
                            story_id=sid,
                            confidence="high",
                            priority=t.get("priority", epic.priority),
                            status="todo",
                            assignee=None,
                        ))
                        yield sse("task", {"task": output.tasks[-1].model_dump()})

                    if rejected_count > 0 and added_count == 0:
                        log_warning("Phase3", f"All {rejected_count} tasks rejected due to invalid story_ids for epic {epic.id}")
                        yield sse("warning", {"message": f"⚠️ All tasks for {epic.title} were rejected (invalid story references). AI model may need better prompting."})
                    elif added_count > 0:
                        log_info("Phase3", f"Added {added_count} tasks for epic {epic.id}" + (f" ({rejected_count} rejected)" if rejected_count > 0 else ""))
                        yield sse("status", {"step": "generating", "message": f"Tasks ready for {epic.title} ({epics_done}/{len(epics_with_stories)} epics)…"})

    def _fetch_for_epic(self, text: str, epic: Epic, epic_stories: list) -> tuple[list, Exception | None]:
        """Runs in a thread pool — same shape as StoryGenerator._fetch_for_epic."""
        last_error = None
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_task_generation_message(text, epic_stories, MIN_TASKS_PER_STORY)
                log_debug("Phase3", f"Generating tasks for epic {epic.id} (attempt {attempt+1})")
                raw = self.provider.generate(TASK_GENERATION_SYSTEM.format(n=MIN_TASKS_PER_STORY), prompt_msg)
                log_debug("Phase3", f"AI response received for {epic.title}")
                tasks_data = _parse_json_array(raw)
                if tasks_data:
                    return tasks_data, None
                log_warning("Phase3", f"Empty tasks list for epic {epic.id} - will retry" if attempt == 0 else f"Empty tasks after retry for epic {epic.id}")
            except Exception as e:
                log_error("Phase3", f"Failed to generate tasks for epic {epic.id}", exception=e)
                last_error = e
        return [], last_error


class TestCaseGenerator(PhaseGenerator):
    """Phase 4: Test Case Generation, batched and concurrent across ALL
    epics. Attaches test cases onto output.tasks in-place.

    Providers cap completions at ~8000 tokens (app/services/providers.py). A
    full epic (~20 tasks × 2-3 detailed manual tests each) comfortably
    exceeds that, so the response gets truncated mid-JSON and every parse
    fails — silently zeroing out test generation. Splitting into small task
    batches keeps each response well under the cap; every epic's batches are
    flattened into one queue so the whole backlog's tests generate under a
    single concurrency limit instead of epic-by-epic."""

    name = "tests"

    def run(self, text: str, output: GenerationOutput) -> Iterator[str]:
        if not output.tasks:
            return

        work_items = []  # (epic, batch) pairs across all epics
        for epic in output.epics:
            epic_tasks = [t for t in output.tasks if t.story_id and any(s.id == t.story_id and s.epic_id == epic.id for s in output.stories)]
            if not epic_tasks:
                continue
            batches = [epic_tasks[i:i + TASKS_PER_TEST_BATCH] for i in range(0, len(epic_tasks), TASKS_PER_TEST_BATCH)]
            work_items.extend((epic, batch) for batch in batches)

        yield sse("status", {"step": "generating", "message": f"Generating test cases for {len(output.tasks)} tasks ({len(work_items)} batches)…"})

        total_tests_added = 0
        tests_added_by_epic: dict[str, int] = {}
        batches_done = 0
        exhaustion_warned = False

        with ThreadPoolExecutor(max_workers=EPIC_CONCURRENCY) as executor:
            futures = {
                executor.submit(self._fetch_batch, text, epic.id, batch): (epic, batch)
                for epic, batch in work_items
            }
            for future in as_completed(futures):
                epic, batch = futures[future]
                test_cases_by_task_id, error = future.result()
                batches_done += 1

                if error or not test_cases_by_task_id:
                    if isinstance(error, AllProvidersExhaustedError):
                        if not exhaustion_warned:
                            exhaustion_warned = True
                            yield sse("status", {"message": f"⚠️ {error}"})
                        log_warning("Phase4", f"Test generation for epic {epic.id} batch skipped — providers exhausted")
                    elif error:
                        log_warning("Phase4", f"Skipping test generation for epic {epic.id} batch after retry failure")
                    else:
                        log_warning("Phase4", f"Skipping test generation for epic {epic.id} batch due to invalid response")
                    continue

                batch_tests_added = 0
                for task in batch:
                    if task.id in test_cases_by_task_id:
                        test_count = 0
                        for idx, tc in enumerate(test_cases_by_task_id[task.id], start=1):
                            if not isinstance(tc, dict):
                                continue
                            try:
                                steps = tc.get("steps", [])
                                if isinstance(steps, str):
                                    steps = [steps] if steps.strip() else []
                                elif isinstance(steps, list):
                                    steps = [str(s) for s in steps if str(s).strip()]
                                else:
                                    steps = []
                                task.test_cases.append(TestCase(
                                    id=f"{task.id}-T{idx}",
                                    title=tc.get("title", ""),
                                    test_type=tc.get("test_type", "functional"),
                                    description=tc.get("description", ""),
                                    preconditions=tc.get("preconditions", "None"),
                                    steps=steps,
                                    expected_result=tc.get("expected_result", ""),
                                ))
                                test_count += 1
                                batch_tests_added += 1
                                total_tests_added += 1
                            except Exception as e:
                                log_debug("Phase4", f"Failed to add test case for task {task.id}: {str(e)[:50]}")
                        if test_count > 0:
                            log_debug("Phase4", f"Added {test_count} test cases to task {task.id}")
                            # Re-send the task now that it has test cases —
                            # the client already has this task from Phase 3
                            # and merges by id rather than re-appending.
                            yield sse("task", {"task": task.model_dump()})

                if batch_tests_added > 0:
                    tests_added_by_epic[epic.id] = tests_added_by_epic.get(epic.id, 0) + batch_tests_added

                # One status line per batch would flood the client (dozens of
                # batches per generation) — report every 5th completion instead.
                if batches_done % 5 == 0 or batches_done == len(work_items):
                    yield sse("status", {"step": "generating", "message": f"Generated tests for {batches_done}/{len(work_items)} batches…"})

        for epic_id, count in tests_added_by_epic.items():
            log_info("Phase4", f"Added {count} test cases for epic {epic_id}")
        for epic in output.epics:
            if epic.id not in tests_added_by_epic and any(t.story_id and any(s.id == t.story_id and s.epic_id == epic.id for s in output.stories) for t in output.tasks):
                log_warning("Phase4", f"No test cases added for epic {epic.id}")

        if total_tests_added > 0:
            log_info("Phase4", f"Successfully added {total_tests_added} test cases across all tasks")
            yield sse("status", {"step": "generating", "message": f"Generated {total_tests_added} test cases. Processing complete…"})
        else:
            log_warning("Phase4", "No test cases were generated, but generation completed")
            yield sse("status", {"message": "⚠️ Test case generation did not produce results, but continuing…"})

    def _fetch_batch(self, text: str, epic_id: str, batch: list) -> tuple[dict, Exception | None]:
        """Runs in a thread pool — generates test cases for one small batch
        of tasks (see TASKS_PER_TEST_BATCH) and returns task_id -> test_cases."""
        last_error = None
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_test_generation_message(text, batch, tests_per_task=3)
                log_debug("Phase4", f"Generating test cases for epic {epic_id} batch of {len(batch)} tasks (attempt {attempt+1})")
                raw = self.provider.generate(TEST_GENERATION_SYSTEM, prompt_msg)
                log_debug("Phase4", f"AI response received: {len(raw)} chars")

                try:
                    test_data = json.loads(clean_raw(raw))
                except json.JSONDecodeError:
                    test_data = {}
                    log_debug("Phase4", f"Failed to parse test generation response for epic {epic_id} batch")

                if isinstance(test_data, dict) and "tasks" in test_data:
                    test_cases_by_task_id = {}
                    for task_entry in test_data.get("tasks", []):
                        if not isinstance(task_entry, dict):
                            continue
                        task_id = task_entry.get("task_id", "")
                        if task_id:
                            test_cases_by_task_id[task_id] = task_entry.get("test_cases", [])
                    return test_cases_by_task_id, None
                log_debug("Phase4", f"Invalid test data for epic {epic_id} batch - will retry" if attempt == 0 else f"Invalid test data after retry for epic {epic_id} batch")
            except Exception as e:
                log_error("Phase4", f"Failed to generate test cases for epic {epic_id} batch", exception=e)
                last_error = e
        return {}, last_error


# Prevent pytest from treating this imported production class as a test container.
TestCaseGenerator.__test__ = False


class GenerationPipeline:
    """Chains all four phases — the concrete 'interconnected' piece: each
    stage mutates the same GenerationOutput, so its output is literally the
    next stage's input. Used by the one-click flow (run_all); each stage is
    also independently constructible for the step-by-step endpoints, which
    call e.g. EpicGenerator(provider).run(...) directly instead."""

    def __init__(self, provider):
        self.provider = provider
        self.epics = EpicGenerator(provider)
        self.stories = StoryGenerator(provider)
        self.tasks = TaskGenerator(provider)
        self.tests = TestCaseGenerator(provider)
        self.stages: list[PhaseGenerator] = [self.epics, self.stories, self.tasks, self.tests]

    def run_all(self, text: str, output: GenerationOutput) -> Iterator[str]:
        yield from self.epics.run(text, output)
        if not output.epics:
            return
        yield from self.stories.run(text, output)
        yield from self.tasks.run(text, output)
        yield from self.tests.run(text, output)
