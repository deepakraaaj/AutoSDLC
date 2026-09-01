"""LangGraph orchestration for the PR code-review agent.

This is a *separate* graph from app/services/langgraph_pipeline.py's backlog
generation StateGraph, not a node added to it. The two are triggered by
different events with unrelated inputs — generation runs on a project brief
(text/output/provider), this runs on a Bitbucket PR webhook or manual trigger
(repo_full_name/pr_id/diff/provider/related_context) — so sharing one state
schema would mean padding _PipelineState with fields the generation graph
never uses, or vice versa. Same StateGraph/node/conditional-edge vocabulary,
its own small state.

Sequence: review -> (verify, skipped if there are no findings to check) ->
filter -> done. This mirrors run_code_review's previous plain-Python body in
app/services/langgraph_pipeline.py exactly — same two LLM calls, same
skip-verification-when-empty short circuit, same deterministic filter step —
expressed as graph nodes instead of a linear function so a future step
(another pass, a conditional branch on severity, etc.) is one node/edge, not
a restructure.

Parsing: CodeReviewResult (below) replaces the previous hand-rolled
json.loads + manual key-checking (_parse_code_review_response) with a
Pydantic schema validated via PydanticOutputParser — this works with
AutoSDLCChatModel's plain text-completion interface as-is (no bind_tools /
function-calling required, which the wrapped AIProvider.generate() can't do
across every configured provider), so no changes to app/services/langchain_provider.py.
Malformed output still degrades to ("", []) exactly as before — a review is
never worth crashing over — but a well-formed response is now schema-checked
instead of trusted blind.
"""
from __future__ import annotations

from typing import Annotated, Iterator, Optional

import operator
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from app.services.langchain_provider import AutoSDLCChatModel
from app.services.prompt import (
    CODE_REVIEW_SYSTEM,
    CODE_REVIEW_VERIFY_SYSTEM,
    build_code_review_message,
    build_code_review_verification_message,
)
from app.services.providers import AllProvidersExhaustedError
from app.services.review_filters import filter_code_review_findings
from app.utils.error_handler import GenerationError, log_error, safe_exc
from app.utils.sse import sse
from app.utils.text_parsing import clean_raw


class CodeReviewFinding(BaseModel):
    file: str
    line: Optional[int] = None
    severity: str = "minor"
    comment: str = ""
    verification: str = "risk"
    evidence: str = ""


class CodeReviewResult(BaseModel):
    """The {"summary": str, "findings": [...]} shape both CODE_REVIEW_SYSTEM
    and CODE_REVIEW_VERIFY_SYSTEM are prompted to return — one schema for
    both calls since the verify prompt is instructed to echo the same
    shape back (app/services/prompt.py's CODE_REVIEW_VERIFY_SYSTEM:
    "Return only the same JSON object shape as the draft review")."""
    summary: str = ""
    findings: list[CodeReviewFinding] = Field(default_factory=list)


_result_parser = PydanticOutputParser(pydantic_object=CodeReviewResult)


def _parse_code_review_response(raw: str) -> tuple[str, list[dict]]:
    """Validates raw LLM output against CodeReviewResult. Same fallback
    contract as the hand-rolled parser it replaces: a bare findings array
    (the pre-summary-field legacy shape) still yields usable findings with
    an empty summary; anything unparsable or failing validation yields
    ("", []) rather than raising — a review is never worth crashing the
    request over."""
    cleaned = clean_raw(raw)
    try:
        result = _result_parser.parse(cleaned)
        return result.summary, [f.model_dump() for f in result.findings]
    except (ValidationError, Exception):
        pass
    try:
        import json
        data = json.loads(cleaned)
    except Exception:
        return "", []
    if isinstance(data, list):
        return "", [f for f in data if isinstance(f, dict)]
    return "", []


class _CodeReviewState(TypedDict):
    repo_full_name: str
    pr_id: object
    diff: str
    provider: object
    related_context: str
    review_input: str
    summary: str
    findings: list[dict]
    integrity_checked: bool
    filtered_findings: list[dict]
    error: Optional[dict]
    events: Annotated[list[str], operator.add]


def _review_node(state: _CodeReviewState) -> dict:
    model = AutoSDLCChatModel(provider=state["provider"])
    review_input = build_code_review_message(state["diff"], state["related_context"])
    try:
        response = model.invoke([
            SystemMessage(content=CODE_REVIEW_SYSTEM),
            HumanMessage(content=review_input),
        ])
        summary, findings = _parse_code_review_response(str(response.content))
        return {"review_input": review_input, "summary": summary, "findings": findings}
    except AllProvidersExhaustedError as e:
        log_error("CodeReview", "All configured providers exhausted", exception=e)
        return {"error": GenerationError(message=str(e), phase="Code Review").to_dict()}
    except Exception as e:
        log_error("CodeReview", f"Code review failed: {safe_exc(e)}", exception=e)
        return {"error": GenerationError(message=f"Code review failed: {safe_exc(e)}", phase="Code Review").to_dict()}


