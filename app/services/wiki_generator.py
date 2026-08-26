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
    CHAPTER_WIKI_SYSTEM,
    WIKI_PROJECT_SYSTEM,
    WIKI_REPO_SYSTEM,
    build_chapter_wiki_message,
    build_project_wiki_message,
    build_repo_wiki_message,
)
from app.utils.text_parsing import clean_raw


class WikiGenerationError(Exception):
    """The model responded, but not with the JSON shape a wiki page needs.
    Distinct from AllProvidersExhaustedError (no provider could even be
    reached) so the endpoint can log/report the two cases with an accurate
    message rather than a generic 'something went wrong'."""


# Extension-agnostic on purpose: build_repo_context_block() (bitbucket/client.py)
# and intelligence_prompt() (repo_intelligence.py) pull in files of any type —
# .cs, .go, .php, .sql, .vue, whatever the repo actually has — and the wiki
# prompt asks the model to cite any of them as `path:line`. An earlier
# version of this regex whitelisted a handful of extensions (py/java/js/...);
# citations into anything outside that list were real, correctly-formatted
# citations that still failed validation. The extension only has to start
# with a letter (rules out matching a bare "1.2:3" version/ratio string as a
# citation) and the colon must be followed by digits (the line number) —
# narrow enough to avoid stray false positives, broad enough to match a
# citation into any real source file.
SOURCE_CITATION = re.compile(r"(?:[\w .-]+/)*[\w .-]+\.[A-Za-z][\w-]{0,9}:\d+", re.IGNORECASE)
# Matches vendor/bundled PATH CONTEXT (a node_modules/vendor directory, or a
# minified/bundle filename) rather than bare library-name keywords. The
# previous version (`bootstrap|jquery|...|datatables|...`) matched those
# names as a case-insensitive substring ANYWHERE in the citation — which
# also matches a first-party folder that merely shares letters with one,
# e.g. this app's own `src/components/dataTables/` (a component folder for
# rendering data tables, plural noun phrase) collided with the vendor
# "datatables" (the jQuery DataTables plugin) on nothing but case-folding.
# That false-positive was silently discarding every section whose evidence
# happened to live under dataTables/ — a large fraction of this repo's real
# business capabilities (asset tables, user tables, compliance report
# tables) — which is what actually caused most of the "why is my wiki page
# so thin" reports, not a real vendor citation.
VENDOR_CITATION = re.compile(
    r"(?:^|/)(?:node_modules|vendor|third[-_]?party)/"
    r"|\.min\.(?:js|css|map)(?::|$)"
    r"|(?:^|/)(?:jquery|bootstrap|font-?awesome)[\w.\-]*\.(?:js|css)(?::|$)",
    re.IGNORECASE,
)
ACRONYM_EXPANSION = re.compile(r"\b([A-Z]{2,6})\s*\(([^)]+)\)")


def _normalize_citation(raw: str) -> str | None:
    """Extract the leading path:line citation from a raw evidence string,
    tolerant of trailing annotation the model sometimes appends — observed
    live: mistral-small-latest copying a symbol name along with the citation
    straight from the source artifact's own `name (kind) — path:line` bullet
    format, e.g. "Facility.tsx:36:FacilityProps" instead of "Facility.tsx:36".
    That's not a fabricated or wrong citation, just an over-eager one — a
    fullmatch requirement rejected genuinely-grounded sections over it.
    Returns None when nothing resembling a citation is present at all (e.g.
    a bare route/endpoint string), which is still a real violation."""
    match = SOURCE_CITATION.search(str(raw).strip().strip("`"))
    return match.group(0) if match else None


