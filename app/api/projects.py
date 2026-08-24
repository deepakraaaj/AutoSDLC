from concurrent.futures import ThreadPoolExecutor
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.models import (
    ProjectCreateRequest,
    ProjectRepoCreateRequest,
    ProjectRepoUpdateRequest,
    PublishReviewRequest,
    ProjectSettingsUpdate,
    SprintPlanRequest,
    ProjectUpdateRequest,
)
from app.services.database import (
    add_project_repo,
    create_project,
    delete_project,
    delete_project_repo,
    get_generation,
    get_latest_security_scan_job,
    get_project,
    get_project_settings,
    get_review_publication,
    get_wiki_page,
    list_bitbucket_review_jobs,
    list_related_repos,
    list_projects,
    list_project_sprints,
    create_project_sprint,
    update_project_sprint,
    delete_project_sprint,
    list_wiki_pages,
    mark_repo_verified,
    record_token_usage,
    record_review_publication,
    update_project,
    update_project_repo,
    upsert_project_settings,
    upsert_wiki_page,
)
from app.services.jobs import create_job, list_events
from app.services.providers import AllProvidersExhaustedError, get_provider
from app.services.wiki_generator import WikiGenerationError, generate_project_wiki, generate_repo_wiki
from app.utils.error_handler import AppError, ErrorSeverity, ValidationError, log_error, log_info, log_warning
from bitbucket.client import (
    BitbucketConfig,
    BitbucketWritesDisabledError,
    build_repo_context_block,
    get_file_content,
    get_repo_metadata,
    list_pull_requests,
    post_pr_comment,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/sprints")
def list_sprints_endpoint(project_id: int):
    if not get_project(project_id): return JSONResponse(status_code=404, content={"message": "Project not found"})
    return {"sprints": list_project_sprints(project_id)}


@router.post("/{project_id}/sprints", status_code=201)
def create_sprint_endpoint(project_id: int, request: SprintPlanRequest):
    if not get_project(project_id): return JSONResponse(status_code=404, content={"message": "Project not found"})
    if request.end_date < request.start_date: return JSONResponse(status_code=400, content={"message": "End date must not precede start date"})
    return create_project_sprint(project_id, **request.model_dump())


@router.put("/{project_id}/sprints/{sprint_id}")
def update_sprint_endpoint(project_id: int, sprint_id: int, request: SprintPlanRequest):
    sprint = update_project_sprint(project_id, sprint_id, **request.model_dump())
    return sprint or JSONResponse(status_code=404, content={"message": "Sprint not found"})


@router.delete("/{project_id}/sprints/{sprint_id}")
def delete_sprint_endpoint(project_id: int, sprint_id: int):
    if not delete_project_sprint(project_id, sprint_id):
        return JSONResponse(status_code=404, content={"message": "Sprint not found"})
    return {"deleted": True}


@router.post("")
def create_project_endpoint(request: ProjectCreateRequest):
    return create_project(request.name.strip(), request.description.strip(), request.ticket_prefix.strip().upper())


@router.get("")
def list_projects_endpoint():
    return {"projects": list_projects()}


@router.get("/{project_id}")
def get_project_endpoint(project_id: int):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    return project


@router.put("/{project_id}")
def update_project_endpoint(project_id: int, request: ProjectUpdateRequest):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    fields = request.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    if "ticket_prefix" in fields:
        fields["ticket_prefix"] = (fields["ticket_prefix"] or "").strip().upper()
    return update_project(project_id, **fields)


@router.delete("/{project_id}")
def delete_project_endpoint(project_id: int):
    """Deletes the project and its repos/settings (cascade). Generations
    that were attached to it are kept — only unlinked (project_id -> NULL),
    not deleted; a project going away must never take a backlog with it."""
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    delete_project(project_id)
    return {"deleted": True}


@router.post("/{project_id}/repos", status_code=201)
def add_project_repo_endpoint(project_id: int, request: ProjectRepoCreateRequest):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())

    repo = add_project_repo(
        project_id, request.workspace.strip(), request.repo_slug.strip(),
        label=request.label.strip(),
    )

    verification: dict = {"attempted": False}
    if request.verify:
        verification["attempted"] = True
        config = BitbucketConfig.from_env()
        config.workspace = request.workspace.strip()
        config.repo_slug = request.repo_slug.strip()
        if not config.access_token:
            verification["error"] = "BITBUCKET_ACCESS_TOKEN not set on the server — repo linked but not verified."
        else:
            try:
                get_repo_metadata(config)
                mark_repo_verified(repo["id"])
                verification["ok"] = True
            except Exception as e:
                # Best-effort — linking a repo the token doesn't have access
                # to (yet) must not fail the whole request.
                log_warning("Projects", f"Repo verification failed for project {project_id} repo {request.workspace}/{request.repo_slug}: {e}")
                verification["ok"] = False
                verification["error"] = str(e)

    # Re-read so verified_at reflects the actual persisted value rather than
    # the interim placeholder assigned above.
    refreshed_project = get_project(project_id)
    refreshed_repo = next((r for r in refreshed_project["repos"] if r["id"] == repo["id"]), repo)
    return {**refreshed_repo, "verification": verification}


