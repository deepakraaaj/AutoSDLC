"""AI-generated project/repo wiki pages.

Mirrors run_code_review() in app/services/langgraph_pipeline.py — the one
existing precedent for a standalone LLM call outside the 4-phase
epics->stories->tasks->tests pipeline. Unlike that one (and unlike every
PhaseGenerator), this isn't a streaming SSE call: it's a single blocking
request/response, called synchronously from a plain POST endpoint
(app/api/projects.py), the same shape as repairTaskDependencies /
improveGenerationQuality — one request, one response, no job/streaming
infrastructure needed.
"""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.langchain_provider import AutoSDLCChatModel
from app.services.prompt import (
    WIKI_PROJECT_SYSTEM,
    WIKI_REPO_SYSTEM,
    build_project_wiki_message,
    build_repo_wiki_message,
)
from app.utils.text_parsing import clean_raw


class WikiGenerationError(Exception):
    """The model responded, but not with the JSON shape a wiki page needs.
    Distinct from AllProvidersExhaustedError (no provider could even be
    reached) so the endpoint can log/report the two cases with an accurate
    message rather than a generic 'something went wrong'."""


def _parse_wiki_response(raw: str) -> dict:
    try:
        data = json.loads(clean_raw(raw))
    except json.JSONDecodeError as e:
        raise WikiGenerationError(f"Model response was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise WikiGenerationError("Model response was not a JSON object.")
    missing = [k for k in ("title", "summary", "sections") if k not in data]
    if missing:
        raise WikiGenerationError(f"Model response is missing required field(s): {', '.join(missing)}.")
    if not isinstance(data["sections"], list):
        raise WikiGenerationError("Model response's 'sections' field was not a list.")
    sections = []
    for item in data["sections"]:
        if isinstance(item, dict) and "heading" in item and "body" in item:
            sections.append({"heading": str(item["heading"]), "body": str(item["body"])})
    return {
        "title": str(data["title"]).strip() or "Untitled",
        "summary": str(data["summary"]).strip(),
        "sections": sections,
    }


def generate_project_wiki(
    provider,
    project_name: str,
    description: str,
    brief_text: str | None,
    repo_materials: list[dict] | None = None,
) -> dict:
    """Grounded in the project's description plus the most recent
    generation's input_text (the original brief), and — when the project has
    linked repos — each repo's actual file listing/README (see
    app/api/projects.py's generate_project_wiki_endpoint, which gathers
    `repo_materials` the same way generate_repo_wiki does per-repo)."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([
        SystemMessage(content=WIKI_PROJECT_SYSTEM),
        HumanMessage(content=build_project_wiki_message(project_name, description, brief_text, repo_materials)),
    ])
    return _parse_wiki_response(str(response.content))


def generate_repo_wiki(provider, project_name: str, repo_label: str, context_block: str, readme_text: str | None) -> dict:
    """Grounded in build_repo_context_block()'s file listing plus a
    best-effort README fetch — both degrade gracefully to a thinner prompt
    (see build_repo_wiki_message) rather than failing outright when Bitbucket
    isn't configured or the repo can't be reached."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([
        SystemMessage(content=WIKI_REPO_SYSTEM),
        HumanMessage(content=build_repo_wiki_message(project_name, repo_label, context_block, readme_text)),
    ])
    return _parse_wiki_response(str(response.content))
