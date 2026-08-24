"""Bitbucket PR webhook — the trigger for the Phase 3 code-review agent.

This is the first inbound-authenticated endpoint in AutoSDLC (see
app/utils/webhook_auth.py's docstring). Signature verification happens
before anything else in the handler body — no DB write, no job scheduling —
on the raw, unparsed request bytes, since HMAC has to be computed over
exactly what Bitbucket sent, not a re-serialized version of it.
"""
import json
import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.database import list_related_repos, record_webhook_delivery
from app.services.jobs import create_job
from app.utils.error_handler import RateLimitError, log_error, log_info, log_warning
from app.utils.rate_limit import BITBUCKET_WEBHOOK_LIMIT_PER_MINUTE, enforce_rate_limit
from app.utils.webhook_auth import verify_bitbucket_signature


router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SUPPORTED_EVENTS = {"pullrequest:created", "pullrequest:updated"}


@router.post("/bitbucket", status_code=202)
async def bitbucket_webhook(request: Request):
    try:
        enforce_rate_limit(request, bucket="bitbucket_webhook", limit=BITBUCKET_WEBHOOK_LIMIT_PER_MINUTE)
    except RateLimitError as e:
        log_warning("Webhook", "Rate limit hit on /webhooks/bitbucket")
        return JSONResponse(status_code=429, content=e.to_dict())

    body = await request.body()
    secret = os.getenv("BITBUCKET_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Hub-Signature")
    if not verify_bitbucket_signature(body, signature, secret):
        log_warning("Webhook", "Rejected Bitbucket webhook: missing or invalid signature")
        return JSONResponse(status_code=401, content={"message": "Invalid or missing webhook signature"})

    event_key = request.headers.get("X-Event-Key", "")
    if event_key not in SUPPORTED_EVENTS:
        log_info("Webhook", f"Ignoring unsupported Bitbucket event: {event_key}")
        return JSONResponse(status_code=202, content={"message": f"Ignored event: {event_key}"})

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"message": "Invalid JSON payload"})

    delivery_id = request.headers.get("X-Request-UUID") or str(uuid.uuid4())
    if not record_webhook_delivery(delivery_id, event_key):
        log_info("Webhook", f"Duplicate Bitbucket webhook delivery ignored: {delivery_id}")
        return JSONResponse(status_code=202, content={"message": "Already processed", "delivery_id": delivery_id})

    pr = payload.get("pullrequest") or {}
    repo = payload.get("repository") or {}
    pr_id = pr.get("id")
    repo_full_name = repo.get("full_name", "")
    if pr_id is None or not repo_full_name:
        log_warning("Webhook", f"Bitbucket webhook missing pullrequest.id/repository.full_name: {event_key}")
        return JSONResponse(status_code=202, content={"message": "Payload missing pull request or repository info"})

    try:
        job = create_job("bitbucket_review", {
            "repo_full_name": repo_full_name, "pr_id": pr_id,
            "related_repos": list_related_repos(repo_full_name),
        })
    except Exception as e:
        log_error("Webhook", "Failed to schedule bitbucket_review job", exception=e)
        return JSONResponse(status_code=500, content={"message": "Failed to schedule review job"})

    log_info("Webhook", f"Scheduled review job {job['id']} for PR #{pr_id} in {repo_full_name}")
    return {"job_id": job["id"], "delivery_id": delivery_id}
