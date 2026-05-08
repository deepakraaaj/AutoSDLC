import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from metrics import compute_metrics
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

load_dotenv()

app = FastAPI(title="Story & Task Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize database
init_db()

BASE_DIR = Path(__file__).resolve().parent
BRIEF_RESOURCE_FILES = {
    "project_template": BASE_DIR / "docs" / "PROJECT_BRIEF_TEMPLATE.md",
    "idea_prompt": BASE_DIR / "prompts" / "IDEA_TO_PROJECT_BRIEF.md",
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


def _three_phase_generate(text: str, provider, output: GenerationOutput):
    """3-phase generation: epics → stories → tasks. Populates output in-place, yields SSE events."""

    # ── Phase 1: Epic Generation ────────────────────────────────────────────
    yield _sse("status", {"step": "generating", "message": "Identifying all feature areas and epics…"})
    try:
        raw = provider.generate(EPIC_GENERATION_SYSTEM, build_epic_generation_message(text))
        print(f"[DEBUG Phase 1] Raw AI response: {raw[:500]}...")
        epics_data = _parse_json_array(raw)
        if not epics_data:
            yield _sse("error", {"message": "Epic generation returned empty. Check your brief or provider configuration."})
            return

        valid_epics = 0
        for i, e in enumerate(epics_data, start=1):
            if not isinstance(e, dict):
                print(f"[DEBUG Phase 1] Skipping item {i}: not a dict")
                continue
            title = e.get("title", "").strip()
            description = e.get("description", "").strip()

            # Validate epic has required fields
            if not title:
                print(f"[DEBUG Phase 1] Skipping item {i}: empty title. Data: {e}")
                continue
            if not description:
                print(f"[DEBUG Phase 1] Skipping item {i}: empty description. Data: {e}")
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
            print(f"[DEBUG Phase 1] Added epic E{valid_epics}: {title}")

        if not output.epics:
            yield _sse("error", {"message": "Epic generation succeeded but all epics were invalid (missing title/description). Check brief quality."})
            return

        yield _sse("status", {"step": "generating", "message": f"Found {len(output.epics)} valid epics. Generating stories…"})
    except Exception as e:
        yield _sse("error", {"message": f"Phase 1 (epics) failed: {str(e)[:100]}"})
        print(f"[ERROR Phase 1] {e}")
        return

    # ── Phase 2: Story Generation per Epic ──────────────────────────────────
    import traceback
    story_counter = 0
    for epic in output.epics:
        yield _sse("status", {"step": "generating", "message": f"Generating stories for: {epic.title}…"})
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_story_generation_message(text, epic.title, epic.description, MIN_STORIES_PER_EPIC)
                print(f"[DEBUG Phase 2] Generating stories for epic {epic.id} '{epic.title}' (attempt {attempt+1})")
                print(f"[DEBUG Phase 2] Prompt message (first 300 chars): {prompt_msg[:300]}...")
                print(f"[DEBUG Phase 2] About to call provider.generate()")
                raw = provider.generate(
                    STORY_GENERATION_SYSTEM.format(n=MIN_STORIES_PER_EPIC),
                    prompt_msg,
                )
                print(f"[DEBUG Phase 2] Provider.generate() returned successfully")
                print(f"[DEBUG Phase 2] Raw AI response for {epic.title} (first 500 chars): {raw[:500]}...")
                stories_data = _parse_json_array(raw)
                print(f"[DEBUG Phase 2] Parsed {len(stories_data)} stories for epic {epic.id}")

                if not stories_data:
                    print(f"[DEBUG Phase 2] Empty stories list for epic {epic.id} '{epic.title}' - will retry")
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
                print(f"[DEBUG Phase 2] Added {len(stories_data)} stories for epic {epic.id}")
                break
            except Exception as e:
                print(f"[ERROR Phase 2] Epic {epic.id}: {type(e).__name__}: {e}")
                print(f"[TRACEBACK Phase 2]\n{traceback.format_exc()}")
                if attempt == 1:
                    yield _sse("status", {"message": f"Story generation for {epic.title} failed after retry, continuing…"})

    yield _sse("status", {"step": "generating", "message": f"Generated {len(output.stories)} stories. Generating tasks…"})

    # ── Phase 3: Task Generation per Epic (batching stories) ────────────────
    task_counter = 0
    for epic in output.epics:
        epic_stories = [s for s in output.stories if s.epic_id == epic.id]
        if not epic_stories:
            print(f"[DEBUG Phase 3] No stories for epic {epic.id} '{epic.title}', skipping tasks")
            continue
        yield _sse("status", {"step": "generating", "message": f"Generating tasks for {epic.title} ({len(epic_stories)} stories)…"})
        for attempt in range(2):  # 1 retry
            try:
                prompt_msg = build_task_generation_message(text, epic_stories, MIN_TASKS_PER_STORY)
                print(f"[DEBUG Phase 3] Generating tasks for epic {epic.id} with {len(epic_stories)} stories (attempt {attempt+1})")
                print(f"[DEBUG Phase 3] Prompt message (first 300 chars): {prompt_msg[:300]}...")
                raw = provider.generate(
                    TASK_GENERATION_SYSTEM.format(n=MIN_TASKS_PER_STORY),
                    prompt_msg,
                )
                print(f"[DEBUG Phase 3] Raw AI response for {epic.title}: {raw[:500]}...")
                tasks_data = _parse_json_array(raw)
                print(f"[DEBUG Phase 3] Parsed {len(tasks_data)} tasks for epic {epic.id}")

                if not tasks_data:
                    print(f"[DEBUG Phase 3] Empty tasks list for epic {epic.id} '{epic.title}' - will retry")
                    if attempt == 0:
                        continue
                    else:
                        yield _sse("status", {"message": f"Task generation for {epic.title} returned empty after retry, skipping…"})
                        break

                valid_story_ids = {s.id for s in epic_stories}
                added_count = 0
                for t in tasks_data:
                    if not isinstance(t, dict):
                        continue
                    sid = t.get("story_id")
                    if sid not in valid_story_ids:
                        print(f"[DEBUG Phase 3] Task has invalid story_id {sid}, skipping. Valid IDs: {valid_story_ids}")
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
                print(f"[DEBUG Phase 3] Added {added_count} tasks for epic {epic.id}")
                break
            except Exception as e:
                print(f"[ERROR Phase 3] Epic {epic.id}: {e}")
                if attempt == 1:
                    yield _sse("status", {"message": f"Task generation for {epic.title} failed after retry, continuing…"})


def _stream_generate(text: str, clarification_answers: dict):
    if looks_like_structured_brief(text):
        yield _sse("status", {"step": "connecting", "message": "Compiling structured brief into a backlog…"})
        try:
            yield _sse("status", {"step": "generating", "message": "Rule-based compiler is building epics, stories, and tasks…"})
            output = generate_rule_based_output(text)
        except Exception as e:
            yield _sse("error", {"message": f"Rule-based compilation error: {e}"})
            return

        yield _sse("status", {"step": "parsing", "message": "Assembling structured output…"})
        yield _sse("status", {"step": "scoring", "message": "Scoring quality…"})
        output.metrics = compute_metrics(output)
        try:
            gen_id = save_generation(text, output)
            save_generation_normalized(gen_id, output)
            output_dict = output.model_dump()
            output_dict["generation_id"] = gen_id
            yield _sse("done", {"output": output_dict})
        except Exception as e:
            yield _sse("error", {"message": f"Failed to save generation: {e}"})
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
        output.metrics = compute_metrics(output)

        # Save to database
        try:
            gen_id = save_generation(text, output)
            save_generation_normalized(gen_id, output)
            output_dict = output.model_dump()
            output_dict["generation_id"] = gen_id
            yield _sse("done", {"output": output_dict})
        except Exception as e:
            yield _sse("error", {"message": f"Failed to save generation: {e}"})
    else:
        yield _sse("error", {"message": "Generation failed. Please check your brief and try again."})


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/generate-stream")
def generate_stream(request: GenerateRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Input text is required.")
    return StreamingResponse(
        _stream_generate(request.text, request.clarification_answers or {}),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/generate-from-file-stream")
async def generate_from_file_stream(file: UploadFile = File(...)):
    if not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are accepted.")
    content = await file.read()
    text = content.decode("utf-8", errors="ignore").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return StreamingResponse(
        _stream_generate(text, {}),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    provider_name = os.getenv("AI_PROVIDER", "groq")
    return {"status": "ok", "provider": provider_name}


@app.get("/brief-resources")
def get_brief_resources():
    try:
        resources = {
            name: path.read_text(encoding="utf-8")
            for name, path in BRIEF_RESOURCE_FILES.items()
        }
        return {"resources": resources}
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Brief resource missing: {e.filename}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read brief resources: {e}")


@app.get("/history")
def get_history():
    try:
        generations = list_generations()
        return {"generations": generations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/{gen_id}")
def get_history_item(gen_id: int):
    try:
        gen = get_generation(gen_id)
        if not gen:
            raise HTTPException(status_code=404, detail="Generation not found")
        return gen
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/history/{gen_id}")
def delete_history_item(gen_id: int):
    try:
        deleted = delete_generation(gen_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Generation not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export-excel/{gen_id}")
def export_excel(gen_id: int):
    try:
        gen = get_generation(gen_id)
        if not gen:
            raise HTTPException(status_code=404, detail="Generation not found")
        output = GenerationOutput(**gen['output'])

        # Validate backlog depth before export
        validation_errors = validate_backlog_depth(output)
        if validation_errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Backlog is too shallow to export. Run generation on a more detailed brief or allow expansion to complete.",
                    "errors": validation_errors[:20]  # limit to first 20 errors
                }
            )

        excel_bytes = generate_excel(output)
        return StreamingResponse(
            iter([excel_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=stories_tasks_{gen_id}.xlsx"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/epics/{epic_id}/status")
def update_epic_status_endpoint(epic_id: int, request: StatusUpdateRequest):
    try:
        valid = {"planned", "in-progress", "done"}
        if request.status not in valid:
            raise HTTPException(400, f"Invalid status. Choose from: {valid}")
        updated = update_epic_status(epic_id, request.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Epic not found")
        return {"updated": True, "id": epic_id, "status": request.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/stories/{story_id}/status")
def update_story_status_endpoint(story_id: int, request: StatusUpdateRequest):
    try:
        valid = {"planned", "in-progress", "review", "done"}
        if request.status not in valid:
            raise HTTPException(400, f"Invalid status. Choose from: {valid}")
        updated = update_story_status(story_id, request.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Story not found")
        return {"updated": True, "id": story_id, "status": request.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/tasks/{task_id}/status")
def update_task_status_endpoint(task_id: int, request: StatusUpdateRequest):
    try:
        valid = {"todo", "in-progress", "testing", "done"}
        if request.status not in valid:
            raise HTTPException(400, f"Invalid status. Choose from: {valid}")
        updated = update_task_status(task_id, request.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"updated": True, "id": task_id, "status": request.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/tasks/{task_id}/assignee")
def update_task_assignee_endpoint(task_id: int, request: AssigneeUpdateRequest):
    try:
        updated = update_task_assignee(task_id, request.assignee)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"updated": True, "id": task_id, "assignee": request.assignee}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard")
def get_dashboard_endpoint():
    try:
        return get_dashboard_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projects")
def list_projects_endpoint():
    try:
        return {"projects": get_all_projects()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/redmine/projects/list")
def list_redmine_projects_endpoint(request: RedmineConnectionRequest):
    try:
        return describe_redmine_workspace(request.redmine_url, request.redmine_api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/redmine/projects/create")
def create_redmine_project_endpoint(request: RedmineProjectCreateRequest):
    try:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Project name is required")
        return create_redmine_project(
            request.redmine_url,
            request.redmine_api_key,
            name=request.name.strip(),
            identifier=request.identifier.strip() if request.identifier else None,
            description=request.description.strip(),
            parent_project_ref=request.parent_project_ref.strip() if request.parent_project_ref else None,
            is_public=request.is_public,
            inherit_members=request.inherit_members,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            raise HTTPException(status_code=404, detail="Generation not found")
        return hierarchy
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/push-to-redmine")
def push_to_redmine_endpoint(request: RedminePushRequest):
    try:
        config = RedmineConfig(
            url=request.redmine_url,
            api_key=request.redmine_api_key,
            project_id=request.redmine_project_id
        )

        if not config.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Redmine URL, API key, and project ID are required"
            )

        # Load output from DB if generation_id provided
        if request.generation_id:
            hierarchy = get_generation_hierarchy(request.generation_id)
            if not hierarchy:
                raise HTTPException(status_code=404, detail="Generation not found")
            gen = get_generation(request.generation_id)
            if not gen:
                raise HTTPException(status_code=404, detail="Generation not found")
            output = GenerationOutput(**gen['output'])
            result = push_to_redmine(output, config)
            _record_redmine_ids(result, hierarchy)
        elif request.output:
            output = GenerationOutput(**request.output)
            result = push_to_redmine(output, config)
        else:
            raise HTTPException(status_code=400, detail="Provide generation_id or output")

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
