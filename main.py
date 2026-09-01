import json
import os
import re
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.utils.error_handler import (
    AppError,
    ValidationError,
    RateLimitError,
    APIError,
    DatabaseError,
    FileError,
    GenerationError,
    ErrorSeverity,
    log_error,
    log_info,
    log_warning,
    log_debug,
    format_error_for_sse,
    safe_exc,
)
from app.utils.rate_limit import enforce_rate_limit, GENERATE_LIMIT_PER_MINUTE, CLARIFY_LIMIT_PER_MINUTE, ASSISTANT_LIMIT_PER_MINUTE
from app.services.metrics import compute_metrics, run_validation, score_single_story, score_single_task
from app.services.prompt import (
    SYSTEM_PROMPT,
    prepare_user_message,
    CLARIFY_CHECK_SYSTEM,
    ASSISTANT_ROUTER_SYSTEM,
    CHANGE_REQUEST_SYSTEM,
    build_clarify_check_message,
    build_assistant_router_message,
)
from app.core.rule_based_generator import (
    generate_rule_based_output,
    looks_like_structured_brief,
    validate_backlog_depth,
    MIN_EPICS,
    MIN_STORIES_PER_EPIC,
    MIN_TASKS_PER_STORY,
)
from app.services.providers import (
    get_provider, list_ui_providers, select_ui_provider, refresh_provider_status,
    estimate_call_cost_usd, AllProvidersExhaustedError,
)
from app.services.generators import (
    EpicGenerator,
    StoryGenerator,
    TaskGenerator,
    TestCaseGenerator,
    GenerationPipeline,
    EPIC_CONCURRENCY,
    TASKS_PER_TEST_BATCH,
    _parse_json_array,
)
from app.services.langgraph_pipeline import LangGraphGenerationPipeline, run_pr_security_review, run_security_review
from app.services.code_review_graph import run_code_review
from app.services.related_repo_context import build_related_repo_context_block
from app.services.vapt import create_repository_snapshot, run_deterministic_scan
from app.services.repo_intelligence import INDEX_VERSION as REPO_INDEX_VERSION, index_repository, repository_index_from_dict
from app.services.security.baseline import baseline_fingerprints, classify_against_baseline, select_baseline
from app.services.security.context_budget import TruncationRecord, default_budget
from app.services.security.correlation import RELATION_UNRELATED, correlate_finding, merge_correlated_findings
from app.services.security.fingerprint import fingerprint_finding
from app.services.security.impact_graph import build_impact_graph, enrich_with_security_context
from app.services.security.pr_diff import fetch_pull_request_diff
from app.services.security.pr_llm_context import build_pr_review_context
from app.services.security.pr_symbols import build_fallback_change_summary, map_pr_changes_to_symbols
from app.services.security.related_code import find_security_context
from bitbucket.client import (
    BitbucketConfig,
    BitbucketWritesDisabledError,
    build_repo_context_block,
    get_pull_request,
    get_pull_request_diff,
    push_backlog_to_bitbucket,
    validate_bitbucket_url,
)
from app.utils.sse import sse as _sse
from app.utils.text_parsing import clean_raw as _clean_raw
from app.schemas.models import GenerateRequest, GenerationOutput, TokenUsage
from app.services.database import (init_db, save_generation, save_generation_normalized, list_generations,
                      extract_project_name,
                      get_generation, delete_generation, get_generation_hierarchy, get_dashboard_stats,
                      get_all_projects, update_epic_status, update_story_status, update_task_status,
                      update_task_assignee, update_epic_redmine_id, update_story_redmine_id,
                      update_task_redmine_id, save_stories_only, save_tasks_only, save_test_cases,
                      sync_task_dependencies,
                      get_epic_id_map, get_story_id_map, get_task_id_map, update_generation_output,
                      update_epic_priority, update_story_priority, update_task_priority,
                      update_epic_content, update_story_content, update_task_content,
                      create_epic, create_story, create_task, delete_epic, delete_story, delete_task,
                      update_epic_bitbucket_id, update_story_bitbucket_id, update_task_bitbucket_id,
                      get_project_settings, list_knowledge_entries,
                      get_project, get_generation_project_id)
from app.services.knowledge_base import format_knowledge_context
from app.services.database import save_generation_with_backlog
from app.services.database import record_token_usage, get_token_usage_summary, list_token_usage
from app.services.database import (
    create_security_scan, get_repository_index, get_security_scan,
    list_security_findings, save_repository_index, save_security_findings, update_security_scan,
)
from app.services.export import generate_excel
from redmine.client import (
    RedmineConfig,
    create_redmine_project,
    create_single_issue,
    describe_redmine_workspace,
    get_issue,
    list_issues,
    push_to_redmine,
    update_issue_fields,
    validate_redmine_url,
)
from app.core.backlog_quality import normalize_task_dependencies, find_weak_items, WEAK_ITEM_THRESHOLD
from app.schemas.models import (
    AssigneeUpdateRequest,
    AssistantChatRequest,
    AssistantChatResponse,
    BitbucketPushRequest,
    ClarifyChatRequest,
    EpicCreateRequest,
    EpicEditRequest,
    ImproveQualityRequest,
    PriorityUpdateRequest,
    ProviderSelectRequest,
    RedmineConnectionRequest,
    RedmineProjectCreateRequest,
    RedminePushRequest,
    StatusUpdateRequest,
    StoryEditRequest,
    StoryCreateRequest,
    TaskCreateRequest,
    TaskEditRequest,
)
from app.services.brief_upload import SUPPORTED_UPLOAD_EXTENSIONS, extract_uploaded_brief_text
from app.api.providers import router as providers_router
from app.api.operations import router as operations_router
from app.api.jobs import router as jobs_router
from app.api.history import router as history_router
from app.api.bitbucket import router as bitbucket_router
from app.api.webhooks import router as webhooks_router
from app.api.projects import router as projects_router
from app.api.integrations import router as integrations_router
from app.api.usage import router as usage_router
from app.services.telemetry import record_request
from app.services.jobs import configure_runner, recover_jobs
from app.services.backlog_service import generation_output_from_row as _service_generation_output_from_row, rescored_output as _service_rescored_output

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    recovered = recover_jobs()
    if recovered:
        log_info("Jobs", f"Recovered {recovered} interrupted job(s)")
    yield


app = FastAPI(title="Story & Task Generator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(providers_router)
app.include_router(operations_router)
app.include_router(jobs_router)
app.include_router(history_router)
app.include_router(bitbucket_router)
app.include_router(webhooks_router)
app.include_router(projects_router)
app.include_router(integrations_router)
app.include_router(usage_router)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    """Attach a correlation id and one structured completion log per request.

    Bodies and headers are intentionally excluded because they may contain briefs or
    Redmine credentials. The id is returned to clients so a reported failure can be
    matched to server logs without exposing sensitive content.
    """
    request_id = request.headers.get("X-Request-ID", "").strip()[:100] or str(uuid.uuid4())
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        log_error("HTTP", "Unhandled request failure", request_id=request_id, method=request.method, path=request.url.path)
        raise
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    route = getattr(request.scope.get("route"), "path", request.url.path)
    record_request(request.method, route, response.status_code, elapsed_ms)
    response.headers["X-Request-ID"] = request_id
    log_info(
        "HTTP",
        "Request completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response

# Initialize database
init_db()

# EPIC_CONCURRENCY / TASKS_PER_TEST_BATCH now live in app/services/generators.py
# (the module that actually uses them) — imported above, re-read here by
# /estimate-tokens to predict the real call count the pipeline will make.

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "5")) * 1_000_000
# How many back-and-forth rounds the clarify-chat loop will run before it
# forces itself to stop and generate anyway, regardless of what the model asks.
MAX_CLARIFY_ROUNDS = int(os.getenv("MAX_CLARIFY_ROUNDS", "3"))
# How many /generations/{id}/improve-quality _generate_content_change calls run at
# once. Each targeted fix is one independent AI call — running them one at a time
# was the actual bottleneck on a large selection (30+ items sequentially could take
# minutes). Same idea as generators.py's EPIC_CONCURRENCY, kept as its own knob here
# since it's a different endpoint with a different call shape.
IMPROVE_QUALITY_CONCURRENCY = int(os.getenv("IMPROVE_QUALITY_CONCURRENCY", "6"))
# How many times /generations/{id}/improve-quality will automatically retry a single
# item against its *current* weak dimensions before giving up on it for this request.
# A rewrite clearing some dimensions but not others (moving 61% to 75% against an 80%
# bar, say) used to just sit there until the user noticed and clicked "Fix" again
# themselves — this closes that loop within one request instead of making it manual.
MAX_FIX_ATTEMPTS = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
# Pause between rounds when the last one hit transient provider errors. Sized to clear
# LiteLLMProvider._EXHAUSTION_COOLDOWN_SECONDS (20s) — retrying inside that window just
# trips the same circuit breaker and spends the remaining attempts for nothing.
TRANSIENT_RETRY_BACKOFF_SECONDS = float(os.getenv("TRANSIENT_RETRY_BACKOFF_SECONDS", "21"))
# Selects the one-click pipeline's orchestration engine: the hand-written
# GenerationPipeline (app/services/generators.py) or the LangGraph-wrapped
# equivalent (app/services/langgraph_pipeline.py) — see that module's
# docstring for the streaming-granularity trade-off. Only affects
# _three_phase_generate below; the step-by-step endpoints call each
# PhaseGenerator directly regardless of this flag, since there's no
# multi-phase orchestration to swap for a single isolated phase.
GENERATION_ENGINE = os.getenv("GENERATION_ENGINE", "legacy").strip().lower()

BASE_DIR = Path(__file__).resolve().parent
BRIEF_RESOURCE_FILES = {
    "project_template": BASE_DIR / "docs" / "PROJECT_BRIEF_EXAMPLE.md",
    "extract_docs_prompt": BASE_DIR / "prompts" / "EXTRACT_FROM_DOCS.md",
    "extract_repo_prompt": BASE_DIR / "prompts" / "EXTRACT_FROM_REPO.md",
}


def _stream_generate_from_file(text: str):
    """Stream generation for uploaded files and keep the extracted text available client-side."""
    yield _sse("input", {"text": text})
    yield from _stream_generate(text, {})


def _with_bitbucket_context(text: str, bitbucket_repo: str | None) -> str:
    """Prepend a bounded repo-context block to the brief when the request
    opts in via bitbucket_repo (GenerateRequest.bitbucket_repo). Bitbucket
    not configured, the path not found, or any fetch failure all degrade to
    returning `text` unchanged — this must never block generation."""
    if not bitbucket_repo:
        return text
    config = BitbucketConfig.from_env()
    if not config.is_configured():
        return text
    context_block = build_repo_context_block(config, path=bitbucket_repo)
    return f"{context_block}\n\n{text}" if context_block else text


def _bitbucket_config_for_project(project_id: int | None, repo_id: int | None = None) -> BitbucketConfig:
    """BitbucketConfig.from_env(), with workspace/repo_slug overridden by
    one of the project's linked repos (app/services/database.py's
    project_repos — a project can hold N repos, e.g. frontend/backend).
    `repo_id` picks a specific one; omitted uses the first repo linked to
    the project (there's no "default" marking — just link order). Falls
    back to the bare env config when project_id is None or the project has
    no linked repos at all — access token and base URL always stay
    env-only, no per-project secret storage introduced."""
    config = BitbucketConfig.from_env()
    if project_id is None:
        return config
    project = get_project(project_id)
    repos = (project or {}).get("repos", [])
    if repo_id is not None:
        repo = next((r for r in repos if r["id"] == repo_id), None)
    else:
        repo = repos[0] if repos else None
    if repo:
        config.workspace = repo["workspace"]
        config.repo_slug = repo["repo_slug"]
    return config


def _with_project_instructions(text: str, gen_id: int) -> str:
    """Prepend the generation's project's saved custom_instructions
    (project_settings) and knowledge base entries (project_knowledge_entries),
    if any — same bounded-injection pattern as _with_bitbucket_context. Only
    callable once a generation already exists (a gen_id) and belongs to a
    project, so this only ever applies to step-by-step phases resuming an
    existing generation, never the first (epics) call of a brand-new one.

    The knowledge base (app/services/knowledge_base.py) grounds epics/
    stories/tasks/tests in domain facts the brief/repo alone can't express —
    the same anti-hallucination purpose it serves for wiki generation, just
    without the [KB-n] citation requirement (backlog items aren't graded on
    per-claim evidence the way wiki sections are)."""
    project_id = get_generation_project_id(gen_id)
    if project_id is None:
        return text
    settings = get_project_settings(project_id)
    instructions = (settings.get("custom_instructions") or "").strip()
    knowledge_block = format_knowledge_context(list_knowledge_entries(project_id))
    prefix = ""
    if instructions:
        prefix += f"## Project Instructions\n\n{instructions}\n\n"
    if knowledge_block:
        prefix += f"{knowledge_block}\n\n"
    return f"{prefix}{text}" if prefix else text


def _maybe_auto_push_bitbucket(gen_id: int, output: GenerationOutput) -> dict | None:
    """Fire-and-forget auto-push, called after any phase leaves `output`
    freshly scored. No-ops (returns None) unless the generation belongs to
    a project with auto_push_bitbucket on AND the backlog is currently
    trust_level == 'trusted' — reusing the existing trust gate rather than
    inventing a separate numeric threshold. Never raises: a push failure
    here must not fail the generation/phase that triggered it."""
    if not output.validation or output.validation.trust_level != "trusted":
        return None
    project_id = get_generation_project_id(gen_id)
    if project_id is None:
        return None
    settings = get_project_settings(project_id)
    if not settings.get("auto_push_bitbucket"):
        return None
    try:
        config = _bitbucket_config_for_project(project_id)
        if not config.is_configured():
            log_warning("Bitbucket", f"Auto-push skipped for generation {gen_id}: Bitbucket not configured")
            return None
        hierarchy = get_generation_hierarchy(gen_id)
        result = push_backlog_to_bitbucket(output, config, _existing_bitbucket_ids(hierarchy) if hierarchy else None)
        if hierarchy:
            _record_bitbucket_ids(result, hierarchy)
        log_info("Bitbucket", f"Auto-pushed generation {gen_id} to Bitbucket ({config.workspace}/{config.repo_slug})")
        return result
    except Exception as e:
        log_warning("Bitbucket", f"Auto-push failed for generation {gen_id}: {type(e).__name__}: {e}")
        return None


# Thin delegates to app/services/generators.py's OOP pipeline — kept as
# module-level functions (rather than updating every call site to construct
# a generator class directly) so the step-by-step endpoints below and the
# existing test suite (tests/test_three_phase_generation.py,
# tests/test_step_generation.py) keep working unchanged. The real logic for
# each phase now lives on EpicGenerator/StoryGenerator/TaskGenerator/
# TestCaseGenerator; these just construct and run one.

def _generate_epics_phase(text: str, provider, output: GenerationOutput):
    yield from EpicGenerator(provider).run(text, output)


def _generate_stories_phase(text: str, provider, output: GenerationOutput):
    yield from StoryGenerator(provider).run(text, output)


def _generate_tasks_phase(text: str, provider, output: GenerationOutput):
    yield from TaskGenerator(provider).run(text, output)


def _generate_test_cases_phase(text: str, provider, output: GenerationOutput):
    yield from TestCaseGenerator(provider).run(text, output)


def _three_phase_generate(text: str, provider, output: GenerationOutput):
    """4-phase generation: epics → stories → tasks → test cases. Populates
    output in-place, yields SSE events. Runs all four phases back to back —
    the one-click pipeline, via GenerationPipeline (app/services/generators.py)
    or its LangGraph-orchestrated equivalent (app/services/langgraph_pipeline.py,
    selected by GENERATION_ENGINE), either of which chains the four phase
    objects together — each stage's output becomes the next stage's input
    through the shared, mutated `output`. Each phase is also independently
    callable (see /generate-epics, /generate-stories/{id}, /generate-tasks/{id},
    /generate-test-cases/{id}) for the step-by-step flow, unaffected by
    GENERATION_ENGINE — see that flag's definition above."""
    pipeline_cls = LangGraphGenerationPipeline if GENERATION_ENGINE == "langgraph" else GenerationPipeline
    yield from pipeline_cls(provider).run_all(text, output)


