"""AI provider administration routes.

Kept separate from generation orchestration so provider policy can evolve without
growing the application entry point. Authentication is intentionally out of scope
for this migration; the existing HTTP contract is preserved.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.models import ProviderSelectRequest
from app.services.providers import list_ui_providers, refresh_provider_status, select_ui_provider
from app.utils.error_handler import AppError, ErrorSeverity, ValidationError, log_error, log_info, log_warning


router = APIRouter(tags=["providers"])


@router.get("/providers")
def get_providers():
    try:
        return list_ui_providers()
    except Exception as exc:
        error = AppError("Failed to load provider status", ErrorSeverity.WARNING)
        log_error("Providers", "Error listing providers", exception=exc)
        return JSONResponse(status_code=500, content=error.to_dict())


@router.post("/providers/refresh")
def refresh_providers():
    try:
        return refresh_provider_status()
    except Exception as exc:
        error = AppError("Failed to refresh provider status", ErrorSeverity.WARNING)
        log_error("Providers", "Error refreshing provider status", exception=exc)
        return JSONResponse(status_code=500, content=error.to_dict())


@router.post("/providers/select")
def select_provider(request: ProviderSelectRequest):
    try:
        result = select_ui_provider(request.provider)
        log_info("Providers", f"Active provider switched to {request.provider}")
        return result
    except ValueError as exc:
        error = ValidationError(str(exc))
        log_warning("Providers", f"Provider switch rejected: {exc}")
        return JSONResponse(status_code=400, content=error.to_dict())
    except Exception as exc:
        error = AppError("Failed to switch provider", ErrorSeverity.WARNING)
        log_error("Providers", "Error switching provider", exception=exc)
        return JSONResponse(status_code=500, content=error.to_dict())
