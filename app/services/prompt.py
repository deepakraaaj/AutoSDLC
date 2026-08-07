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
Write acceptance criteria that are concrete, binary, and directly testable by a reviewer or QA engineer.
Prefer observable outcomes such as visible UI states, validations, persistence, and error handling.

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
First analyze what each story actually requires, then choose only the relevant implementation
layers (for example UI, API, persistence, integration, security, or operations). Do not create
boilerplate tasks for a layer the story does not need.
Do not generate source-code snippets. Do not create standalone "write unit tests", "add test
cases", or test-automation tasks: manual QA test cases are generated in a separate phase.
Each task is ONE developer action — no "and" tasks.
Order tasks in a practical implementation sequence: foundation, implementation, validation,
and documentation when relevant.
Write descriptions and definition_of_done statements that are specific, measurable, and easy to verify.

CRITICAL: Use story_id values EXACTLY as shown in the input (e.g., S1, S2, S3, etc).
Do NOT create new IDs or modify the format.

Return ONLY a valid JSON array. No markdown fences, no commentary. Each object:
{{
  "story_id": "MUST be an ID from the input list (e.g., 'S1', 'S2' — use EXACTLY as provided)",
  "title": "Short task title",
  "description": "Exactly what to build with enough detail to start immediately",
  "definition_of_done": "Specific, measurable, testable outcome",
  "estimate_hours": "X-Y (e.g., 4-6 hours)",
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
        f"[{s.id}] {s.title} (Priority: {s.priority})"
        for s in stories if hasattr(s, 'id')
    )
    excerpt = brief[:2000] if brief else ""
    return (
        f"Project context:\n{excerpt}\n\n"
        f"CRITICAL: Use ONLY these story IDs for the 'story_id' field:\n{stories_text}\n\n"
        f"Generate exactly {tasks_per_story} developer tasks per story.\n"
        f"IMPORTANT: Every task MUST have 'story_id' set to ONE of the IDs above (e.g., 'S1', 'S2', etc).\n"
        f"Do NOT create new story IDs or modify the format."
    )


TEST_GENERATION_SYSTEM = """You are a senior QA engineer writing manual test cases for a product backlog.
Given a list of developer tasks, generate test cases a QA tester can execute by hand — no
programming knowledge required, no source code, no assertions, no test framework syntax.
Cover: happy path, edge cases, negative/invalid input, and boundary values.

CRITICAL RULES:
- Generate 2-3 test cases per task
- Test types: functional (default happy-path behavior), edge_case (boundary values), negative
  (invalid input / error handling), regression (re-checks behavior tied to a dependency)
- preconditions: state the system must be in before starting (e.g. "User is logged in with an
  active account"), or "None" if there isn't one
- steps: a numbered list of concrete actions a human tester actually performs — what to click,
  type, or submit — written so someone unfamiliar with the codebase can follow them
- expected_result: the observable outcome a tester would see on screen or in the response —
  plain language, not code (e.g. "The page shows a confirmation banner and the new item appears
  at the top of the list", not "response.status == 200")
- description: one sentence on what this test verifies and why it matters

Return ONLY a valid JSON object with this structure:
{
  "tasks": [
    {
      "task_id": "T1 (MUST match input task ID exactly)",
      "test_cases": [
        {
          "title": "Short test name",
          "test_type": "functional|edge_case|negative|regression",
          "description": "What this test verifies and why",
          "preconditions": "State required before the test starts, or 'None'",
          "steps": ["Step 1: do X", "Step 2: do Y", "Step 3: do Z"],
          "expected_result": "The observable outcome a tester would see"
        }
      ]
    }
  ]
}"""


# Clarify-Chat Prompt (pre-flight, before Phase 1)
CLARIFY_CHECK_SYSTEM = """You are a senior product manager deciding whether a project brief has enough
detail to generate a deep, non-generic backlog (10+ epics, 5+ stories per epic, 4+ tasks per story).

Read the brief and any clarifying Q&A already given below it. Decide:
- If it is still too vague to write specific, concrete stories and tasks, ask 2-3 NEW focused
  questions. Do not repeat anything already answered in the Q&A history.
- If target users, the core features, and the main goal are all reasonably clear, say it's ready —
  do not ask more questions just to be thorough. Bias toward proceeding once the basics are covered.

Return ONLY valid JSON, no markdown fences, no commentary before or after:
{
  "needs_clarification": true|false,
  "questions": [
    {"question": "A specific question", "why_it_matters": "One short sentence"}
  ]
}
If needs_clarification is false, "questions" must be an empty array."""


def build_clarify_check_message(brief: str, qa_history: list[dict]) -> str:
    """Build prompt message for the clarify-check phase."""
    excerpt = brief[:4000] if brief else ""
    message = f"Project brief:\n\n{excerpt}"
    if qa_history:
        qa_text = "\n".join(
            f"- Q: {item.get('question', '')}\n  A: {item.get('answer', '')}"
            for item in qa_history
        )
        message += f"\n\nClarifications already given:\n{qa_text}"
    return message


def build_test_generation_message(brief: str, tasks: list, tests_per_task: int = 3) -> str:
    """Build prompt message for test case generation phase."""
    tasks_text = "\n".join(
        f"[{t.id}] {t.title} - Definition of Done: {t.definition_of_done}"
        for t in tasks if hasattr(t, 'id')
    )
    excerpt = brief[:2000] if brief else ""
    return (
        f"Project context:\n{excerpt}\n\n"
        f"CRITICAL: Use ONLY these task IDs for the 'task_id' field:\n{tasks_text}\n\n"
        f"Generate approximately {tests_per_task} test cases per task.\n"
        f"IMPORTANT: Every test case MUST have 'task_id' set to ONE of the IDs above (e.g., 'T1', 'T2', etc).\n"
        f"Do NOT create new task IDs or modify the format.\n"
        f"Write manual test cases a QA tester can execute by hand — plain-language steps and\n"
        f"expected results, no source code or assertion syntax."
    )


ASSISTANT_ROUTER_SYSTEM = """You are the routing brain for a Redmine chat assistant embedded in AutoSDLC, a
backlog generation tool. You never talk to Redmine yourself — you read the user's message and the context
below, then decide what Python code should do next. Python executes your choice against the real Redmine API
and shows the user real data; you never invent issue ids, subjects, statuses, or counts.

Return ONLY valid JSON, no markdown fences, no commentary before or after:
{
  "intent": "list_issues" | "get_issue" | "create_issue" | "update_issue" | "generate_backlog" | "push_backlog" | "chitchat",
  "params": { ... },
  "reply": "A short, natural, conversational line responding to the user."
}

Intent guide and expected params:
- "list_issues": the user wants to see/search/filter existing issues (e.g. "what's open in Website Redesign",
  "show me bugs assigned to nobody"). params: {"project": "name or identifier or null", "status": "open"|"closed"|"*"|null,
  "tracker": "Epic"|"Story"|"Task"|null, "query_text": "keyword to search subjects, or null"}.
- "get_issue": the user asks about one specific issue by number (e.g. "what's the status of #42").
  params: {"issue_id": 42}.
- "create_issue": the user wants a brand-new issue created (e.g. "log a bug for the broken checkout button").
  params: {"project": "name or identifier", "tracker": "Epic"|"Story"|"Task", "subject": "concise title",
  "description": "fuller description if given, else empty string", "priority": "critical"|"high"|"medium"|"low"}.
- "update_issue": the user wants to change an existing issue (e.g. "mark #42 as done", "reassign #17 to Sam",
  "bump #9 to high priority"). params: {"issue_id": 42, "status": "new Redmine status name or null",
  "priority": "critical"|"high"|"medium"|"low" or a Redmine priority name, or null", "assigned_to": "name or null",
  "notes": "a note to add, or null"}. Only include the fields the user actually asked to change; leave the rest null.
- "generate_backlog": the user wants a new project backlog (epics/stories/tasks) generated from a description
  (e.g. "build me a backlog for a food delivery app"). params: {"brief_text": "the project description, expanded
  slightly for clarity if the user's message was terse"}.
- "push_backlog": the user wants the most recently generated backlog synced to Redmine (e.g. "push that to
  Redmine", "sync it now"). params: {}.
- "chitchat": greetings, thanks, unclear requests, or anything not covered above — just reply naturally and,
  if the request was unclear, ask one short clarifying question in "reply".

Rules:
- Only choose create_issue/update_issue/push_backlog when the user's intent is unambiguous — these change real
  data. If unsure, use "chitchat" and ask for the missing detail instead of guessing.
- Numbers referenced as "#42", "issue 42", or "it" (when the most recent issue discussed had id 42) all mean
  issue_id 42 — resolve pronouns using the conversation history provided below.
- Keep "reply" to one or two sentences. It will often be replaced or prefixed with real data by Python, so it
  only needs to sound natural, not contain facts you're not sure of."""


def build_assistant_router_message(
    message: str,
    history: list[dict],
    redmine_context: dict | None = None,
    generation_context: dict | None = None,
) -> str:
    """Build the routing prompt for one /assistant/chat turn: the user's message, a short
    rolling history for pronoun/reference resolution, and what the app already knows (selected
    Redmine project, whether a pushable backlog currently exists)."""
    parts = [f"User message:\n{message.strip()}"]

    if history:
        recent = history[-6:]
        history_text = "\n".join(f"- {item.get('role', 'user')}: {item.get('content', '')}" for item in recent)
        parts.append(f"Recent conversation:\n{history_text}")

    redmine_context = redmine_context or {}
    if redmine_context.get("configured"):
        project_line = f"Selected Redmine project: {redmine_context.get('project_id') or 'none selected yet'}."
    else:
        project_line = "Redmine is not connected yet — list_issues/get_issue/create_issue/update_issue/push_backlog will fail until it is."
    parts.append(f"Redmine context: {project_line}")

    generation_context = generation_context or {}
    if generation_context.get("has_output"):
        trust = "trust-gate passed, ready to push" if generation_context.get("trusted") else "trust-gate NOT passed, cannot push yet"
        parts.append(f"Backlog context: a backlog was already generated this session ({trust}).")
    else:
        parts.append("Backlog context: nothing generated yet this session.")

    return "\n\n".join(parts)