def _grounding_violations(page: dict, source_material: str) -> list[str]:
    # Brief-only projects and extremely thin repositories may not contain any
    # deterministic path:line evidence. Do not demand citations the model was
    # never given; the stricter gate applies whenever repository intelligence
    # actually supplied citations.
    if not SOURCE_CITATION.search(source_material):
        return []
    violations = []
    for item in page.get("sections", []):
        label = f"section '{item['heading']}'"
        body = item.get("body", "")
        # Citations live in the section's own "evidence" array, never in
        # "body" — asking the model to both write business-only prose AND
        # weave a specific `Evidence: path:line.` sentence into that same
        # prose was two conflicting instructions in one field, and in
        # practice (mistral-small-latest, this app's default provider) the
        # model reliably dropped the citation rather than reconcile them,
        # substituting a route/endpoint mention instead — which reads as
        # sourced but isn't a checkable path:line. A separate field removes
        # the conflict: "evidence" is pure citation, "body" is pure prose.
        # Normalized the same way _parse_wiki_response does: a route/endpoint
        # string with no path:line shape at all drops out entirely (still
        # "no citation" below), while a citation with harmless trailing
        # annotation (a symbol name copied alongside it) is kept, cleaned.
        raw_evidence = item.get("evidence") or []
        evidence = [e for e in (_normalize_citation(r) for r in raw_evidence) if e]
        if body.strip() and not evidence:
            violations.append(f"{label} has no source-file citation")
        if any(VENDOR_CITATION.search(e) for e in evidence):
            violations.append(f"{label} relies on a third-party bundle citation")
        for match in ACRONYM_EXPANSION.finditer(body):
            if match.group(0).lower() not in source_material.lower():
                violations.append(f"{label} invents the expansion '{match.group(0)}'")
    return violations


def _repair_invalid_json(model, system_prompt: str, user_prompt: str, raw: str, error: Exception) -> dict:
    """One repair attempt for a response that failed to parse as the
    required wiki JSON shape (invalid JSON syntax — a stray unescaped quote
    or literal newline inside a string value is the common case with
    smaller models — or valid JSON missing a required field). Mirrors the
    one-repair-attempt pattern _invoke_grounded already uses for citation
    grounding, just for structural validity instead. Lets a second failure
    propagate as before — this is one extra chance, not an unbounded loop."""
    repair = (
        f"{user_prompt}\n\nYour previous response could not be parsed as JSON: {error}\n\n"
        "Return ONLY valid JSON in the required shape, no markdown fences, no commentary. "
        "Escape every double quote, newline, and backslash inside string values correctly. "
        "Previous response:\n" + raw[:12000]
    )
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=repair)])
    return _parse_wiki_response(str(response.content))


def _invoke_and_parse(model, system_prompt: str, user_prompt: str, *, is_followup: bool = False) -> dict:
    """`is_followup` is True once the caller has already supplied
    clarification_answers — the user message says as much (see
    build_project_wiki_message/build_repo_wiki_message), but that's a soft
    instruction competing with the system prompt's own "you may return
    needs_clarification" branch, and in practice a small model doesn't
    reliably honor it: the same repository can trigger a fresh round of
    questions on every single follow-up call, trapping the UI in what looks
    like an infinite loop with no code-level guarantee it ever ends. When
    is_followup is True and the model asks again anyway, force one more call
    with a blunt, unambiguous instruction to write the page now instead of
    silently accepting an endless negotiation."""
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    raw = str(response.content)
    try:
        page = _parse_wiki_response(raw)
    except WikiGenerationError as e:
        return _repair_invalid_json(model, system_prompt, user_prompt, raw, e)
    if is_followup and page.get("needs_clarification"):
        forced = (
            f"{user_prompt}\n\nYou returned another clarification request, but the user has already "
            "answered your previous questions — see the clarifications above. Do not ask again under "
            "any circumstances. Pick the most reasonable interpretation for anything still ambiguous "
            "and return the wiki page JSON now."
        )
        response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=forced)])
        raw = str(response.content)
        try:
            page = _parse_wiki_response(raw)
        except WikiGenerationError as e:
            return _repair_invalid_json(model, system_prompt, user_prompt, raw, e)
    return page


def _grounded_sections(page: dict, source_material: str) -> list[dict]:
    """Sections whose own "evidence" array is real (non-empty, well-formed
    path:line strings, no vendor bundle, no invented acronym expansion) —
    the last-resort filter after a repair attempt still leaves some
    violations: keep what's individually grounded rather than discard the
    whole page over one bad section among several good ones."""
    kept = []
    for section in page.get("sections", []):
        body = section.get("body", "")
        evidence = [e for e in (_normalize_citation(r) for r in (section.get("evidence") or [])) if e]
        no_vendor = not any(VENDOR_CITATION.search(e) for e in evidence)
        expansions_supported = all(
            match.group(0).lower() in source_material.lower()
            for match in ACRONYM_EXPANSION.finditer(body)
        )
        if evidence and no_vendor and expansions_supported:
            kept.append({**section, "evidence": evidence})
    return kept


