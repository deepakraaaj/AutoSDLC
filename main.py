import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from error_handler import (
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
)
from metrics import compute_metrics, run_validation
from prompt import (
    SYSTEM_PROMPT,
    prepare_user_message,
    EPIC_GENERATION_SYSTEM,
    STORY_GENERATION_SYSTEM,
    TASK_GENERATION_SYSTEM,
    build_epic_generation_message,
    build_story_generation_message,
    build_task_generation_message,
)
from rule_based_generator import (
    generate_rule_based_output,
    looks_like_structured_brief,
    validate_backlog_depth,
    MIN_EPICS,
    MIN_STORIES_PER_EPIC,
    MIN_TASKS_PER_STORY,
)
from providers import get_provider
from schemas import GenerateRequest, GenerationOutput, Epic, Story, Task
from database import (init_db, save_generation, save_generation_normalized, list_generations,
                      get_generation, delete_generation, get_generation_hierarchy, get_dashboard_stats,
                      get_all_projects, update_epic_status, update_story_status, update_task_status,
                      update_task_assignee, update_epic_redmine_id, update_story_redmine_id,
                      update_task_redmine_id)
from export import generate_excel
from redmine import RedmineConfig, create_redmine_project, describe_redmine_workspace, push_to_redmine
from schemas import (
    AssigneeUpdateRequest,
    RedmineConnectionRequest,
    RedmineProjectCreateRequest,
    RedminePushRequest,
    StatusUpdateRequest,
)
from brief_upload import SUPPORTED_UPLOAD_EXTENSIONS, extract_uploaded_brief_text

load_dotenv()

