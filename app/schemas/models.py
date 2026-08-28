from pydantic import BaseModel, Field
from typing import Literal


class AcceptanceCriteria(BaseModel):
    criterion: str


class Epic(BaseModel):
    id: str
    title: str
    description: str
    feature_area: str
    priority: Literal["critical", "high", "medium", "low"]
    status: Literal["planned", "in-progress", "done"] = "planned"


class Story(BaseModel):
    id: str
    title: str
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[str]
    feature_area: str
    size: Literal["small", "medium", "large"]
    confidence: Literal["high", "medium", "low"]
    epic_id: str | None = None
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    status: Literal["planned", "in-progress", "review", "done"] = "planned"


class TestCase(BaseModel):
    """A manual QA test case — deliberately not code. This backlog tool
    generates product-management artifacts (epics/stories/tasks), and these
    test cases are meant for a QA tester to execute by hand or attach to a
    Redmine issue, not a source-code test suite."""
    id: str
    title: str
    test_type: Literal["functional", "edge_case", "negative", "regression"]
    description: str
    preconditions: str
    steps: list[str]
    expected_result: str


# Pytest sees this domain model when tests import it and otherwise attempts to
# collect it as a test class because of the name.
TestCase.__test__ = False


class Task(BaseModel):
    id: str
    title: str
    description: str
    definition_of_done: str
    estimate_hours: str
    dependencies: list[str]
    test_cases: list[TestCase] = []
    story_id: str | None = None
    confidence: Literal["high", "medium", "low"]
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    status: Literal["todo", "in-progress", "testing", "done"] = "todo"
    assignee: str | None = None


class Gap(BaseModel):
    description: str
    severity: Literal["blocking", "important", "minor"]


class ClarifyingQuestion(BaseModel):
    question: str
    why_it_matters: str


