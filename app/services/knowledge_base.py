"""Project knowledge base — user-authored facts (glossary/rule/decision/
constraint) a project owner supplies to ground AI generation in domain
knowledge the repo/brief can't express on its own: business rules, naming
decisions, "X is deprecated, use Y instead", clarifications that would
otherwise force the model to guess.

Two consumers:
  - Backlog generation (main.py's _with_project_instructions) prepends
    format_knowledge_context() the same bounded-injection way custom_instructions
    is prepended today.
  - Wiki generation (app/services/wiki_generator.py, app/services/prompt.py)
    includes it as additional grounding material alongside repo intelligence
    facts, and accepts "[KB-<id>]" as a valid citation in a section's
    "evidence" array — see KNOWLEDGE_CITATION below, checked wherever
    wiki_generator.py currently only recognized a path:line SOURCE_CITATION.

Two ways entries get populated:
  - parse_knowledge_markdown() below, which splits an uploaded .md/.docx
    template (already extracted to plain text by app/services/brief_upload.py
    — same file the brief-upload flow accepts) into candidate entries by
    heading, and flags ones that look too thin to actually ground anything.
    Deliberately NOT an LLM call: the whole point of a knowledge base is to
    stop the model from guessing, so this extraction step stays fully
    deterministic — nothing here can itself hallucinate a fact into
    existence.
  - extract_knowledge_from_repo() below, for when there IS no up-to-date
    document to upload — an enterprise codebase's real domain knowledge often
    lives only in the code and in a legacy engineer's head. One grounded LLM
    call per linked repo, citation-checked the same way wiki_generator.py's
    pages are (a claim needs a real path:line, never a route/vendor-bundle
    citation), so it CAN produce prose ("what this validation rule actually
    means") but can't silently invent a fact with no code behind it — an
    unclear case gets flagged with needs_info=True instead of guessed at.

Both produce the same KnowledgeCandidate shape (entry_type/title/body/
needs_info/reason) so the frontend has one staged-review screen regardless of
where a candidate came from — nothing is saved to the database by either
path; saving is a separate, explicit step (app/api/projects.py's
/knowledge/extract and /knowledge/extract-from-repo endpoints).
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

ENTRY_TYPE_LABELS = {
    "glossary": "Glossary",
    "rule": "Business rule",
    "decision": "Decision",
    "constraint": "Constraint",
}

# The citable handle for a knowledge entry, mirroring path:line's role as
# wiki_generator.py's other recognized evidence shape. Deliberately requires
# the literal "KB-" prefix (not just a bare number) so it can't collide with
# an incidental "[3]"-style footnote a model might otherwise emit.
KNOWLEDGE_CITATION = re.compile(r"\[KB-(\d+)\]")


def format_knowledge_context(entries: list[dict]) -> str:
    """Renders KB entries as a numbered, typed block whose citation handle
    (`[KB-<id>]`) a model can copy verbatim into a section's "evidence"
    array. Empty entries list -> empty string (no-op, same graceful-omission
    contract as build_repo_context_block when a repo has nothing to offer)."""
    if not entries:
        return ""
    lines = [
        f"[KB-{e['id']}] ({ENTRY_TYPE_LABELS.get(e['entry_type'], e['entry_type'])}) "
        f"{e['title']}: {e['body']}"
        for e in entries
    ]
    return "## Project Knowledge Base\n\n" + "\n".join(lines)


# ── Extraction from an uploaded template ────────────────────────────────

HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)

# Heading-text keywords that pick the entry_type — checked in this order, so
# a heading like "Business Rule: Refund Window" matches "rule" before falling
# through to the glossary default. Deliberately keyword-based, not the LLM
# doing the classification — same "extraction can't hallucinate" reasoning
# as the module docstring.
TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("decision", "decision"),
    ("constraint", "constraint"),
    ("rule", "rule"),
    ("glossary", "glossary"),
    ("term", "glossary"),
    ("definition", "glossary"),
]

# A section this short (after stripping markdown noise) doesn't actually say
# anything a generation could ground itself in — same spirit as
# wiki_generator.py refusing to accept an empty "evidence" array: a heading
# with nothing under it is a gap, not a fact.
MIN_BODY_WORDS = 6

PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b|\?{2,}|<[^>]*(fill|todo|tbd)[^>]*>", re.IGNORECASE)

# A trailing "Source: path/to/file.ext" line (prompts/GENERATE_KNOWLEDGE_BASE_
# FROM_REPO.md's citation shape — same idea as wiki_generator.py keeping
# citations in a separate "evidence" field instead of inline in prose).
# Stripped out of the displayed body into its own `source` field so a
# reviewer sees a clean sentence, with the citation available separately
# rather than trailing the paragraph.
SOURCE_LINE_RE = re.compile(r"(?:^|\n)\s*Source:\s*(.+?)\s*$", re.IGNORECASE)

# A body that still leaks code after stripping the Source: line failed the
# "plain business English, no code" instruction — flagging it rather than
# silently accepting it is a second line of defense, since a prompt-only
# instruction has already been observed to not reliably hold (a real
# extraction run produced bodies like "`NotificationType` (`constants/
# NotificationType.java`) has 4 values: `NONE(0)`, `SMS(1)`, `EMAIL(2)`,
# `VAIOT(3)`" before this check existed, and a subsequent narrower version
# of this check still let similar enum-dump prose through when the model
# dropped the backticks but kept the same shape). Four independent tells,
# any one of which is enough — each deliberately narrow enough on its own to
# avoid flagging ordinary prose that happens to contain a capitalized word:
#   1. a backtick anywhere (unambiguous — the model marked it as code itself)
#   2. a `.ext` file reference (java/py/ts/js/sql/yml/json/xml/properties/...)
#   3. an enum/constant-style token immediately followed by a parenthesized
#      value, e.g. "NONE(0)" or "fetchUnreadNotifications(id)" — no prose
#      sentence naturally produces this shape
#   4. three or more comma-separated ALL_CAPS or snake_case tokens in a row
#      (a raw enum/constant value dump — "NONE, SMS, EMAIL, VAIOT" reads as
#      a value list transcribed from code, not a description of what it means)
CODE_LEAKAGE_RE = re.compile(
    r"`[^`]+`"
    r"|\b[\w./-]+\.(?:java|kt|py|rb|go|cs|php|c|cpp|h|ts|tsx|js|jsx|vue|sql|yml|yaml|json|xml|properties)\b"
    r"|\b[A-Za-z_][\w]*\([^()\s]{0,20}\)"
    r"|(?:\b[A-Z][A-Z0-9_]{2,}\b\s*,\s*){2,}\b[A-Z][A-Z0-9_]{2,}\b",
    re.IGNORECASE,
)

# Strips a leading category label off the heading once it's already been used
# to classify entry_type — "Rule: Refund window" -> "Refund window". Without
# this the type is shown twice (once in the entry's own type badge, once
# baked into the title text), which is what prompts/EXTRACT_KNOWLEDGE_BASE.md's
# "## Rule: [name]" heading shape would otherwise produce verbatim. Optional
# "Business "/"Domain "/etc. prefix before the label tolerates a model
# writing "Business Rule: ..." instead of the bare "Rule: ...". Also strips
# Business Context's own 7 kind labels ("Problem Statement:", "Competitive
# Landscape:", "Proposed Solution:", "Objective:", "Stakeholder:", "Scope
# Boundary:", "Success Metric:") for the same reason — see
# guess_business_context_kind, which classifies from the same heading text
# before this stripping happens.
TITLE_PREFIX_RE = re.compile(
    r"^(?:[\w ]*\s)?(glossary|term|definition|rule|decision|constraint"
    r"|problem\s*statement|competitive\s*landscape|proposed\s*solution"
    r"|objective|stakeholder|scope\s*boundary|success\s*metric)\s*:\s*",
    re.IGNORECASE,
)

# The 15 SDLC areas prompts/GENERATE_KNOWLEDGE_BASE_FROM_REPO.md (and
# EXTRACT_KNOWLEDGE_BASE.md) asks a heading to be tagged with, e.g.
# "## Rule: Refund window (Business Rules)". Order here is the canonical
# display/grouping order the frontend renders in — it mirrors the fixed SDLC
# pipeline sequence (discovery -> requirements -> architecture -> ... ->
# production), not alphabetical, so a reviewer sees facts in the order a
# project actually gets built rather than a shuffled list.
SDLC_AREAS: list[str] = [
    "Business Context", "Domain & Glossary", "Actors & Roles", "Business Processes",
    "Business Rules", "Functional Requirements", "Non-Functional Requirements",
    "Architecture Decisions", "System Architecture", "Data Domain", "APIs & Integrations",
    "Security & Compliance", "Testing Knowledge", "Deployment & Release", "Operations & Production",
]
_SDLC_AREA_LOOKUP = {area.lower(): area for area in SDLC_AREAS}

# Business Context's own structured breakdown — the reference extraction
# table's row #01, extended with the real Business Case/Charter sections a
# BRD actually opens with (problem statement, competitive landscape,
# proposed solution) ahead of objectives/stakeholders/scope/metrics — used
# in place of entry_type's generic glossary/rule/decision/constraint for
# entries in that one area. Order here is the canonical form/select order,
# and matches the order a real BRD is read in: state the problem, the
# competitive context, the proposed fix, then the objectives/stakeholders/
# scope/metrics that follow from it.
BUSINESS_CONTEXT_KINDS: list[str] = [
    "problem_statement", "competitive_landscape", "proposed_solution",
    "objective", "stakeholder", "scope_boundary", "success_metric",
]
BUSINESS_CONTEXT_KIND_LABELS = {
    "problem_statement": "Problem Statement",
    "competitive_landscape": "Competitive Landscape",
    "proposed_solution": "Proposed Solution",
    "objective": "Objective",
    "stakeholder": "Stakeholder",
    "scope_boundary": "Scope Boundary",
    "success_metric": "Success Metric",
}
# Heading-text keywords that pick business_context_kind, same
# keyword-checked-in-order approach as TYPE_KEYWORDS below — deterministic,
# not model classification, for the same "extraction can't hallucinate"
# reason. Order matters: more specific multi-word keywords are checked
# before the shorter/broader ones they'd otherwise be swallowed by ("success
# metric" before "metric", "competitive landscape"/"competitor" before
# nothing else could collide with them).
BUSINESS_CONTEXT_KIND_KEYWORDS: list[tuple[str, str]] = [
    ("problem statement", "problem_statement"),
    ("problem", "problem_statement"),
    ("competitive landscape", "competitive_landscape"),
    ("competitor", "competitive_landscape"),
    ("proposed solution", "proposed_solution"),
    ("solution", "proposed_solution"),
    ("stakeholder", "stakeholder"),
    ("scope", "scope_boundary"),
    ("success metric", "success_metric"),
    ("metric", "success_metric"),
    ("kpi", "success_metric"),
    ("objective", "objective"),
]


def guess_business_context_kind(heading: str) -> str | None:
    lowered = heading.lower()
    for keyword, kind in BUSINESS_CONTEXT_KIND_KEYWORDS:
        if keyword in lowered:
            return kind
    return None

# Captures a trailing "(Some Area Name)" on a heading, once the category
# prefix has already been stripped — e.g. "Refund window (Business Rules)"
# -> title "Refund window", area tag "Business Rules". Only matches when
# what's inside the parens is one of the 15 known area names (case-
# insensitively) — an unrelated parenthetical a human writes for their own
# reasons (a citation, a ticket number) is left in the title untouched
# rather than misread as an area tag.
_AREA_SUFFIX_RE = re.compile(r"\s*\(([^()]+)\)\s*$")


def _guess_entry_type(heading: str) -> str:
    lowered = heading.lower()
    for keyword, entry_type in TYPE_KEYWORDS:
        if keyword in lowered:
            return entry_type
    return "glossary"


def _extract_sdlc_area(title: str) -> tuple[str, str | None]:
    """Splits a trailing "(Area Name)" off an already-category-stripped
    title, returning (title_without_area_tag, area_or_None). Only strips it
    when the parenthetical is a real match against SDLC_AREAS — see
    _AREA_SUFFIX_RE's docstring note above."""
    match = _AREA_SUFFIX_RE.search(title)
    if not match:
        return title, None
    area = _SDLC_AREA_LOOKUP.get(match.group(1).strip().lower())
    if area is None:
        return title, None
    return title[: match.start()].strip() or title, area


