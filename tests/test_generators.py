"""Tests for the OOP generator classes in app/services/generators.py —
EpicGenerator/StoryGenerator/TaskGenerator/TestCaseGenerator and the
GenerationPipeline that chains them. This is the refactor target of
main.py's former _generate_*_phase functions and _three_phase_generate;
tests/test_three_phase_generation.py already covers the underlying
generation logic in detail via main._three_phase_generate (which now just
delegates to GenerationPipeline.run_all) — these tests instead confirm the
classes are independently usable and that the pipeline composes them
correctly, which is the actual point of the refactor."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fake_provider import FakeProvider  # noqa: E402
from app.schemas.models import GenerationOutput  # noqa: E402
from app.services.generators import (  # noqa: E402
    EpicGenerator,
    StoryGenerator,
    TaskGenerator,
    TestCaseGenerator,
    GenerationPipeline,
    PhaseGenerator,
)


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


def _parsed_events(events, event_type):
    out = []
    for e in events:
        if not e.startswith("data: "):
            continue
        payload = json.loads(e[len("data: "):])
        if payload.get("type") == event_type:
            out.append(payload)
    return out


# ── Each generator class is independently usable ───────────────────────────

def test_epic_generator_populates_epics_and_streams_them():
    provider = FakeProvider()
    output = _empty_output()
    events = list(EpicGenerator(provider).run("Build a small SaaS product.", output))

    assert len(output.epics) == 2
    epic_events = _parsed_events(events, "epic")
    assert [e["epic"]["id"] for e in epic_events] == [e.id for e in output.epics]


def test_story_generator_requires_epics_already_on_output():
    """StoryGenerator only needs `output.epics` populated — it doesn't care
    how they got there, confirming it's genuinely decoupled from EpicGenerator."""
    provider = FakeProvider()
    output = _empty_output()
    list(EpicGenerator(provider).run("Build a small SaaS product.", output))
    assert len(output.epics) == 2

    list(StoryGenerator(provider).run("Build a small SaaS product.", output))
    assert len(output.stories) == 4  # 2 epics x 2 stories/epic (FakeProvider default)
    epic_ids = {e.id for e in output.epics}
    assert all(s.epic_id in epic_ids for s in output.stories)


def test_task_generator_requires_stories_already_on_output():
    provider = FakeProvider()
    output = _empty_output()
    list(EpicGenerator(provider).run("Build a small SaaS product.", output))
    list(StoryGenerator(provider).run("Build a small SaaS product.", output))

    list(TaskGenerator(provider).run("Build a small SaaS product.", output))
    assert len(output.tasks) == 8  # 4 stories x 2 tasks/story
    story_ids = {s.id for s in output.stories}
    assert all(t.story_id in story_ids for t in output.tasks)


def test_test_case_generator_attaches_to_existing_tasks():
    provider = FakeProvider()
    output = _empty_output()
    list(EpicGenerator(provider).run("Build a small SaaS product.", output))
    list(StoryGenerator(provider).run("Build a small SaaS product.", output))
    list(TaskGenerator(provider).run("Build a small SaaS product.", output))

    list(TestCaseGenerator(provider).run("Build a small SaaS product.", output))
    assert all(len(t.test_cases) == 1 for t in output.tasks)


def test_generators_share_the_common_phase_generator_interface():
    provider = FakeProvider()
    for cls in (EpicGenerator, StoryGenerator, TaskGenerator, TestCaseGenerator):
        instance = cls(provider)
        assert isinstance(instance, PhaseGenerator)
        assert instance.provider is provider
        assert isinstance(instance.name, str) and instance.name


# ── GenerationPipeline chains all four, matching the old _three_phase_generate ──

def test_pipeline_run_all_chains_all_four_phases():
    provider = FakeProvider()
    output = _empty_output()
    pipeline = GenerationPipeline(provider)
    events = list(pipeline.run_all("Build a small SaaS product for managing team tasks.", output))

    assert len(output.epics) == 2
    assert len(output.stories) == 4
    assert len(output.tasks) == 8
    assert all(t.test_cases for t in output.tasks)
    assert not any('"type": "error"' in e for e in events)

    # The pipeline exposes each stage it ran — confirms the "interconnected"
    # composition, not just four independent calls happening to be sequenced.
    assert pipeline.stages == [pipeline.epics, pipeline.stories, pipeline.tasks, pipeline.tests]


def test_pipeline_stops_after_epics_if_epic_phase_fails():
    provider = FakeProvider(epics="[]")
    output = _empty_output()
    events = list(GenerationPipeline(provider).run_all("Build a small SaaS product.", output))

    assert output.epics == []
    assert output.stories == []
    assert output.tasks == []
    assert any('"type": "error"' in e for e in events)
    # Only the epics phase's AI call should have happened — nothing downstream.
    assert len(provider.calls) == 1
