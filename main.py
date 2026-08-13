import json
import os
import time
from pathlib import Path

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
from app.services.metrics import compute_metrics, run_validation
from app.services.prompt import (
    SYSTEM_PROMPT,
    prepare_user_message,
    CLARIFY_CHECK_SYSTEM,
    ASSISTANT_ROUTER_SYSTEM,
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
from app.services.providers import get_provider, list_ui_providers, select_ui_provider, refresh_provider_status, estimate_call_cost_usd
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
from app.utils.sse import sse as _sse
from app.utils.text_parsing import clean_raw as _clean_raw
from app.schemas.models import GenerateRequest, GenerationOutput, TokenUsage
from app.services.database import (init_db, save_generation, save_generation_normalized, list_generations,
                      get_generation, delete_generation, get_generation_hierarchy, get_dashboard_stats,
                      get_all_projects, update_epic_status, update_story_status, update_task_status,
                      update_task_assignee, update_epic_redmine_id, update_story_redmine_id,
                      update_task_redmine_id, save_stories_only, save_tasks_only, save_test_cases,
                      get_epic_id_map, get_story_id_map, get_task_id_map, update_generation_output)
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
)
from app.core.backlog_quality import normalize_task_dependencies
from app.schemas.models import (
    AssigneeUpdateRequest,
    AssistantChatRequest,
    AssistantChatResponse,
    ClarifyChatRequest,
    ProviderSelectRequest,
    RedmineConnectionRequest,
    RedmineProjectCreateRequest,
    RedminePushRequest,
    StatusUpdateRequest,
)
from app.services.brief_upload import SUPPORTED_UPLOAD_EXTENSIONS, extract_uploaded_brief_text

load_dotenv()

app = FastAPI(title="Story & Task Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize database
init_db()

# EPIC_CONCURRENCY / TASKS_PER_TEST_BATCH now live in app/services/generators.py
# (the module that actually uses them) — imported above, re-read here by
# /estimate-tokens to predict the real call count the pipeline will make.

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "5")) * 1_000_000
# How many back-and-forth rounds the clarify-chat loop will run before it
# forces itself to stop and generate anyway, regardless of what the model asks.
MAX_CLARIFY_ROUNDS = int(os.getenv("MAX_CLARIFY_ROUNDS", "3"))

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
    the one-click pipeline, via GenerationPipeline (app/services/generators.py),
    which is what actually chains the four phase objects together — each
    stage's output becomes the next stage's input through the shared,
    mutated `output`. Each phase is also independently callable (see
    /generate-epics, /generate-stories/{id}, /generate-tasks/{id},
    /generate-test-cases/{id}) for the step-by-step flow."""
    yield from GenerationPipeline(provider).run_all(text, output)


def _stream_generate(text: str, clarification_answers: dict):
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
                gen_id = save_generation(text, output)
                save_generation_normalized(gen_id, output)
                output_dict = output.model_dump()
                output_dict["generation_id"] = gen_id
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
                gen_id = save_generation(text, output)
                save_generation_normalized(gen_id, output)
                output_dict = output.model_dump()
                output_dict["generation_id"] = gen_id
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
    return row["input_text"], GenerationOutput(**row["output"])


def _stream_generate_epics(text: str):
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
        gen_id = save_generation(text, output)
        save_generation_normalized(gen_id, output)  # stories/tasks are empty — only epics get inserted
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
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
    yield from _generate_stories_phase(text, provider, output)
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
    yield from _generate_tasks_phase(text, provider, output)
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
    yield from _generate_test_cases_phase(text, provider, output)

    try:
        save_test_cases(gen_id, output.tasks)
        yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
        output.metrics = compute_metrics(output)
        # Only measures this phase's own duration, not the whole step-by-step
        # run — each phase is a separate request with no shared start time.
        output.metrics.generation_seconds = round(time.time() - gen_started_at, 1)
        if hasattr(provider, "usage_summary"):
            output.metrics.token_usage = TokenUsage(**provider.usage_summary())
        output.validation = run_validation(output.metrics)
        update_generation_output(gen_id, output)
        output_dict = output.model_dump()
        output_dict["generation_id"] = gen_id
        log_info("Database", f"Generation {gen_id} finalized (test cases + metrics)")
        yield _sse("done", {"phase": "tests", "output": output_dict})
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
        return StreamingResponse(
            _stream_generate(request.text, request.clarification_answers or {}),
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
            _stream_generate_epics(request.text),
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
    router prompt and to gate the push_backlog intent server-side."""
    if not generation_id:
        return {"has_output": False, "trusted": False}
    gen = get_generation(generation_id)
    if not gen:
        return {"has_output": False, "trusted": False}
    validation = (gen.get("output") or {}).get("validation") or {}
    return {"has_output": True, "trusted": validation.get("trust_level") == "trusted"}


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
    """Run a create/update action the user already confirmed. The only place a chat turn
    actually mutates Redmine."""
    if not redmine_configured:
        return AssistantChatResponse(reply="Redmine isn't connected anymore — reconnect and try again.")

    intent = pending_action.get("intent")
    params = pending_action.get("params") or {}

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


@app.get("/health")
def health():
    try:
        provider_name = list_ui_providers()["active"]
        log_debug("Health", f"Health check: {provider_name}")
        return {"status": "ok", "provider": provider_name}
    except Exception as e:
        error = AppError(
            message="Health check failed",
            severity=ErrorSeverity.WARNING,
            details=str(e)
        )
        log_error("Health", "Health check error", exception=e)
        return JSONResponse(
            status_code=503,
            content=error.to_dict()
        )


@app.get("/providers")
def get_providers():
    try:
        return list_ui_providers()
    except Exception as e:
        error = AppError(
            message="Failed to load provider status",
            severity=ErrorSeverity.WARNING,
            details=str(e)
        )
        log_error("Providers", "Error listing providers", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/providers/refresh")
def post_refresh_providers():
    try:
        return refresh_provider_status()
    except Exception as e:
        error = AppError(
            message="Failed to refresh provider status",
            severity=ErrorSeverity.WARNING,
            details=str(e)
        )
        log_error("Providers", "Error refreshing provider status", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


@app.post("/providers/select")
def post_select_provider(request: ProviderSelectRequest):
    try:
        result = select_ui_provider(request.provider)
        log_info("Providers", f"Active provider switched to {request.provider}")
        return result
    except ValueError as e:
        error = ValidationError(str(e))
        log_warning("Providers", f"Provider switch rejected: {e}")
        return JSONResponse(status_code=400, content=error.to_dict())
    except Exception as e:
        error = AppError(
            message="Failed to switch provider",
            severity=ErrorSeverity.WARNING,
            details=str(e)
        )
        log_error("Providers", "Error switching provider", exception=e)
        return JSONResponse(status_code=500, content=error.to_dict())


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


@app.get("/history")
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


@app.get("/history/{gen_id}")
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


@app.delete("/history/{gen_id}")
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


@app.get("/export-excel/{gen_id}")
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

        output = GenerationOutput(**gen['output'])

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


@app.get("/projects")
def list_projects_endpoint():
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
        result = describe_redmine_workspace(request.redmine_url, request.redmine_api_key)
        log_info("Redmine", "Projects listed from Redmine")
        return result
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
        result = create_redmine_project(
            request.redmine_url,
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
        config = RedmineConfig(
            url=request.redmine_url,
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
            output = GenerationOutput(**gen['output'])
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
