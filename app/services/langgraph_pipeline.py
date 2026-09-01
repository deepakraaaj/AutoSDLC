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

import json
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
from app.services.prompt import (
    PR_SECURITY_REVIEW_SYSTEM,
    SECURITY_REVIEW_SYSTEM,
    build_pr_security_review_message,
    build_security_review_message,
)
from app.services.providers import AllProvidersExhaustedError
from app.utils.error_handler import GenerationError, log_error, safe_exc
from app.utils.sse import sse
from app.utils.text_parsing import clean_raw


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


# The Bitbucket PR code-review agent (Phase 3) turned out to need its own
# graph rather than a node here: it's triggered by a PR webhook with inputs
# (repo_full_name/pr_id/diff) that don't fit _PipelineState, which this
# module's generation graph is scoped to. See
# app/services/code_review_graph.py's module docstring for that graph and
# why it's separate.


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


def _diff_touched_files(diff: str) -> list[str]:
    """File paths touched by a unified diff, in order, deduped. Read from
    `+++ b/...` lines (the "new" side of each file's hunk) — present for
    additions and modifications; a pure deletion has `+++ /dev/null`
    instead, so those fall back to the paired `--- a/...` line. Purely for
    surfacing "what did the review actually look at" in the UI — never fed
    back into the model, so a best-effort parse that misses an edge case
    (renames, binary files) costs a UI list being incomplete, not a wrong
    review."""
    files: list[str] = []
    seen: set[str] = set()
    pending_old: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            pending_old = line[len("--- a/"):].strip()
        elif line.startswith("+++ "):
            path = line[len("+++ "):].strip()
            if path.startswith("b/"):
                path = path[2:]
            elif path == "/dev/null" and pending_old:
                path = pending_old
            else:
                continue
            if path and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def run_security_review(repo_id: int, repo_label: str, context_block: str, provider) -> Iterator[str]:
    """VAPT Phase 1 — an LLM security pass over a repo's current contents.
    Same shape as run_code_review (app/services/code_review_graph.py — SSE-event
    convention, job runner adapter in main.py) but scans repo_context_block's
    file listing rather than a PR diff, and reports findings once at the end
    rather than posting them anywhere — this is a project-wide posture
    check, not a PR gate."""
    yield sse("status", {"message": f"Scanning {repo_label} for security issues…"})

    model = AutoSDLCChatModel(provider=provider)
    try:
        response = model.invoke([
            SystemMessage(content=SECURITY_REVIEW_SYSTEM),
            HumanMessage(content=build_security_review_message(repo_label, context_block)),
        ])
        findings = _parse_json_array(str(response.content))
    except AllProvidersExhaustedError as e:
        error = GenerationError(message=str(e), phase="Security Scan")
        log_error("SecurityScan", "All configured providers exhausted", exception=e)
        yield sse("error", error.to_dict())
        return
    except Exception as e:
        error = GenerationError(message=f"Security scan failed: {safe_exc(e)}", phase="Security Scan")
        log_error("SecurityScan", str(error.message), exception=e)
        yield sse("error", error.to_dict())
        return

    for finding in findings:
        if isinstance(finding, dict):
            yield sse("finding", {"finding": finding})
    yield sse("done", {"repo_id": repo_id, "repo_label": repo_label, "findings": findings})


def _parse_pr_security_response(raw: str) -> tuple[str, list[dict]]:
    """Parse PR_SECURITY_REVIEW_SYSTEM's {"summary": str, "findings": [...]}
    shape into (summary, normalized_findings). Normalizes each finding into
    the same finding-dict fields vapt.py's deterministic scanners use
    (file, comment, recommendation, evidence, severity) plus the PR-specific
    fields (symbol, related_files/symbols, execution path) — so downstream
    (persistence, correlation-merge, the UI) doesn't need two finding
    shapes. Enforces PHASE 21's evidence requirement server-side rather
    than trusting the model's self-reported confidence: a finding with no
    concrete `reason_for_pr_relevance` is capped at "low" confidence no
    matter what the model claimed.

    Tolerant of a model that ignores the object shape and returns a bare
    findings array (same fallback app/services/code_review_graph.py's
    _parse_code_review_response uses for the equivalent code-review
    contract) — that yields usable findings with an empty summary rather
    than nothing at all."""
    try:
        data = json.loads(clean_raw(raw))
    except json.JSONDecodeError:
        data = []
    summary = ""
    if isinstance(data, dict):
        summary = str(data.get("summary") or "").strip()
        items = data.get("findings")
        items = items if isinstance(items, list) else []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    findings = []
    for item in items:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason_for_pr_relevance") or "").strip()
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "medium"
        confidence = str(item.get("confidence") or "low").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        if not reason:
            confidence = "low"
        findings.append({
            "source": "llm_pr_review",
            "tool": "llm_pr_review",
            "title": str(item.get("title") or "Security finding"),
            "severity": severity,
            "confidence": confidence,
            "evidence_class": item.get("evidence_class") if item.get("evidence_class") in {"verified_bug", "contract_risk", "needs_manual_confirmation"} else "needs_manual_confirmation",
            "file": item.get("changed_file") or None,
            "symbol": item.get("changed_symbol") or None,
            "related_files": item.get("related_files") if isinstance(item.get("related_files"), list) else [],
            "related_symbols": item.get("related_symbols") if isinstance(item.get("related_symbols"), list) else [],
            "execution_or_security_path": item.get("execution_or_security_path") or None,
            "comment": reason or "No PR-relevance reason provided by the model.",
            "evidence": str(item.get("execution_or_security_path") or ""),
            "security_impact": str(item.get("security_impact") or ""),
            "recommendation": str(item.get("recommendation") or ""),
        })
    return summary, findings


def run_pr_security_review(pr_context: str, provider) -> Iterator[str]:
    """PR Impact Security Analysis's LLM pass — a separate prompt from
    run_security_review's full-repository one (see PR_SECURITY_REVIEW_SYSTEM's
    docstring in prompt.py for why). `pr_context` is pre-assembled,
    pre-budgeted text (security/pr_llm_context.py) — this function does no
    context assembly of its own, matching run_security_review's contract of
    taking an already-built context_block."""
    yield sse("status", {"message": "Running PR security impact review…"})

    model = AutoSDLCChatModel(provider=provider)
    try:
        response = model.invoke([
            SystemMessage(content=PR_SECURITY_REVIEW_SYSTEM),
            HumanMessage(content=build_pr_security_review_message(pr_context)),
        ])
        summary, findings = _parse_pr_security_response(str(response.content))
    except AllProvidersExhaustedError as e:
        error = GenerationError(message=str(e), phase="PR Security Review")
        log_error("PRSecurityReview", "All configured providers exhausted", exception=e)
        yield sse("error", error.to_dict())
        return
    except Exception as e:
        error = GenerationError(message=f"PR security review failed: {safe_exc(e)}", phase="PR Security Review")
        log_error("PRSecurityReview", str(error.message), exception=e)
        yield sse("error", error.to_dict())
        return

    for finding in findings:
        yield sse("finding", {"finding": finding})
    yield sse("done", {"summary": summary, "findings": findings})


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
