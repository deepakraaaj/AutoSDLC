import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from metrics import compute_metrics
from prompt import SYSTEM_PROMPT, prepare_user_message
from rule_based_generator import generate_rule_based_output, looks_like_structured_brief
from providers import get_provider
from schemas import GenerateRequest, GenerationOutput
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


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _clean_raw(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


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
    user_message, compacted = prepare_user_message(text, clarification_answers)

    connect_message = "Connecting to AI provider…"
    if compacted:
        connect_message = "Input is large, so it was contextualized before sending to the AI provider…"
    yield _sse("status", {"step": "connecting", "message": connect_message})

    accumulated = ""
    try:
        yield _sse("status", {"step": "generating", "message": "AI is generating stories and tasks…"})

        for chunk in provider.generate_stream(SYSTEM_PROMPT, user_message):
            accumulated += chunk
            yield _sse("token", {"text": chunk})

    except Exception as e:
        yield _sse("error", {"message": f"AI provider error: {e}"})
        return

    yield _sse("status", {"step": "parsing", "message": "Parsing results…"})

    try:
        cleaned = _clean_raw(accumulated)
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        yield _sse("error", {"message": f"AI returned invalid JSON: {e}"})
        return

    try:
        output = GenerationOutput(**data)
    except Exception as e:
        yield _sse("error", {"message": f"Output structure error: {e}"})
        return

    if not output.needs_clarification:
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
        yield _sse("done", {"output": output.model_dump()})


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