app = FastAPI(title="Story & Task Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize database
init_db()

BASE_DIR = Path(__file__).resolve().parent
BRIEF_RESOURCE_FILES = {
    "project_template": BASE_DIR / "docs" / "PROJECT_BRIEF_EXAMPLE.md",
    "extract_docs_prompt": BASE_DIR / "prompts" / "EXTRACT_FROM_DOCS.md",
    "extract_repo_prompt": BASE_DIR / "prompts" / "EXTRACT_FROM_REPO.md",
}


def _next_id_counters(output: GenerationOutput) -> tuple[int, int, int]:
    """Get the next ID number for each type (epic, story, task)."""
    epic_max = max(
        (int(e.id[1:]) for e in output.epics if e.id.startswith("E") and e.id[1:].isdigit()),
        default=0,
    )
    story_max = max(
        (int(s.id[1:]) for s in output.stories if s.id.startswith("S") and s.id[1:].isdigit()),
        default=0,
    )
    task_max = max(
        (int(t.id[1:]) for t in output.tasks if t.id.startswith("T") and t.id[1:].isdigit()),
        default=0,
    )
    return epic_max, story_max, task_max


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _parse_json_array(raw: str) -> list:
    """Parse a JSON array from raw text, handling markdown fences."""
    cleaned = _clean_raw(raw)
    print(f"[DEBUG _parse_json_array] Raw input (first 200 chars): {raw[:200]}")
    print(f"[DEBUG _parse_json_array] Cleaned (first 200 chars): {cleaned[:200]}")
    try:
        data = json.loads(cleaned)
        print(f"[DEBUG _parse_json_array] Parsed successfully, type: {type(data)}, items: {len(data) if isinstance(data, list) else 1}")
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError as e:
        print(f"[DEBUG _parse_json_array] JSON parse error: {e}")
        print(f"[DEBUG _parse_json_array] Tried to parse: {cleaned[:300]}")
        return []


def _clean_raw(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _stream_generate_from_file(text: str):
    """Stream generation for uploaded files and keep the extracted text available client-side."""
    yield _sse("input", {"text": text})
    yield from _stream_generate(text, {})


def _three_phase_generate(text: str, provider, output: GenerationOutput):
    """3-phase generation: epics → stories → tasks. Populates output in-place, yields SSE events."""

    # ── Phase 1: Epic Generation ────────────────────────────────────────────
    yield _sse("status", {"step": "generating", "message": "Identifying all feature areas and epics…"})
    try:
        raw = provider.generate(EPIC_GENERATION_SYSTEM, build_epic_generation_message(text))
        log_debug("Phase1", f"AI response received: {len(raw)} chars")
        epics_data = _parse_json_array(raw)
        if not epics_data:
            error = GenerationError(
                message="Epic generation returned empty. Check your brief or provider configuration.",
                phase="Epic Generation",
                user_action="Add more detail to your brief — include specific features, users, and goals."
            )
            yield json.dumps({
                "type": "error",
                **error.to_dict()
            }) + "\n\n"
            return

        valid_epics = 0
        for i, e in enumerate(epics_data, start=1):
            if not isinstance(e, dict):
                log_debug("Phase1", f"Skipping item {i}: not a dict")
                continue
            title = e.get("title", "").strip()
            description = e.get("description", "").strip()

            if not title or not description:
                log_debug("Phase1", f"Skipping item {i}: missing title or description")
                continue

            valid_epics += 1
            output.epics.append(Epic(
                id=f"E{valid_epics}",
                title=title,
                description=description,
                feature_area=e.get("feature_area", "General").strip(),
                priority=e.get("priority", "medium"),
                status="planned",
            ))
            log_debug("Phase1", f"Added epic E{valid_epics}: {title}")

        if not output.epics:
            error = GenerationError(
                message="All epics were invalid (missing title/description).",
                phase="Epic Validation",
                user_action="Check your brief has valid section headings and descriptions."
            )
            yield json.dumps({
                "type": "error",
                **error.to_dict()
            }) + "\n\n"
            return

        log_info("Phase1", f"Successfully generated {len(output.epics)} epics")
        yield _sse("status", {"step": "generating", "message": f"Found {len(output.epics)} valid epics. Generating stories…"})
    except Exception as e:
        error = GenerationError(
            message=f"Epic generation failed: {str(e)[:100]}",
            phase="Epic Generation"
        )
        log_error("Phase1", str(error.message), exception=e)
        yield json.dumps({
            "type": "error",
            **error.to_dict()
        }) + "\n\n"
        return

    # ── Phase 2: Story Generation per Epic ──────────────────────────────────
    story_counter = 0
    for epic in output.epics:
        yield _sse("status", {"step": "generating", "message": f"Generating stories for: {epic.title}…"})
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_story_generation_message(text, epic.title, epic.description, MIN_STORIES_PER_EPIC)
                log_debug("Phase2", f"Generating stories for epic {epic.id} (attempt {attempt+1})")
                raw = provider.generate(
                    STORY_GENERATION_SYSTEM.format(n=MIN_STORIES_PER_EPIC),
                    prompt_msg,
                )
                log_debug("Phase2", f"AI response received for {epic.title}")
                stories_data = _parse_json_array(raw)

                if not stories_data:
                    log_debug("Phase2", f"Empty stories list for epic {epic.id} - will retry" if attempt == 0 else f"Empty stories after retry for epic {epic.id}")
                    if attempt == 0:
                        continue
                    else:
                        yield _sse("status", {"message": f"Story generation for {epic.title} returned empty after retry, skipping…"})
                        break

                for s in stories_data:
                    if not isinstance(s, dict):
                        continue
                    story_counter += 1
                    output.stories.append(Story(
                        id=f"S{story_counter}",
                        title=s.get("title", ""),
                        as_a=s.get("as_a", ""),
                        i_want=s.get("i_want", ""),
                        so_that=s.get("so_that", ""),
                        acceptance_criteria=s.get("acceptance_criteria", []),
                        feature_area=epic.feature_area,
                        size=s.get("size", "medium"),
                        confidence="high",
                        epic_id=epic.id,
                        priority=s.get("priority", epic.priority),
                        status="planned",
                    ))
                log_info("Phase2", f"Added {len(stories_data)} stories for epic {epic.id}")
                break
            except Exception as e:
                log_error("Phase2", f"Failed to generate stories for epic {epic.id}", exception=e)
                if attempt == 1:
                    yield _sse("status", {"message": f"Story generation for {epic.title} failed after retry, continuing…"})

    yield _sse("status", {"step": "generating", "message": f"Generated {len(output.stories)} stories. Generating tasks…"})

    # ── Phase 3: Task Generation per Epic (batching stories) ────────────────
    task_counter = 0
    for epic in output.epics:
        epic_stories = [s for s in output.stories if s.epic_id == epic.id]
        if not epic_stories:
            log_debug("Phase3", f"No stories for epic {epic.id}, skipping tasks")
            continue
        yield _sse("status", {"step": "generating", "message": f"Generating tasks for {epic.title} ({len(epic_stories)} stories)…"})
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_task_generation_message(text, epic_stories, MIN_TASKS_PER_STORY)
                log_debug("Phase3", f"Generating tasks for epic {epic.id} (attempt {attempt+1})")
                raw = provider.generate(
                    TASK_GENERATION_SYSTEM.format(n=MIN_TASKS_PER_STORY),
                    prompt_msg,
                )
                log_debug("Phase3", f"AI response received for {epic.title}")
                tasks_data = _parse_json_array(raw)

                if not tasks_data:
                    log_warning("Phase3", f"Empty tasks list for epic {epic.id} - will retry" if attempt == 0 else f"Empty tasks after retry for epic {epic.id}")
                    if attempt == 0:
                        continue
                    else:
                        error = GenerationError(
                            message=f"Task generation for {epic.title} returned empty",
                            phase="Task Generation",
                            user_action="Your brief may be too abstract — add concrete requirements or expand your stories."
                        )
                        log_warning("Phase3", f"No tasks generated for epic {epic.id} after retry")
                        yield json.dumps({
                            "type": "warning",
                            "message": f"⚠️ Task generation for {epic.title} returned empty after retry, skipping…"
                        }) + "\n\n"
                        break

                valid_story_ids = {s.id for s in epic_stories}
                added_count = 0
                rejected_count = 0
                for t in tasks_data:
                    if not isinstance(t, dict):
                        continue
                    sid = t.get("story_id")
                    if sid not in valid_story_ids:
                        log_debug("Phase3", f"Task rejected: invalid story_id '{sid}' (valid: {valid_story_ids})")
                        rejected_count += 1
                        continue
                    task_counter += 1
                    added_count += 1
                    output.tasks.append(Task(
                        id=f"T{task_counter}",
                        title=t.get("title", ""),
                        description=t.get("description", ""),
                        definition_of_done=t.get("definition_of_done", ""),
                        estimate_hours=t.get("estimate_hours", ""),
                        dependencies=t.get("dependencies", []),
                        story_id=sid,
                        confidence="high",
                        priority=t.get("priority", epic.priority),
                        status="todo",
                        assignee=None,
                    ))

                if rejected_count > 0 and added_count == 0:
                    log_warning("Phase3", f"All {rejected_count} tasks rejected due to invalid story_ids for epic {epic.id}")
                    yield json.dumps({
                        "type": "warning",
                        "message": f"⚠️ All tasks for {epic.title} were rejected (invalid story references). AI model may need better prompting."
                    }) + "\n\n"
                elif added_count > 0:
                    log_info("Phase3", f"Added {added_count} tasks for epic {epic.id}" + (f" ({rejected_count} rejected)" if rejected_count > 0 else ""))

                break
            except Exception as e:
                log_error("Phase3", f"Failed to generate tasks for epic {epic.id}", exception=e)
                if attempt == 1:
                    yield _sse("status", {"message": f"Task generation for {epic.title} failed after retry, continuing…"})


def _stream_generate(text: str, clarification_answers: dict):
    try:
        if looks_like_structured_brief(text):
            yield _sse("status", {"step": "connecting", "message": "Compiling structured brief into a backlog…"})
            try:
                yield _sse("status", {"step": "generating", "message": "Rule-based compiler is building epics, stories, and tasks…"})
                output = generate_rule_based_output(text)
                log_info("RuleGenerator", "Structured brief compilation completed successfully")
            except Exception as e:
                error = GenerationError(
                    message=f"Rule-based compilation failed: {str(e)[:100]}",
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
                output.validation = run_validation(output.metrics)
                log_info("Metrics", f"Validation: {output.validation.trust_level}")
            except Exception as e:
                error = GenerationError(
                    message=f"Metrics computation failed: {str(e)[:100]}",
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
                    message=f"Failed to save generation: {str(e)[:100]}",
                    operation="save_generation"
                )
                log_error("Database", str(error.message), exception=e)
                yield json.dumps({
                    "type": "error",
                    **error.to_dict()
                }) + "\n\n"
            return

        provider = get_provider()

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
        yield from _three_phase_generate(text, provider, output)

        # Score and save if generation succeeded
        if output.epics:
            yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
            try:
                output.metrics = compute_metrics(output)
                output.validation = run_validation(output.metrics)
                log_info("Metrics", f"Validation: {output.validation.trust_level}")
            except Exception as e:
                error = GenerationError(
                    message=f"Metrics computation failed: {str(e)[:100]}",
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
                    message=f"Failed to save generation: {str(e)[:100]}",
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
            message=f"Unexpected error during generation: {str(e)[:100]}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("StreamGenerator", "Unhandled exception", exception=e)
        yield json.dumps({
            "type": "error",
            **error.to_dict()
        }) + "\n\n"


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/generate-stream")
def generate_stream(request: GenerateRequest):
    try:
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
    except Exception as e:
        error = AppError(
            message=f"Failed to start generation: {str(e)[:100]}",
            severity=ErrorSeverity.CRITICAL,
            details=str(e)
        )
        log_error("API", "Error in /generate-stream", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


@app.post("/generate-from-file-stream")
async def generate_from_file_stream(file: UploadFile = File(...)):
    try:
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
    except Exception as e:
        error = FileError(
            message=f"Failed to process uploaded file: {str(e)[:100]}",
            filename=file.filename
        )
        log_error("FileUpload", "Error processing file", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


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


@app.post("/estimate-tokens")
def estimate_tokens(request: GenerateRequest):
    text = request.text or ""
    word_count = len(text.split())
    estimated_epics = max(3, min(10, word_count // 50))
    estimated_calls = 1 + estimated_epics * 2
    input_tokens_per_call = max(500, word_count * 1.35)
    total_tokens = estimated_calls * (input_tokens_per_call + 500)
    cost_usd = (total_tokens / 1_000_000) * 0.20
    estimated_time_seconds = estimated_calls * max(3, word_count // 150)
    return JSONResponse(content={
        "word_count": word_count,
        "estimated_calls": estimated_calls,
        "estimated_time_seconds": int(estimated_time_seconds),
        "cost_usd": round(cost_usd, 3),
    })


@app.get("/health")
def health():
    try:
        provider_name = os.getenv("AI_PROVIDER", "groq")
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
            message=f"Failed to list Redmine projects: {str(e)[:100]}",
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
            message=f"Failed to create Redmine project: {str(e)[:100]}",
            status_code=None
        )
        log_error("Redmine", "Error creating Redmine project", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
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
            result = push_to_redmine(output, config)
            _record_redmine_ids(result, hierarchy)
        elif request.output:
            output = GenerationOutput(**request.output)
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
            message=f"Failed to push to Redmine: {str(e)[:100]}",
            status_code=None
        )
        log_error("Redmine", "Error pushing to Redmine", exception=e)
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )
