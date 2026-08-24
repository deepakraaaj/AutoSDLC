"""Regression guard for the LangGraph wrapper (app/services/langgraph_pipeline.py):
running the same brief through GenerationPipeline (legacy) and
LangGraphGenerationPipeline must produce an identical GenerationOutput, since
the LangGraph nodes call the exact same PhaseGenerator classes under the
hood — see that module's docstring for the streaming-granularity trade-off
this test does NOT cover (final output only, not per-event timing)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_provider import FakeProvider  # noqa: E402
from app.schemas.models import GenerationOutput  # noqa: E402
from app.services.generators import GenerationPipeline  # noqa: E402
from app.services.langgraph_pipeline import LangGraphGenerationPipeline  # noqa: E402

BRIEF = "Build a project management tool with user accounts and billing."


def _fresh_output() -> GenerationOutput:
    return GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[], stories=[], tasks=[], gaps=[],
    )


def test_langgraph_pipeline_matches_legacy_pipeline_output():
    legacy_output = _fresh_output()
    list(GenerationPipeline(FakeProvider()).run_all(BRIEF, legacy_output))

    langgraph_output = _fresh_output()
    events = list(LangGraphGenerationPipeline(FakeProvider()).run_all(BRIEF, langgraph_output))

    assert events, "LangGraph pipeline should still yield SSE-framed progress events"
    assert [e.model_dump() for e in legacy_output.epics] == [e.model_dump() for e in langgraph_output.epics]
    assert [s.model_dump() for s in legacy_output.stories] == [s.model_dump() for s in langgraph_output.stories]
    assert [t.model_dump() for t in legacy_output.tasks] == [t.model_dump() for t in langgraph_output.tasks]


def test_langgraph_pipeline_short_circuits_on_empty_epics():
    """Mirrors GenerationPipeline.run_all's `if not output.epics: return`."""
    output = _fresh_output()
    provider = FakeProvider(epics="[]")
    list(LangGraphGenerationPipeline(provider).run_all(BRIEF, output))
    assert output.epics == []
    assert output.stories == []
    assert output.tasks == []
