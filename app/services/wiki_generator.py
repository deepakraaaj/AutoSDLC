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
import re

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


SOURCE_CITATION = re.compile(r"(?:[\w .-]+/)*[\w .-]+\.(?:py|java|js|jsx|ts|tsx|json|ya?ml|md|html):\d+", re.IGNORECASE)
VENDOR_CITATION = re.compile(r"(?:bootstrap|jquery|markerclusterer|datatables|datepicker|font-?awesome|\.min\.)", re.IGNORECASE)
ACRONYM_EXPANSION = re.compile(r"\b([A-Z]{2,6})\s*\(([^)]+)\)")


def _grounding_violations(page: dict, source_material: str) -> list[str]:
    # Brief-only projects and extremely thin repositories may not contain any
    # deterministic path:line evidence. Do not demand citations the model was
    # never given; the stricter gate applies whenever repository intelligence
    # actually supplied citations.
    if not SOURCE_CITATION.search(source_material):
        return []
    violations = []
    paragraphs = [(f"section '{item['heading']}'", item.get("body", "")) for item in page.get("sections", [])]
    for label, text in paragraphs:
        citations = SOURCE_CITATION.findall(text)
        if text.strip() and not citations:
            violations.append(f"{label} has no source-file citation")
        if any(VENDOR_CITATION.search(citation) for citation in citations):
            violations.append(f"{label} relies on a third-party bundle citation")
        for match in ACRONYM_EXPANSION.finditer(text):
            if match.group(0).lower() not in source_material.lower():
                violations.append(f"{label} invents the expansion '{match.group(0)}'")
    return violations


def _invoke_grounded(model, system_prompt: str, user_prompt: str) -> dict:
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    raw = str(response.content)
    page = _parse_wiki_response(raw)
    violations = _grounding_violations(page, user_prompt)
    if violations:
        repair = (
            f"{user_prompt}\n\nYour previous JSON was rejected for grounding violations:\n- "
            + "\n- ".join(violations)
            + "\n\nRewrite it as valid JSON. Every summary and section body must contain at least one real "
              "first-party source-file path:line citation from the supplied evidence. Remove unsupported "
              "claims and acronym expansions; never cite bundled third-party files. Previous JSON:\n"
            + raw[:12000]
        )
        response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=repair)])
        page = _parse_wiki_response(str(response.content))
        remaining = _grounding_violations(page, user_prompt)
        if remaining:
            grounded_sections = []
            for section in page.get("sections", []):
                body = section.get("body", "")
                citations = SOURCE_CITATION.findall(body)
                expansions_supported = all(
                    match.group(0).lower() in user_prompt.lower()
                    for match in ACRONYM_EXPANSION.finditer(body)
                )
                if citations and not any(VENDOR_CITATION.search(item) for item in citations) and expansions_supported:
                    grounded_sections.append(section)
            if not grounded_sections:
                raise WikiGenerationError("Wiki grounding validation failed: " + "; ".join(remaining))
            page["sections"] = grounded_sections
        if not SOURCE_CITATION.search(page.get("summary", "")):
            page["summary"] = f"Repository-backed technical overview for {page.get('title') or 'this project'}. See the cited sections for verified details."
    return page


def _parse_wiki_response(raw: str) -> dict:
    try:
        data = json.loads(clean_raw(raw))
    except json.JSONDecodeError as e:
        raise WikiGenerationError(f"Model response was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise WikiGenerationError("Model response was not a JSON object.")
    if data.get("needs_clarification") is True:
        questions = []
        for item in data.get("clarifying_questions", [])[:4]:
            if isinstance(item, dict) and item.get("question"):
                questions.append({
                    "id": str(item.get("id") or f"question_{len(questions) + 1}"),
                    "question": str(item["question"]),
                    "why": str(item.get("why") or "This changes the business meaning of the wiki."),
                })
        if questions:
            return {"needs_clarification": True, "clarifying_questions": questions}
        raise WikiGenerationError("The model requested clarification without asking a question.")
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
    clarification_answers: dict[str, str] | None = None,
) -> dict:
    """Grounded in the project's description plus the most recent
    generation's input_text (the original brief), and — when the project has
    linked repos — each repo's actual file listing/README (see
    app/api/projects.py's generate_project_wiki_endpoint, which gathers
    `repo_materials` the same way generate_repo_wiki does per-repo)."""
    model = AutoSDLCChatModel(provider=provider)
    message = build_project_wiki_message(project_name, description, brief_text, repo_materials, clarification_answers)
    page = _invoke_grounded(model, WIKI_PROJECT_SYSTEM, message)
    if page.get("needs_clarification"):
        return page
    page["title"] = project_name
    if page["summary"].startswith("Repository-backed technical overview for "):
        page["summary"] = f"Repository-backed technical overview for {project_name}. See the cited sections for verified details."
    return page


def generate_repo_wiki(provider, project_name: str, repo_label: str, context_block: str, readme_text: str | None, clarification_answers: dict[str, str] | None = None) -> dict:
    """Grounded in build_repo_context_block()'s file listing plus a
    best-effort README fetch — both degrade gracefully to a thinner prompt
    (see build_repo_wiki_message) rather than failing outright when Bitbucket
    isn't configured or the repo can't be reached."""
    model = AutoSDLCChatModel(provider=provider)
    message = build_repo_wiki_message(project_name, repo_label, context_block, readme_text, clarification_answers)
    page = _invoke_grounded(model, WIKI_REPO_SYSTEM, message)
    if page.get("needs_clarification"):
        return page
    page["title"] = repo_label
    if page["summary"].startswith("Repository-backed technical overview for "):
        page["summary"] = f"Repository-backed technical overview for {repo_label}. See the cited sections for verified details."
    return page