def _invoke_grounded(model, system_prompt: str, user_prompt: str, *, is_followup: bool = False) -> dict:
    page = _invoke_and_parse(model, system_prompt, user_prompt, is_followup=is_followup)
    if page.get("needs_clarification"):
        return page
    violations = _grounding_violations(page, user_prompt)
    if violations:
        raw = json.dumps(page)
        repair = (
            f"{user_prompt}\n\nYour previous JSON was rejected for grounding violations:\n- "
            + "\n- ".join(violations)
            + "\n\nRewrite it as valid JSON. Every section with a non-empty \"body\" must have a non-empty "
              "\"evidence\" array containing at least one real first-party path:line citation copied "
              "verbatim from the repository intelligence facts above — never put a route, endpoint, or "
              "citation inside \"body\" itself, and never leave \"evidence\" empty for a section that makes "
              "a claim. Remove unsupported claims and acronym expansions; never cite bundled third-party "
              "files. Previous JSON:\n" + raw[:12000]
        )
        response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=repair)])
        raw = str(response.content)
        try:
            page = _parse_wiki_response(raw)
        except WikiGenerationError as e:
            page = _repair_invalid_json(model, system_prompt, user_prompt, raw, e)
        remaining = _grounding_violations(page, user_prompt)
        if remaining:
            grounded_sections = _grounded_sections(page, user_prompt)
            if not grounded_sections:
                raise WikiGenerationError("Wiki grounding validation failed: " + "; ".join(remaining))
            page["sections"] = grounded_sections
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
    return {
        "title": str(data["title"]).strip() or "Untitled",
        "summary": str(data["summary"]).strip(),
        "sections": _parse_sections(data["sections"]),
    }


def _parse_sections(items: list) -> list[dict]:
    """{"heading","body","evidence"} dicts out of a raw JSON list — shared
    by the flat page parser above and _parse_chapter_response below, since
    Pass 1 chapter generation (wiki_chapters.py's tree, narrated by
    CHAPTER_WIKI_SYSTEM) reuses this exact section shape."""
    sections = []
    for item in items:
        if isinstance(item, dict) and "heading" in item and "body" in item:
            evidence = item.get("evidence")
            # Normalize each entry to its clean path:line citation (dropping
            # trailing annotation) here, once, so every downstream consumer
            # (grounding validation, the fallback filter, the stored page)
            # sees the same clean strings rather than re-deriving them.
            # An entry with no citation shape at all (a route string, an
            # empty value) is dropped outright — that's correctly still "no
            # evidence" for grounding purposes, not silently kept.
            normalized = [_normalize_citation(e) for e in evidence] if isinstance(evidence, list) else []
            sections.append({
                "heading": str(item["heading"]), "body": str(item["body"]),
                "evidence": [e for e in normalized if e],
            })
    return sections


