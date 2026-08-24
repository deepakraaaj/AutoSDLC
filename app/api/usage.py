"""Token spend reporting — everything logged via
app/services/database.py's record_token_usage, real per-call usage from
each LiteLLMProvider's own response (never an estimate). Read-only: nothing
here triggers AI calls, it only reports what already happened."""
from fastapi import APIRouter

from app.services.database import get_token_usage_summary, list_token_usage


router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary")
def get_usage_summary():
    return get_token_usage_summary()


@router.get("/log")
def get_usage_log(limit: int = 100, offset: int = 0):
    return {"entries": list_token_usage(limit=limit, offset=offset)}