def _clean_title(heading: str) -> tuple[str, str | None]:
    stripped = TITLE_PREFIX_RE.sub("", heading, count=1).strip() or heading.strip()
    return _extract_sdlc_area(stripped)


def _extract_source(body: str) -> tuple[str, str | None]:
    """Splits a trailing "Source: path" line off the body (see
    SOURCE_LINE_RE) — the citation is real and worth keeping, just not
    inline in the sentence a reviewer reads. Returns (body_without_source,
    source_or_None); when the line is present but empty after "Source:",
    still strips it (a stray label is not useful content either way)."""
    match = SOURCE_LINE_RE.search(body)
    if not match:
        return body, None
    source = match.group(1).strip() or None
    return body[: match.start()].strip(), source


def parse_knowledge_markdown(text: str) -> list[dict]:
    """Split an uploaded markdown template into candidate knowledge entries,
    one per `##`/`###`/... heading, entirely deterministically (no LLM call —
    see module docstring). Each candidate is
    {"entry_type", "title", "sdlc_area", "body", "source", "needs_info",
    "reason"}: `sdlc_area` is one of SDLC_AREAS when the heading tagged it
    with a recognized "(Area Name)" suffix, else None (grouped as "Other" by
    the frontend). `source` is a trailing "Source: path" line
    (prompts/GENERATE_KNOWLEDGE_BASE_FROM_REPO.md's citation shape) stripped
    out of the body into its own field, else None. `needs_info` is True when
    the section is too short to ground anything, still contains a placeholder
    marker (TODO/TBD/???/<fill in>), or still leaks code (backticks, a file
    extension) into what's supposed to be plain business prose — the caller
    (the /knowledge/extract endpoint) surfaces these to the user as gaps
    needing a rewrite rather than saving unreadable entries silently.

    A doc with no headings at all becomes a single untitled candidate from
    the whole text, still run through the same needs_info check — better to
    flag a whole unstructured file as "add more detail" than to silently
    accept it as one giant, uncitable entry."""
    stripped = text.strip()
    if not stripped:
        return []

    matches = list(HEADING_RE.finditer(stripped))
    if not matches:
        return [_candidate("glossary", "Untitled", None, None, stripped, None)]

    candidates = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        raw_body = stripped[start:end].strip()
        title, sdlc_area = _clean_title(heading)
        body, source = _extract_source(raw_body)
        business_context_kind = guess_business_context_kind(heading) if sdlc_area == "Business Context" else None
        candidates.append(_candidate(_guess_entry_type(heading), title, sdlc_area, business_context_kind, body, source))
    return candidates


def check_body_quality(title: str, body: str) -> str | None:
    """The same four gap checks _candidate applies to a freshly-parsed
    candidate, factored out so app/api/projects.py's /knowledge/recheck
    endpoint can run them against entries ALREADY saved to the database —
    entries saved before this check existed (or before CODE_LEAKAGE_RE was
    broadened to catch enum-value dumps without backticks — see that
    regex's comment for the real KB-110-style case that motivated it) never
    got graded and can otherwise sit there unreadable forever. Returns None
    when the body passes every check, else a human-readable reason."""
    word_count = len(body.split())
    if word_count == 0:
        return f'"{title}" has no content under it.'
    if PLACEHOLDER_RE.search(body):
        return f'"{title}" still contains a placeholder marker (TODO/TBD/etc).'
    if CODE_LEAKAGE_RE.search(body):
        return f'"{title}" still has code (a backtick, file reference, or raw enum/constant dump) in the explanation — rewrite it in plain business language.'
    if word_count < MIN_BODY_WORDS:
        return f'"{title}" is very short — add enough detail to actually ground a claim.'
    return None


def _candidate(entry_type: str, title: str, sdlc_area: str | None, business_context_kind: str | None, body: str, source: str | None) -> dict:
    reason = check_body_quality(title, body)
    return {
        "entry_type": entry_type, "title": title or "Untitled", "sdlc_area": sdlc_area,
        "business_context_kind": business_context_kind,
        "body": body, "source": source, "needs_info": reason is not None, "reason": reason,
    }


# ── Extraction from a linked repository ─────────────────────────────────

VALID_ENTRY_TYPES = {"glossary", "rule", "decision", "constraint"}


class KnowledgeExtractionError(Exception):
    """The model responded, but not with the JSON shape extraction needs.
    Mirrors wiki_generator.WikiGenerationError's role for that pipeline."""


def _parse_extraction_response(raw: str, source_material: str) -> list[dict]:
    # Local imports: wiki_generator.py has no import of this module (only the
    # reverse), so this isn't a real cycle — kept local so knowledge_base.py's
    # deterministic pieces (parse_knowledge_markdown, format_knowledge_context)
    # stay importable without pulling in wiki_generator's LangChain/provider
    # imports, same lazy-import precedent wiki_chapters.py already uses.
    from app.services.wiki_generator import (
        SOURCE_CITATION,
        VENDOR_CITATION,
        _normalize_citation,
    )
    from app.utils.text_parsing import clean_raw

    try:
        data = json.loads(clean_raw(raw))
    except json.JSONDecodeError as e:
        raise KnowledgeExtractionError(f"Model response was not valid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise KnowledgeExtractionError("Model response was missing a 'candidates' list.")

    # Whether the source material actually contained any deterministic
    # path:line evidence — same "don't demand citations the model was never
    # given" gate wiki_generator._grounding_violations uses. An unreachable
    # or empty repo (context_block never built) yields no citable facts at
    # all, so nothing here can be graded against citations it never saw.
    grounded_material = bool(SOURCE_CITATION.search(source_material))

    candidates = []
    for item in data["candidates"]:
        if not isinstance(item, dict) or "title" not in item or "body" not in item:
            continue
        entry_type = str(item.get("entry_type") or "glossary").lower()
        if entry_type not in VALID_ENTRY_TYPES:
            entry_type = "glossary"
        title = str(item["title"]).strip() or "Untitled"
        sdlc_area = _SDLC_AREA_LOOKUP.get(str(item.get("sdlc_area") or "").strip().lower())
        business_context_kind = None
        if sdlc_area == "Business Context":
            raw_kind = str(item.get("business_context_kind") or "").strip().lower()
            business_context_kind = raw_kind if raw_kind in BUSINESS_CONTEXT_KINDS else None
        body = str(item["body"]).strip()
        raw_evidence = item.get("evidence") or []
        evidence = [e for e in (_normalize_citation(r) for r in raw_evidence) if e]
        needs_info = bool(item.get("needs_info"))
        reason = str(item["reason"]).strip() if item.get("reason") else None

        vendor_only = evidence and all(VENDOR_CITATION.search(e) for e in evidence)
        if grounded_material and body and not evidence:
            needs_info, reason = True, reason or f'"{title}" has no source citation from the repository.'
        elif vendor_only:
            needs_info, reason = True, reason or f'"{title}" only cites a third-party/bundled file, not first-party code.'
        elif not body:
            needs_info, reason = True, reason or f'"{title}" has no content.'
        elif CODE_LEAKAGE_RE.search(body):
            needs_info, reason = True, reason or f'"{title}" still has code (a backtick or file reference) in the explanation — rewrite it in plain business language.'

        candidates.append({
            "entry_type": entry_type, "title": title, "sdlc_area": sdlc_area,
            "business_context_kind": business_context_kind, "body": body,
            "source": (evidence[0] if evidence else None), "needs_info": needs_info, "reason": reason,
        })
    return candidates


def _repair_extraction_json(model, system_prompt: str, user_prompt: str, raw: str, error: Exception, source_material: str) -> list[dict]:
    """One repair attempt, same one-extra-chance pattern as
    wiki_generator._repair_invalid_json — a second failure propagates."""
    repair = (
        f"{user_prompt}\n\nYour previous response could not be parsed: {error}\n\n"
        "Return ONLY valid JSON in the required shape, no markdown fences, no commentary. "
        "Previous response:\n" + raw[:12000]
    )
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=repair)])
    return _parse_extraction_response(str(response.content), source_material)