@router.put("/{project_id}/repos/{repo_id}")
def update_project_repo_endpoint(project_id: int, repo_id: int, request: ProjectRepoUpdateRequest):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    if not any(r["id"] == repo_id for r in project["repos"]):
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    fields = request.model_dump(exclude_unset=True)
    if "workspace" in fields:
        fields["workspace"] = fields["workspace"].strip()
    if "repo_slug" in fields:
        fields["repo_slug"] = fields["repo_slug"].strip()
    if "label" in fields:
        fields["label"] = (fields["label"] or "").strip()
    return update_project_repo(repo_id, **fields)


@router.delete("/{project_id}/repos/{repo_id}")
def delete_project_repo_endpoint(project_id: int, repo_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    delete_project_repo(repo_id)
    return {"deleted": True}


@router.get("/{project_id}/settings")
def get_project_settings_endpoint(project_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    return get_project_settings(project_id)


@router.put("/{project_id}/settings")
def update_project_settings_endpoint(project_id: int, request: ProjectSettingsUpdate):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    try:
        return upsert_project_settings(project_id, **request.model_dump(exclude_unset=True))
    except Exception as e:
        log_error("Projects", f"Failed to update settings for project {project_id}", exception=e)
        return JSONResponse(status_code=500, content=ValidationError(f"Failed to save settings: {e}").to_dict())


# ── Wiki ─────────────────────────────────────────────────────────────────
# One AI-generated page for the project itself, plus one per linked repo.
# See app/services/wiki_generator.py for the generation call and
# app/services/prompt.py for WIKI_PROJECT_SYSTEM / WIKI_REPO_SYSTEM.

def _wiki_generation_error_response(e: Exception, context: str) -> JSONResponse:
    """Same status/message split PhaseGenerator's run() uses for this same
    exception in the streaming pipeline (app/services/generators.py) — every
    provider being unavailable is a different, more actionable situation than
    a bug, so it gets its own message rather than a generic 500."""
    if isinstance(e, AllProvidersExhaustedError):
        log_error("Wiki", f"All configured providers exhausted while {context}", exception=e)
        return JSONResponse(status_code=503, content=AppError(message=str(e), severity=ErrorSeverity.WARNING).to_dict())
    if isinstance(e, WikiGenerationError):
        log_error("Wiki", f"Malformed model response while {context}", exception=e)
        return JSONResponse(status_code=502, content=AppError(message=str(e)).to_dict())
    log_error("Wiki", f"Failed while {context}", exception=e)
    return JSONResponse(status_code=500, content=AppError(message=f"Wiki generation failed: {e}").to_dict())


def _readme_content(config: BitbucketConfig) -> str | None:
    """Best-effort README fetch — tries the common filenames and returns the
    first hit, or None if the repo has none of them / isn't reachable. Never
    raises: a missing README is normal, not an error."""
    for candidate in ("README.md", "readme.md", "README.rst", "README"):
        try:
            return get_file_content(config, candidate)
        except Exception:
            continue
    return None


def _collect_repo_wiki_material(repo: dict) -> dict:
    """Build one bounded knowledge source for the project overview.

    Kept best-effort per repository: one unavailable frontend/backend must
    not prevent the remaining repositories from producing useful knowledge.
    """
    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    configured = config.is_configured()
    return {
        "label": repo["label"] or repo["repo_slug"],
        "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
        "context_block": build_repo_context_block(config) if configured else "",
        "readme_text": _readme_content(config) if configured else None,
    }


@router.get("/{project_id}/wiki")
def get_project_wiki_endpoint(project_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    return {"project_id": project_id, "pages": list_wiki_pages(project_id)}


@router.post("/{project_id}/wiki/generate")
def generate_project_wiki_endpoint(project_id: int):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())

    # Ground the page in the most recent generation's original brief, the same
    # input_text backlog generation itself was grounded in — reusing real data
    # already on hand rather than re-deriving a summary from epics/stories.
    brief_text = None
    if project["generations"]:
        latest = get_generation(project["generations"][0]["id"])
        if latest:
            brief_text = latest["input_text"]

    # Also ground it in what every linked repo actually contains — same
    # graceful-degradation contract as generate_repo_wiki_endpoint below
    # (unconfigured/unreachable repos just contribute a thin/empty block,
    # never fail the request). Repositories are independent remote reads, so
    # gather them concurrently and retain their configured order in the
    # resulting prompt. This includes all linked repos, not an arbitrary first
    # three, because omitting a service can fundamentally misstate scope.
    if project["repos"]:
        with ThreadPoolExecutor(max_workers=min(len(project["repos"]), 8)) as pool:
            repo_materials = list(pool.map(_collect_repo_wiki_material, project["repos"]))
    else:
        repo_materials = []

    provider = get_provider()
    generation_started_at = time.monotonic()
    try:
        page = generate_project_wiki(
            provider, project["name"], project["description"] or "", brief_text, repo_materials or None,
        )
    except Exception as e:
        return _wiki_generation_error_response(e, f"generating the wiki for project {project_id}")

    if hasattr(provider, "usage_summary"):
        usage = provider.usage_summary()
        if usage.get("ai_calls"):
            record_token_usage(
                "wiki", str(project_id), getattr(provider, "provider_id", None), usage,
                duration_seconds=round(time.monotonic() - generation_started_at, 1),
            )

    log_info("Wiki", f"Generated project wiki for project {project_id}")
    return upsert_wiki_page(project_id, None, page["title"], page["summary"], page["sections"])


@router.post("/{project_id}/repos/{repo_id}/wiki/generate")
def generate_repo_wiki_endpoint(project_id: int, repo_id: int):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    repo = next((r for r in project["repos"] if r["id"] == repo_id), None)
    if not repo:
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    repo_label = repo["label"] or repo["repo_slug"]
    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    # Graceful degradation, same convention as build_repo_context_block and
    # add_project_repo_endpoint's own verification step: an unreachable or
    # unconfigured repo must not fail the whole request — the prompt is
    # written to handle a thin/empty context block on its own.
    context_block = build_repo_context_block(config) if config.is_configured() else ""
    readme_text = _readme_content(config) if config.is_configured() else None

    provider = get_provider()
    generation_started_at = time.monotonic()
    try:
        page = generate_repo_wiki(provider, project["name"], repo_label, context_block, readme_text)
    except Exception as e:
        return _wiki_generation_error_response(e, f"generating the wiki for repo {repo_id} on project {project_id}")

    if hasattr(provider, "usage_summary"):
        usage = provider.usage_summary()
        if usage.get("ai_calls"):
            record_token_usage(
                "wiki", f"{project_id}/{repo_id}", getattr(provider, "provider_id", None), usage,
                duration_seconds=round(time.monotonic() - generation_started_at, 1),
            )

    log_info("Wiki", f"Generated repo wiki for project {project_id} repo {repo_id}")
    return upsert_wiki_page(project_id, repo_id, page["title"], page["summary"], page["sections"])


# ── Pull requests ────────────────────────────────────────────────────────
# PR listings come live from Bitbucket (source of truth for what's open);
# review status/findings come from the 'bitbucket_review' jobs the webhook
# (app/api/webhooks.py) and the manual trigger (app/api/bitbucket.py)
# schedule — see list_bitbucket_review_jobs's docstring for why jobs are the
# source of truth for review state rather than a separate table.

def _pr_summary(pr: dict, review: dict | None) -> dict:
    result = (review or {}).get("result") or {}
    findings = result.get("findings", [])
    files_reviewed = result.get("files_reviewed", [])
    summary = result.get("summary") or ""
    token_usage = result.get("token_usage")
    duration_seconds = result.get("duration_seconds")
    publication = get_review_publication(review["job_id"]) if review else None
    severity_counts = {"blocking": 0, "important": 0, "minor": 0}
    for finding in findings:
        severity = finding.get("severity") if isinstance(finding, dict) else None
        if severity in severity_counts:
            severity_counts[severity] += 1
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "author": (pr.get("author") or {}).get("display_name"),
        "source_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "destination_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name"),
        "state": pr.get("state"),
        "created_on": pr.get("created_on"),
        "updated_on": pr.get("updated_on"),
        "html_url": ((pr.get("links") or {}).get("html") or {}).get("href"),
        "review": {
            "status": review["status"] if review else "not_reviewed",
            "job_id": review["job_id"] if review else None,
            "error": review.get("error") if review else None,
            "reviewed_at": review.get("updated_at") if review else None,
            # Plain-English "what this diff changes" (CODE_REVIEW_SYSTEM),
            # not "reviewed the diff" — a summary of the change itself, so
            # the review reads as substance even before findings/files below.
            "summary": summary,
            "findings_count": len(findings),
            "severity_counts": severity_counts,
            # Full findings, not just the count — a "succeeded" badge with
            # zero context beyond a number reads as "trust me" rather than
            # an actual review; the frontend needs the real per-finding
            # file/line/severity/comment to show what was actually checked.
            "findings": findings,
            # The diff's touched files (langgraph_pipeline.py's
            # _diff_touched_files) — the other half of "what was actually
            # checked" alongside findings, especially when there are none.
            "files_reviewed": files_reviewed,
            # Real per-call usage from the LiteLLM response (LiteLLMProvider
            # .usage_summary() in app/services/providers.py), not an
            # estimate — null for jobs that ran before this field existed,
            # or on a provider that doesn't report usage.
            "token_usage": token_usage,
            "duration_seconds": duration_seconds,
            "integrity_check": result.get("integrity_check"),
            "related_repositories_checked": result.get("related_repositories_checked", 0),
            "publication": publication,
        },
    }


def _fetch_repo_pull_requests(repo: dict) -> dict:
    """One repo's entry for list_project_pull_requests_endpoint — factored
    out so it can run on a thread pool (see below): each call is a blocking
    network round trip to Bitbucket (paginated), independent of every other
    repo's, so N repos fetched one after another cost N times the latency
    of the slowest one for no reason. Best-effort: an unconfigured or
    unreachable repo contributes an `error` on its own entry rather than
    failing the whole request."""
    repo_full_name = f"{repo['workspace']}/{repo['repo_slug']}"
    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    entry = {
        "repo_id": repo["id"],
        "label": repo["label"] or repo["repo_slug"],
        "repo_full_name": repo_full_name,
        "pull_requests": [],
        "error": None,
    }
    if not config.is_configured():
        entry["error"] = "Bitbucket not configured for this repo (missing access token)."
        return entry
    try:
        prs = list_pull_requests(config)
    except Exception as e:
        log_warning("Projects", f"Failed to list PRs for {repo_full_name}: {e}")
        entry["error"] = str(e)
        return entry
    reviews = list_bitbucket_review_jobs(repo_full_name)
    entry["pull_requests"] = [_pr_summary(pr, reviews.get(str(pr.get("id")))) for pr in prs]
    return entry


@router.get("/{project_id}/pull-requests")
def list_project_pull_requests_endpoint(project_id: int):
    """One entry per linked repo, each with its open PRs and — where a
    'bitbucket_review' job has run for that PR — the AI review outcome.

    Repos are fetched concurrently (ThreadPoolExecutor), not one after
    another: each is a paginated Bitbucket round trip, and a project with
    a handful of repos was taking several seconds end to end purely from
    running those sequentially — this collapses it to roughly the slowest
    single repo's fetch time. list_bitbucket_review_jobs' order-preserving
    zip with project['repos'] keeps repos_out in the same order regardless
    of which thread finishes first."""
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())

    if not project["repos"]:
        return {"project_id": project_id, "repos": []}

    with ThreadPoolExecutor(max_workers=min(len(project["repos"]), 8)) as pool:
        repos_out = list(pool.map(_fetch_repo_pull_requests, project["repos"]))

    return {"project_id": project_id, "repos": repos_out}