def _stream_generate(text: str, clarification_answers: dict, project_id: int | None = None):
    gen_started_at = time.time()
    try:
        if looks_like_structured_brief(text):
            yield _sse("status", {"step": "connecting", "message": "Compiling structured brief into a backlog…"})
            try:
                yield _sse("status", {"step": "generating", "message": "Rule-based compiler is building epics, stories, and tasks…"})
                output = generate_rule_based_output(text)
                log_info("RuleGenerator", "Structured brief compilation completed successfully")
            except Exception as e:
                error = GenerationError(
                    message=f"Rule-based compilation failed: {safe_exc(e)}",
                    phase="Rule-Based Compilation"
                )
                log_error("RuleGenerator", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
                return

            yield _sse("status", {"step": "parsing", "message": "Assembling structured output…"})
            yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
            try:
                output.metrics = compute_metrics(output)
                output.metrics.generation_seconds = round(time.time() - gen_started_at, 1)
                output.validation = run_validation(output.metrics)
                log_info("Metrics", f"Validation: {output.validation.trust_level}")
            except Exception as e:
                error = GenerationError(
                    message=f"Metrics computation failed: {safe_exc(e)}",
                    phase="Validation"
                )
                log_error("Metrics", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
                return

            try:
                gen_id = save_generation_with_backlog(text, output, project_id)
                if output.metrics and output.metrics.token_usage and output.metrics.token_usage.ai_calls:
                    record_token_usage(
                        "generation", str(gen_id), getattr(provider, "provider_id", None),
                        output.metrics.token_usage.model_dump(),
                        duration_seconds=output.metrics.generation_seconds,
                    )
                output_dict = output.model_dump()
                output_dict["generation_id"] = gen_id
                # GenerationOutput has no project_name field of its own (it's a
                # DB/history concept, not generated content) — derive it the same way
                # save_generation does, from the same `text`, so every 'done' event
                # carries it and the frontend is never mid-generation with no idea
                # what backlog this is.
                output_dict["project_name"] = extract_project_name(text)
                # Same story as project_name just above: not part of GenerationOutput itself,
                # bolted on so the frontend can show this generation's project wiki on Overview
                # without a second round trip. None for a generation that was never attached
                # to a project.
                output_dict["project_id"] = get_generation_project_id(gen_id)
                log_info("Database", f"Generation saved with ID {gen_id}")
                yield _sse("done", {"output": output_dict})
            except Exception as e:
                error = DatabaseError(
                    message=f"Failed to save generation: {safe_exc(e)}",
                    operation="save_generation"
                )
                log_error("Database", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
            return

        provider = get_provider()

        # Fold clarification answers into the brief the pipeline actually reads.
        # (clarification_answers was previously accepted here but silently
        # dropped — Phase 1 never saw it.)
        generation_text = text
        if clarification_answers:
            qa_text = "\n".join(
                f"- {q}: {a}" for q, a in clarification_answers.items() if str(a).strip()
            )
            if qa_text:
                generation_text = f"{text}\n\nClarifications:\n{qa_text}"

        # Use 3-phase generation for comprehensive backlog
        output = GenerationOutput(
            needs_clarification=False,
            clarifying_questions=[],
            epics=[],
            stories=[],
            tasks=[],
            gaps=[],
            metrics=None,
        )
        yield from _three_phase_generate(generation_text, provider, output)
        normalize_task_dependencies(output)

        # Score and save if generation succeeded
        if output.epics:
            yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
            try:
                output.metrics = compute_metrics(output)
                output.metrics.generation_seconds = round(time.time() - gen_started_at, 1)
                if hasattr(provider, "usage_summary"):
                    output.metrics.token_usage = TokenUsage(**provider.usage_summary())
                output.validation = run_validation(output.metrics)
                log_info("Metrics", f"Validation: {output.validation.trust_level}")
            except Exception as e:
                error = GenerationError(
                    message=f"Metrics computation failed: {safe_exc(e)}",
                    phase="Validation"
                )
                log_error("Metrics", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
                return

            # Save to database
            try:
                gen_id = save_generation_with_backlog(text, output, project_id)
                if output.metrics and output.metrics.token_usage and output.metrics.token_usage.ai_calls:
                    record_token_usage(
                        "generation", str(gen_id), getattr(provider, "provider_id", None),
                        output.metrics.token_usage.model_dump(),
                        duration_seconds=output.metrics.generation_seconds,
                    )
                output_dict = output.model_dump()
                output_dict["generation_id"] = gen_id
                # GenerationOutput has no project_name field of its own (it's a
                # DB/history concept, not generated content) — derive it the same way
                # save_generation does, from the same `text`, so every 'done' event
                # carries it and the frontend is never mid-generation with no idea
                # what backlog this is.
                output_dict["project_name"] = extract_project_name(text)
                # Same story as project_name just above: not part of GenerationOutput itself,
                # bolted on so the frontend can show this generation's project wiki on Overview
                # without a second round trip. None for a generation that was never attached
                # to a project.
                output_dict["project_id"] = get_generation_project_id(gen_id)
                log_info("Database", f"Generation saved with ID {gen_id}")
                yield _sse("done", {"output": output_dict})
            except Exception as e:
                error = DatabaseError(
                    message=f"Failed to save generation: {safe_exc(e)}",
                    operation="save_generation"
                )
                log_error("Database", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
        else:
            error = GenerationError(
                message="Generation failed. Please check your brief and try again.",
                phase="Epic Generation",
                user_action="Expand your brief with specific features, user roles, and goals (aim for 50+ words)."
            )
            log_warning("Generator", "Generation produced no epics")
            yield json.dumps({
                "type": "error",
                **error.to_dict()
            }) + "\n\n"
    except Exception as e:
        error = AppError(
            message=f"Unexpected error during generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("StreamGenerator", "Unhandled exception", exception=e)
        yield json.dumps({
            "type": "error",
            **error.to_dict()
        }) + "\n\n"


# ── Step-by-step generation (one phase per request) ─────────────────────────
# Alternative to the one-click _stream_generate/_three_phase_generate above —
# each phase is its own HTTP request so the UI can pause for review between
# Epics/Stories/Tasks/Test Cases. Every phase persists what it produced and
# updates the same `generations` row (via update_generation_output) so
# GET /history/{id} reflects partial progress even if the user stops early.

def _load_generation_for_resume(gen_id: int) -> tuple[str, GenerationOutput] | None:
    """Reload a generation's brief text + everything generated so far, ready
    to hand to the next phase function. GenerationOutput(**output) round-trips
    cleanly because output_json is exactly GenerationOutput.model_dump()."""
    row = get_generation(gen_id)
    if not row:
        return None
    return row["input_text"], _generation_output_from_row(row["output"])


def _stream_generate_epics(text: str, project_id: int | None = None):
    provider = get_provider()
    output = GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[],
        stories=[],
        tasks=[],
        gaps=[],
    )
    yield from _generate_epics_phase(text, provider, output)
    if not output.epics:
        return  # _generate_epics_phase already yielded an error event

    try:
        gen_id = save_generation_with_backlog(text, output, project_id)  # stories/tasks are empty — only epics get inserted
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
        # GenerationOutput has no project_name field of its own (it's a DB/history
        # concept, not generated content) — derive it the same way save_generation
        # does, from the same `text`, so every 'done' event carries it and the
        # frontend never has to be mid-generation with no idea what backlog this is.
        output_dict["project_name"] = extract_project_name(text)
        # Same story as project_name just above: not part of GenerationOutput itself,
        # bolted on so the frontend can show this generation's project wiki on Overview
        # without a second round trip. None for a generation that was never attached
        # to a project.
        output_dict["project_id"] = get_generation_project_id(gen_id)
        log_info("Database", f"Generation {gen_id} created (epics phase, {len(output.epics)} epics)")
        yield _sse("done", {"phase": "epics", "output": output_dict})
    except Exception as e:
        error = DatabaseError(message=f"Failed to save generation: {safe_exc(e)}", operation="save_generation")
        log_error("Database", str(error.message), exception=e)
        yield _sse("error", error.to_dict())


def _stream_generate_stories(gen_id: int):
    loaded = _load_generation_for_resume(gen_id)
    if not loaded:
        yield _sse("error", GenerationError(message=f"Generation {gen_id} not found.", phase="Story Generation").to_dict())
        return
    text, output = loaded
    if not output.epics:
        yield _sse("error", GenerationError(
            message="No epics found for this generation — generate epics first.",
            phase="Story Generation",
        ).to_dict())
        return

    existing_story_ids = {s.id for s in output.stories}
    provider = get_provider()
    yield from _generate_stories_phase(_with_project_instructions(text, gen_id), provider, output)
    new_stories = [s for s in output.stories if s.id not in existing_story_ids]
    if not new_stories:
        yield _sse("error", GenerationError(
            message="Story generation produced no new stories.",
            phase="Story Generation",
            user_action="Try again, or check your AI provider configuration.",
        ).to_dict())
        return

    try:
        epic_id_map = get_epic_id_map(gen_id)
        save_stories_only(gen_id, new_stories, epic_id_map)
        update_generation_output(gen_id, output)
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
        # GenerationOutput has no project_name field of its own (it's a DB/history
        # concept, not generated content) — derive it the same way save_generation
        # does, from the same `text`, so every 'done' event carries it and the
        # frontend never has to be mid-generation with no idea what backlog this is.
        output_dict["project_name"] = extract_project_name(text)
        # Same story as project_name just above: not part of GenerationOutput itself,
        # bolted on so the frontend can show this generation's project wiki on Overview
        # without a second round trip. None for a generation that was never attached
        # to a project.
        output_dict["project_id"] = get_generation_project_id(gen_id)
        log_info("Database", f"Generation {gen_id} updated ({len(new_stories)} new stories)")
        yield _sse("done", {"phase": "stories", "output": output_dict})
    except Exception as e:
        error = DatabaseError(message=f"Failed to save stories: {safe_exc(e)}", operation="save_stories_only")
        log_error("Database", str(error.message), exception=e)
        yield _sse("error", error.to_dict())


def _stream_generate_tasks(gen_id: int):
    loaded = _load_generation_for_resume(gen_id)
    if not loaded:
        yield _sse("error", GenerationError(message=f"Generation {gen_id} not found.", phase="Task Generation").to_dict())
        return
    text, output = loaded
    if not output.stories:
        yield _sse("error", GenerationError(
            message="No stories found for this generation — generate stories first.",
            phase="Task Generation",
        ).to_dict())
        return

    existing_task_ids = {t.id for t in output.tasks}
    provider = get_provider()
    yield from _generate_tasks_phase(_with_project_instructions(text, gen_id), provider, output)
    # The task generator can return prose dependencies. Normalize them into
    # real task IDs before persisting/scoring so a valid backlog doesn't land
    # in a confusing "review needed" state solely due to format mismatch.
    normalize_task_dependencies(output)
    new_tasks = [t for t in output.tasks if t.id not in existing_task_ids]
    if not new_tasks:
        yield _sse("error", GenerationError(
            message="Task generation produced no new tasks.",
            phase="Task Generation",
            user_action="Try again, or check your AI provider configuration.",
        ).to_dict())
        return

    try:
        story_id_map = get_story_id_map(gen_id)
        save_tasks_only(gen_id, new_tasks, story_id_map)
        update_generation_output(gen_id, output)
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
        # GenerationOutput has no project_name field of its own (it's a DB/history
        # concept, not generated content) — derive it the same way save_generation
        # does, from the same `text`, so every 'done' event carries it and the
        # frontend never has to be mid-generation with no idea what backlog this is.
        output_dict["project_name"] = extract_project_name(text)
        # Same story as project_name just above: not part of GenerationOutput itself,
        # bolted on so the frontend can show this generation's project wiki on Overview
        # without a second round trip. None for a generation that was never attached
        # to a project.
        output_dict["project_id"] = get_generation_project_id(gen_id)
        log_info("Database", f"Generation {gen_id} updated ({len(new_tasks)} new tasks)")
        yield _sse("done", {"phase": "tasks", "output": output_dict})
    except Exception as e:
        error = DatabaseError(message=f"Failed to save tasks: {safe_exc(e)}", operation="save_tasks_only")
        log_error("Database", str(error.message), exception=e)
        yield _sse("error", error.to_dict())


def _stream_generate_test_cases(gen_id: int):
    gen_started_at = time.time()
    loaded = _load_generation_for_resume(gen_id)
    if not loaded:
        yield _sse("error", GenerationError(message=f"Generation {gen_id} not found.", phase="Test Case Generation").to_dict())
        return
    text, output = loaded
    if not output.tasks:
        yield _sse("error", GenerationError(
            message="No tasks found for this generation — generate tasks first.",
            phase="Test Case Generation",
        ).to_dict())
        return

    provider = get_provider()
    yield from _generate_test_cases_phase(_with_project_instructions(text, gen_id), provider, output)

    try:
        save_test_cases(gen_id, output.tasks)
        yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
        output.metrics = compute_metrics(output)
        # Only measures this phase's own duration, not the whole step-by-step
        # run — each phase is a separate request with no shared start time.
        output.metrics.generation_seconds = round(time.time() - gen_started_at, 1)
        if hasattr(provider, "usage_summary"):
            usage = provider.usage_summary()
            output.metrics.token_usage = TokenUsage(**usage)
            if usage.get("ai_calls"):
                record_token_usage(
                    "generation", str(gen_id), getattr(provider, "provider_id", None), usage,
                    duration_seconds=output.metrics.generation_seconds,
                )
        output.validation = run_validation(output.metrics)
        update_generation_output(gen_id, output)
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
        # GenerationOutput has no project_name field of its own (it's a DB/history
        # concept, not generated content) — derive it the same way save_generation
        # does, from the same `text`, so every 'done' event carries it and the
        # frontend never has to be mid-generation with no idea what backlog this is.
        output_dict["project_name"] = extract_project_name(text)
        # Same story as project_name just above: not part of GenerationOutput itself,
        # bolted on so the frontend can show this generation's project wiki on Overview
        # without a second round trip. None for a generation that was never attached
        # to a project.
        output_dict["project_id"] = get_generation_project_id(gen_id)
        log_info("Database", f"Generation {gen_id} finalized (test cases + metrics)")
        done_payload = {"phase": "tests", "output": output_dict}
        auto_pushed = _maybe_auto_push_bitbucket(gen_id, output)
        if auto_pushed is not None:
            done_payload["auto_pushed"] = auto_pushed
        yield _sse("done", done_payload)
    except Exception as e:
        error = DatabaseError(message=f"Failed to save test cases: {safe_exc(e)}", operation="save_test_cases")
        log_error("Database", str(error.message), exception=e)
        yield _sse("error", error.to_dict())


@app.get("/")
def index():
    # This app is actively developed and redeployed; without an explicit
    # Cache-Control, browsers can heuristically cache this HTML and keep
    # serving a stale UI after an update with no way to tell short of a hard
    # refresh. no-cache forces revalidation (via ETag/Last-Modified) on every
    # load instead of trusting a local copy blindly.
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/app/{frontend_path:path}", include_in_schema=False)
def app_route(frontend_path: str):
    """Serve the SPA shell for route-backed frontend workspaces.
    API endpoints retain their own prefixes, while /app/backlog and friends
    are safe to bookmark or refresh directly."""
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, must-revalidate"})


@app.post("/generate-stream")
def generate_stream(request: GenerateRequest, http_request: Request):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        if not request.text.strip():
            error = ValidationError("Input text is required.")
            log_warning("API", "Empty input text provided")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        log_info("API", "Generation stream started")
        generation_text = _with_bitbucket_context(request.text, request.bitbucket_repo)
        return StreamingResponse(
            _stream_generate(generation_text, request.clarification_answers or {}, request.project_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except RateLimitError as error:
        log_warning("API", "Rate limit hit on /generate-stream")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message=f"Failed to start generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-stream", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


# ── Step-by-step generation endpoints ────────────────────────────────────
# Alongside /generate-stream (the one-click flow above), these let the UI
# run one phase at a time: POST /generate-epics to start, then feed the
# returned generation_id into /generate-stories/{id} -> /generate-tasks/{id}
# -> /generate-test-cases/{id} in order, reviewing between each call.

@app.post("/generate-epics")
def generate_epics(request: GenerateRequest, http_request: Request):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        if not request.text.strip():
            error = ValidationError("Input text is required.")
            log_warning("API", "Empty input text provided")
            return JSONResponse(status_code=400, content=error.to_dict())
        log_info("API", "Step-by-step generation started (epics)")
        return StreamingResponse(
            _stream_generate_epics(request.text, request.project_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except RateLimitError as error:
        log_warning("API", "Rate limit hit on /generate-epics")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message=f"Failed to start epic generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-epics", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/generate-stories/{gen_id}")
def generate_stories(gen_id: int, http_request: Request):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        log_info("API", f"Step-by-step generation started (stories) for generation {gen_id}")
        return StreamingResponse(
            _stream_generate_stories(gen_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except RateLimitError as error:
        log_warning("API", "Rate limit hit on /generate-stories")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message=f"Failed to start story generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-stories", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/generate-tasks/{gen_id}")
def generate_tasks(gen_id: int, http_request: Request):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        log_info("API", f"Step-by-step generation started (tasks) for generation {gen_id}")
        return StreamingResponse(
            _stream_generate_tasks(gen_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except RateLimitError as error:
        log_warning("API", "Rate limit hit on /generate-tasks")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message=f"Failed to start task generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-tasks", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/generate-test-cases/{gen_id}")
def generate_test_cases(gen_id: int, http_request: Request):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        log_info("API", f"Step-by-step generation started (test cases) for generation {gen_id}")
        return StreamingResponse(
            _stream_generate_test_cases(gen_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except RateLimitError as error:
        log_warning("API", "Rate limit hit on /generate-test-cases")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message=f"Failed to start test case generation: {safe_exc(e)}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-test-cases", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/generate-from-file-stream")
async def generate_from_file_stream(http_request: Request, file: UploadFile = File(...)):
    try:
        enforce_rate_limit(http_request, bucket="generate", limit=GENERATE_LIMIT_PER_MINUTE)
        filename = file.filename or ""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
            error = ValidationError("Only .md and .docx files are accepted.")
            log_warning("FileUpload", f"Invalid file type: {file.filename}")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            error = ValidationError(
                f"File is too large ({len(content) / 1_000_000:.1f}MB). "
                f"Max size is {MAX_UPLOAD_BYTES / 1_000_000:.0f}MB."
            )
            log_warning("FileUpload", f"Rejected oversized upload: {file.filename} ({len(content)} bytes)")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        try:
            text = extract_uploaded_brief_text(filename, content)
        except ValueError as exc:
            error = ValidationError(str(exc))
            log_warning("FileUpload", f"Failed to read uploaded file: {file.filename}")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        if not text:
            error = ValidationError("Uploaded file is empty or has no readable text.")
            log_warning("FileUpload", "Empty file uploaded")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        log_info("FileUpload", f"File uploaded: {file.filename} ({len(text)} chars)")
        return StreamingResponse(
            _stream_generate_from_file(text),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except RateLimitError as error:
        log_warning("FileUpload", "Rate limit hit on /generate-from-file-stream")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = FileError(
            message=f"Failed to process uploaded file: {safe_exc(e)}",
            filename=file.filename
        )
        log_error("FileUpload", "Error processing file", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/extract-brief")
async def extract_brief_endpoint(file: UploadFile = File(...)):
    """Extract an uploaded brief so it can enter the shared clarification flow."""
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
        return JSONResponse(status_code=400, content={"message": "Only .md and .docx files are accepted."})
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=400, content={"message": "Uploaded file is too large."})
    try:
        text = extract_uploaded_brief_text(filename, content)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})
    if not text.strip():
        return JSONResponse(status_code=400, content={"message": "Uploaded file has no readable text."})
    return {"text": text}


@app.post("/clarify-chat")
def clarify_chat_endpoint(request: ClarifyChatRequest, http_request: Request):
    """One round of the pre-generation clarify loop: given the brief and the
    Q&A so far, either ask more focused questions or say it's ready. Bounded
    by MAX_CLARIFY_ROUNDS so the loop always terminates."""
    try:
        enforce_rate_limit(http_request, bucket="clarify", limit=CLARIFY_LIMIT_PER_MINUTE)

        text = (request.text or "").strip()
        if not text:
            error = ValidationError("Input text is required.")
            return JSONResponse(status_code=400, content=error.to_dict())

        round_number = len(request.qa_history) + 1

        if round_number > MAX_CLARIFY_ROUNDS:
            log_info("ClarifyChat", f"Round {round_number} exceeds cap ({MAX_CLARIFY_ROUNDS}), forcing ready")
            return JSONResponse(content={"needs_clarification": False, "questions": [], "round": round_number})

        provider = get_provider()
        raw = provider.generate(CLARIFY_CHECK_SYSTEM, build_clarify_check_message(text, request.qa_history))
        try:
            data = json.loads(_clean_raw(raw))
        except json.JSONDecodeError:
            log_debug("ClarifyChat", "Failed to parse clarify-check response, defaulting to ready")
            data = {}

        questions = []
        if isinstance(data, dict):
            for q in (data.get("questions") or [])[:4]:
                if isinstance(q, dict) and q.get("question", "").strip():
                    questions.append({
                        "question": q.get("question", "").strip(),
                        "why_it_matters": q.get("why_it_matters", "").strip(),
                    })

        needs_clarification = bool(isinstance(data, dict) and data.get("needs_clarification")) and bool(questions)

        # Last allowed round: stop asking even if the model wants to keep going.
        if needs_clarification and round_number >= MAX_CLARIFY_ROUNDS:
            log_info("ClarifyChat", f"Round {round_number} hit cap after model asked more — forcing ready")
            needs_clarification = False
            questions = []

        log_info("ClarifyChat", f"Round {round_number}: needs_clarification={needs_clarification}, {len(questions)} question(s)")
        return JSONResponse(content={
            "needs_clarification": needs_clarification,
            "questions": questions,
            "round": round_number,
        })
    except RateLimitError as error:
        log_warning("ClarifyChat", "Rate limit hit on /clarify-chat")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = APIError(
            provider=os.getenv("AI_PROVIDER", "unknown"),
            message=f"Clarification check failed: {safe_exc(e)}",
        )
        log_error("ClarifyChat", "Error in /clarify-chat", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


def _assistant_generation_context(generation_id: int | None) -> dict:
    """Whether a backlog exists this session and whether it already passed the trust gate,
    read from the saved generation (not trusted from the client) — used both to inform the
    router prompt and to gate the push_backlog intent server-side. Also carries the full
    DB-backed hierarchy (epics/stories/tasks with real ids) when one exists — the router prompt
    only surfaces epic titles from it (see build_assistant_router_message), but change_request
    dispatch needs the whole thing to resolve a story/task reference and to hand the matched
    item's current field values to _generate_content_change."""
    if not generation_id:
        return {"has_output": False, "trusted": False, "hierarchy": None}
    gen = get_generation(generation_id)
    if not gen:
        return {"has_output": False, "trusted": False, "hierarchy": None}
    # Rescored, not read straight off the stored blob: this trust_level is what gates
    # the push_backlog intent server-side, so a verdict frozen under an older pass bar
    # would keep authorizing a backlog that no longer clears the current one.
    stored_output = gen.get("output")
    validation = (_rescored_output_dict(stored_output) if isinstance(stored_output, dict) else {}).get("validation") or {}
    hierarchy = get_generation_hierarchy(generation_id)
    return {
        "has_output": True,
        "trusted": validation.get("trust_level") == "trusted",
        "hierarchy": hierarchy,
        "brief_text": gen.get("input_text") or "",
    }


EDITABLE_FIELDS: dict[str, list[str]] = {
    "epic": ["title", "description", "feature_area"],
    # "size" is included so a targeted quality fix (see find_weak_items's "sizing"
    # dimension) can correct a size label that no longer matches the story's AC
    # count/length — the assistant's change_request flow never asks for it, but
    # _generate_content_change ignores any field the caller doesn't put in play.
    "story": ["title", "as_a", "i_want", "so_that", "acceptance_criteria", "feature_area", "size"],
    "task": ["title", "description", "definition_of_done", "estimate_hours", "dependencies"],
}

# Fields in EDITABLE_FIELDS whose schema type is a closed Literal, not a free string —
# _generate_content_change's model call returns plain JSON with no schema enforcement
# of its own, so a value outside these sets (e.g. "Large" or "extra-large" for a field
# that must be exactly "small"/"medium"/"large") would otherwise get applied via
# setattr() with no validation, silently corrupting the in-memory Story/Task object.
# model_dump()/JSON serialization don't validate either, so it would write happily to
# both the DB and output_json — the corruption only surfaces the *next* time that
# generation is reloaded, when GenerationOutput(**row["output"]) re-validates and
# rejects it, 500ing every endpoint that touches that generation until it's repaired.
# See _sanitize_generation_output_dict for repairing a generation already corrupted
# this way before this check existed.
CONSTRAINED_FIELD_VALUES: dict[tuple[str, str], set[str]] = {
    ("story", "size"): {"small", "medium", "large"},
}


def _sanitize_generation_output_dict(raw: dict) -> dict:
    """Repairs a stored output_json dict in place before it's validated into a
    GenerationOutput — specifically, any story whose "size" isn't exactly
    "small"/"medium"/"large" (case differences tolerated) gets defaulted to
    "medium". This is recovery for data written before CONSTRAINED_FIELD_VALUES
    existed to prevent it: without this, a generation corrupted that way stays
    permanently broken — every endpoint that reloads it (weak-items, improve-quality,
    repair-dependencies, export, Redmine push) 500s on Pydantic validation forever,
    since nothing ever gets the chance to write a valid value back. Mutates and
    returns `raw` so a caller can pass it straight into GenerationOutput(**...)."""
    for story in raw.get("stories") or []:
        if not isinstance(story, dict):
            continue
        size = str(story.get("size", "")).strip().lower()
        if size not in {"small", "medium", "large"}:
            story["size"] = "medium"
    return raw


def _generation_output_from_row(output_dict: dict) -> GenerationOutput:
    """GenerationOutput(**output_dict), but tolerant of a *stored* output_json that
    predates constrained-value enforcement (see _sanitize_generation_output_dict) —
    use this rather than calling GenerationOutput(...) directly wherever a saved
    generation's output is being reloaded from the DB."""
    return _service_generation_output_from_row(output_dict)


def _rescored_output_dict(output_dict: dict) -> dict:
    """A stored output_json with its metrics and validation recomputed from the
    content that's actually in it, rather than served as they were frozen at
    generation time.

    Both are pure, deterministic functions of the backlog (compute_metrics /
    run_validation) — there is nothing in them worth trusting a stale copy of. And a
    stale copy actively lies once the pass bar moves: a generation scored when the
    bar was 70 keeps reporting "5/5 checks passed · Story Quality 76% (>= 70%)"
    forever, while the Scorecard beside it — which reads the *current*
    QUALITY_PASS_THRESHOLD — puts a "Fix" link on every dimension under 80 and the
    weak-items panel lists dozens of items to fix. Same backlog, two verdicts.

    It also matters beyond cosmetics: trust_level is what gates the Redmine push
    (see _assistant_generation_context), so a frozen "trusted" would keep waving
    through a backlog that no longer clears the bar.

    Falls back to the stored dict untouched if it can't be scored — this runs on
    read paths that previously did no validation at all, and a generation that
    renders today must not start erroring because its scores couldn't be refreshed."""
    return _service_rescored_output(output_dict)


def _flatten_hierarchy_items(hierarchy: dict) -> list[dict]:
    """Every epic/story/task in a hierarchy as one flat list, each tagged with its own
    `kind` — the pool change_request target resolution searches over."""
    items = []
    for epic in hierarchy.get("epics") or []:
        items.append({**epic, "kind": "epic"})
        for story in epic.get("stories") or []:
            items.append({**story, "kind": "story"})
            for task in story.get("tasks") or []:
                items.append({**task, "kind": "task"})
    return items


def _resolve_change_target(hierarchy: dict, target_id: str | None, target_hint: str) -> dict | list[dict] | None:
    """Resolve a change_request's target against the real backlog — locally, by id or title
    match, not via the LLM — so resolution stays correct (and cheap) no matter how many
    stories/tasks exist; the router prompt only ever sees epic titles (see
    build_assistant_router_message), never the full list. Returns the single matching item, a
    short list of candidates when the hint matches more than one item, or None when nothing did."""
    items = _flatten_hierarchy_items(hierarchy)

    if target_id:
        tid = str(target_id).strip().lstrip("#").upper()
        for item in items:
            if (item.get("ai_id") or "").upper() == tid or str(item.get("issue_id") or "").upper() == tid:
                return item

    hint = (target_hint or "").strip().lower()
    if not hint:
        return None
    exact = [item for item in items if item["title"].lower() == hint]
    if len(exact) == 1:
        return exact[0]
    contains = [item for item in items if hint in item["title"].lower() or item["title"].lower() in hint]
    if len(contains) == 1:
        return contains[0]
    if contains:
        return contains[:5]
    return None


def _generate_content_change(target: dict, change_description: str, provider=None) -> dict:
    """One provider call turning a free-form change_description into a structured field diff
    for the resolved item — the one genuinely new LLM call this intent needs, since the router
    call above only extracts what to find and what was asked for, not the resulting content.

    `provider` lets a caller making many of these calls share ONE provider instance across
    them. That matters more than it looks: get_provider() builds a fresh LiteLLMProvider
    every time, and the "all providers exhausted" circuit breaker is per-instance state
    (see its docstring). A caller that fans 40 items out concurrently while each builds
    its own provider gets 40 independent retry+fallback chains hammering an API that has
    already started 429ing, instead of the first failure short-circuiting the rest."""
    kind = target["kind"]
    allowed = EDITABLE_FIELDS[kind]
    current = {field: target.get(field) for field in allowed}
    user_message = (
        f"Item type: {kind}\n"
        f"Current values:\n{json.dumps(current, indent=2)}\n\n"
        f"Allowed fields: {', '.join(allowed)}\n\n"
        f"Requested change: {change_description}"
    )
    raw = (provider or get_provider()).generate(CHANGE_REQUEST_SYSTEM, user_message)
    try:
        parsed = json.loads(_clean_raw(raw))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    fields = {field: value for field, value in parsed.items() if field in allowed and value is not None}
    for field in list(fields):
        allowed_values = CONSTRAINED_FIELD_VALUES.get((kind, field))
        if allowed_values is None:
            continue
        normalized = str(fields[field]).strip().lower()
        if normalized in allowed_values:
            fields[field] = normalized
        else:
            # Drop rather than guess a substitute — an unrequested field simply
            # doesn't change this round, which is safe; writing a fabricated value
            # in its place would not be.
            del fields[field]
    return fields


def _generate_new_epics(brief_text: str, hierarchy: dict, request_text: str, count: int) -> list[dict]:
    """Generate a small set of non-overlapping manual epics for the current backlog.
    The user confirms the resulting preview before any rows are written."""
    existing = "; ".join(epic.get("title", "") for epic in (hierarchy.get("epics") or []))
    prompt = (
        "Return ONLY a JSON array of up to {count} new backlog epics. Each object must have "
        '"title", "description", "feature_area", and "priority" (critical, high, medium, or low). '
        "They must be concrete, relevant to the project brief, and must not duplicate existing epics.\n\n"
        "Project brief:\n{brief}\n\nExisting epics:\n{existing}\n\nUser request:\n{request}"
    ).format(count=count, brief=brief_text[:6000], existing=existing, request=request_text)
    raw = get_provider().generate("You are a senior product manager who produces concise, non-overlapping backlog epics.", prompt)
    try:
        parsed = json.loads(_clean_raw(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    valid_priorities = {"critical", "high", "medium", "low"}
    result = []
    for item in parsed[:count]:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        result.append({
            "title": str(item["title"]).strip()[:250],
            "description": str(item.get("description") or "").strip(),
            "feature_area": str(item.get("feature_area") or "General").strip(),
            "priority": str(item.get("priority") or "medium").lower() if str(item.get("priority") or "medium").lower() in valid_priorities else "medium",
        })
    return result


def _dispatch_assistant_intent(
    intent: str,
    params: dict,
    reply: str,
    request: AssistantChatRequest,
    redmine_configured: bool,
    generation_context: dict,
) -> AssistantChatResponse:
    """Execute a routed intent deterministically. Read intents (list/get) hit Redmine directly
    and the reply is built from the real result. Mutating intents (create/update) never touch
    Redmine here — they only return requires_confirmation + pending_action for the frontend to
    echo back on a follow-up confirmed call. generate_backlog/push_backlog don't touch Redmine
    or the generation pipeline at all; they just tell the frontend which existing flow to run."""
    if intent in ("list_issues", "get_issue", "create_issue", "update_issue") and not redmine_configured:
        return AssistantChatResponse(
            reply="Connect Redmine first (URL + API key) — open the Redmine panel from the Backlog tab, then ask me again.",
            warnings=["Redmine is not connected."],
        )

    if intent == "list_issues":
        try:
            issues = list_issues(
                request.redmine_url,
                request.redmine_api_key,
                project_id=params.get("project") or request.redmine_project_id or None,
                status=params.get("status"),
                tracker=params.get("tracker"),
                query_text=params.get("query_text"),
            )
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't fetch issues: {safe_exc(e)}")
        if not issues:
            return AssistantChatResponse(reply="No matching issues found.", issues=[])
        summary = "; ".join(f"#{i['id']} {i['subject']} ({i['status']})" for i in issues[:5])
        more = f" and {len(issues) - 5} more" if len(issues) > 5 else ""
        return AssistantChatResponse(reply=f"Found {len(issues)} issue(s): {summary}{more}.", issues=issues)

    if intent == "get_issue":
        issue_id = params.get("issue_id")
        if not issue_id:
            return AssistantChatResponse(reply="Which issue number do you mean?")
        try:
            issue = get_issue(request.redmine_url, request.redmine_api_key, issue_id)
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't fetch issue #{issue_id}: {safe_exc(e)}")
        return AssistantChatResponse(
            reply=(
                f"#{issue['id']} {issue['subject']} — {issue['status']}, priority {issue['priority']}, "
                f"assigned to {issue['assignee'] or 'nobody'}."
            ),
            issue=issue,
        )

    if intent == "create_issue":
        subject = str(params.get("subject") or "").strip()
        project = params.get("project") or request.redmine_project_id
        if not subject or not project:
            return AssistantChatResponse(
                reply="I need at least a project and a title to create an issue — what should it be called, and in which project?"
            )
        return AssistantChatResponse(
            reply=reply or f"Create a {params.get('tracker', 'Task')} titled \"{subject}\" in {project} — confirm?",
            requires_confirmation=True,
            pending_action={"intent": "create_issue", "params": params},
        )

    if intent == "update_issue":
        issue_id = params.get("issue_id")
        if not issue_id:
            return AssistantChatResponse(reply="Which issue number do you want me to update?")
        return AssistantChatResponse(
            reply=reply or f"Update issue #{issue_id} as described — confirm?",
            requires_confirmation=True,
            pending_action={"intent": "update_issue", "params": params},
        )

    if intent == "change_request":
        hierarchy = generation_context.get("hierarchy")
        if not hierarchy:
            return AssistantChatResponse(reply="Nothing's been generated yet this session to change — generate a backlog first.")
        change_description = str(params.get("change_description") or "").strip()
        if not change_description:
            return AssistantChatResponse(reply="What should I change, and on which epic/story/task?")
        target = _resolve_change_target(hierarchy, params.get("target_id"), str(params.get("target_hint") or ""))
        if target is None:
            return AssistantChatResponse(
                reply="I couldn't find an epic, story, or task matching that — try its id (like EP-0199 or US-0042) or be a bit more specific."
            )
        if isinstance(target, list):
            options = "; ".join(f"{t['kind']} {t.get('ai_id') or t.get('issue_id') or t['db_id']}: {t['title']}" for t in target)
            return AssistantChatResponse(reply=f"That could mean a few things — {options}. Which one, by id?")
        try:
            fields = _generate_content_change(target, change_description)
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't work out that change: {safe_exc(e)}")
        if not fields:
            return AssistantChatResponse(reply="I couldn't turn that into a concrete change — could you be more specific about what should be different?")
        summary = ", ".join(f'{field} → "{value}"' if isinstance(value, str) and len(value) < 60 else field for field, value in fields.items())
        target_label = target.get("ai_id") or target.get("issue_id") or target["db_id"]
        return AssistantChatResponse(
            reply=f"On {target['kind']} {target_label} ({target['title']}): {summary} — confirm?",
            requires_confirmation=True,
            pending_action={"intent": "change_request", "params": {"kind": target["kind"], "db_id": target["db_id"], "fields": fields}},
        )

    if intent == "add_epics":
        hierarchy = generation_context.get("hierarchy")
        if not hierarchy or not request.generation_id:
            return AssistantChatResponse(reply="Generate or open a backlog first, then I can add epics to it.")
        try:
            count = max(1, min(5, int(params.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1
        try:
            epics = _generate_new_epics(
                str(generation_context.get("brief_text") or ""), hierarchy, request.message, count
            )
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't draft the new epics: {safe_exc(e)}")
        if not epics:
            return AssistantChatResponse(reply="I couldn't draft distinct epics from that request. Tell me which capability area to add.")
        preview = "; ".join(epic["title"] for epic in epics)
        return AssistantChatResponse(
            reply=f"Add {len(epics)} epic(s): {preview} — confirm?",
            requires_confirmation=True,
            pending_action={"intent": "add_epics", "params": {"generation_id": request.generation_id, "epics": epics}},
        )

    if intent == "generate_backlog":
        brief_text = str(params.get("brief_text") or request.message or "").strip()
        if not brief_text:
            return AssistantChatResponse(reply="What should the project backlog be about?")
        return AssistantChatResponse(
            reply=reply or "Starting generation now — watch the Backlog tab.",
            action="trigger_generation",
            generation_text=brief_text,
        )

    if intent == "push_backlog":
        if not generation_context.get("has_output"):
            return AssistantChatResponse(reply="Nothing's been generated yet this session — generate a backlog first.")
        if not generation_context.get("trusted"):
            return AssistantChatResponse(
                reply="This backlog hasn't passed the trust gate yet, so I can't push it automatically. Open the Redmine panel to see what's blocking it."
            )
        if not redmine_configured:
            return AssistantChatResponse(reply="Connect Redmine first (URL + API key), then ask me to push again.")
        return AssistantChatResponse(reply=reply or "Pushing the backlog to Redmine now.", action="trigger_push")

    return AssistantChatResponse(reply=reply)


def _execute_assistant_action(
    pending_action: dict,
    request: AssistantChatRequest,
    redmine_configured: bool,
) -> AssistantChatResponse:
    """Run a create/update/change action the user already confirmed. change_request never
    touches Redmine — it's the one confirmable intent that doesn't need redmine_configured, so
    it's dispatched before that gate; create_issue/update_issue are checked after."""
    intent = pending_action.get("intent")
    params = pending_action.get("params") or {}

    if intent == "change_request":
        kind = params.get("kind")
        db_id = params.get("db_id")
        fields = params.get("fields") or {}
        updater = {"epic": update_epic_content, "story": update_story_content, "task": update_task_content}.get(kind)
        if not updater or not db_id:
            return AssistantChatResponse(reply="I lost track of what to change — can you ask again?")
        try:
            updated = updater(db_id, fields)
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't save that change: {safe_exc(e)}")
        if not updated:
            return AssistantChatResponse(reply=f"Couldn't find that {kind} anymore — it may have been deleted.")
        return AssistantChatResponse(reply=f"Updated the {kind}.")

    if intent == "add_epics":
        generation_id = params.get("generation_id")
        epics = params.get("epics") or []
        if not isinstance(generation_id, int) or not isinstance(epics, list):
            return AssistantChatResponse(reply="I lost track of the epics to add — please ask again.")
        created = []
        try:
            for epic in epics:
                if not isinstance(epic, dict) or not str(epic.get("title") or "").strip():
                    continue
                row = create_epic(generation_id, {
                    "title": str(epic["title"]).strip(),
                    "description": str(epic.get("description") or ""),
                    "feature_area": str(epic.get("feature_area") or "General"),
                    "priority": str(epic.get("priority") or "medium"),
                })
                if row:
                    created.append(row["issue_id"])
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't add the new epics: {safe_exc(e)}")
        if not created:
            return AssistantChatResponse(reply="No epics were added — the backlog may no longer exist.")
        return AssistantChatResponse(reply=f"Added {len(created)} epic(s): {', '.join(created)}.")

    if not redmine_configured:
        return AssistantChatResponse(reply="Redmine isn't connected anymore — reconnect and try again.")

    if intent == "create_issue":
        try:
            issue = create_single_issue(
                request.redmine_url,
                request.redmine_api_key,
                project_ref=params.get("project") or request.redmine_project_id,
                tracker_name=params.get("tracker") or "Task",
                subject=str(params.get("subject") or "").strip(),
                description=str(params.get("description") or ""),
                priority_label=str(params.get("priority") or "medium"),
            )
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't create the issue: {safe_exc(e)}")
        return AssistantChatResponse(reply=f"Created #{issue['id']}: {issue['subject']}.", issue=issue)

    if intent == "update_issue":
        issue_id = params.get("issue_id")
        try:
            issue = update_issue_fields(
                request.redmine_url,
                request.redmine_api_key,
                issue_id,
                status_label=params.get("status"),
                priority_label=params.get("priority"),
                assigned_to=params.get("assigned_to"),
                notes=params.get("notes"),
            )
        except Exception as e:
            return AssistantChatResponse(reply=f"Couldn't update #{issue_id}: {safe_exc(e)}")
        return AssistantChatResponse(
            reply=f"Updated #{issue['id']}: now {issue['status']}, priority {issue['priority']}.",
            issue=issue,
        )

    return AssistantChatResponse(reply="I lost track of what to confirm — can you ask again?")


@app.post("/assistant/chat")
def assistant_chat_endpoint(request: AssistantChatRequest, http_request: Request):
    """One turn of the Redmine chat assistant: a single LLM call classifies intent + params
    (same strict-JSON pattern as /clarify-chat), then Python executes that intent deterministically
    — the model never talks to Redmine or invents issue data itself. Mutating intents (create/update
    issue) always require a separate confirmed follow-up call; nothing changes Redmine on the first
    pass. generate_backlog/push_backlog don't execute here at all — they tell the frontend to reuse
    the existing /generate-stream and /push-to-redmine flows so behavior stays identical to the
    Brief/Chat tabs and the Redmine modal."""
    try:
        enforce_rate_limit(http_request, bucket="assistant", limit=ASSISTANT_LIMIT_PER_MINUTE)

        redmine_configured = bool(request.redmine_url.strip() and request.redmine_api_key.strip())
        if redmine_configured:
            try:
                request.redmine_url = validate_redmine_url(request.redmine_url)
            except ValueError as exc:
                return JSONResponse(status_code=400, content=ValidationError(str(exc)).to_dict())

        if request.confirm and request.pending_action:
            response = _execute_assistant_action(request.pending_action, request, redmine_configured)
            return JSONResponse(content=response.model_dump(exclude_none=True))

        message = (request.message or "").strip()
        if not message:
            error = ValidationError("Message is required.")
            return JSONResponse(status_code=400, content=error.to_dict())

        generation_context = _assistant_generation_context(request.generation_id)
        redmine_context = {"configured": redmine_configured, "project_id": request.redmine_project_id or None}

        provider = get_provider()
        raw = provider.generate(
            ASSISTANT_ROUTER_SYSTEM,
            build_assistant_router_message(message, request.history, redmine_context, generation_context),
        )
        try:
            routed = json.loads(_clean_raw(raw))
        except json.JSONDecodeError:
            log_debug("Assistant", "Failed to parse router response, defaulting to chitchat")
            routed = {}
        if not isinstance(routed, dict):
            routed = {}

        intent = str(routed.get("intent") or "chitchat")
        params = routed.get("params") if isinstance(routed.get("params"), dict) else {}
        reply = str(routed.get("reply") or "").strip() or "Got it."

        response = _dispatch_assistant_intent(intent, params, reply, request, redmine_configured, generation_context)
        log_info("Assistant", f"Routed to intent={intent}")
        return JSONResponse(content=response.model_dump(exclude_none=True))
    except RateLimitError as error:
        log_warning("Assistant", "Rate limit hit on /assistant/chat")
        return JSONResponse(status_code=429, content=error.to_dict())
    except Exception as e:
        error = APIError(
            provider=os.getenv("AI_PROVIDER", "unknown"),
            message=f"Assistant chat failed: {safe_exc(e)}",
        )
        log_error("Assistant", "Error in /assistant/chat", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/validate-brief")
def validate_brief(request: GenerateRequest):
    text = request.text or ""
    word_count = len(text.split())
    lower = text.lower()
    checks = [
        {
            "name": "length",
            "passed": word_count >= 50,
            "hint": f"Too short ({word_count} words). Aim for at least 50."
        },
        {
            "name": "features",
            "passed": any(kw in lower for kw in [
                "feature", "function", "allow", "enable", "support",
                "capability", "ability", "user can", "users can"
            ]),
            "hint": "Describe specific features or what users can do."
        },
        {
            "name": "users",
            "passed": any(kw in lower for kw in [
                "user", "customer", "admin", "manager", "employee",
                "client", "team", "developer", "owner", "vendor"
            ]),
            "hint": "Name who will use this product (e.g. 'admin users', 'customers')."
        },
        {
            "name": "goal",
            "passed": any(kw in lower for kw in [
                "goal", "objective", "purpose", "so that", "in order to",
                "enable", "achieve", "outcome", "result", "help"
            ]),
            "hint": "State the main goal or business outcome."
        },
    ]
    passed_count = sum(1 for c in checks if c["passed"])
    score = "strong" if passed_count >= 3 else "moderate" if passed_count >= 2 else "vague"
    suggestions = [c["hint"] for c in checks if not c["passed"]]
    return JSONResponse(content={"word_count": word_count, "score": score, "suggestions": suggestions})


# Empirical average per AI call across providers/phases (epic/story/task/test
# generation), from real generation runs — not a formal SLA, just the
# baseline the wave-count math below uses to turn a call count into seconds.
SECONDS_PER_CALL = 17


@app.post("/estimate-tokens")
def estimate_tokens(request: GenerateRequest):
    text = request.text or ""
    word_count = len(text.split())
    # EPIC_GENERATION_SYSTEM has a hard floor of 10 epics regardless of brief
    # length ("Produce a minimum of 10 epics... For large enterprise briefs
    # expect 12-20") — confirmed empirically too (a 48-word brief still
    # produced 9 epics). Scale up for longer/more detailed briefs, but never
    # guess below that floor for short ones the way word_count // 50 did.
    estimated_epics = max(10, min(20, 10 + word_count // 100))
    estimated_stories = estimated_epics * MIN_STORIES_PER_EPIC
    estimated_tasks = estimated_stories * MIN_TASKS_PER_STORY

    phase1_calls = 1
    phase2_calls = estimated_epics  # 1 story-generation call per epic
    phase3_calls = estimated_epics  # 1 task-generation call per epic
    phase4_calls = -(-estimated_tasks // TASKS_PER_TEST_BATCH)  # ceil division
    estimated_calls = phase1_calls + phase2_calls + phase3_calls + phase4_calls

    input_tokens_per_call = max(500, word_count * 1.35)
    output_tokens_per_call = 900  # rough average completion size across phases

    # Real per-token pricing for whichever provider is actually active,
    # rather than one flat guess regardless of provider — Cerebras, Groq,
    # and Gemini have meaningfully different rates (see UI_PROVIDERS).
    per_call_cost = estimate_call_cost_usd(int(input_tokens_per_call), int(output_tokens_per_call))
    if per_call_cost is not None:
        cost_usd = estimated_calls * per_call_cost
    else:
        total_tokens = estimated_calls * (input_tokens_per_call + output_tokens_per_call)
        cost_usd = (total_tokens / 1_000_000) * 0.20  # blended fallback guess

    # Phase 1 always runs as a single call; phases 2/3/4 each run their calls
    # concurrently in waves of EPIC_CONCURRENCY (see that constant) rather
    # than one at a time, so wall-clock time tracks wave count, not raw call
    # count — mirrors _stream_generate's actual concurrency model.
    def waves(n: int) -> int:
        return -(-n // EPIC_CONCURRENCY) if n else 0

    estimated_time_seconds = SECONDS_PER_CALL * (
        1 + waves(phase2_calls) + waves(phase3_calls) + waves(phase4_calls)
    )
    return JSONResponse(content={
        "word_count": word_count,
        "estimated_calls": estimated_calls,
        "estimated_time_seconds": int(estimated_time_seconds),
        "cost_usd": round(cost_usd, 4),
    })


@app.get("/brief-resources")
def get_brief_resources():
    try:
        resources = {
            name: path.read_text(encoding="utf-8")
            for name, path in BRIEF_RESOURCE_FILES.items()
        }
        log_info("BriefResources", f"Loaded {len(resources)} resource files")
        return {"resources": resources}
    except FileNotFoundError as e:
        error = FileError(
            message=f"Brief resource missing: {e.filename}",
            filename=str(e.filename)
        )
        log_error("BriefResources", f"Missing file: {e.filename}", exception=e)
        return JSONResponse(
            status_code=404,
            content=error.to_dict()
        )
    except OSError as e:
        error = FileError(
            message=f"Failed to read brief resources",
            filename="multiple"
        )
        log_error("BriefResources", "File read error", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


def get_history():
    try:
        generations = list_generations()
        log_info("History", f"Listed {len(generations)} generations")
        return {"generations": generations}
    except Exception as e:
        error = DatabaseError(
            message="Failed to retrieve generation history",
            operation="list_generations"
        )
        log_error("History", "Error listing generations", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


def get_history_item(gen_id: int):
    try:
        gen = get_generation(gen_id)
        if not gen:
            error = AppError(
                message=f"Generation {gen_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("History", f"Generation {gen_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        # The Backlog page's own source of truth for the Checks panel and the trust
        # banner — score it against today's bar, not the one in force when it was
        # generated. See _rescored_output_dict.
        if isinstance(gen.get("output"), dict):
            gen["output"] = _rescored_output_dict(gen["output"])
        log_debug("History", f"Retrieved generation {gen_id}")
        return gen
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to retrieve generation {gen_id}",
            operation="get_generation"
        )
        log_error("History", f"Error retrieving generation {gen_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


def delete_history_item(gen_id: int):
    try:
        deleted = delete_generation(gen_id)
        if not deleted:
            error = AppError(
                message=f"Generation {gen_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("History", f"Generation {gen_id} not found for deletion")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_info("History", f"Deleted generation {gen_id}")
        return {"deleted": True}
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to delete generation {gen_id}",
            operation="delete_generation"
        )
        log_error("History", f"Error deleting generation {gen_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/generations/{gen_id}/repair-dependencies")
def repair_generation_dependencies(gen_id: int):
    """Repair legacy/stepwise task dependency references and re-score the run.
    This is deterministic cleanup, not a second AI generation call."""
    try:
        loaded = _load_generation_for_resume(gen_id)
        if not loaded:
            return JSONResponse(status_code=404, content=AppError(
                message=f"Generation {gen_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        _, output = loaded
        if not output.tasks:
            return JSONResponse(status_code=422, content=ValidationError(
                "This backlog has no tasks to repair yet. Generate tasks first."
            ).to_dict())
        normalize_task_dependencies(output)
        output.metrics = compute_metrics(output)
        output.validation = run_validation(output.metrics)
        update_generation_output(gen_id, output)
        sync_task_dependencies(gen_id, output.tasks)
        log_info("BacklogRepair", f"Normalized dependencies for generation {gen_id}")
        result = output.model_dump()
        result["generation_id"] = gen_id
        return {"repaired": True, "output": result}
    except Exception as e:
        log_error("BacklogRepair", f"Failed dependency repair for generation {gen_id}", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message="Failed to repair task dependencies", operation="repair_dependencies"
        ).to_dict())


@app.get("/generations/{gen_id}/weak-items")
def get_generation_weak_items(gen_id: int, max_items: int = 40, threshold: int = WEAK_ITEM_THRESHOLD, dimension: str | None = None):
    """Diagnosis only — no AI call, no write. Returns every specific story/task
    dragging the Scorecard's quality scores down (uncapped, up to a generous safety
    ceiling — not an arbitrary top-N a user has to blind-guess) and, for each, exactly
    which dimension is weak, its current score, and why (find_weak_items). `threshold`
    defaults to WEAK_ITEM_THRESHOLD (the same bar run_validation's trust gate uses) but
    is a real parameter, not a hardcoded cutoff — pass a stricter one to re-check after
    a fix pass, or a looser one to only surface the worst offenders. `dimension` (e.g.
    "definition_of_done") narrows this to only items weak on that one Scorecard bar —
    the Scorecard's "Fix" link on a weak bar uses this so clicking, say, Definition of
    done goes straight to the items dragging *that* score down instead of the whole
    mixed list. Filtered against the *full* weak set before max_items is applied, so a
    less common dimension isn't crowded out of the response by unrelated ones. The UI
    groups these by kind so the user can tick which ones to actually fix, rather than
    the backend silently picking "the worst N" for them."""
    try:
        loaded = _load_generation_for_resume(gen_id)
        if not loaded:
            return JSONResponse(status_code=404, content=AppError(
                message=f"Generation {gen_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        _, output = loaded
        all_weak = find_weak_items(output, max_items=None, threshold=threshold)
        if dimension:
            all_weak = [w for w in all_weak if any(d["name"] == dimension for d in w["weak_dimensions"])]
        weak_items = all_weak[:max(1, min(200, max_items))]
        return {
            "items": [
                {"kind": w["kind"], "id": w["id"], "title": w["title"], "weak_dimensions": w["weak_dimensions"]}
                for w in weak_items
            ],
        }
    except Exception as e:
        log_error("QualityImprove", f"Failed to list weak items for generation {gen_id}", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message=f"Failed to analyze backlog quality: {safe_exc(e)}", operation="weak_items"
        ).to_dict())


def _item_dimension_scores(kind: str, item, all_task_ids: set[str]) -> dict[str, int]:
    """Every dimension score for one story/task, using the exact rubric
    find_weak_items and the Scorecard use.

    The task dependency dimension is excluded because improve-quality never targets
    it (that's repair-dependencies' job), so including it would let unrelated
    dependency noise decide whether a clarity/DoD rewrite is kept."""
    if kind == "story":
        return score_single_story(item)
    scores = score_single_task(item, all_task_ids)
    scores.pop("dependency", None)
    return scores


def _item_quality_signature(kind: str, item, all_task_ids: set[str]) -> tuple[int, int]:
    """A comparable score for one story/task: (worst dimension, sum of dimensions).
    Compared as a tuple so "the weakest dimension got better" outranks "some
    already-strong dimension got even stronger" — a rewrite that lifts an 85 to 95
    while dropping the 61 that actually made the item weak is a regression, not an
    improvement."""
    values = list(_item_dimension_scores(kind, item, all_task_ids).values())
    return (min(values), sum(values))


# Why an item's fix attempt didn't land. "blocked" means the backlog was deliberately
# left alone — nothing broke, and clicking Fix again will do exactly the same thing.
# "failed" means something actually went wrong (the model call raised, the DB write
# failed) and a retry could plausibly succeed. The UI styles and re-ticks these very
# differently, so the distinction is made here rather than by matching on message text.
ERROR_BLOCKED = "blocked"
ERROR_FAILED = "failed"
# A call that didn't complete for a reason that has nothing to do with this item —
# every provider rate-limited, a timeout. Retrying is the *correct* response, and the
# retry has to outlive the provider's own cooldown to be worth anything. Kept distinct
# from ERROR_FAILED so a burst 429 isn't reported to the user as "this item can't be
# fixed" when the truth is "the API was busy; we should wait and go again".
ERROR_TRANSIENT = "transient"


def _classify_provider_error(e: Exception) -> str:
    """Transient (worth waiting and retrying) vs a real failure for this item."""
    if isinstance(e, AllProvidersExhaustedError):
        return ERROR_TRANSIENT
    text = f"{type(e).__name__}: {e}".lower()
    if any(marker in text for marker in ("rate limit", "ratelimit", "429", "timeout", "timed out",
                                         "temporarily unavailable", "503", "502", "overloaded")):
        return ERROR_TRANSIENT
    return ERROR_FAILED


def _improve_quality_events(gen_id: int, request: ImproveQualityRequest):
    """Generator form of the targeted quality fix. Yields ("progress", {...}) as it
    works and finally exactly one ("result", {...}) or ("error", {...}).

    It's a generator so the same code can back both the plain JSON endpoint and the SSE
    one below without the work being written twice: a run over a few dozen items does
    several rounds of AI calls and can pause 20s+ waiting out a rate limit, which is far
    too long to leave the caller staring at a spinner with nothing to show.

    Fix only the specific stories/tasks the caller asks for, in place — not a full
    regeneration. Normal path: `request.items` is the exact set the user ticked on the
    GET /weak-items diagnosis (so no arbitrary top-N cutoff picks for them); each one
    gets a single targeted _generate_content_change call (the same machinery the
    assistant's change_request intent uses) describing only that item's specific weak
    dimensions. `request.items` omitted falls back to the old top-`max_items`-worst
    behavior for callers that skip the diagnosis step. Each item is retried against its
    own current weak dimensions up to `max_attempts` times within this one request if
    a rewrite improves it without fully clearing the bar — the caller doesn't have to
    notice and ask again. Every rewrite is scored against the item it would replace
    (_item_quality_signature) and discarded unless it's strictly better, so no number
    of rounds or repeat clicks can leave an item worse than it started. The fix is
    written to both the normalized DB rows
    (hierarchy/detail views) and the stored output_json (re-scored), so the response's
    metrics reflect what actually changed. Each result item carries both the diagnosis
    (weak_dimensions: why it's *still* weak, refreshed after every round) and the fix
    (changes: the before → after values spanning every round, not just the last one) —
    the two are easy to conflate but answer different questions, so both travel
    together rather than just a field name list."""
    try:
        loaded = _load_generation_for_resume(gen_id)
        if not loaded:
            yield "error", {"status": 404, "body": AppError(
                message=f"Generation {gen_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict()}
            return
        _, output = loaded
        if not output.stories and not output.tasks:
            return JSONResponse(status_code=422, content=ValidationError(
                "This backlog has no stories or tasks to improve yet."
            ).to_dict())

        threshold = request.threshold if request.threshold is not None else WEAK_ITEM_THRESHOLD
        if request.items is not None:
            by_key = {(w["kind"], w["id"]): w for w in find_weak_items(output, max_items=None, threshold=threshold)}
            weak_items = [by_key[(sel.kind, sel.id)] for sel in request.items if (sel.kind, sel.id) in by_key]
        else:
            weak_items = find_weak_items(output, max_items=max(1, min(20, request.max_items)), threshold=threshold)
        if not weak_items:
            yield "result", {
                "targeted": 0, "updated": 0, "resolved": 0, "items": [],
                "message": "Nothing scored below the quality bar — there's no specific item to target.",
            }
            return

        # Direct generation_id -> {ai_id: db_id} lookups — NOT a walk through the
        # epic->story->task hierarchy join (get_generation_hierarchy), which silently
        # drops any story/task whose parent link (epic_id/story_id) is missing or
        # broken. That was the actual bug behind "these items never improve, they
        # keep showing up again and again": find_weak_items scores everything in
        # output.stories/output.tasks regardless of parent linkage, but the old
        # hierarchy-walk lookup below could only ever find the properly-linked subset
        # — so an orphaned item would be flagged as weak, immediately fail the fix
        # with "No longer in the backlog", and get flagged as weak again on every
        # subsequent check, forever, with no way to ever actually fix it.
        story_id_map = get_story_id_map(gen_id)
        task_id_map = get_task_id_map(gen_id)
        stories_by_id = {s.id: s for s in output.stories}
        tasks_by_id = {t.id: t for t in output.tasks}
        # Stable for the whole request: "id" isn't in EDITABLE_FIELDS, and this endpoint
        # never adds or removes items — it only rewrites fields on existing ones.
        all_task_ids = {t.id for t in output.tasks}

        def _db_id(kind: str, ai_id: str) -> int | None:
            return (story_id_map if kind == "story" else task_id_map).get(ai_id)

        # ONE provider for the whole request, not one per item. get_provider() builds a
        # fresh LiteLLMProvider each call, and its "every provider is rate-limited"
        # circuit breaker is per-instance — so building one per item meant 40 concurrent
        # calls each burning their own retry+fallback chain against an API that had
        # already started refusing them. That is what produced a wall of red "Failed"
        # rows on a run this size.
        provider = get_provider()

        def _fetch_change(weak: dict) -> tuple[dict, dict | None, dict | None, tuple[str, str] | None]:
            """Runs in the thread pool — the AI call only, same split as
            generators.py's _fetch_for_epic. Returns (weak, target, fields, error),
            where error is (message, ERROR_BLOCKED|ERROR_FAILED|ERROR_TRANSIENT); never
            touches `output` or the DB, so nothing here needs a lock."""
            kind, ai_id = weak["kind"], weak["id"]
            model_item = (stories_by_id if kind == "story" else tasks_by_id).get(ai_id)
            if _db_id(kind, ai_id) is None or not model_item:
                return weak, None, None, ("No longer in the backlog", ERROR_BLOCKED)
            target = {**model_item.model_dump(), "kind": kind}
            try:
                fields = _generate_content_change(target, weak["change_description"], provider=provider)
            except Exception as e:
                return weak, target, None, (safe_exc(e), _classify_provider_error(e))
            if not fields:
                return weak, target, None, ("The model returned no usable change for this item", ERROR_BLOCKED)
            return weak, target, fields, None

        # Snapshot each targeted item's editable fields before any round touches them —
        # this is the true "before" for the cumulative diff a caller sees, since round
        # 2+'s own `target` (rebuilt from the now-mutated model_item) would otherwise
        # only show that round's own small delta, hiding how much actually changed
        # since the very first attempt.
        original_values: dict[tuple[str, str], dict] = {}
        # The same snapshot idea for scores: what each item scored before this request
        # touched anything, so the caller can show a real "55% -> 78%" delta rather
        # than a bare current number the user can't tell apart from where it started.
        baseline_scores: dict[tuple[str, str], dict[str, int]] = {}
        for weak in weak_items:
            kind, ai_id = weak["kind"], weak["id"]
            model_item = (stories_by_id if kind == "story" else tasks_by_id).get(ai_id)
            if model_item is not None:
                original_values[(kind, ai_id)] = model_item.model_dump()
                baseline_scores[(kind, ai_id)] = _item_dimension_scores(kind, model_item, all_task_ids)

        def _signature(key: tuple[str, str]) -> tuple[int, int] | None:
            kind, ai_id = key
            model_item = (stories_by_id if kind == "story" else tasks_by_id).get(ai_id)
            return None if model_item is None else _item_quality_signature(kind, model_item, all_task_ids)

        max_attempts = max(1, min(5, request.max_attempts if request.max_attempts is not None else MAX_FIX_ATTEMPTS))
        entries: dict[tuple[str, str], dict] = {}
        attempts: dict[tuple[str, str], int] = {}
        pending = list(weak_items)

        # Retry loop: an item that improves without fully clearing the bar (see the
        # resolved-vs-updated distinction below) is automatically retried against its
        # *current* weak dimensions, up to max_attempts, instead of requiring the user
        # to notice it's still short and click "Fix" again themselves — that repeated
        # manual re-click was the actual complaint this loop exists to remove. Each
        # round still fans its items out concurrently; only the number of rounds is
        # sequential, bounded by max_attempts.
        total = len(weak_items)
        completed = 0
        yield "progress", {
            "phase": "start", "total": total, "completed": 0,
            "message": f"Fixing {total} item{'s' if total != 1 else ''}…",
        }

        for _round in range(max_attempts):
            if not pending:
                break
            if _round > 0:
                yield "progress", {
                    "phase": "round", "total": total, "completed": completed,
                    "round": _round + 1, "max_rounds": max_attempts,
                    "message": f"Retrying {len(pending)} item{'s' if len(pending) != 1 else ''} "
                               f"(pass {_round + 1} of {max_attempts})…",
                }
            round_start_signatures = {(w["kind"], w["id"]): _signature((w["kind"], w["id"])) for w in pending}
            round_error_kinds: dict[tuple[str, str], str] = {}
            with ThreadPoolExecutor(max_workers=min(IMPROVE_QUALITY_CONCURRENCY, len(pending))) as executor:
                futures = [executor.submit(_fetch_change, weak) for weak in pending]
                for future in as_completed(futures):
                    weak, target, fields, error = future.result()
                    kind, ai_id = weak["kind"], weak["id"]
                    key = (kind, ai_id)
                    attempts[key] = attempts.get(key, 0) + 1
                    entry = entries.setdefault(key, {
                        "kind": kind, "id": ai_id, "title": weak["title"],
                        "weak_dimensions": weak["weak_dimensions"], "updated": False,
                    })
                    if error:
                        message, kind_of_error = error
                        round_error_kinds[key] = kind_of_error
                        # Don't let a late round's error overwrite an earlier round's
                        # real success — the item did improve, it just stopped there.
                        if not entry["updated"]:
                            entry["error"] = message
                            entry["error_kind"] = kind_of_error
                        continue
                    model_item = (stories_by_id if kind == "story" else tasks_by_id)[ai_id]

                    # Score the rewrite BEFORE committing it anywhere. Nothing about a
                    # model rewrite guarantees it's an improvement — it can drop an AC,
                    # shorten a rationale, or trade the weak dimension for a strong one —
                    # and without this check every rewrite was written to the DB and to
                    # output unconditionally. Across max_attempts rounds per click, and
                    # repeat clicks on items that never clear the bar, that let "Improve
                    # quality" walk an item steadily *downhill*: each round overwrote the
                    # previous content with whatever came back, with no way to get the
                    # original back. Applying to a deep copy first means a rejected
                    # rewrite is simply discarded — no DB write to undo, and the item is
                    # left exactly as it was.
                    candidate = model_item.model_copy(deep=True)
                    for field, value in fields.items():
                        setattr(candidate, field, value)
                    if _item_quality_signature(kind, candidate, all_task_ids) <= _item_quality_signature(kind, model_item, all_task_ids):
                        # Don't clobber an earlier round's genuine success with this.
                        if not entry["updated"]:
                            entry["error"] = "The rewrite scored no better than what's already there, so the original was kept"
                            entry["error_kind"] = ERROR_BLOCKED
                        continue

                    updater = update_story_content if kind == "story" else update_task_content
                    if updater(_db_id(kind, ai_id), fields):
                        entry.pop("error", None)
                        entry.pop("error_kind", None)
                        base = original_values.get(key, target)
                        changes_by_field = {c["field"]: c for c in entry.get("changes", [])}
                        for field, value in fields.items():
                            changes_by_field[field] = {"field": field, "before": base.get(field), "after": value}
                            setattr(model_item, field, value)
                        entry["changes"] = list(changes_by_field.values())
                        entry["updated"] = True
                    else:
                        entry["error"] = "Database update failed"
                        entry["error_kind"] = ERROR_FAILED

                    completed += 1
                    yield "progress", {
                        "phase": "item", "total": total, "completed": completed,
                        "title": entry["title"], "kind": entry["kind"], "id": entry["id"],
                        "updated": entry["updated"],
                        "message": f"{entry['title']} — {'rewritten' if entry['updated'] else 'left as-is'}",
                    }

            # Re-diagnose against the now-mutated output to decide what needs another
            # round — using the refreshed weak_dimensions/change_description (not the
            # stale pre-round ones) so a retry targets what's *actually* still wrong.
            still_weak_by_key = {(w["kind"], w["id"]): w for w in find_weak_items(output, max_items=None, threshold=threshold)}
            pending = []
            for key in (attempts.keys() & still_weak_by_key.keys()):
                if attempts[key] >= max_attempts:
                    continue
                # Stop retrying an item this round moved nowhere. A retry re-sends the
                # same change_description to the same model against the same content,
                # so a round that scored identically is overwhelmingly likely to keep
                # scoring identically — and some items simply cannot be fixed by a
                # field rewrite at all (a "large" story scores a flat 50 on sizing no
                # matter what its prose says; only splitting it, which this endpoint
                # can't do, or a genuinely wrong size label would move it). Those used
                # to burn every attempt on every click and still report "3 attempts",
                # which is what made repeated Fix clicks feel like pointless churn.
                # Only a round that actually produced an answer can prove an item is
                # stuck. A round that errored (rate limit, timeout) leaves the score
                # untouched too, and treating that as "stalled" retired the item on the
                # spot — turning a transient API blip into a permanent "Failed" that no
                # amount of retrying would ever have been allowed to fix.
                if key not in round_error_kinds and round_start_signatures.get(key) is not None \
                        and _signature(key) == round_start_signatures[key]:
                    entries[key]["stalled"] = True
                    continue
                pending.append(still_weak_by_key[key])

            if pending and any(kind == ERROR_TRANSIENT for kind in round_error_kinds.values()):
                log_info(
                    "QualityImprove",
                    f"Generation {gen_id}: {sum(1 for k in round_error_kinds.values() if k == ERROR_TRANSIENT)} "
                    f"item(s) hit a transient provider error; pausing "
                    f"{TRANSIENT_RETRY_BACKOFF_SECONDS}s before retrying them",
                )
                yield "progress", {
                    "phase": "waiting", "total": total, "completed": completed,
                    "seconds": TRANSIENT_RETRY_BACKOFF_SECONDS,
                    "message": f"Provider rate-limited — waiting {int(TRANSIENT_RETRY_BACKOFF_SECONDS)}s "
                               f"before retrying {len(pending)} item(s)…",
                }
                time.sleep(TRANSIENT_RETRY_BACKOFF_SECONDS)

        # "updated" only means at least one round's write succeeded — it says nothing
        # about whether the final rewrite actually cleared the bar (a rewrite can move
        # a dimension from 61% to 75%, real progress but still below an 80% threshold).
        # Diagnose once more against the fully-settled output so each entry can say
        # which of those it actually is.
        still_weak_by_key = {(w["kind"], w["id"]): w for w in find_weak_items(output, max_items=None, threshold=threshold)}
        for entry in entries.values():
            key = (entry["kind"], entry["id"])
            entry["attempts"] = attempts.get(key, 0)
            # Scores travel for *every* entry, not just updated ones — an item that
            # was deliberately left alone still needs to show where it actually
            # stands, otherwise "Failed" is the only thing the user ever sees for it.
            model_item = (stories_by_id if entry["kind"] == "story" else tasks_by_id).get(entry["id"])
            if model_item is not None:
                entry["before_scores"] = baseline_scores.get(key)
                entry["current_scores"] = _item_dimension_scores(entry["kind"], model_item, all_task_ids)
            if not entry["updated"]:
                # Always present, so a consumer never has to tell "not resolved" apart
                # from "this key wasn't sent" — nothing was written, so nothing cleared.
                entry["resolved"] = False
                continue
            still_weak = still_weak_by_key.get(key)
            entry["resolved"] = still_weak is None
            # Refresh weak_dimensions to match reality post-fix either way — resolved
            # means none left (not the stale pre-fix list still sitting there implying
            # otherwise), not-resolved means whatever's still actually weak now.
            entry["weak_dimensions"] = still_weak["weak_dimensions"] if still_weak is not None else []
            # The full, unfiltered per-dimension scores — not just the weak ones. The
            # pass bar (threshold) only decides when we stop touching an item; the
            # model is never told to aim for exactly that number, so a "resolved" item
            # can genuinely score anywhere from the threshold up to 100. Sending the
            # real numbers lets the UI show that instead of a bare "Fixed" badge that
            # reads like the score got clamped at the bar.
            model_item = (stories_by_id if entry["kind"] == "story" else tasks_by_id)[entry["id"]]
            if entry["kind"] == "story":
                entry["current_scores"] = score_single_story(model_item)
            else:
                task_scores = score_single_task(model_item, all_task_ids)
                task_scores.pop("dependency", None)
                entry["current_scores"] = task_scores

        results = list(entries.values())

        yield "progress", {
            "phase": "scoring", "total": total, "completed": completed,
            "message": "Re-scoring the backlog…",
        }
        output.metrics = compute_metrics(output)
        output.validation = run_validation(output.metrics)
        update_generation_output(gen_id, output)

        updated_count = sum(1 for r in results if r["updated"])
        resolved_count = sum(1 for r in results if r.get("resolved"))
        log_info(
            "QualityImprove",
            f"Generation {gen_id}: targeted {len(weak_items)} item(s), updated {updated_count}, "
            f"resolved {resolved_count} (below the bar even after rewrite: {updated_count - resolved_count})",
        )
        result = output.model_dump()
        result["generation_id"] = gen_id
        result_payload = {
            "targeted": len(weak_items), "updated": updated_count, "resolved": resolved_count,
            "items": results, "output": result,
        }
        # A fix pass can be exactly what flips a backlog from "review" to
        # "trusted" — check auto-push here too, not just at test-case-phase
        # completion, since this is the other place trust_level gets
        # recomputed on an existing generation.
        auto_pushed = _maybe_auto_push_bitbucket(gen_id, output)
        if auto_pushed is not None:
            result_payload["auto_pushed"] = auto_pushed
        yield "result", result_payload
    except Exception as e:
        log_error("QualityImprove", f"Failed targeted quality improvement for generation {gen_id}", exception=e)
        yield "error", {"status": 500, "body": DatabaseError(
            message=f"Failed to improve backlog quality: {safe_exc(e)}", operation="improve_quality"
        ).to_dict()}


@app.post("/generations/{gen_id}/improve-quality")
def improve_generation_quality(gen_id: int, request: ImproveQualityRequest = ImproveQualityRequest()):
    """Blocking form: runs the fix to completion and returns the final result. Callers
    that want to show the user what's happening while a few dozen items are rewritten
    should use the -stream variant below instead."""
    for name, data in _improve_quality_events(gen_id, request):
        if name == "error":
            return JSONResponse(status_code=data["status"], content=data["body"])
        if name == "result":
            return data
    return JSONResponse(status_code=500, content=DatabaseError(
        message="Quality improvement produced no result", operation="improve_quality"
    ).to_dict())


@app.post("/generations/{gen_id}/improve-quality-stream")
def improve_generation_quality_stream(gen_id: int, request: ImproveQualityRequest = ImproveQualityRequest()):
    """Same work as above, reported as it happens. A run over a few dozen items does
    several rounds of concurrent AI calls and can pause 20s+ waiting out a provider rate
    limit — long enough that a silent spinner reads as a hang. Emits `progress` events
    (per item, per retry round, and while waiting on a rate limit) and closes with a
    single `result` or `error` carrying exactly the payload the JSON endpoint returns."""
    def events():
        try:
            for name, data in _improve_quality_events(gen_id, request):
                yield _sse(name, data)
        except Exception as e:
            log_error("QualityImprove", f"improve-quality stream failed for generation {gen_id}", exception=e)
            yield _sse("error", {"status": 500, "body": DatabaseError(
                message=f"Failed to improve backlog quality: {safe_exc(e)}", operation="improve_quality"
            ).to_dict()})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def export_excel(gen_id: int):
    try:
        gen = get_generation(gen_id)
        if not gen:
            error = AppError(
                message=f"Generation {gen_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("Export", f"Generation {gen_id} not found for export")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )

        output = _generation_output_from_row(gen['output'])

        # Validate backlog depth before export
        validation_errors = validate_backlog_depth(output)
        if validation_errors:
            error = ValidationError(
                message="Backlog is too shallow to export. Run generation on a more detailed brief or allow expansion to complete.",
                details=f"{len(validation_errors)} validation errors found"
            )
            log_warning("Export", f"Validation failed for export: {len(validation_errors)} errors")
            return JSONResponse(
                status_code=422,
                content={
                    **error.to_dict(),
                    "validation_errors": validation_errors[:20]
                }
            )

        excel_bytes = generate_excel(output)
        log_info("Export", f"Excel file generated for generation {gen_id}")
        return StreamingResponse(
            iter([excel_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=stories_tasks_{gen_id}.xlsx"}
        )
    except Exception as e:
        error = FileError(
            message=f"Failed to export Excel for generation {gen_id}",
            filename=f"stories_tasks_{gen_id}.xlsx"
        )
        log_error("Export", f"Error exporting generation {gen_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.patch("/epics/{epic_id}/status")
def update_epic_status_endpoint(epic_id: int, request: StatusUpdateRequest):
    try:
        valid = {"planned", "in-progress", "done"}
        if request.status not in valid:
            error = ValidationError(f"Invalid status '{request.status}'. Choose from: {', '.join(valid)}")
            log_warning("StatusUpdate", f"Invalid epic status: {request.status}")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        updated = update_epic_status(epic_id, request.status)
        if not updated:
            error = AppError(
                message=f"Epic {epic_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("StatusUpdate", f"Epic {epic_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_info("StatusUpdate", f"Epic {epic_id} status updated to {request.status}")
        return {"updated": True, "id": epic_id, "status": request.status}
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to update epic {epic_id} status",
            operation="update_epic_status"
        )
        log_error("StatusUpdate", f"Error updating epic {epic_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.patch("/stories/{story_id}/status")
def update_story_status_endpoint(story_id: int, request: StatusUpdateRequest):
    try:
        valid = {"planned", "in-progress", "review", "done"}
        if request.status not in valid:
            error = ValidationError(f"Invalid status '{request.status}'. Choose from: {', '.join(valid)}")
            log_warning("StatusUpdate", f"Invalid story status: {request.status}")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        updated = update_story_status(story_id, request.status)
        if not updated:
            error = AppError(
                message=f"Story {story_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("StatusUpdate", f"Story {story_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_info("StatusUpdate", f"Story {story_id} status updated to {request.status}")
        return {"updated": True, "id": story_id, "status": request.status}
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to update story {story_id} status",
            operation="update_story_status"
        )
        log_error("StatusUpdate", f"Error updating story {story_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.patch("/tasks/{task_id}/status")
def update_task_status_endpoint(task_id: int, request: StatusUpdateRequest):
    try:
        valid = {"todo", "in-progress", "testing", "done"}
        if request.status not in valid:
            error = ValidationError(f"Invalid status '{request.status}'. Choose from: {', '.join(valid)}")
            log_warning("StatusUpdate", f"Invalid task status: {request.status}")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        updated = update_task_status(task_id, request.status)
        if not updated:
            error = AppError(
                message=f"Task {task_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("StatusUpdate", f"Task {task_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_info("StatusUpdate", f"Task {task_id} status updated to {request.status}")
        return {"updated": True, "id": task_id, "status": request.status}
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to update task {task_id} status",
            operation="update_task_status"
        )
        log_error("StatusUpdate", f"Error updating task {task_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.patch("/tasks/{task_id}/assignee")
def update_task_assignee_endpoint(task_id: int, request: AssigneeUpdateRequest):
    try:
        updated = update_task_assignee(task_id, request.assignee)
        if not updated:
            error = AppError(
                message=f"Task {task_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("AssigneeUpdate", f"Task {task_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_info("AssigneeUpdate", f"Task {task_id} assigned to {request.assignee or 'Unassigned'}")
        return {"updated": True, "id": task_id, "assignee": request.assignee}
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to update task {task_id} assignee",
            operation="update_task_assignee"
        )
        log_error("AssigneeUpdate", f"Error updating task {task_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.patch("/epics/{epic_id}/priority")
def update_epic_priority_endpoint(epic_id: int, request: PriorityUpdateRequest):
    try:
        updated = update_epic_priority(epic_id, request.priority)
        if not updated:
            error = AppError(message=f"Epic {epic_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("PriorityUpdate", f"Epic {epic_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("PriorityUpdate", f"Epic {epic_id} priority updated to {request.priority}")
        return {"updated": True, "id": epic_id, "priority": request.priority}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update epic {epic_id} priority", operation="update_epic_priority")
        log_error("PriorityUpdate", f"Error updating epic {epic_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.patch("/stories/{story_id}/priority")
def update_story_priority_endpoint(story_id: int, request: PriorityUpdateRequest):
    try:
        updated = update_story_priority(story_id, request.priority)
        if not updated:
            error = AppError(message=f"Story {story_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("PriorityUpdate", f"Story {story_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("PriorityUpdate", f"Story {story_id} priority updated to {request.priority}")
        return {"updated": True, "id": story_id, "priority": request.priority}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update story {story_id} priority", operation="update_story_priority")
        log_error("PriorityUpdate", f"Error updating story {story_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.patch("/tasks/{task_id}/priority")
def update_task_priority_endpoint(task_id: int, request: PriorityUpdateRequest):
    try:
        updated = update_task_priority(task_id, request.priority)
        if not updated:
            error = AppError(message=f"Task {task_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("PriorityUpdate", f"Task {task_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("PriorityUpdate", f"Task {task_id} priority updated to {request.priority}")
        return {"updated": True, "id": task_id, "priority": request.priority}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update task {task_id} priority", operation="update_task_priority")
        log_error("PriorityUpdate", f"Error updating task {task_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.patch("/epics/{epic_id}")
def update_epic_content_endpoint(epic_id: int, request: EpicEditRequest):
    try:
        fields = request.model_dump(exclude_unset=True)
        updated = update_epic_content(epic_id, fields)
        if not updated:
            error = AppError(message=f"Epic {epic_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("ContentUpdate", f"Epic {epic_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("ContentUpdate", f"Epic {epic_id} content updated ({', '.join(fields) or 'no fields'})")
        return {"updated": True, "id": epic_id, **fields}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update epic {epic_id} content", operation="update_epic_content")
        log_error("ContentUpdate", f"Error updating epic {epic_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/epics")
def create_epic_endpoint(request: EpicCreateRequest):
    try:
        created = create_epic(request.generation_id, request.model_dump(exclude={"generation_id"}))
        if not created:
            return JSONResponse(status_code=404, content=AppError(
                message=f"Generation {request.generation_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Created epic {created['issue_id']} in generation {request.generation_id}")
        return {"created": True, **created}
    except Exception as e:
        log_error("BacklogCRUD", "Error creating epic", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message="Failed to create epic", operation="create_epic"
        ).to_dict())


@app.delete("/epics/{epic_id}")
def delete_epic_endpoint(epic_id: int):
    try:
        if not delete_epic(epic_id):
            return JSONResponse(status_code=404, content=AppError(
                message=f"Epic {epic_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Deleted epic {epic_id} and its descendants")
        return {"deleted": True, "id": epic_id}
    except Exception as e:
        log_error("BacklogCRUD", f"Error deleting epic {epic_id}", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message=f"Failed to delete epic {epic_id}", operation="delete_epic"
        ).to_dict())


@app.patch("/stories/{story_id}")
def update_story_content_endpoint(story_id: int, request: StoryEditRequest):
    try:
        fields = request.model_dump(exclude_unset=True)
        updated = update_story_content(story_id, fields)
        if not updated:
            error = AppError(message=f"Story {story_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("ContentUpdate", f"Story {story_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("ContentUpdate", f"Story {story_id} content updated ({', '.join(fields) or 'no fields'})")
        return {"updated": True, "id": story_id, **fields}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update story {story_id} content", operation="update_story_content")
        log_error("ContentUpdate", f"Error updating story {story_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/stories")
def create_story_endpoint(request: StoryCreateRequest):
    try:
        created = create_story(request.epic_id, request.model_dump(exclude={"epic_id"}))
        if not created:
            return JSONResponse(status_code=404, content=AppError(
                message=f"Epic {request.epic_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Created story {created['issue_id']} under epic {request.epic_id}")
        return {"created": True, **created}
    except Exception as e:
        log_error("BacklogCRUD", "Error creating story", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message="Failed to create story", operation="create_story"
        ).to_dict())


@app.delete("/stories/{story_id}")
def delete_story_endpoint(story_id: int):
    try:
        if not delete_story(story_id):
            return JSONResponse(status_code=404, content=AppError(
                message=f"Story {story_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Deleted story {story_id} and its tasks")
        return {"deleted": True, "id": story_id}
    except Exception as e:
        log_error("BacklogCRUD", f"Error deleting story {story_id}", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message=f"Failed to delete story {story_id}", operation="delete_story"
        ).to_dict())


@app.patch("/tasks/{task_id}")
def update_task_content_endpoint(task_id: int, request: TaskEditRequest):
    try:
        fields = request.model_dump(exclude_unset=True)
        updated = update_task_content(task_id, fields)
        if not updated:
            error = AppError(message=f"Task {task_id} not found", severity=ErrorSeverity.WARNING)
            log_warning("ContentUpdate", f"Task {task_id} not found")
            return JSONResponse(status_code=404, content=error.to_dict())
        log_info("ContentUpdate", f"Task {task_id} content updated ({', '.join(fields) or 'no fields'})")
        return {"updated": True, "id": task_id, **fields}
    except Exception as e:
        error = DatabaseError(message=f"Failed to update task {task_id} content", operation="update_task_content")
        log_error("ContentUpdate", f"Error updating task {task_id}", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/tasks")
def create_task_endpoint(request: TaskCreateRequest):
    try:
        created = create_task(request.story_id, request.model_dump(exclude={"story_id"}))
        if not created:
            return JSONResponse(status_code=404, content=AppError(
                message=f"Story {request.story_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Created task {created['issue_id']} under story {request.story_id}")
        return {"created": True, **created}
    except Exception as e:
        log_error("BacklogCRUD", "Error creating task", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message="Failed to create task", operation="create_task"
        ).to_dict())


@app.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: int):
    try:
        if not delete_task(task_id):
            return JSONResponse(status_code=404, content=AppError(
                message=f"Task {task_id} not found", severity=ErrorSeverity.WARNING
            ).to_dict())
        log_info("BacklogCRUD", f"Deleted task {task_id}")
        return {"deleted": True, "id": task_id}
    except Exception as e:
        log_error("BacklogCRUD", f"Error deleting task {task_id}", exception=e)
        return JSONResponse(status_code=500, content=DatabaseError(
            message=f"Failed to delete task {task_id}", operation="delete_task"
        ).to_dict())


@app.get("/dashboard")
def get_dashboard_endpoint():
    try:
        stats = get_dashboard_stats()
        log_debug("Dashboard", "Dashboard stats retrieved")
        return stats
    except Exception as e:
        error = DatabaseError(
            message="Failed to retrieve dashboard statistics",
            operation="get_dashboard_stats"
        )
        log_error("Dashboard", "Error retrieving dashboard stats", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.get("/generation-summaries")
def list_generation_summaries_endpoint():
    """Every generation with epic/story/task counts — not to be confused
    with GET /projects (app/api/projects.py), the first-class Project
    entity. This predates Projects and was never called by the frontend or
    tested directly; kept (renamed off the now-taken /projects path) rather
    than removed outright in case something external still hits it."""
    try:
        projects = get_all_projects()
        log_debug("Projects", f"Listed {len(projects)} projects")
        return {"projects": projects}
    except Exception as e:
        error = DatabaseError(
            message="Failed to retrieve projects",
            operation="get_all_projects"
        )
        log_error("Projects", "Error listing projects", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/redmine/projects/list")
def list_redmine_projects_endpoint(request: RedmineConnectionRequest):
    try:
        redmine_url = validate_redmine_url(request.redmine_url)
        result = describe_redmine_workspace(redmine_url, request.redmine_api_key)
        log_info("Redmine", "Projects listed from Redmine")
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content=ValidationError(str(e)).to_dict())
    except Exception as e:
        error = APIError(
            provider="Redmine",
            message=f"Failed to list Redmine projects: {safe_exc(e)}",
            status_code=None
        )
        log_error("Redmine", "Error listing Redmine projects", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/redmine/projects/create")
def create_redmine_project_endpoint(request: RedmineProjectCreateRequest):
    try:
        if not request.name.strip():
            error = ValidationError("Project name is required.")
            log_warning("Redmine", "Project creation failed: empty name")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )
        redmine_url = validate_redmine_url(request.redmine_url)
        result = create_redmine_project(
            redmine_url,
            request.redmine_api_key,
            name=request.name.strip(),
            identifier=request.identifier.strip() if request.identifier else None,
            description=request.description.strip(),
            parent_project_ref=request.parent_project_ref.strip() if request.parent_project_ref else None,
            is_public=request.is_public,
            inherit_members=request.inherit_members,
        )
        log_info("Redmine", f"Project created in Redmine: {request.name}")
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content=ValidationError(str(e)).to_dict())
    except Exception as e:
        error = APIError(
            provider="Redmine",
            message=f"Failed to create Redmine project: {safe_exc(e)}",
            status_code=None
        )
        log_error("Redmine", "Error creating Redmine project", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


def _scope_output_to_epic(output: GenerationOutput, epic_id: str) -> GenerationOutput:
    """Reduce a full backlog down to one epic and everything under it — used
    for "push this to Redmine" from a single epic/story/task's detail view.
    Always includes the whole branch (never a bare story/task alone), so the
    pushed issues can never end up orphaned in Redmine with no epic parent."""
    epic = next((e for e in output.epics if e.id == epic_id), None)
    if epic is None:
        raise ValueError(f"Epic '{epic_id}' not found in this generation")
    stories = [s for s in output.stories if s.epic_id == epic_id]
    story_ids = {s.id for s in stories}
    tasks = [t for t in output.tasks if t.story_id in story_ids]
    return GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[epic],
        stories=stories,
        tasks=tasks,
        gaps=[],
        metrics=None,
        validation=None,
    )


def _record_redmine_ids(result: dict, hierarchy: dict) -> None:
    """Persist Redmine issue ids and actual Redmine priority labels into normalized rows."""
    row_maps = {"epic": {}, "story": {}, "task": {}}
    for epic in hierarchy.get("epics", []):
        row_maps["epic"][epic.get("ai_id")] = epic.get("db_id")
        for story in epic.get("stories", []):
            row_maps["story"][story.get("ai_id")] = story.get("db_id")
            for task in story.get("tasks", []):
                row_maps["task"][task.get("ai_id")] = task.get("db_id")

    updaters = {
        "epic": update_epic_redmine_id,
        "story": update_story_redmine_id,
        "task": update_task_redmine_id,
    }

    for issue in result.get("created_issues", []):
        if issue.get("error") or not issue.get("redmine_id"):
            continue
        issue_type = issue.get("type")
        ai_id = issue.get("ai_id")
        db_id = row_maps.get(issue_type, {}).get(ai_id)
        if not db_id:
            continue
        issue["db_id"] = db_id
        updaters[issue_type](db_id, int(issue["redmine_id"]), issue.get("redmine_priority_name"))


def _existing_redmine_ids(hierarchy: dict) -> dict[str, dict[str, int]]:
    """Build the saved AutoSDLC id -> Redmine id map used for idempotent sync."""
    result: dict[str, dict[str, int]] = {"epic": {}, "story": {}, "task": {}}
    for epic in hierarchy.get("epics", []):
        epic_ai_id = epic.get("ai_id") or epic.get("issue_id")
        if epic_ai_id and epic.get("redmine_id"):
            result["epic"][epic_ai_id] = int(epic["redmine_id"])
        for story in epic.get("stories", []):
            story_ai_id = story.get("ai_id") or story.get("issue_id")
            if story_ai_id and story.get("redmine_id"):
                result["story"][story_ai_id] = int(story["redmine_id"])
            for task in story.get("tasks", []):
                task_ai_id = task.get("ai_id") or task.get("issue_id")
                if task_ai_id and task.get("redmine_id"):
                    result["task"][task_ai_id] = int(task["redmine_id"])
    return result


def _record_bitbucket_ids(result: dict, hierarchy: dict) -> None:
    """Bitbucket counterpart to _record_redmine_ids — same row-map-then-update shape."""
    row_maps = {"epic": {}, "story": {}, "task": {}}
    for epic in hierarchy.get("epics", []):
        row_maps["epic"][epic.get("ai_id")] = epic.get("db_id")
        for story in epic.get("stories", []):
            row_maps["story"][story.get("ai_id")] = story.get("db_id")
            for task in story.get("tasks", []):
                row_maps["task"][task.get("ai_id")] = task.get("db_id")

    updaters = {
        "epic": update_epic_bitbucket_id,
        "story": update_story_bitbucket_id,
        "task": update_task_bitbucket_id,
    }
    for issue in result.get("created_issues", []):
        if issue.get("error") or not issue.get("bitbucket_id"):
            continue
        issue_type = issue.get("type")
        db_id = row_maps.get(issue_type, {}).get(issue.get("ai_id"))
        if not db_id:
            continue
        issue["db_id"] = db_id
        updaters[issue_type](db_id, str(issue["bitbucket_id"]))


def _existing_bitbucket_ids(hierarchy: dict) -> dict[str, dict[str, str]]:
    """Bitbucket counterpart to _existing_redmine_ids."""
    result: dict[str, dict[str, str]] = {"epic": {}, "story": {}, "task": {}}
    for epic in hierarchy.get("epics", []):
        epic_ai_id = epic.get("ai_id") or epic.get("issue_id")
        if epic_ai_id and epic.get("bitbucket_id"):
            result["epic"][epic_ai_id] = str(epic["bitbucket_id"])
        for story in epic.get("stories", []):
            story_ai_id = story.get("ai_id") or story.get("issue_id")
            if story_ai_id and story.get("bitbucket_id"):
                result["story"][story_ai_id] = str(story["bitbucket_id"])
            for task in story.get("tasks", []):
                task_ai_id = task.get("ai_id") or task.get("issue_id")
                if task_ai_id and task.get("bitbucket_id"):
                    result["task"][task_ai_id] = str(task["bitbucket_id"])
    return result


def _run_redmine_trust_gate(output: GenerationOutput) -> JSONResponse | None:
    """Independently re-score a backlog immediately before external sync."""
    metrics = compute_metrics(output)
    validation = run_validation(metrics)
    output.metrics = metrics
    output.validation = validation
    if validation.trust_level == "trusted":
        return None

    failed = [
        f"{check.label}: {check.value} (required {check.threshold})"
        for check in validation.checks
        if not check.passed
    ]
    message = "Automated trust gate blocked Redmine sync. " + "; ".join(failed)
    return JSONResponse(
        status_code=422,
        content={
            "message": message,
            "userAction": "Improve the flagged backlog areas and regenerate before syncing.",
            "validation": validation.model_dump(),
        },
    )


@app.get("/hierarchy/{gen_id}")
def get_hierarchy_endpoint(gen_id: int):
    try:
        hierarchy = get_generation_hierarchy(gen_id)
        if not hierarchy:
            error = AppError(
                message=f"Generation {gen_id} not found",
                severity=ErrorSeverity.WARNING
            )
            log_warning("Hierarchy", f"Generation {gen_id} not found")
            return JSONResponse(
                status_code=404,
                content=error.to_dict()
            )
        log_debug("Hierarchy", f"Hierarchy retrieved for generation {gen_id}")
        return hierarchy
    except Exception as e:
        error = DatabaseError(
            message=f"Failed to retrieve hierarchy for generation {gen_id}",
            operation="get_generation_hierarchy"
        )
        log_error("Hierarchy", f"Error retrieving hierarchy for {gen_id}", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/push-to-redmine")
def push_to_redmine_endpoint(request: RedminePushRequest):
    try:
        redmine_url = validate_redmine_url(request.redmine_url)
        config = RedmineConfig(
            url=redmine_url,
            api_key=request.redmine_api_key,
            project_id=request.redmine_project_id
        )

        if not config.is_configured():
            error = ValidationError("Redmine URL, API key, and project ID are required.")
            log_warning("Redmine", "Push to Redmine: missing configuration")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )

        # Load output from DB if generation_id provided
        if request.generation_id:
            hierarchy = get_generation_hierarchy(request.generation_id)
            if not hierarchy:
                error = AppError(
                    message=f"Generation {request.generation_id} not found",
                    severity=ErrorSeverity.WARNING
                )
                log_warning("Redmine", f"Generation {request.generation_id} not found for push")
                return JSONResponse(
                    status_code=404,
                    content=error.to_dict()
                )
            gen = get_generation(request.generation_id)
            if not gen:
                error = AppError(
                    message=f"Generation {request.generation_id} not found",
                    severity=ErrorSeverity.WARNING
                )
                log_warning("Redmine", f"Generation {request.generation_id} not found")
                return JSONResponse(
                    status_code=404,
                    content=error.to_dict()
                )
            output = _generation_output_from_row(gen['output'])
            trust_failure = _run_redmine_trust_gate(output)
            if trust_failure:
                log_warning("Redmine", "Automated trust gate blocked sync")
                return trust_failure
            if request.epic_id:
                try:
                    output = _scope_output_to_epic(output, request.epic_id)
                except ValueError as e:
                    error = ValidationError(str(e))
                    log_warning("Redmine", f"Scoped push failed: {e}")
                    return JSONResponse(status_code=400, content=error.to_dict())
            result = push_to_redmine(output, config, _existing_redmine_ids(hierarchy))
            # hierarchy (not the possibly-scoped output) is the full ai_id ->
            # db_id map _record_redmine_ids needs — it only touches whatever
            # issues actually appear in result["created_issues"], so passing
            # the unscoped hierarchy here is correct either way.
            _record_redmine_ids(result, hierarchy)
        elif request.output:
            output = GenerationOutput(**request.output)
            trust_failure = _run_redmine_trust_gate(output)
            if trust_failure:
                log_warning("Redmine", "Automated trust gate blocked sync")
                return trust_failure
            result = push_to_redmine(output, config)
        else:
            error = ValidationError("Provide generation_id or output.")
            log_warning("Redmine", "Push to Redmine: no generation_id or output provided")
            return JSONResponse(
                status_code=400,
                content=error.to_dict()
            )

        log_info("Redmine", f"Successfully pushed to Redmine project {config.project_id}")
        return result
    except ValueError as e:
        error = ValidationError(str(e))
        log_warning("Redmine", f"Redmine request rejected: {e}")
        return JSONResponse(status_code=400, content=error.to_dict())
    except Exception as e:
        error = APIError(
            provider="Redmine",
            message=f"Failed to push to Redmine: {safe_exc(e)}",
            status_code=None
        )
        log_error("Redmine", "Error pushing to Redmine", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/push-to-bitbucket")
def push_to_bitbucket_endpoint(request: BitbucketPushRequest):
    """Mirrors /push-to-redmine's shape (main.py's push_to_redmine_endpoint)
    closely: same trust-gate-before-push, same generation_id-or-output
    branching. Bitbucket connection config resolves through the
    generation's project (N linked repos — request.repo_id picks one,
    omitted uses the project's default) with env vars as the fallback —
    see _bitbucket_config_for_project."""
    try:
        project_id = get_generation_project_id(request.generation_id) if request.generation_id else None
        config = _bitbucket_config_for_project(project_id, request.repo_id)
        if not config.is_configured():
            error = ValidationError(
                "Bitbucket not configured. Set BITBUCKET_BASE_URL, BITBUCKET_WORKSPACE, "
                "BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN in .env"
            )
            log_warning("Bitbucket", "Push to Bitbucket: missing configuration")
            return JSONResponse(status_code=400, content=error.to_dict())
        validate_bitbucket_url(config.base_url)

        if request.generation_id:
            hierarchy = get_generation_hierarchy(request.generation_id)
            if not hierarchy:
                error = AppError(message=f"Generation {request.generation_id} not found", severity=ErrorSeverity.WARNING)
                log_warning("Bitbucket", f"Generation {request.generation_id} not found for push")
                return JSONResponse(status_code=404, content=error.to_dict())
            gen = get_generation(request.generation_id)
            if not gen:
                error = AppError(message=f"Generation {request.generation_id} not found", severity=ErrorSeverity.WARNING)
                return JSONResponse(status_code=404, content=error.to_dict())
            output = _generation_output_from_row(gen['output'])
            trust_failure = _run_redmine_trust_gate(output)  # same trust gate; not Redmine-specific despite the name
            if trust_failure:
                log_warning("Bitbucket", "Automated trust gate blocked sync")
                return trust_failure
            if request.epic_id:
                try:
                    output = _scope_output_to_epic(output, request.epic_id)
                except ValueError as e:
                    return JSONResponse(status_code=400, content=ValidationError(str(e)).to_dict())
            result = push_backlog_to_bitbucket(output, config, _existing_bitbucket_ids(hierarchy))
            _record_bitbucket_ids(result, hierarchy)
        elif request.output:
            output = GenerationOutput(**request.output)
            trust_failure = _run_redmine_trust_gate(output)
            if trust_failure:
                log_warning("Bitbucket", "Automated trust gate blocked sync")
                return trust_failure
            result = push_backlog_to_bitbucket(output, config)
        else:
            return JSONResponse(status_code=400, content=ValidationError("Provide generation_id or output.").to_dict())

        log_info("Bitbucket", f"Successfully pushed to Bitbucket repo {config.workspace}/{config.repo_slug}")
        return result
    except BitbucketWritesDisabledError as e:
        # Not safe_exc()'d — this message is meant to be seen (it's not
        # leaking anything, it's the whole point), and safe_exc hides it
        # behind a generic placeholder in production.
        log_warning("Bitbucket", str(e))
        return JSONResponse(status_code=403, content=ValidationError(str(e)).to_dict())
    except ValueError as e:
        log_warning("Bitbucket", f"Bitbucket request rejected: {e}")
        return JSONResponse(status_code=400, content=ValidationError(str(e)).to_dict())
    except Exception as e:
        log_error("Bitbucket", "Error pushing to Bitbucket", exception=e)
        return JSONResponse(status_code=500, content=APIError(provider="Bitbucket", message=f"Failed to push to Bitbucket: {safe_exc(e)}").to_dict())


def _generation_job_runner(payload: dict):
    """Adapt the existing generation SSE stream to persisted job events."""
    for chunk in _stream_generate(payload.get("text", ""), payload.get("clarification_answers") or {}, payload.get("project_id")):
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            event_type = str(event.pop("type", "message"))
            yield event_type, event


def _generation_phase_job_runner(payload: dict):
    phase = payload.get("phase")
    if phase == "epics":
        stream = _stream_generate_epics(payload.get("text", ""), payload.get("project_id"))
    elif phase == "stories":
        stream = _stream_generate_stories(int(payload["generation_id"]))
    elif phase == "tasks":
        stream = _stream_generate_tasks(int(payload["generation_id"]))
    elif phase == "tests":
        stream = _stream_generate_test_cases(int(payload["generation_id"]))
    else:
        raise ValueError(f"Unsupported generation phase: {phase}")
    for chunk in stream:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                event = json.loads(line[len("data: "):])
                yield str(event.pop("type", "message")), event


_DIFF_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
# Generic identifiers common enough in almost any diff to be useless as a
# related-repo search term (they'd match nearly every file and defeat the
# point of ranking by relevance at all).
_DIFF_TERM_STOPWORDS = {
    "self", "this", "true", "false", "null", "none", "return", "import",
    "export", "const", "function", "class", "async", "await", "from",
    "value", "props", "state", "index", "params", "config", "error",
}


def _extract_diff_terms(diff_text: str, limit: int = 12) -> list[str]:
    """Identifiers touched by a PR's added/removed lines (e.g. ``getDayEnd``,
    ``maxDateTime``) — used to steer a related repo's file selection toward
    what this PR actually changed instead of a generic file sample. Diff
    context/unchanged lines are skipped so this reflects the change itself,
    not everything the changed files happen to reference."""
    counts: Counter[str] = Counter()
    for line in diff_text.splitlines():
        if not line[:1] in {"+", "-"} or line[:3] in {"+++", "---"}:
            continue
        for term in _DIFF_TERM_RE.findall(line[1:]):
            lower = term.lower()
            if lower in _DIFF_TERM_STOPWORDS:
                continue
            counts[term] += 1
    return [term for term, _ in counts.most_common(limit)]


def _related_repo_review_context(related_repos: list[dict] | None, diff_text: str = "") -> str:
    terms = _extract_diff_terms(diff_text) if diff_text else []
    blocks = []
    for repo in (related_repos or [])[:5]:
        config = BitbucketConfig.from_env()
        config.workspace = repo.get("workspace", "")
        config.repo_slug = repo.get("repo_slug", "")
        if not config.is_configured():
            continue
        label = repo.get("label") or f"{config.workspace}/{config.repo_slug}"
        if terms:
            # Diff-derived identifiers (getDayEnd, maxDateTime, ...) — one
            # shallow clone + local grep (app/services/related_repo_context.py)
            # instead of an API file-walk, which would cost one Bitbucket
            # request per candidate file searched and risks rate limits.
            context = build_related_repo_context_block(
                config, terms, label=label, branch=repo.get("scan_branch"),
            )
        else:
            # No diff terms to search on (e.g. an empty/binary-only diff) —
            # fall back to the old generic snapshot rather than skipping
            # the related repo's context entirely.
            context = build_repo_context_block(config, max_files=120)
        if context:
            blocks.append(context if terms else f"## Related repository: {label}\n{context}")
    return "\n\n".join(blocks)


def _stream_bitbucket_review(
    repo_full_name: str, pr_id: int | str, related_repos: list[dict] | None = None
):
    """Orchestrates one PR review, triggered by the webhook (app/api/webhooks.py)
    or run manually: fetch PR context -> run the review agent -> retain the
    result inside this app. Publishing is a separate confirmed endpoint in
    app/api/projects.py and is never part of this job. Same
    SSE-event convention as generation, so the job runner adapter below is
    identical in shape to _generation_job_runner.

    config used to be BitbucketConfig.from_env() unconditionally, which
    ignored repo_full_name entirely and always queried the single
    BITBUCKET_WORKSPACE/BITBUCKET_REPO_SLUG env repo — harmless with one
    linked repo, but a 404 for every PR on any other repo once a project has
    N repos (app/api/projects.py's per-repo trigger endpoint). Overriding
    workspace/repo_slug from repo_full_name here is what
    _stream_security_scan already does correctly for its own per-repo config."""
    review_started_at = time.monotonic()
    config = BitbucketConfig.from_env()
    if "/" in repo_full_name:
        workspace, _, repo_slug = repo_full_name.partition("/")
        config.workspace = workspace
        config.repo_slug = repo_slug
    if not config.is_configured():
        yield _sse("error", GenerationError(message="Bitbucket not configured.", phase="Code Review").to_dict())
        return
    try:
        get_pull_request(config, pr_id)  # existence/permissions check before the (heavier) diff fetch
        diff = get_pull_request_diff(config, pr_id)
    except Exception as e:
        log_error("CodeReview", f"Failed to fetch PR #{pr_id} context", exception=e)
        yield _sse("error", GenerationError(message=f"Failed to fetch PR: {safe_exc(e)}", phase="Code Review").to_dict())
        return

    provider = get_provider()
    related_context = _related_repo_review_context(related_repos, diff_text=diff)
    findings: list[dict] = []
    review_stream = (
        run_code_review(repo_full_name, pr_id, diff, provider, related_context)
        if related_context else run_code_review(repo_full_name, pr_id, diff, provider)
    )
    for chunk in review_stream:
        # sse() (app/utils/sse.py) frames exactly one event per chunk, so
        # there's at most one "data: " line to find here.
        event = next((json.loads(line[len("data: "):]) for line in chunk.splitlines() if line.startswith("data: ")), None)
        if event is None:
            yield chunk
            continue
        event_type = event.get("type")
        if event_type == "finding":
            findings.append(event["finding"])
        if event_type != "done":
            yield chunk
            continue
        findings = event.get("findings", findings)
        # provider is fresh per review (get_provider() above, not reused
        # across calls), so usage_log holds exactly this review's one
        # completion — same pattern main.py's generation endpoints use to
        # populate output.metrics.token_usage.
        if hasattr(provider, "usage_summary"):
            usage = provider.usage_summary()
            event["token_usage"] = usage
            event["duration_seconds"] = round(time.monotonic() - review_started_at, 1)
            if usage.get("ai_calls"):
                record_token_usage(
                    "bitbucket_review", f"{repo_full_name}#{pr_id}", getattr(provider, "provider_id", None), usage,
                    duration_seconds=event["duration_seconds"],
                )
        yield _sse("done", {k: v for k, v in event.items() if k != "type"})

    # Deliberately read-only. Review findings remain in this app and are
    # never posted to Bitbucket implicitly. Publishing requires a separate,
    # explicit user-confirmed action (none of the review triggers do that).


def _bitbucket_review_job_runner(payload: dict):
    """Adapt _stream_bitbucket_review's SSE stream to persisted job events —
    identical adapter shape to _generation_job_runner/_generation_phase_job_runner."""
    for chunk in _stream_bitbucket_review(
        payload.get("repo_full_name", ""), payload.get("pr_id"), payload.get("related_repos"),
    ):
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            event_type = str(event.pop("type", "message"))
            yield event_type, event


def _persist_full_repository_scan(
    *, project_id: int | None, repo_id: int, branch: str | None, commit_sha: str | None,
    findings: list[dict], ai_error: str | None,
) -> None:
    """Best-effort: writes a FULL_REPOSITORY security_scans/security_findings
    row alongside the existing jobs/job_events record, so this scan becomes
    a usable PR-analysis baseline (security/baseline.py) without changing
    anything the existing Security view already reads from jobs. Never
    raises — a persistence failure here must not turn a successful scan
    into a failed job."""
    try:
        scan = create_security_scan(scan_type="FULL_REPOSITORY", project_id=project_id, repo_id=repo_id, branch=branch, commit_sha=commit_sha)
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        rows = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity") or "medium").lower()
            if severity not in severity_counts:
                severity = "medium"
            severity_counts[severity] += 1
            rows.append({
                "fingerprint": finding.get("fingerprint") or fingerprint_finding(finding),
                "source": finding.get("tool") or finding.get("source") or "llm_repository_review",
                "rule_id": finding.get("rule_id"), "title": finding.get("comment") or finding.get("title"),
                "description": finding.get("comment") or finding.get("description"),
                "severity": severity, "confidence": None,
                "file": finding.get("file"), "start_line": finding.get("line") or finding.get("start_line"),
                "end_line": finding.get("end_line"), "symbol": finding.get("symbol"),
                "category": finding.get("category"), "cwe": finding.get("cwe"), "cve": None,
                "evidence": finding.get("evidence"), "remediation": finding.get("recommendation"),
                "relation_to_pr": None, "relation_confidence": None,
            })
        save_security_findings(scan["id"], rows)
        update_security_scan(
            scan["id"], status="succeeded", severity_counts=severity_counts,
            llm_review_status="failed" if ai_error else "ok", completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        log_warning("SecurityScan", f"Failed to persist FULL_REPOSITORY scan record for repo {repo_id}: {exc}")


def _stream_security_scan(repo_id: int, label: str, workspace: str, repo_slug: str, scan_branch: str | None = None, project_id: int | None = None):
    """VAPT Phase 1 — orchestrates one repo's security scan: fetch its
    current contents -> run the security review agent. No push-back step
    (unlike _stream_bitbucket_review's PR comments): this is a project-wide
    posture check, read into the Security view, not something posted
    anywhere on Bitbucket. ``scan_branch`` pins both the AI review's context
    and the deterministic scanners to a specific branch, for a repo whose
    Bitbucket-configured default branch isn't where the real code lives.
    ``project_id`` is only used to link the persisted security_scans row
    (PHASE 16) — every existing behavior here is otherwise unaffected."""
    scan_started_at = time.monotonic()
    config = BitbucketConfig.from_env()
    config.workspace = workspace
    config.repo_slug = repo_slug
    if not config.is_configured():
        yield _sse("error", GenerationError(message="Bitbucket not configured for this repo.", phase="Security Scan").to_dict())
        return
    try:
        context_block = build_repo_context_block(config, ref=scan_branch or "HEAD")
    except Exception as e:
        log_error("SecurityScan", f"Failed to fetch repo context for {label}", exception=e)
        yield _sse("error", GenerationError(message=f"Failed to fetch repo contents: {safe_exc(e)}", phase="Security Scan").to_dict())
        return

    provider = get_provider()
    deterministic = {"tools": [], "findings": [], "snapshot_files": 0, "commit": None, "partial": True}
    try:
        for event_type, payload in run_deterministic_scan(config, branch=scan_branch):
            yield _sse(event_type, payload)
            if event_type == "deterministic_complete":
                deterministic = {
                    "tools": [{**tool, "name": tool.get("name") or tool.get("tool")} for tool in payload.get("tools", [])],
                    "findings": payload.get("findings", []),
                    "snapshot_files": payload.get("snapshot_files", 0),
                    "commit": payload.get("commit"),
                    "partial": payload.get("partial", False),
                }
    except Exception as e:
        log_error("SecurityScan", f"Deterministic VAPT scanners failed for {label}", exception=e)
        deterministic["tools"] = [{"name": "repository-snapshot", "status": "failed", "findings_count": 0, "error": safe_exc(e)}]
        yield _sse("scanner_status", {"stage": "snapshot", "status": "failed", "error": safe_exc(e)})
    for chunk in run_security_review(repo_id, label, context_block, provider):
        event = next((json.loads(line[len("data: "):]) for line in chunk.splitlines() if line.startswith("data: ")), None)
        if event is None:
            yield chunk
            continue
        if event.get("type") == "error":
            # Deterministic scanners remain useful even when no AI provider is
            # available. Persist a completed scanner result with the AI error
            # visible instead of turning the entire VAPT run into a blank job.
            error_payload = event.get("error") or event
            ai_error_message = error_payload.get("message", "AI security review failed")
            _persist_full_repository_scan(
                project_id=project_id, repo_id=repo_id, branch=scan_branch, commit_sha=deterministic.get("commit"),
                findings=deterministic.get("findings", []), ai_error=ai_error_message,
            )
            yield _sse("done", {
                "findings": [],
                "scanner_findings": deterministic.get("findings", []),
                "tools": deterministic.get("tools", []),
                "snapshot_files": deterministic.get("snapshot_files", 0),
                "ai_error": ai_error_message,
                "duration_seconds": round(time.monotonic() - scan_started_at, 1),
            })
            return
        if event.get("type") != "done":
            yield chunk
            continue
        event["tools"] = deterministic.get("tools", [])
        event["scanner_findings"] = deterministic.get("findings", [])
        event["snapshot_files"] = deterministic.get("snapshot_files", 0)
        event["scanner_commit"] = deterministic.get("commit")
        event["duration_seconds"] = round(time.monotonic() - scan_started_at, 1)
        _persist_full_repository_scan(
            project_id=project_id, repo_id=repo_id, branch=scan_branch, commit_sha=deterministic.get("commit"),
            findings=[*deterministic.get("findings", []), *event.get("findings", [])], ai_error=None,
        )
        if hasattr(provider, "usage_summary"):
            usage = provider.usage_summary()
            event["token_usage"] = usage
            if usage.get("ai_calls"):
                record_token_usage(
                    "security_scan", f"{workspace}/{repo_slug}", getattr(provider, "provider_id", None), usage,
                    duration_seconds=event["duration_seconds"],
                )
        yield _sse("done", {k: v for k, v in event.items() if k != "type"})


def _security_scan_job_runner(payload: dict):
    """Same adapter shape as _bitbucket_review_job_runner."""
    for chunk in _stream_security_scan(
        payload.get("repo_id"), payload.get("label", ""), payload.get("workspace", ""), payload.get("repo_slug", ""),
        scan_branch=payload.get("scan_branch"), project_id=payload.get("project_id"),
    ):
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            event_type = str(event.pop("type", "message"))
            yield event_type, event


# ── PR Impact Security Analysis ──────────────────────────────────────────
# Orchestrates every stage in app/services/security/: PR diff -> head
# snapshot -> repository index -> changed-symbol mapping -> impact graph ->
# security-context enrichment -> existing deterministic scanners (same
# snapshot, unmodified) -> correlation -> baseline -> PR LLM review ->
# merge -> persistence. Every optional/heuristic stage degrades gracefully
# rather than failing the whole scan (PHASE 30 of the plan) — only PR
# metadata/diff fetch and the repository snapshot are hard requirements.

def _stream_pr_security_scan(
    project_id: int | None, repo_id: int, workspace: str, repo_slug: str,
    pull_request_id: str, scan_branch: str | None = None,
):
    scan_started_at = time.monotonic()
    config = BitbucketConfig.from_env()
    config.workspace = workspace
    config.repo_slug = repo_slug
    if not config.is_configured():
        yield _sse("error", GenerationError(message="Bitbucket not configured for this repo.", phase="PR Security Scan").to_dict())
        return

    yield _sse("status", {"stage": "pr_metadata", "status": "running", "message": f"Fetching PR #{pull_request_id} metadata and diff…"})
    try:
        pr_diff = fetch_pull_request_diff(config, pull_request_id)
    except Exception as e:
        log_error("PRSecurityScan", f"Failed to fetch PR #{pull_request_id} for {workspace}/{repo_slug}", exception=e)
        yield _sse("error", GenerationError(message=f"Failed to fetch PR: {safe_exc(e)}", phase="PR Security Scan").to_dict())
        return
    yield _sse("status", {"stage": "pr_metadata", "status": "completed", "changed_files": len(pr_diff.files), "diff_truncated": pr_diff.truncated})

    budget = default_budget()
    truncation = TruncationRecord()
    if pr_diff.truncated:
        truncation.note("diff_truncated", "PR diff exceeded size/file limits and was truncated")

    security_scan = create_security_scan(
        scan_type="PULL_REQUEST", project_id=project_id, repo_id=repo_id, pull_request_id=str(pull_request_id),
        base_commit_sha=pr_diff.info.base_sha or None, head_commit_sha=pr_diff.info.head_sha or None,
    )
    update_security_scan(security_scan["id"], status="running", started_at=datetime.now(timezone.utc).isoformat())

    with TemporaryDirectory(prefix="autosdlc-pr-security-") as temp:
        source = Path(temp) / "source"
        yield _sse("status", {"stage": "snapshot", "status": "running", "message": "Creating repository snapshot at PR head…"})
        try:
            head_commit = create_repository_snapshot(
                config, source, branch=pr_diff.info.source_branch or scan_branch or None,
                commit_sha=pr_diff.info.head_sha or None,
                timeout_seconds=max(30, int(os.getenv("PR_SNAPSHOT_TIMEOUT_SECONDS", "180"))),
            )
        except Exception as e:
            log_error("PRSecurityScan", f"Failed to snapshot PR #{pull_request_id} head for {workspace}/{repo_slug}", exception=e)
            update_security_scan(security_scan["id"], status="failed", completed_at=datetime.now(timezone.utc).isoformat())
            yield _sse("error", GenerationError(message=f"Failed to create repository snapshot: {safe_exc(e)}", phase="PR Security Scan").to_dict())
            return
        yield _sse("status", {"stage": "snapshot", "status": "completed", "commit": head_commit})

        yield _sse("status", {"stage": "index", "status": "running", "message": "Building repository intelligence index…"})
        index = None
        if project_id is not None:
            try:
                cached = get_repository_index(repo_id, head_commit, branch_name=pr_diff.info.source_branch)
                if cached is None:
                    cached = get_repository_index(repo_id, head_commit)
                if cached and cached.get("stats", {}).get("index_version") == REPO_INDEX_VERSION:
                    index = repository_index_from_dict(cached)
            except Exception as e:
                log_warning("PRSecurityScan", f"Failed to read cached repository index for repo {repo_id}: {e}")
        if index is None:
            index = index_repository(source, head_commit)
            if project_id is not None:
                try:
                    save_repository_index(project_id, repo_id, index.as_dict(), branch_name=pr_diff.info.source_branch)
                except Exception as e:
                    log_warning("PRSecurityScan", f"Failed to persist repository index for repo {repo_id}: {e}")
        yield _sse("status", {"stage": "index", "status": "completed", "symbols": len(index.symbols), "relations": len(index.relations)})

        yield _sse("status", {"stage": "symbols", "status": "running", "message": "Mapping PR changes to repository symbols…"})
        seeds = map_pr_changes_to_symbols(pr_diff, index)
        # Every changed file the diff produced a seed for, symbol-resolved
        # or not — a file whose declaration the indexer couldn't map to a
        # specific symbol (a new .tsx component, a config/dependency file,
        # a deletion) still needs to show up as "changed by this PR" below,
        # even though it can't seed the symbol-level impact-graph traversal.
        changed_seed_files = {s.file for s in seeds}
        symbol_seeds = [s for s in seeds if s.symbol_id]
        if len(symbol_seeds) > budget.max_changed_symbols:
            truncation.note("changed_symbols_truncated", f"{len(symbol_seeds) - budget.max_changed_symbols} changed symbol(s) excluded from impact graph seeding")
            symbol_seeds = symbol_seeds[: budget.max_changed_symbols]
        seed_ids = [s.symbol_id for s in symbol_seeds]
        yield _sse("status", {"stage": "symbols", "status": "completed", "changed_symbols": len(seeds), "seeded_symbols": len(seed_ids)})

        yield _sse("status", {"stage": "impact_graph", "status": "running", "message": "Traversing repository-wide impact graph…"})
        graph = build_impact_graph(index, seed_ids, max_depth=budget.max_graph_depth, max_nodes=budget.max_graph_nodes, max_files=budget.max_graph_files)
        if graph.truncated:
            truncation.note("graph_truncated", "impact graph traversal hit a size/depth limit")
        yield _sse("status", {"stage": "impact_graph", "status": "completed", "nodes": len(graph.nodes), "edges": len(graph.edges), "files": len(graph.files), "truncated": graph.truncated})

        yield _sse("status", {"stage": "security_context", "status": "running", "message": "Finding security-relevant context…"})
        try:
            matches = find_security_context(source, index=index, max_matches=budget.max_security_matches)
            security_context_status = "completed"
        except Exception as e:
            log_warning("PRSecurityScan", f"ast-grep security-context discovery failed for repo {repo_id}: {e}")
            matches = []
            security_context_status = "degraded"
        if len(matches) >= budget.max_security_matches:
            truncation.note("security_matches_truncated", "security-context match count hit its limit")
        enrich_with_security_context(graph, matches)
        yield _sse("status", {"stage": "security_context", "status": security_context_status, "matches": len(matches)})

        yield _sse("status", {"stage": "scanners", "status": "running", "message": "Running deterministic security scanners…"})
        deterministic_findings: list[dict] = []
        try:
            # Reuse the snapshot already fetched above for the repository
            # index/ast-grep pass — do not fetch the repository from
            # Bitbucket a second time for the same commit. See
            # run_deterministic_scan's docstring: the prior double-fetch
            # was doubling request volume against Bitbucket's rate limits
            # for the same token, which is what actually caused snapshot
            # failures under repeated PR-scan use.
            for event_type, payload in run_deterministic_scan(config, source=source, commit=head_commit):
                yield _sse(event_type, payload)
                if event_type == "deterministic_complete":
                    deterministic_findings = payload.get("findings", [])
        except Exception as e:
            log_error("PRSecurityScan", f"Deterministic scanners failed for PR #{pull_request_id}", exception=e)
            yield _sse("scanner_status", {"stage": "snapshot", "status": "failed", "error": safe_exc(e)})

        yield _sse("status", {"stage": "correlation", "status": "running", "message": "Correlating findings to PR impact…"})
        correlated = [
            correlate_finding(finding, fingerprint_finding(finding), diff=pr_diff, seeds=seeds, graph=graph)
            for finding in deterministic_findings if isinstance(finding, dict)
        ]
        if len(correlated) > budget.max_scanner_findings:
            truncation.note("scanner_findings_truncated", "correlated deterministic finding count exceeded budget")
            correlated = correlated[: budget.max_scanner_findings]

        baseline_selection = select_baseline(repo_id, base_commit_sha=pr_diff.info.base_sha, destination_branch=pr_diff.info.destination_branch)
        baseline_fps = baseline_fingerprints(baseline_selection)
        for item in correlated:
            item.finding = {**item.finding, "baseline_state": classify_against_baseline(item.fingerprint, baseline_fps)}
        yield _sse("status", {"stage": "baseline", "status": "completed", "source": baseline_selection.source, "confidence": baseline_selection.confidence})

        yield _sse("status", {"stage": "llm_review", "status": "running", "message": "Running PR security impact review…"})
        provider = get_provider()
        llm_review_status = "ok"
        llm_findings: list[dict] = []
        llm_summary = ""
        try:
            snippets: dict[str, str] = {}
            for file_change in pr_diff.files:
                if len(snippets) >= budget.max_snippets or file_change.status in {"BINARY", "DELETED"}:
                    continue
                candidate = source / file_change.path
                try:
                    if candidate.is_file() and candidate.stat().st_size <= 200_000:
                        snippets[file_change.path] = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
            pr_context = build_pr_review_context(
                diff=pr_diff, seeds=seeds, graph=graph, correlated_findings=correlated,
                baseline=baseline_selection, budget=budget, truncation=truncation,
                snippets=snippets, branch_indexes=[index],
            )
            for chunk in run_pr_security_review(pr_context, provider):
                event = next((json.loads(line[len("data: "):]) for line in chunk.splitlines() if line.startswith("data: ")), None)
                if event is None:
                    continue
                if event.get("type") == "error":
                    llm_review_status = "failed"
                    break
                if event.get("type") == "done":
                    llm_findings = event.get("findings", [])
                    llm_summary = str(event.get("summary") or "").strip()
        except Exception as e:
            log_error("PRSecurityScan", f"PR LLM review failed for PR #{pull_request_id}", exception=e)
            llm_review_status = "failed"
        yield _sse("status", {"stage": "llm_review", "status": llm_review_status, "findings": len(llm_findings)})

        # A manager reading this result needs to know what the PR actually
        # did even when there's nothing security-relevant to flag (the
        # common case) — never leave this silent just because findings are
        # empty. Falls back to a deterministic, non-LLM summary (built from
        # the diff/seeds) when the AI review failed or returned nothing.
        change_summary = llm_summary or build_fallback_change_summary(pr_diff, seeds)

        llm_correlated = [
            correlate_finding(finding, fingerprint_finding(finding, symbol=finding.get("symbol")), diff=pr_diff, seeds=seeds, graph=graph)
            for finding in llm_findings
        ]
        for item in llm_correlated:
            item.finding = {**item.finding, "baseline_state": classify_against_baseline(item.fingerprint, baseline_fps)}

        # UNRELATED findings are deliberately excluded from the PR result —
        # PHASE 13 is explicit that they must not be prominently included.
        # They're still visible via the Full Repository Scan (a separate,
        # already-existing view), just not here.
        merged = [item for item in merge_correlated_findings([*correlated, *llm_correlated]) if item.relation_to_pr != RELATION_UNRELATED]

        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        relation_counts: dict[str, int] = {}
        rows = []
        for item in merged:
            severity = str(item.finding.get("severity") or "medium").lower()
            if severity not in severity_counts:
                severity = "medium"
            severity_counts[severity] += 1
            relation_counts[item.relation_to_pr] = relation_counts.get(item.relation_to_pr, 0) + 1
            sources = item.finding.get("sources")
            rows.append({
                "fingerprint": item.fingerprint,
                "source": ",".join(sources) if sources else str(item.finding.get("tool") or item.finding.get("source") or ""),
                "rule_id": item.finding.get("rule_id"), "title": item.finding.get("title") or item.finding.get("comment"),
                "description": item.finding.get("comment") or item.finding.get("description"),
                "severity": severity, "confidence": item.finding.get("confidence"),
                "file": item.finding.get("file"), "start_line": item.finding.get("start_line") or item.finding.get("line"),
                "end_line": item.finding.get("end_line"), "symbol": item.finding.get("symbol"),
                "category": item.finding.get("category"), "cwe": item.finding.get("cwe"),
                "evidence": item.finding.get("evidence"), "remediation": item.finding.get("recommendation"),
                "relation_to_pr": item.relation_to_pr, "relation_confidence": item.relation_confidence,
                "affected_path": item.affected_path,
                "metadata": {"baseline_state": item.finding.get("baseline_state"), "reason": item.reason},
            })
        save_security_findings(security_scan["id"], rows)
        update_security_scan(
            security_scan["id"], status="succeeded", head_commit_sha=head_commit,
            context_truncated=truncation.any_truncated, graph_truncated=graph.truncated,
            llm_review_status=llm_review_status, severity_counts=severity_counts,
            metadata_json=json.dumps({"summary": change_summary, "summary_source": "llm" if llm_summary else "fallback"}),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        if hasattr(provider, "usage_summary"):
            usage = provider.usage_summary()
            if usage.get("ai_calls"):
                record_token_usage(
                    "pr_security_scan", f"{workspace}/{repo_slug}#{pull_request_id}", getattr(provider, "provider_id", None),
                    usage, duration_seconds=round(time.monotonic() - scan_started_at, 1),
                )

        log_info(
            "PRSecurityScan",
            f"PR #{pull_request_id} on {workspace}/{repo_slug}: {len(merged)} findings "
            f"({relation_counts}), graph {len(graph.nodes)} nodes/{len(graph.edges)} edges, "
            f"baseline={baseline_selection.source}, truncated={truncation.any_truncated}",
        )
        yield _sse("done", {
            "scan_id": security_scan["id"],
            "pull_request_id": str(pull_request_id),
            "summary": change_summary,
            "summary_source": "llm" if llm_summary else "fallback",
            "changed_files": len([f for f in pr_diff.files if f.status != "BINARY"]),
            "changed_symbols": len(symbol_seeds),
            "affected_files": len(changed_seed_files | graph.files),
            "affected_symbols": len(graph.nodes),
            # The stat tiles above are just counts — these give the UI
            # something to actually show when a reader asks "which ones?"
            # instead of a bare number with no way to drill in.
            "changed_symbols_detail": [
                {"file": seed.file, "symbol": seed.symbol_name, "change_status": seed.change_status, "seed_type": seed.seed_type}
                for seed in symbol_seeds
            ],
            # "seed" flags every file the PR's diff actually touched vs.
            # files only reached by traversing calls/inherits away from it.
            # Union with changed_seed_files (not just graph.files) because
            # the impact graph is seeded from *symbol-resolved* changes only
            # — a changed file the indexer couldn't map to a symbol (a new
            # component, a config/dependency file, a deletion) never enters
            # the graph at all and would otherwise vanish from this list
            # entirely instead of showing up as "changed by this PR."
            "affected_files_detail": [
                {"path": path, "seed": path in changed_seed_files}
                for path in sorted(changed_seed_files | graph.files)
            ],
            "findings": rows,
            "findings_by_relation": relation_counts,
            "severity_counts": severity_counts,
            "baseline": {"source": baseline_selection.source, "confidence": baseline_selection.confidence, "commit_sha": baseline_selection.commit_sha},
            "context_truncated": truncation.any_truncated,
            "graph_truncated": graph.truncated,
            "truncation_reasons": truncation.reasons,
            "llm_review_status": llm_review_status,
            "duration_seconds": round(time.monotonic() - scan_started_at, 1),
        })


def _pr_security_scan_job_runner(payload: dict):
    """Same adapter shape as _security_scan_job_runner."""
    for chunk in _stream_pr_security_scan(
        payload.get("project_id"), payload.get("repo_id"), payload.get("workspace", ""), payload.get("repo_slug", ""),
        payload.get("pull_request_id"), scan_branch=payload.get("scan_branch"),
    ):
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            event_type = str(event.pop("type", "message"))
            yield event_type, event


configure_runner("generation", _generation_job_runner)
configure_runner("generation_phase", _generation_phase_job_runner)
configure_runner("bitbucket_review", _bitbucket_review_job_runner)
configure_runner("security_scan", _security_scan_job_runner)
configure_runner("pr_security_scan", _pr_security_scan_job_runner)
