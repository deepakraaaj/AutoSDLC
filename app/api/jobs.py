from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal

from app.services.jobs import create_job, get_job, list_events, request_cancel


router = APIRouter(prefix="/jobs", tags=["jobs"])


class GenerationJobRequest(BaseModel):
    text: str
    clarification_answers: dict[str, str] = {}


class PhaseJobRequest(BaseModel):
    phase: Literal["epics", "stories", "tasks", "tests"]
    generation_id: int | None = None
    text: str = ""


@router.post("/generations", status_code=202)
def start_generation_job(request: GenerationJobRequest):
    if not request.text.strip():
        return JSONResponse(status_code=400, content={"message": "Input text is required."})
    return create_job("generation", request.model_dump())


@router.post("/phases", status_code=202)
def start_phase_job(request: PhaseJobRequest):
    if request.phase == "epics" and not request.text.strip():
        return JSONResponse(status_code=400, content={"message": "Input text is required for the epics phase."})
    if request.phase != "epics" and request.generation_id is None:
        return JSONResponse(status_code=400, content={"message": "generation_id is required for this phase."})
    return create_job("generation_phase", request.model_dump())


@router.get("/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    return job if job else JSONResponse(status_code=404, content={"message": "Job not found"})


@router.get("/{job_id}/events")
def job_events(job_id: str, after: int = 0):
    if not get_job(job_id):
        return JSONResponse(status_code=404, content={"message": "Job not found"})
    return {"events": list_events(job_id, max(0, after))}


@router.delete("/{job_id}")
def cancel_job(job_id: str):
    if request_cancel(job_id):
        return {"cancel_requested": True}
    job = get_job(job_id)
    return JSONResponse(status_code=404 if not job else 409, content={"message": "Job not found" if not job else f"Job is already {job['status']}"})