@router.post("/{project_id}/repos/{repo_id}/pull-requests/{pr_id}/review", status_code=202)
def trigger_project_pull_request_review_endpoint(project_id: int, repo_id: int, pr_id: str):
    """Same 'bitbucket_review' job app/api/bitbucket.py's trigger_bitbucket_review
    schedules, but resolved against one of this project's N repos instead of
    the single BITBUCKET_* env repo — for re-running a review, or reviewing a
    PR from before the webhook was configured, on a non-default repo."""
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    repo = next((r for r in project["repos"] if r["id"] == repo_id), None)
    if not repo:
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    if not config.is_configured():
        return JSONResponse(status_code=400, content=ValidationError("Bitbucket not configured for this repo (missing access token).").to_dict())

    repo_full_name = f"{repo['workspace']}/{repo['repo_slug']}"
    try:
        job = create_job("bitbucket_review", {
            "repo_full_name": repo_full_name, "pr_id": pr_id,
            "related_repos": list_related_repos(repo_full_name),
        })
    except Exception as e:
        log_error("Projects", f"Failed to schedule review for PR #{pr_id} on {repo_full_name}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=str(e)).to_dict())
    return job


@router.post("/{project_id}/repos/{repo_id}/pull-requests/{pr_id}/review/publish")
def publish_project_pull_request_review_endpoint(
    project_id: int, repo_id: int, pr_id: str, request: PublishReviewRequest,
):
    """Publish the latest completed review as one Bitbucket comment.

    This is the only review path allowed to write to Bitbucket and requires
    an explicit confirmation flag. Generation/webhook review jobs stay
    strictly read-only.
    """
    if not request.confirm:
        return JSONResponse(status_code=400, content=ValidationError("Explicit confirmation is required before publishing.").to_dict())
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found").to_dict())
    repo = next((r for r in project["repos"] if r["id"] == repo_id), None)
    if not repo:
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}").to_dict())

    repo_full_name = f"{repo['workspace']}/{repo['repo_slug']}"
    review = list_bitbucket_review_jobs(repo_full_name).get(str(pr_id))
    if not review or review["status"] != "succeeded" or not review.get("result"):
        return JSONResponse(status_code=409, content=ValidationError("A completed review is required before publishing.").to_dict())
    existing = get_review_publication(review["job_id"])
    if existing:
        return {"published": True, "already_published": True, **existing}

    result = review["result"]
    findings = result.get("findings") or []
    lines = ["## AI-assisted code review", "", result.get("summary") or "Review completed."]
    if findings:
        lines.extend(["", "### Findings"])
        for finding in findings:
            location = finding.get("file", "unknown file")
            if finding.get("line"):
                location += f":{finding['line']}"
            verification = finding.get("verification", "risk").title()
            lines.append(f"- **{finding.get('severity', 'minor').title()} · {verification}** `{location}` — {finding.get('comment', '')}")
    else:
        lines.extend(["", "No issues were flagged by this AI review."])
    lines.extend(["", "_AI-generated review; human verification is still recommended._"])

    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    try:
        comment = post_pr_comment(config, pr_id, "\n".join(lines))
        publication = record_review_publication(review["job_id"], str(comment.get("id")) if comment.get("id") is not None else None)
    except BitbucketWritesDisabledError as e:
        log_warning("Projects", str(e))
        return JSONResponse(status_code=403, content=ValidationError(str(e)).to_dict())
    except Exception as e:
        log_error("Projects", f"Failed to publish review for PR #{pr_id} on {repo_full_name}", exception=e)
        return JSONResponse(status_code=502, content=AppError(message=f"Failed to publish review: {e}").to_dict())
    return {"published": True, "already_published": False, **publication}