def extract_knowledge_from_repo(provider, project_name: str, repo_label: str, context_block: str, readme_text: str | None) -> list[dict]:
    """One grounded LLM call per linked repo, mining it for the same
    15-SDLC-area knowledge prompts/EXTRACT_KNOWLEDGE_BASE.md asks a human to
    extract by hand from documents — sourced from the actual code instead.
    Returns a list of KnowledgeCandidate dicts, same shape
    parse_knowledge_markdown() produces, so the frontend's staged-review
    screen is identical regardless of source. Never writes to the database;
    the caller (app/api/projects.py) is responsible for that, after review."""
    from app.services.langchain_provider import AutoSDLCChatModel
    from app.services.prompt import KNOWLEDGE_EXTRACTION_SYSTEM, build_knowledge_extraction_message

    model = AutoSDLCChatModel(provider=provider)
    message = build_knowledge_extraction_message(project_name, repo_label, context_block, readme_text)
    response = model.invoke([SystemMessage(content=KNOWLEDGE_EXTRACTION_SYSTEM), HumanMessage(content=message)])
    raw = str(response.content)
    try:
        return _parse_extraction_response(raw, message)
    except KnowledgeExtractionError as e:
        return _repair_extraction_json(model, KNOWLEDGE_EXTRACTION_SYSTEM, message, raw, e, message)
