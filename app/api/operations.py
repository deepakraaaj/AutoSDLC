from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.database import get_connection
from app.services.providers import list_ui_providers
from app.services.telemetry import snapshot
from app.utils.error_handler import log_error


router = APIRouter(tags=["operations"])


@router.get("/health")
def health():
    """Liveness only: the process is running and can answer HTTP."""
    try:
        provider = list_ui_providers()["active"]
    except Exception:
        provider = None
    # `provider` is retained for the existing sidebar health contract; failure to
    # inspect it does not make a live process unhealthy.
    return {"status": "ok", "provider": provider}


@router.get("/ready")
def readiness():
    """Readiness for traffic: database and built SPA are both available."""
    checks = {"database": False, "frontend": Path("static/index.html").is_file()}
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["database"] = True
    except Exception as exc:
        log_error("Readiness", "Database check failed", exception=exc)

    try:
        provider_state = list_ui_providers()
        checks["active_provider"] = provider_state["active"]
        checks["configured_providers"] = sum(1 for item in provider_state["providers"] if item["configured"])
    except Exception:
        checks["active_provider"] = None
        checks["configured_providers"] = 0

    ready = bool(checks["database"] and checks["frontend"])
    return JSONResponse(status_code=200 if ready else 503, content={"status": "ready" if ready else "not_ready", "checks": checks})


@router.get("/metrics")
def operational_metrics():
    """Dependency-free JSON metrics for the current process."""
    return snapshot()