def _has_findings_to_verify(state: _CodeReviewState) -> bool:
    """Same short-circuit as the original `if integrity_checked:` branch —
    only spend a second LLM call verifying findings that actually exist."""
    return bool(state.get("error") is None and state["findings"])


def _verify_node(state: _CodeReviewState) -> dict:
    model = AutoSDLCChatModel(provider=state["provider"])
    try:
        response = model.invoke([
            SystemMessage(content=CODE_REVIEW_VERIFY_SYSTEM),
            HumanMessage(content=build_code_review_verification_message(
                state["review_input"], {"summary": state["summary"], "findings": state["findings"]},
            )),
        ])
        verified_summary, verified_findings = _parse_code_review_response(str(response.content))
        return {
            "summary": verified_summary or state["summary"],
            "findings": verified_findings,
            "integrity_checked": True,
        }
    except Exception as e:
        # Verification failing is not a reason to discard an otherwise-good
        # draft review — keep the unverified findings rather than erroring
        # the whole request, same as review_node's own errors do NOT apply
        # here (this is a best-effort second pass, not the primary result).
        log_error("CodeReview", f"Verification pass failed, keeping draft findings: {safe_exc(e)}", exception=e)
        return {"integrity_checked": False}


def _filter_node(state: _CodeReviewState) -> dict:
    if state.get("error") is not None:
        return {}
    kept, removed = filter_code_review_findings(state["findings"], state["review_input"])
    return {"filtered_findings": [{**f} for f in removed], "findings": kept}


def _route_after_review(state: _CodeReviewState) -> str:
    if state.get("error") is not None:
        return "end"
    return "verify" if _has_findings_to_verify(state) else "filter"


def _build_graph():
    graph = StateGraph(_CodeReviewState)
    graph.add_node("review", _review_node)
    graph.add_node("verify", _verify_node)
    graph.add_node("filter", _filter_node)
    graph.set_entry_point("review")
    graph.add_conditional_edges("review", _route_after_review, {"verify": "verify", "filter": "filter", "end": END})
    graph.add_edge("verify", "filter")
    graph.add_edge("filter", END)
    return graph.compile()


_GRAPH = _build_graph()


def _diff_touched_files(diff: str) -> list[str]:
    from app.services.langgraph_pipeline import _diff_touched_files as _impl
    return _impl(diff)


def _code_review_context_factors(review_input: str, related_context: str, integrity_checked: bool, filtered_count: int) -> list[str]:
    """Short UI-facing facts about the context/fact-checking used for this
    review. These are not prompts; they are persisted with the job result so
    the PR card can show what the reviewer actually considered."""
    import re
    factors = ["diff changed files"]
    related_count = related_context.count("## Related repository:")
    if related_count:
        factors.append(f"{related_count} related service {'repository' if related_count == 1 else 'repositories'}")
    if re.search(r"\b(?:date|time|datetime|timestamp|calendar|picker|moment|dayjs|luxon)\b", review_input, re.I):
        factors.append("temporal UI/date-handling context")
    if "matched in related-service evidence" in review_input:
        factors.append("related-service contract evidence")
    if integrity_checked:
        factors.append("second-pass finding verification")
    if filtered_count:
        factors.append(f"{filtered_count} unsupported model {'claim' if filtered_count == 1 else 'claims'} suppressed")
    return factors


def run_code_review(
    repo_full_name: str, pr_id, diff: str, provider, related_context: str = ""
) -> Iterator[str]:
    """Same signature, same Iterator[str] SSE-event contract, same event
    order as before — main.py's _stream_bitbucket_review call site does not
    change. The review/verify/filter sequence now runs as a compiled
    LangGraph graph (_GRAPH) instead of inline try/except code."""
    yield sse("status", {"message": f"Reviewing PR #{pr_id} in {repo_full_name}…"})

    initial_state: _CodeReviewState = {
        "repo_full_name": repo_full_name,
        "pr_id": pr_id,
        "diff": diff,
        "provider": provider,
        "related_context": related_context,
        "review_input": "",
        "summary": "",
        "findings": [],
        "integrity_checked": False,
        "filtered_findings": [],
        "error": None,
        "events": [],
    }
    final_state = _GRAPH.invoke(initial_state)

    if final_state.get("error") is not None:
        yield sse("error", final_state["error"])
        return

    findings = final_state["findings"]
    for finding in findings:
        yield sse("finding", {"finding": finding})
    yield sse("done", {
        "pr_id": pr_id, "repo_full_name": repo_full_name, "findings": findings,
        "summary": final_state["summary"],
        "files_reviewed": _diff_touched_files(diff),
        "integrity_check": "second_pass" if final_state["integrity_checked"] else "no_findings_to_verify",
        "related_repositories_checked": related_context.count("## Related repository:"),
        "filtered_findings_count": len(final_state["filtered_findings"]),
        "context_factors": _code_review_context_factors(
            final_state["review_input"], related_context, final_state["integrity_checked"], len(final_state["filtered_findings"]),
        ),
    })
