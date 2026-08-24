"""LangGraph orchestration layer for the generation pipeline.

Principle: LangGraph orchestrates, it does not reimplement generation logic.
Every node below is a thin adapter that calls the *existing* PhaseGenerator
subclasses in app/services/generators.py (EpicGenerator, StoryGenerator,
TaskGenerator, TestCaseGenerator) — the actual epic/story/task/test
generation logic is untouched. This module only chains them as a graph
instead of the hand-written epics->stories->tasks->tests sequence in
GenerationPipeline.run_all (app/services/generators.py:501-522), so that
sequence can grow into a real multi-agent graph (repo-context and
code-review nodes land in Phase 3) without rewriting phase logic again.

LangGraphGenerationPipeline is call-shape compatible with GenerationPipeline:
run_all(text, output) -> Iterator[str]. main.py selects between the two via
the GENERATION_ENGINE env flag — nothing downstream of that selection point
(the job runner contract in app/services/jobs.py, the step-by-step endpoints)
changes shape either way.

Streaming trade-off: the legacy pipeline yields SSE events as soon as each
epic/story/task is produced (mid-phase, from inside a ThreadPoolExecutor
callback). Each LangGraph node here fully runs its wrapped PhaseGenerator
before returning, then this module streams once per *node* (i.e. once per
phase) rather than once per item — coarser-grained progress updates, but the
same final GenerationOutput. The parity test (tests/test_langgraph_pipeline_parity.py)
guards the latter; the former is a documented, deliberate trade-off of
wrapping-not-reimplementing.
"""
from __future__ import annotations

import operator
from typing import Annotated, Iterator, TypedDict

from langgraph.graph import END, StateGraph

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas.models import GenerationOutput
from app.services.generators import (
    EpicGenerator,
    StoryGenerator,
    TaskGenerator,
    TestCaseGenerator,
    _parse_json_array,
)
from app.services.related_context import query_related_context
from app.services.langchain_provider import AutoSDLCChatModel
from app.services.prompt import CODE_REVIEW_SYSTEM, build_code_review_message
from app.services.providers import AllProvidersExhaustedError
from app.utils.error_handler import GenerationError, log_error, safe_exc
from app.utils.sse import sse


class _PipelineState(TypedDict):
    text: str
    output: GenerationOutput  # mutated in place by each node; LangGraph keeps the same reference across nodes
    provider: object
    events: Annotated[list[str], operator.add]  # accumulated across nodes via the operator.add reducer


def _run_phase_node(generator_cls):
    """Build a LangGraph node function that runs one PhaseGenerator
    subclass. Nodes return state *updates*, not a stream — the generator's
    yielded SSE strings are collected into `events` here and re-yielded by
    LangGraphGenerationPipeline.run_all as each node completes."""

    def node(state: _PipelineState) -> dict:
        generator = generator_cls(state["provider"])
        events = list(generator.run(state["text"], state["output"]))
        return {"events": events}

    return node


def _has_epics(state: _PipelineState) -> bool:
    """Mirrors GenerationPipeline.run_all's short-circuit: if epic
    generation produced nothing, don't run stories/tasks/tests."""
    return bool(state["output"].epics)


def _graph_context_node(state: _PipelineState) -> dict:
    """The retrieval step that lets generation know what already exists
    elsewhere — across every project, not just this one — before it runs,
    and folds it into the brief text every downstream phase reads. Backed
    by a plain SQL query over the existing epics/generations tables
    (app/services/related_context.py), not a separate graph database: the
    actual requirement is "the LLM knows what's already there," which a
    keyword query already satisfies. A DB error or empty result degrades to
    a no-op (query_related_context is itself fail-open), so this never
    blocks generation."""
    related = query_related_context(state["text"])
    if not related:
        return {}
    lines = ["## Related Work Already In The System (other projects)", ""]
    for row in related:
        project = row.get("project_name") or f"generation {row.get('generation_id')}"
        lines.append(f"- [{project}] {row.get('title', '')} ({row.get('feature_area', '')})")
    context_block = "\n".join(lines)
    return {
        "text": f"{context_block}\n\n{state['text']}",
        "events": [sse("status", {"message": f"Found {len(related)} related item(s) across other projects."})],
    }


# repo_context_node / review_node: activated in Phase 3 (Bitbucket PR review
# agent). Not wired into the graph's edges yet — the graph shape below is
# stable so Phase 3 only needs to add nodes/edges, not restructure this file.


def _build_graph():
    graph = StateGraph(_PipelineState)
    graph.add_node("graph_context", _graph_context_node)
    graph.add_node("epics", _run_phase_node(EpicGenerator))
    graph.add_node("stories", _run_phase_node(StoryGenerator))
    graph.add_node("tasks", _run_phase_node(TaskGenerator))
    graph.add_node("tests", _run_phase_node(TestCaseGenerator))
    graph.set_entry_point("graph_context")
    graph.add_edge("graph_context", "epics")
    graph.add_conditional_edges("epics", _has_epics, {True: "stories", False: END})
    graph.add_edge("stories", "tasks")
    graph.add_edge("tasks", "tests")
    graph.add_edge("tests", END)
    return graph.compile()


def run_code_review(repo_full_name: str, pr_id: int | str, diff: str, provider) -> Iterator[str]:
    """The Phase 3 code-review agent — the one place in this codebase that
    calls a LangChain chat model directly (AutoSDLCChatModel,
    app/services/langchain_provider.py) rather than PhaseGenerator's plain
    provider.generate(). Same Iterator[str] SSE-event convention as every
    PhaseGenerator.run, so it plugs into app/services/jobs.py's runner
    contract identically to generation (see main.py's
    _bitbucket_review_job_runner)."""
    yield sse("status", {"message": f"Reviewing PR #{pr_id} in {repo_full_name}…"})

    model = AutoSDLCChatModel(provider=provider)
    try:
        response = model.invoke([
            SystemMessage(content=CODE_REVIEW_SYSTEM),
            HumanMessage(content=build_code_review_message(diff)),
        ])
        findings = _parse_json_array(str(response.content))
    except AllProvidersExhaustedError as e:
        error = GenerationError(message=str(e), phase="Code Review")
        log_error("CodeReview", "All configured providers exhausted", exception=e)
        yield sse("error", error.to_dict())
        return
    except Exception as e:
        error = GenerationError(message=f"Code review failed: {safe_exc(e)}", phase="Code Review")
        log_error("CodeReview", str(error.message), exception=e)
        yield sse("error", error.to_dict())
        return

    for finding in findings:
        if isinstance(finding, dict):
            yield sse("finding", {"finding": finding})
    yield sse("done", {"pr_id": pr_id, "repo_full_name": repo_full_name, "findings": findings})


class LangGraphGenerationPipeline:
    """LangGraph-orchestrated replacement for GenerationPipeline
    (app/services/generators.py:501-522). Same call shape:
    run_all(text, output) -> Iterator[str]."""

    def __init__(self, provider):
        self.provider = provider
        self._graph = _build_graph()

    def run_all(self, text: str, output: GenerationOutput) -> Iterator[str]:
        state: _PipelineState = {
            "text": text,
            "output": output,
            "provider": self.provider,
            "events": [],
        }
        for update in self._graph.stream(state, stream_mode="updates"):
            for node_update in update.values():
                # A node that returns {} (e.g. graph_context finding nothing)
                # is reported here as None, not {} — LangGraph's own
                # shorthand for "no state changed".
                if node_update:
                    yield from node_update.get("events", [])