class StoryMetrics(BaseModel):
    specificity_score: int = Field(ge=0, le=100)
    testability_score: int = Field(ge=0, le=100)
    sizing_score: int = Field(ge=0, le=100)
    edge_case_score: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class TaskMetrics(BaseModel):
    clarity_score: int = Field(ge=0, le=100)
    definition_of_done_score: int = Field(ge=0, le=100)
    estimate_score: int = Field(ge=0, le=100)
    dependency_score: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class TestMetrics(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    expected_result_quality_score: int = Field(ge=0, le=100)
    edge_case_coverage_score: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class TokenUsage(BaseModel):
    ai_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class OverallMetrics(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    gap_count: int
    input_quality: Literal["high", "medium", "low"]
    story_metrics: StoryMetrics
    task_metrics: TaskMetrics
    test_metrics: TestMetrics | None = None
    confidence_summary: str
    # Wall-clock time this generation actually took, start to finish —
    # measured server-side, not a client-side timer (which would drift with
    # network/render timing). None for older, already-saved generations.
    generation_seconds: float | None = None
    # None for the rule-based compiler path (no AI calls) or older
    # generations saved before this was tracked.
    token_usage: TokenUsage | None = None


class ValidationCheck(BaseModel):
    label: str
    passed: bool
    value: str
    threshold: str


class ValidationResult(BaseModel):
    trust_level: Literal["trusted", "review", "low"]
    checks: list[ValidationCheck]
    recommendation: str


class GenerationOutput(BaseModel):
    needs_clarification: bool
    clarifying_questions: list[ClarifyingQuestion]
    epics: list[Epic] = []
    stories: list[Story]
    tasks: list[Task]
    gaps: list[Gap]
    metrics: OverallMetrics | None = None
    validation: ValidationResult | None = None


class GenerateRequest(BaseModel):
    text: str
    clarification_answers: dict[str, str] = {}
    # Optional: a path within the configured Bitbucket repo (BITBUCKET_* env
    # vars) whose file tree gets prepended to `text` as extra context before
    # generation. Empty/None (the default) leaves generation exactly as it
    # behaves today — see bitbucket/client.py's build_repo_context_block.
    bitbucket_repo: str | None = None
    # Optional: attach this generation to an existing Project — enables
    # project-scoped repo pushes/reviews and project instructions
    # (app/api/projects.py). None (the default) is an unowned generation,
    # exactly today's behavior.
    project_id: int | None = None


class ClarifyChatRequest(BaseModel):
    text: str
    qa_history: list[dict[str, str]] = []


class ClarifyRequest(BaseModel):
    original_input: str
    questions: list[ClarifyingQuestion]
    answers: dict[str, str]


class StatusUpdateRequest(BaseModel):
    status: str


class AssigneeUpdateRequest(BaseModel):
    assignee: str | None = None


class ProviderSelectRequest(BaseModel):
    provider: str


class PriorityUpdateRequest(BaseModel):
    priority: Literal["critical", "high", "medium", "low"]


class EpicEditRequest(BaseModel):
    """All-optional — only fields actually present in the request body get
    updated (see main.py's use of model_dump(exclude_unset=True))."""
    title: str | None = None
    description: str | None = None
    feature_area: str | None = None


class EpicCreateRequest(BaseModel):
    generation_id: int
    title: str = Field(min_length=1, max_length=250)
    description: str = ""
    feature_area: str = "General"
    priority: Literal["critical", "high", "medium", "low"] = "medium"


class StoryEditRequest(BaseModel):
    title: str | None = None
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None
    acceptance_criteria: list[str] | None = None
    feature_area: str | None = None


class StoryCreateRequest(BaseModel):
    epic_id: int
    title: str = Field(min_length=1, max_length=250)
    as_a: str = "User"
    i_want: str = ""
    so_that: str = ""
    acceptance_criteria: list[str] = []
    feature_area: str = "General"
    size: Literal["small", "medium", "large"] = "medium"
    priority: Literal["critical", "high", "medium", "low"] = "medium"


class TaskEditRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    definition_of_done: str | None = None
    estimate_hours: str | None = None
    dependencies: list[str] | None = None


class QualityItemSelection(BaseModel):
    """One item the user picked, out of the weak items GET /weak-items showed them —
    see main.py's POST /generations/{gen_id}/improve-quality."""
    kind: Literal["story", "task"]
    id: str


class ImproveQualityRequest(BaseModel):
    """`items` set = fix exactly these (from a GET /weak-items diagnosis the user
    picked from). Omitted = fall back to the old top-`max_items`-worst behavior, for
    callers that skip the diagnosis step entirely. `threshold` (below which a
    dimension counts as "weak") defaults to None here rather than a literal number —
    main.py resolves that against backlog_quality.WEAK_ITEM_THRESHOLD, the same bar
    run_validation's trust gate uses, so this schema can't reintroduce a second,
    disconnected magic number that drifts out of sync with it. `max_attempts`
    (defaults to None, resolved against main.py's MAX_FIX_ATTEMPTS the same way) is how
    many times a single item gets automatically retried against its own current weak
    dimensions within this one request, instead of the caller having to notice it's
    still short and ask again."""
    items: list[QualityItemSelection] | None = None
    max_items: int = 8
    threshold: int | None = None
    max_attempts: int | None = None


class TaskCreateRequest(BaseModel):
    story_id: int
    title: str = Field(min_length=1, max_length=250)
    description: str = ""
    definition_of_done: str = ""
    estimate_hours: str = ""
    dependencies: list[str] = []
    priority: Literal["critical", "high", "medium", "low"] = "medium"


class RedmineConnectionRequest(BaseModel):
    redmine_url: str
    redmine_api_key: str


class RedmineProjectCreateRequest(RedmineConnectionRequest):
    name: str
    identifier: str | None = None
    description: str = ""
    parent_project_ref: str | None = None
    is_public: bool = True
    inherit_members: bool = False


class RedminePushRequest(BaseModel):
    generation_id: int | None = None
    output: dict | None = None
    redmine_url: str
    redmine_api_key: str
    redmine_project_id: str
    # Scope the push to one epic and everything under it (used by the "push
    # this" action from an epic/story/task detail view) instead of the whole
    # backlog. Only meaningful together with generation_id — see
    # _scope_output_to_epic in main.py.
    epic_id: str | None = None


class ProjectSettings(BaseModel):
    """Per-project settings (instructions + auto-push). Repo selection lives
    on ProjectRepo (a project can hold N repos), not here."""
    project_id: int
    custom_instructions: str | None = None
    auto_push_bitbucket: bool = False
    # Set once so the push dialog doesn't have to re-ask which Redmine
    # project to target every time — Redmine's url/api_key still only ever
    # live in the browser (see redmine/client.py), this is just the target id.
    default_redmine_project_id: str | None = None
    # Opt-in for the multi-chapter wiki pipeline (app/services/wiki_chapters.py).
    # Default False: the flat single-page wiki stays the default for every
    # project — see the staged rollout plan in wiki_chapters.py's module docstring.
    chapter_wiki_enabled: bool = False


class ProjectSettingsUpdate(BaseModel):
    """All-optional — only fields actually present in the request body get
    updated (see main.py's use of model_dump(exclude_unset=True), same
    pattern as EpicEditRequest)."""
    custom_instructions: str | None = None
    auto_push_bitbucket: bool | None = None
    default_redmine_project_id: str | None = None
    chapter_wiki_enabled: bool | None = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    ticket_prefix: str = Field(default="", max_length=10)


class ProjectUpdateRequest(BaseModel):
    """All-optional partial update, same exclude_unset contract as
    ProjectSettingsUpdate."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    ticket_prefix: str | None = Field(default=None, max_length=10)


class ProjectRepoCreateRequest(BaseModel):
    workspace: str = Field(min_length=1)
    repo_slug: str = Field(min_length=1)
    label: str = ""
    # Whether to attempt a connectivity check against Bitbucket right away —
    # "init the repo" — a failure still creates the row (best-effort, never
    # blocks linking a repo the token doesn't have access to yet).
    verify: bool = True
    # Branch that VAPT scans and repo-context reads snapshot. Blank = use
    # the repo's Bitbucket-configured mainbranch.
    scan_branch: str | None = None


class ProjectRepoUpdateRequest(BaseModel):
    """All-optional partial update, same exclude_unset contract as
    ProjectUpdateRequest. Changing workspace or repo_slug clears
    verified_at — the old verification no longer speaks to the new repo."""
    workspace: str | None = Field(default=None, min_length=1)
    repo_slug: str | None = Field(default=None, min_length=1)
    label: str | None = None
    scan_branch: str | None = None


class ProjectRepo(BaseModel):
    id: int
    label: str | None = None
    workspace: str
    repo_slug: str
    scan_branch: str | None = None
    verified_at: str | None = None
    created_at: str


class ProjectGenerationSummary(BaseModel):
    id: int
    created_at: str
    project_name: str | None = None


class Project(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: str
    ticket_prefix: str | None = None


class ProjectListItem(Project):
    repo_count: int = 0
    generation_count: int = 0


class ProjectDetail(Project):
    repos: list[ProjectRepo] = []
    generations: list[ProjectGenerationSummary] = []


BusinessContextKind = Literal[
    "problem_statement", "competitive_landscape", "proposed_solution",
    "objective", "stakeholder", "scope_boundary", "success_metric",
]


class KnowledgeEntry(BaseModel):
    """A user-authored fact grounding AI generation in domain knowledge the
    repo/brief can't express on its own — cited as "[KB-<id>]" in wiki
    sections the same way code evidence is cited as path:line (see
    app/services/knowledge_base.py, app/services/wiki_generator.py).
    `sdlc_area` is one of app/services/knowledge_base.SDLC_AREAS's 15
    canonical names when it was tagged at extraction time, else None (shown
    grouped as "Other" in the UI). `business_context_kind` is set only when
    `sdlc_area == "Business Context"` — that one area uses its own
    objective/stakeholder/scope_boundary/success_metric breakdown in place
    of entry_type's generic glossary/rule/decision/constraint, matching the
    reference extraction table's own structure for that row; every other
    area leaves this None and keeps using entry_type as usual."""
    id: int
    project_id: int
    entry_type: Literal["glossary", "rule", "decision", "constraint"]
    title: str
    sdlc_area: str | None = None
    business_context_kind: BusinessContextKind | None = None
    body: str
    created_at: str
    updated_at: str


class KnowledgeEntryCreateRequest(BaseModel):
    entry_type: Literal["glossary", "rule", "decision", "constraint"] = "glossary"
    title: str = Field(min_length=1, max_length=200)
    sdlc_area: str | None = None
    business_context_kind: BusinessContextKind | None = None
    body: str = Field(min_length=1, max_length=4000)


class KnowledgeEntryUpdateRequest(BaseModel):
    """All-optional partial update, same exclude_unset contract as
    ProjectRepoUpdateRequest."""
    entry_type: Literal["glossary", "rule", "decision", "constraint"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    sdlc_area: str | None = None
    business_context_kind: BusinessContextKind | None = None
    body: str | None = Field(default=None, min_length=1, max_length=4000)


class KnowledgeCandidate(BaseModel):
    """One section parsed out of an uploaded knowledge-base template
    (app/services/knowledge_base.py's parse_knowledge_markdown), staged for
    the user to review/edit/drop before anything is actually saved as a
    KnowledgeEntry — see the /knowledge/extract endpoint. `sdlc_area` is one
    of app/services/knowledge_base.SDLC_AREAS's 15 canonical names when the
    source tagged the heading with one (or the model returned one for
    extract-from-repo), else None — the frontend groups the review screen by
    this field, falling back to an "Other" group when it's absent."""
    entry_type: Literal["glossary", "rule", "decision", "constraint"]
    title: str
    sdlc_area: str | None = None
    business_context_kind: BusinessContextKind | None = None
    body: str
    # A code citation (a file path, optionally :line) backing this fact —
    # kept out of "body" so the reviewer sees plain business prose, not a
    # sentence with a citation trailing it. Present when the source tagged
    # it with a "Source: path" line, or the model returned repo evidence.
    source: str | None = None
    needs_info: bool
    reason: str | None = None


class KnowledgeExtractResponse(BaseModel):
    candidates: list[KnowledgeCandidate]
    gap_count: int


class ProjectBriefFromRepoRequest(BaseModel):
    """Whatever the user already has in the brief editor, if anything — the
    generated brief reconciles it with the project's linked repositories
    (see app/services/repo_brief.py) rather than discarding it."""
    existing_brief: str = ""


class SprintPlanRequest(BaseModel):
    name: str
    objective: str = ""
    start_date: str
    end_date: str
    capacity_hours: float = Field(default=0, ge=0)
    story_ids: list[str] = []
    status: Literal["draft", "approved", "active", "completed"] = "draft"


class WikiPageSection(BaseModel):
    heading: str
    body: str


class WikiGenerationRequest(BaseModel):
    clarification_answers: dict[str, str] = {}


class WikiPage(BaseModel):
    id: int
    project_id: int
    repo_id: int | None = None
    title: str
    summary: str
    sections: list[WikiPageSection] = []
    generated_at: str
    created_at: str


class PublishReviewRequest(BaseModel):
    """Explicit confirmation gate for writing an AI review to Bitbucket."""
    confirm: bool = False


class PRSecurityScanRequest(BaseModel):
    """POST body for triggering a PR Impact Security Analysis scan."""
    pull_request_id: str


class BitbucketPushRequest(BaseModel):
    generation_id: int | None = None
    output: dict | None = None
    epic_id: str | None = None
    # Target a specific repo when the generation's project has more than
    # one linked repo; omitted = the project's default repo (or env
    # fallback if the project has none).
    repo_id: int | None = None


class AssistantChatRequest(BaseModel):
    message: str
    # Rolling window of prior turns ({"role": "user"|"assistant", "content": "..."}), used only
    # for pronoun/reference resolution ("mark it done") — the assistant is otherwise stateless.
    history: list[dict[str, str]] = []
    # Redmine connection, reused from the same saved config the Redmine modal uses. Optional so
    # chitchat/generate_backlog turns work before Redmine is ever connected.
    redmine_url: str = ""
    redmine_api_key: str = ""
    redmine_project_id: str = ""
    # The most recent generation this session, if any — resolved server-side (not trusted from
    # the client) to decide whether "push that to Redmine" is currently possible.
    generation_id: int | None = None
    # Set together on the follow-up call after the user confirms a create/update action the
    # previous turn flagged with requires_confirmation — pending_action is echoed back verbatim.
    confirm: bool = False
    pending_action: dict | None = None


class AssistantChatResponse(BaseModel):
    reply: str
    action: Literal["none", "trigger_generation", "trigger_push"] = "none"
    # Set when action == "trigger_generation" — the brief text for the frontend to hand to the
    # existing /generate-stream flow.
    generation_text: str | None = None
    issues: list[dict] | None = None
    issue: dict | None = None
    requires_confirmation: bool = False
    pending_action: dict | None = None
    warnings: list[str] | None = None