def _parse_chapter_response(raw: str) -> dict:
    """Pass 1's response shape: either a leaf {"title","summary","sections"}
    or a parent {"title","summary","sub_chapters":[{"title","summary","sections"}]}
    — see CHAPTER_WIKI_SYSTEM. Distinct from _parse_wiki_response because a
    chapter response never has a needs_clarification branch (clarification
    happens once at chapter-set build time in phase 2, not per chapter)."""
    try:
        data = json.loads(clean_raw(raw))
    except json.JSONDecodeError as e:
        raise WikiGenerationError(f"Model response was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise WikiGenerationError("Model response was not a JSON object.")
    missing = [k for k in ("title", "summary") if k not in data]
    if missing:
        raise WikiGenerationError(f"Model response is missing required field(s): {', '.join(missing)}.")
    title = str(data["title"]).strip() or "Untitled"
    summary = str(data["summary"]).strip()
    if "sub_chapters" in data:
        if not isinstance(data["sub_chapters"], list):
            raise WikiGenerationError("Model response's 'sub_chapters' field was not a list.")
        sub_chapters = []
        for item in data["sub_chapters"]:
            if not isinstance(item, dict) or "title" not in item:
                raise WikiGenerationError("Model response's 'sub_chapters' entries must each have a 'title'.")
            sub_chapters.append({
                "title": str(item["title"]).strip() or "Untitled",
                "summary": str(item.get("summary") or "").strip(),
                "sections": _parse_sections(item.get("sections") or []),
            })
        return {"title": title, "summary": summary, "sub_chapters": sub_chapters}
    if not isinstance(data.get("sections"), list):
        raise WikiGenerationError("Model response is missing a 'sections' or 'sub_chapters' list.")
    return {"title": title, "summary": summary, "sections": _parse_sections(data["sections"])}


def _chapter_sections(parsed: dict) -> list[dict]:
    """Every section dict across a chapter response, whether it's a leaf or
    has sub_chapters — lets _grounding_violations validate a chapter
    response the same way it validates a flat page (it only ever looks at
    page.get("sections", []))."""
    if "sub_chapters" in parsed:
        sections = []
        for sub in parsed["sub_chapters"]:
            sections.extend(sub.get("sections", []))
        return sections
    return parsed.get("sections", [])


def _filter_grounded_chapter(parsed: dict, source_material: str) -> dict:
    """_grounded_sections' last-resort partial-keep, adapted to preserve
    whichever nested shape (leaf vs sub_chapters) the response used —
    filters the sections within each sub-chapter individually rather than
    flattening the structure away."""
    if "sub_chapters" in parsed:
        filtered = []
        for sub in parsed["sub_chapters"]:
            grounded = _grounded_sections({"sections": sub.get("sections", [])}, source_material)
            if grounded:
                filtered.append({**sub, "sections": grounded})
        return {**parsed, "sub_chapters": filtered}
    return {**parsed, "sections": _grounded_sections({"sections": parsed.get("sections", [])}, source_material)}


def generate_chapter_wiki(provider, project_name: str, repo_label: str, chapter_context: str, sub_chapter_count: int) -> dict:
    """Pass 1: one LLM call narrating one top-level chapter (and, in the
    same call, all of its sub-chapters — see CHAPTER_WIKI_SYSTEM/
    build_chapter_wiki_message for why they're batched). Reuses the exact
    same grounding-validation machinery as the flat wiki (_grounding_violations/
    _grounded_sections via _chapter_sections' adapter) — every chapter's
    claims are held to the identical anti-hallucination bar as a flat page's.
    No clarification round here: clarification is a project-level concern
    handled once at chapter-set build time (deferred to phase 2), not
    per-chapter."""
    model = AutoSDLCChatModel(provider=provider)
    message = build_chapter_wiki_message(project_name, repo_label, chapter_context, sub_chapter_count)
    response = model.invoke([SystemMessage(content=CHAPTER_WIKI_SYSTEM), HumanMessage(content=message)])
    raw = str(response.content)
    try:
        parsed = _parse_chapter_response(raw)
    except WikiGenerationError as e:
        repair = (
            f"{message}\n\nYour previous response could not be parsed: {e}\n\n"
            "Return ONLY valid JSON in the required shape, no markdown fences, no commentary. "
            "Previous response:\n" + raw[:12000]
        )
        response = model.invoke([SystemMessage(content=CHAPTER_WIKI_SYSTEM), HumanMessage(content=repair)])
        parsed = _parse_chapter_response(str(response.content))

    violations = _grounding_violations({"sections": _chapter_sections(parsed)}, message)
    if violations:
        raw2 = json.dumps(parsed)
        repair = (
            f"{message}\n\nYour previous JSON was rejected for grounding violations:\n- "
            + "\n- ".join(violations)
            + "\n\nRewrite it as valid JSON in the same shape. Every section with a non-empty \"body\" must "
              "have a non-empty \"evidence\" array containing at least one real first-party path:line "
              "citation copied verbatim from the repository intelligence facts above — never put a route, "
              "endpoint, or citation inside \"body\" itself. Previous JSON:\n" + raw2[:12000]
        )
        response = model.invoke([SystemMessage(content=CHAPTER_WIKI_SYSTEM), HumanMessage(content=repair)])
        try:
            parsed = _parse_chapter_response(str(response.content))
        except WikiGenerationError:
            pass  # fall through to filtering the pre-repair parse below
        remaining = _grounding_violations({"sections": _chapter_sections(parsed)}, message)
        if remaining:
            filtered = _filter_grounded_chapter(parsed, message)
            if not _chapter_sections(filtered):
                raise WikiGenerationError("Chapter grounding validation failed: " + "; ".join(remaining))
            parsed = filtered
    return parsed


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
    page = _invoke_grounded(model, WIKI_PROJECT_SYSTEM, message, is_followup=bool(clarification_answers))
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
    page = _invoke_grounded(model, WIKI_REPO_SYSTEM, message, is_followup=bool(clarification_answers))
    if page.get("needs_clarification"):
        return page
    page["title"] = repo_label
    if page["summary"].startswith("Repository-backed technical overview for "):
        page["summary"] = f"Repository-backed technical overview for {repo_label}. See the cited sections for verified details."
    return page