# ── Security / VAPT ──────────────────────────────────────────────────────
# Phase 1: an LLM security pass over each linked repo's current contents
# (app/services/langgraph_pipeline.py's run_security_review), run as a
# durable 'security_scan' job — same pattern as 'bitbucket_review'. Phase 2
# (real scanners — Bandit/Semgrep/pip-audit) lands as a separate job kind
# whose findings merge into the same per-repo view.

def _security_summary(repo: dict, scan: dict | None) -> dict:
    result = (scan or {}).get("result") or {}
    live_tools = result.get("tools", [])
    if scan and scan.get("status") in {"queued", "running"}:
        seen_tools = {}
        for event in list_events(scan["job_id"]):
            if event["type"] == "scanner_status" and event["payload"].get("tool"):
                tool = event["payload"]["tool"]
                seen_tools[tool] = event["payload"]
        live_tools = [{
            "name": name,
            "status": payload.get("status", "queued"),
            "findings_count": payload.get("findings_count", 0),
            "duration_seconds": payload.get("duration_seconds"),
        } for name, payload in seen_tools.items()]
    findings = list(result.get("findings", [])) + list(result.get("scanner_findings", []))
    for finding in findings:
        if finding.get("severity") not in {"critical", "high", "medium", "low"}:
            finding["severity"] = "medium"
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        severity = finding.get("severity") if isinstance(finding, dict) else None
        if severity in severity_counts:
            severity_counts[severity] += 1
    return {
        "repo_id": repo["id"],
        "label": repo["label"] or repo["repo_slug"],
        "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
        "scan": {
            "status": scan["status"] if scan else "not_scanned",
            "job_id": scan["job_id"] if scan else None,
            "error": (scan.get("error") if scan else None) or result.get("ai_error"),
            "scanned_at": scan["updated_at"] if scan else None,
            "findings": findings,
            "severity_counts": severity_counts,
            "token_usage": result.get("token_usage"),
            "tools": live_tools,
            "snapshot_files": result.get("snapshot_files", 0),
            "scanner_commit": result.get("scanner_commit"),
            "duration_seconds": result.get("duration_seconds"),
        },
    }


@router.get("/{project_id}/security")
def get_project_security_endpoint(project_id: int):
    """One entry per linked repo with its latest security_scan job, if any
    has run. Never triggers a scan itself — same read-only/trigger-separate
    split as the pull-requests endpoints above."""
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    repos = [_security_summary(repo, get_latest_security_scan_job(repo["id"])) for repo in project["repos"]]
    return {"project_id": project_id, "repos": repos}


@router.post("/{project_id}/repos/{repo_id}/security-scan", status_code=202)
def trigger_repo_security_scan_endpoint(project_id: int, repo_id: int):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    repo = next((r for r in project["repos"] if r["id"] == repo_id), None)
    if not repo:
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    if not config.is_configured():
        return JSONResponse(status_code=400, content=ValidationError("Bitbucket not configured for this repo (missing access token).").to_dict())

    try:
        job = create_job("security_scan", {
            "repo_id": repo_id,
            "label": repo["label"] or repo["repo_slug"],
            "workspace": repo["workspace"],
            "repo_slug": repo["repo_slug"],
        })
    except Exception as e:
        log_error("Projects", f"Failed to schedule security scan for repo {repo_id} on project {project_id}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=str(e)).to_dict())
    return job
