"""Application-level backlog read, scoring, and export operations."""
from app.schemas.models import GenerationOutput
from app.services.metrics import compute_metrics, run_validation
from app.utils.error_handler import log_warning, safe_exc


def sanitize_generation_output(raw: dict) -> dict:
    for story in raw.get("stories") or []:
        if not isinstance(story, dict):
            continue
        size = str(story.get("size", "")).strip().lower()
        if size not in {"small", "medium", "large"}:
            story["size"] = "medium"
    return raw


def generation_output_from_row(output_dict: dict) -> GenerationOutput:
    return GenerationOutput(**sanitize_generation_output(output_dict))


def rescored_output(output_dict: dict) -> dict:
    """Recompute deterministic metrics against today's quality policy."""
    try:
        output = generation_output_from_row(output_dict)
        output.metrics = compute_metrics(output)
        output.validation = run_validation(output.metrics)
        return output.model_dump()
    except Exception as exc:
        log_warning("Rescore", f"Serving stored metrics/validation as-is: {safe_exc(exc)}")
        return output_dict
