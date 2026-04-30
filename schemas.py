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


class Task(BaseModel):
    id: str
    title: str
    description: str
    definition_of_done: str
    estimate_hours: str
    dependencies: list[str]
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


class OverallMetrics(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    gap_count: int
    input_quality: Literal["high", "medium", "low"]
    story_metrics: StoryMetrics
    task_metrics: TaskMetrics
    confidence_summary: str


class GenerationOutput(BaseModel):
    needs_clarification: bool
    clarifying_questions: list[ClarifyingQuestion]
    epics: list[Epic] = []
    stories: list[Story]
    tasks: list[Task]
    gaps: list[Gap]
    metrics: OverallMetrics | None = None


class GenerateRequest(BaseModel):
    text: str
    clarification_answers: dict[str, str] = {}


class ClarifyRequest(BaseModel):
    original_input: str
    questions: list[ClarifyingQuestion]
    answers: dict[str, str]


class StatusUpdateRequest(BaseModel):
    status: str


class AssigneeUpdateRequest(BaseModel):
    assignee: str | None = None


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
