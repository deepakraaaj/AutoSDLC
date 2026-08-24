from fastapi import APIRouter
from fastapi.responses import JSONResponse

from bitbucket.client import (
    BitbucketConfig,
    get_pull_request,
    get_pull_request_diff,
    get_repo_metadata,
    validate_bitbucket_url,
)
from app.services.jobs import create_job
from app.utils.error_handler import AppError, ValidationError, log_error


router = APIRouter(prefix="/bitbucket", tags=["bitbucket"])


@router.get("/repo")
def bitbucket_repo():
    """Connectivity/config health-check — mirrors describe_redmine_workspace's role.

    Always 200 with a {configured, full_name, workspace, error} envelope
    (graceful-degradation shape: never a bare HTTP error for 'not configured'), rather than a
    4xx/5xx — the frontend's BitbucketModal reads `configured` to decide
    whether to enable push/review, and treating "not configured" as an HTTP
    error made that check unreachable on the success path too."""
    config = BitbucketConfig.from_env()
    if not config.is_configured():
        return {
            "configured": False,
            "error": (
                "Bitbucket not configured. Set BITBUCKET_BASE_URL, BITBUCKET_WORKSPACE, "
                "BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN in .env"
            ),
        }
    try:
        validate_bitbucket_url(config.base_url)
        metadata = get_repo_metadata(config)
        return {
            "configured": True,
            "full_name": metadata.get("full_name", f"{config.workspace}/{config.repo_slug}"),
            "workspace": config.workspace,
        }
    except ValueError as e:
        return {"configured": False, "error": str(e)}
    except Exception as e:
        log_error("Bitbucket", "Repo metadata fetch failed", exception=e)
        return {"configured": False, "error": f"Failed to reach Bitbucket: {e}"}


@router.post("/pull-requests/{pr_id}/review", status_code=202)
def trigger_bitbucket_review(pr_id: str):
    """Manually trigger the same 'bitbucket_review' job the webhook
    (app/api/webhooks.py) schedules automatically on a PR event — for
    re-running a review, or reviewing a PR from before the webhook was
    configured. Uses the repo from BITBUCKET_* env, same as every other
    endpoint in this router."""
    config = BitbucketConfig.from_env()
    if not config.is_configured():
        return JSONResponse(
            status_code=400,
            content=ValidationError("Bitbucket not configured. See /bitbucket/repo for required env vars.").to_dict(),
        )
    repo_full_name = f"{config.workspace}/{config.repo_slug}"
    try:
        job = create_job("bitbucket_review", {"repo_full_name": repo_full_name, "pr_id": pr_id})
    except Exception as e:
        log_error("Bitbucket", f"Failed to schedule manual review for PR #{pr_id}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=str(e)).to_dict())
    return job


@router.get("/pull-requests/{pr_id}")
def bitbucket_pull_request(pr_id: str):
    config = BitbucketConfig.from_env()
    if not config.is_configured():
        return JSONResponse(
            status_code=400,
            content=ValidationError("Bitbucket not configured. See /bitbucket/repo for required env vars.").to_dict(),
        )
    try:
        validate_bitbucket_url(config.base_url)
        pr = get_pull_request(config, pr_id)
        pr["diff"] = get_pull_request_diff(config, pr_id)
        return pr
    except ValueError as e:
        return JSONResponse(status_code=400, content=ValidationError(str(e)).to_dict())
    except Exception as e:
        log_error("Bitbucket", f"Pull request {pr_id} fetch failed", exception=e)
        return JSONResponse(status_code=502, content=AppError(message=str(e)).to_dict())
