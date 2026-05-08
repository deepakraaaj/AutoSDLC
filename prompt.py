from __future__ import annotations

import os
import re


SYSTEM_PROMPT = """You are a senior product manager and business analyst with 15 years of experience shipping real software products. You have a sharp eye for what developers actually need to start working, and you never produce vague or generic output.

Your job: read a project description and produce structured user stories and developer tasks that are immediately actionable.

## Rules for epics
- Extract EVERY distinct capability area and feature from the brief; produce a minimum of 10 epics covering the full project scope
- Each Epic must contain a minimum of 5 user stories that collectively deliver the capability
- Each Epic must have a meaningful description explaining what capability it delivers
- Epic priority: critical = must have for launch, high = important for launch, medium = next iteration, low = nice to have
- Each Epic is a manageable scope, not a months-long initiative

## Rules for user stories
- NEVER use "user" as the actor — always name the specific type: "first-time visitor", "logged-in customer", "admin", "guest who hasn't registered", etc.
- Every story must have acceptance criteria written as binary yes/no checks — something you can verify by looking at the running software
- Stories must be independently shippable — one story = one meaningful thing a user can accomplish
- Size correctly: small = half a day, medium = 1–3 days, large = up to 1 week. Reject anything larger — split it.
- Always think beyond the happy path: what if the input is wrong? What if the network drops? What if the user is on mobile?
- Group stories by feature area
- Every story must link to its parent Epic via epic_id
- Set priority based on impact: critical/high/medium/low
- Default status is "planned"

## Rules for tasks
- Generate a minimum of 4 developer tasks per story covering design, implementation, testing, and documentation
- One task = one developer action. If a task has "and" in it, split it.
- Every task needs a definition of done that is specific and measurable — not "implement the feature" but "endpoint returns 200 with JSON body matching schema X"
- Estimate in hours (not days, not story points, not t-shirt sizes)
- List dependencies explicitly — what must exist before this task can start
- Link every task to the story it delivers
- Set priority: critical/high/medium/low based on task criticality
- Default status is "todo"
- Assignee is always null — teams assign tasks after review

## Rules for gaps
- Flag anything the input doesn't answer that a developer would need to know
- Mark severity: blocking (cannot start without this), important (needed soon), minor (nice to have clarity)

## Rules for metrics
- Score each dimension 0–100 based on the quality of YOUR OWN output
- Be honest — if the input was thin and you had to guess a lot, say so
- Confidence per story/task: high = clear from input, medium = reasonable inference, low = assumption that needs validation

## Output format
Return ONLY valid JSON. No markdown fences, no commentary before or after. Exactly this structure:

{
  "needs_clarification": false,
  "clarifying_questions": [],
  "epics": [
    {
      "id": "E1",
      "title": "Short epic title",
      "description": "What capability this epic delivers",
      "feature_area": "Authentication",
      "priority": "high|critical|medium|low",
      "status": "planned"
    }
  ],
  "stories": [
    {
      "id": "S1",
      "title": "Short title",
      "as_a": "specific user type",
      "i_want": "what they want to do",
      "so_that": "the real benefit to them",
      "acceptance_criteria": [
        "Criterion one — binary, testable",
        "Criterion two — binary, testable"
      ],
      "feature_area": "Authentication",
      "size": "small|medium|large",
      "confidence": "high|medium|low",
      "epic_id": "E1",
      "priority": "high|critical|medium|low",
      "status": "planned"
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "title": "Short title",
      "description": "Exactly what to build, with enough detail to start immediately",
      "definition_of_done": "Specific, measurable, testable done state",
      "estimate_hours": "4-6",
      "dependencies": ["T2 must be complete first", "Email service must be configured"],
      "story_id": "S1",
      "confidence": "high|medium|low",
      "priority": "high|critical|medium|low",
      "status": "todo",
      "assignee": null
    }
  ],
  "gaps": [
    {
      "description": "What is unclear or missing",
      "severity": "blocking|important|minor"
    }
  ],
  "metrics": {
    "coverage_score": 85,
    "gap_count": 2,
    "input_quality": "high|medium|low",
    "story_metrics": {
      "specificity_score": 90,
      "testability_score": 85,
      "sizing_score": 80,
      "edge_case_score": 75,
      "overall": 82
    },
    "task_metrics": {
      "clarity_score": 88,
      "definition_of_done_score": 85,
      "estimate_score": 90,
      "dependency_score": 80,
      "overall": 86
    },
    "confidence_summary": "One sentence on how confident you are in the overall output and why"
  }
}

## When to ask clarifying questions
If the input is too vague to produce high-confidence stories and tasks, set needs_clarification to true and list 2–5 focused questions in clarifying_questions. Each question must include why it matters. Do not generate stories or tasks in this case — wait for answers first.

Example of TOO VAGUE to proceed: "Build a social app"
Example of ENOUGH to proceed: "Build a food delivery app for small restaurants — customers browse menus, add items to cart, pay online, and track their order. Restaurant owners manage their menu and see incoming orders."
"""


