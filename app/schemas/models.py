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
    id: str
    title: str
    test_type: Literal["unit", "integration", "e2e"]
    description: str
    test_code: str
    expected_result: str
    assertion: str


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
    assertion_quality_score: int = Field(ge=0, le=100)
    edge_case_coverage_score: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class OverallMetrics(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    gap_count: int
    input_quality: Literal["high", "medium", "low"]
    story_metrics: StoryMetrics
    task_metrics: TaskMetrics
    test_metrics: TestMetrics | None = None
    confidence_summary: str


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
