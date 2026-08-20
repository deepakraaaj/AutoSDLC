from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.rule_based_generator import validate_backlog_depth
from app.services.backlog_service import generation_output_from_row, rescored_output
from app.services.database import delete_generation, get_generation, list_generations
from app.services.export import generate_excel
from app.utils.error_handler import AppError, DatabaseError, ErrorSeverity, FileError, ValidationError, log_error, log_info, log_warning


router = APIRouter(tags=["history"])


@router.get("/history")
def history_list():
    try:
        generations = list_generations()
        return {"generations": generations}
    except Exception as exc:
        log_error("History", "Error listing generations", exception=exc)
        return JSONResponse(status_code=500, content=DatabaseError("Failed to retrieve generation history", "list_generations").to_dict())


@router.get("/history/{gen_id}")
def history_item(gen_id: int):
    try:
        generation = get_generation(gen_id)
        if not generation:
            return JSONResponse(status_code=404, content=AppError(f"Generation {gen_id} not found", ErrorSeverity.WARNING).to_dict())
        if isinstance(generation.get("output"), dict):
            generation["output"] = rescored_output(generation["output"])
        return generation
    except Exception as exc:
        log_error("History", f"Error retrieving generation {gen_id}", exception=exc)
        return JSONResponse(status_code=500, content=DatabaseError(f"Failed to retrieve generation {gen_id}", "get_generation").to_dict())


@router.delete("/history/{gen_id}")
def history_delete(gen_id: int):
    try:
        if not delete_generation(gen_id):
            return JSONResponse(status_code=404, content=AppError(f"Generation {gen_id} not found", ErrorSeverity.WARNING).to_dict())
        return {"deleted": True}
    except Exception as exc:
        log_error("History", f"Error deleting generation {gen_id}", exception=exc)
        return JSONResponse(status_code=500, content=DatabaseError(f"Failed to delete generation {gen_id}", "delete_generation").to_dict())


@router.get("/export-excel/{gen_id}")
def export_excel(gen_id: int):
    try:
        generation = get_generation(gen_id)
        if not generation:
            return JSONResponse(status_code=404, content=AppError(f"Generation {gen_id} not found", ErrorSeverity.WARNING).to_dict())
        output = generation_output_from_row(generation["output"])
        validation_errors = validate_backlog_depth(output)
        if validation_errors:
            error = ValidationError("Backlog is too shallow to export. Run generation on a more detailed brief or allow expansion to complete.")
            return JSONResponse(status_code=422, content={**error.to_dict(), "validation_errors": validation_errors[:20]})
        excel_bytes = generate_excel(output)
        log_info("Export", f"Excel file generated for generation {gen_id}")
        return StreamingResponse(iter([excel_bytes]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=stories_tasks_{gen_id}.xlsx"})
    except Exception as exc:
        log_error("Export", f"Error exporting generation {gen_id}", exception=exc)
        return JSONResponse(status_code=500, content=FileError(f"Failed to export Excel for generation {gen_id}", f"stories_tasks_{gen_id}.xlsx").to_dict())