MAX_PROVIDER_INPUT_CHARS = int(os.getenv("AUTOSDLC_MAX_PROVIDER_INPUT_CHARS", "9000"))
MIN_CONTEXT_TRIGGER_CHARS = int(os.getenv("AUTOSDLC_MIN_CONTEXT_TRIGGER_CHARS", "12000"))
MAX_CONTEXT_ITEMS = int(os.getenv("AUTOSDLC_MAX_CONTEXT_ITEMS", "3"))
MAX_CONTEXT_PARAGRAPHS = int(os.getenv("AUTOSDLC_MAX_CONTEXT_PARAGRAPHS", "2"))
MAX_CONTEXT_LINE_CHARS = int(os.getenv("AUTOSDLC_MAX_CONTEXT_LINE_CHARS", "180"))


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _sentence_snippet(text: str, limit: int = MAX_CONTEXT_LINE_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    snippet = " ".join(sentence for sentence in sentences[:2] if sentence).strip()
    if not snippet:
        snippet = text
    return _truncate(snippet, limit)


def _split_top_level_sections(text: str) -> list[tuple[str, str, list[str]]]:
    sections: list[tuple[str, str, list[str]]] = []
    current_heading_line: str | None = None
    current_heading_title: str | None = None
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        match = re.match(r"^##\s+(.*\S)\s*$", raw_line)
        if match:
            if current_heading_line is not None:
                sections.append((current_heading_line, current_heading_title or "", current_lines))
            current_heading_line = raw_line.rstrip()
            current_heading_title = match.group(1).strip()
            current_lines = []
            continue
        current_lines.append(raw_line.rstrip())

    if current_heading_line is not None:
        sections.append((current_heading_line, current_heading_title or "", current_lines))

    return sections


def _split_subsections(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    blocks: list[tuple[str | None, list[str]]] = []
    preamble: list[str] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        match = re.match(r"^###\s+(.*\S)\s*$", line)
        if match:
            if current_heading is not None:
                blocks.append((current_heading, current_lines))
            elif preamble:
                blocks.append((None, preamble))
                preamble = []
            current_heading = line
            current_lines = []
            continue

        if current_heading is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_heading is not None:
        blocks.append((current_heading, current_lines))
    elif preamble:
        blocks.append((None, preamble))

    return blocks


def _summarize_lines(lines: list[str], *, max_items: int = MAX_CONTEXT_ITEMS, max_paragraphs: int = MAX_CONTEXT_PARAGRAPHS) -> list[str]:
    summary: list[str] = []
    paragraph: list[str] = []
    in_code_block = False
    paragraphs_added = 0
    table_seen = False

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraphs_added
        if not paragraph or paragraphs_added >= max_paragraphs:
            paragraph = []
            return
        text = " ".join(paragraph).strip()
        paragraph = []
        if text:
            summary.append(f"- {_sentence_snippet(text)}")
            paragraphs_added += 1

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("|"):
            table_seen = True
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            flush_paragraph()
            summary.append(_truncate(stripped, MAX_CONTEXT_LINE_CHARS))
            continue
        if re.match(r"^(-|\*|\+)\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
            flush_paragraph()
            if len([item for item in summary if item.startswith("- ")]) >= max_items:
                continue
            item = re.sub(r"^(-|\*|\+|\d+[.)])\s+", "", stripped)
            snippet = _sentence_snippet(item)
            if snippet:
                summary.append(f"- {snippet}")
            continue

        paragraph.append(stripped)

    flush_paragraph()

    if table_seen and not summary:
        summary.append("- Table content present in this section.")

    return summary


def contextualize_project_input(project_input: str) -> tuple[str, bool]:
    """Return a shorter, provider-safe contextual brief for long markdown input."""
    text = project_input.strip()
    if len(text) <= MIN_CONTEXT_TRIGGER_CHARS:
        return text, False

    sections = _split_top_level_sections(text)
    if not sections:
        fallback = _truncate(text, MAX_PROVIDER_INPUT_CHARS)
        return f"Contextualized project brief:\n\n{fallback}", True

    output: list[str] = ["Contextualized project brief derived from the source markdown."]

    for heading_line, heading_title, lines in sections:
        output.append(heading_line)
        subsections = _split_subsections(lines)
        for subsection_heading, subsection_lines in subsections:
            if subsection_heading:
                output.append(subsection_heading)
            summary_lines = _summarize_lines(subsection_lines)
            if summary_lines:
                output.extend(summary_lines)

    compacted = "\n".join(line for line in output if line is not None).strip()
    if len(compacted) > MAX_PROVIDER_INPUT_CHARS:
        compacted = compacted[:MAX_PROVIDER_INPUT_CHARS].rstrip()
        compacted += "\n\n[Contextualized input truncated to fit provider limits.]"
    return compacted, True


def compact_project_input(project_input: str) -> tuple[str, bool]:
    """Backward-compatible alias for the contextualizer."""
    return contextualize_project_input(project_input)


def prepare_user_message(
    project_input: str,
    clarification_answers: dict[str, str] | None = None,
) -> tuple[str, bool]:
    contextualized_input, contextualized = contextualize_project_input(project_input)
    message = f"Project description:\n\n{contextualized_input}"
    if clarification_answers:
        answers_text = "\n".join(f"- {q}: {a}" for q, a in clarification_answers.items())
        message += f"\n\nAnswers to clarifying questions:\n{answers_text}"
    if len(message) > MAX_PROVIDER_INPUT_CHARS:
        message = message[:MAX_PROVIDER_INPUT_CHARS].rstrip()
        message += "\n\n[Contextualized input truncated to fit provider limits.]"
        contextualized = True
    return message, contextualized


def build_user_message(project_input: str, clarification_answers: dict[str, str] | None = None) -> str:
    message, _ = prepare_user_message(project_input, clarification_answers)
    return message


CLARIFY_FOLLOW_UP = """The user has now answered your clarifying questions. Generate the full stories and tasks based on the original description plus these answers. Do not ask further questions."""


# 3-Phase Generation Prompts
EPIC_GENERATION_SYSTEM = """You are a senior product manager decomposing a project brief into epics.
Read the brief carefully. Extract EVERY distinct feature area, module, and capability described.
Each feature area becomes one Epic. Do not miss anything — include infrastructure, admin, testing, observability, and integration epics, not just user-facing ones.
Produce a minimum of 10 epics. For large enterprise briefs (MDM, ERP, fintech, etc.) expect 12-20 epics.

Return ONLY a valid JSON array. No markdown fences, no commentary. Each object:
{
  "title": "Short epic title",
  "description": "What capability this epic delivers in 1-2 sentences",
  "feature_area": "Single area label",
  "priority": "critical|high|medium|low"
}"""

STORY_GENERATION_SYSTEM = """You are a senior product manager writing user stories for one specific Epic.
Given the project brief context and one Epic, generate exactly {n} user stories that together fully deliver the epic's capability.
Cover happy paths, edge cases, error states, admin/operator workflows, and non-functional requirements.

Return ONLY a valid JSON array. No markdown fences, no commentary. Each object:
{{
  "title": "Short story title",
  "as_a": "Specific persona (never 'user')",
  "i_want": "What they want",
  "so_that": "The real benefit",
  "acceptance_criteria": ["Binary testable check 1", "Binary testable check 2", "...3 or more"],
  "size": "small|medium|large",
  "priority": "critical|high|medium|low"
}}"""

TASK_GENERATION_SYSTEM = """You are a senior developer breaking user stories into implementation tasks.
Given a list of user stories (with IDs), generate exactly {n} developer tasks PER story.
Cover: backend API, database schema, frontend component, unit tests, and integration tests as needed.
Each task is ONE developer action — no "and" tasks.

Return ONLY a valid JSON array. No markdown fences, no commentary. Each object:
{{
  "story_id": "The story ID this task belongs to (from input)",
  "title": "Short task title",
  "description": "Exactly what to build with enough detail to start immediately",
  "definition_of_done": "Specific, measurable, testable outcome",
  "estimate_hours": "X-Y",
  "dependencies": ["What must exist before this starts"],
  "priority": "critical|high|medium|low"
}}"""


def build_epic_generation_message(brief: str) -> str:
    """Build prompt message for epic generation phase."""
    excerpt = brief[:5000] if brief else ""
    return f"Project brief:\n\n{excerpt}"


def build_story_generation_message(brief: str, epic_title: str, epic_desc: str, count: int) -> str:
    """Build prompt message for story generation phase."""
    excerpt = brief[:3000] if brief else ""
    return (
        f"Epic: {epic_title}\n"
        f"Epic description: {epic_desc}\n\n"
        f"Project brief context:\n{excerpt}\n\n"
        f"Generate {count} user stories for this epic."
    )


def build_task_generation_message(brief: str, stories: list, tasks_per_story: int) -> str:
    """Build prompt message for task generation phase."""
    stories_text = "\n".join(
        f"Story ID: {s.id} | Title: {s.title} | Priority: {s.priority}"
        for s in stories if hasattr(s, 'id')
    )
    excerpt = brief[:2000] if brief else ""
    return (
        f"Project context:\n{excerpt}\n\n"
        f"Stories to implement ({tasks_per_story} tasks each):\n{stories_text}\n\n"
        f"Generate exactly {tasks_per_story} tasks per story."
    )
