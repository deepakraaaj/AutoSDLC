from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.models import (
    PRSecurityScanRequest,
    ProjectBriefFromRepoRequest,
    ProjectCreateRequest,
    ProjectRepoCreateRequest,
    ProjectRepoUpdateRequest,
    PublishReviewRequest,
    ProjectSettingsUpdate,
    SprintPlanRequest,
    ProjectUpdateRequest,
    WikiGenerationRequest,
)
from app.services.database import (
    add_project_repo,
    create_project,
    delete_project,
    delete_project_repo,
    get_generation,
    get_latest_security_scan_job,
    get_current_chapter_set,
    get_project,
    get_project_settings,
    get_repository_index,
    get_review_publication,
    get_security_scan,
    get_wiki_page,
    list_bitbucket_review_jobs,
    list_pr_security_scan_jobs,
    list_related_repos,
    list_security_findings,
    list_projects,
    list_project_sprints,
    create_project_sprint,
    update_project_sprint,
    delete_project_sprint,
    list_wiki_pages,
    mark_repo_verified,
    record_token_usage,
    record_review_publication,
    save_repository_index,
    update_project,
    update_project_repo,
    upsert_project_settings,
    upsert_wiki_page,
)
from app.services.jobs import configure_runner, create_job, get_job, list_events
from app.services.artifact_store import get_artifact_store, write_wiki_artifacts
from app.services.repo_intelligence import INDEX_VERSION, index_repository, intelligence_prompt, repository_index_from_dict
from app.services.vapt import best_fix_version, create_repository_snapshot
from app.services.providers import AllProvidersExhaustedError, get_provider
from app.services.repo_brief import RepoBriefGenerationError, generate_repo_derived_brief
from app.services.wiki_generator import WikiGenerationError, generate_project_wiki, generate_repo_wiki
from app.services.wiki_chapters import generate_and_persist_chapter_wiki
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
        label=request.label.strip(), scan_branch=(request.scan_branch or "").strip() or None,
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
    if "scan_branch" in fields:
        fields["scan_branch"] = (fields["scan_branch"] or "").strip() or None
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


def _readme_content(config: BitbucketConfig, ref: str = "HEAD") -> str | None:
    """Best-effort README fetch — tries the common filenames and returns the
    first hit, or None if the repo has none of them / isn't reachable. Never
    raises: a missing README is normal, not an error."""
    for candidate in ("README.md", "readme.md", "README.rst", "README"):
        try:
            return get_file_content(config, candidate) if ref == "HEAD" else get_file_content(config, candidate, ref=ref)
        except Exception:
            continue
    return None


def _collect_repo_wiki_material(repo: dict, project_id: int | None = None) -> dict:
    """Build one bounded knowledge source for the project overview.

    Kept best-effort per repository: one unavailable frontend/backend must
    not prevent the remaining repositories from producing useful knowledge.
    """
    config = BitbucketConfig.from_env()
    config.workspace = repo["workspace"]
    config.repo_slug = repo["repo_slug"]
    configured = config.is_configured()
    ref = repo.get("scan_branch") or "HEAD"
    resolved_ref = ref
    context_block = ""
    readme_text = None
    source_revision = "unavailable"
    intelligence_artifacts: dict[str, str] = {}
    intelligence_stats: dict = {}
    repository_index = None
    collection_error = None
    if configured:
        try:
            # For the default branch Bitbucket exposes the exact HEAD hash in
            # repository metadata. That one cheap request makes unchanged
            # regenerations a real cache hit without re-downloading the repo.
            known_revision = None
            if ref == "HEAD":
                try:
                    metadata = get_repo_metadata(config)
                    main_branch = metadata.get("mainbranch") or {}
                    known_revision = (main_branch.get("target") or {}).get("hash")
                    resolved_ref = main_branch.get("name") or ref
                except Exception:
                    pass
            cached = get_repository_index(repo["id"], known_revision) if project_id is not None and known_revision else None
            if cached and cached.get("stats", {}).get("index_version") == INDEX_VERSION:
                source_revision = known_revision
                index = repository_index_from_dict(cached)
            else:
                with TemporaryDirectory(prefix="autosdlc-wiki-") as temporary:
                    snapshot_root = Path(temporary) / "source"
                    snapshot_revision = create_repository_snapshot(
                        config, snapshot_root, branch=None if resolved_ref == "HEAD" else resolved_ref,
                        timeout_seconds=max(15, int(os.getenv("WIKI_SNAPSHOT_TIMEOUT_SECONDS", "60"))),
                        max_files=max(100, int(os.getenv("WIKI_INDEX_MAX_FILES", "5000"))),
                        max_bytes=max(1_000_000, int(os.getenv("WIKI_INDEX_MAX_BYTES", "30000000"))),
                        strict_limits=False,
                    )
                    source_revision = known_revision or snapshot_revision
                    index = index_repository(snapshot_root, source_revision)
                    if project_id is not None:
                        save_repository_index(project_id, repo["id"], index.as_dict())
                    for candidate in ("README.md", "readme.md", "README.rst", "README"):
                        readme = snapshot_root / candidate
                        if readme.is_file():
                            readme_text = readme.read_text(encoding="utf-8", errors="replace")[:12000]
                            break
            context_block = intelligence_prompt(index)
            intelligence_artifacts = index.artifacts
            intelligence_stats = index.stats
            repository_index = index
        except Exception as exc:
            # The snapshot already tried shallow Git and a bounded REST
            # fallback. Starting the old tree/snippet collector here would
            # repeat the same rate-limited calls with no shared deadline and
            # was observed extending a 60-second failure past five minutes.
            log_warning("Wiki", f"Repository intelligence indexing failed for {repo['repo_slug']}: {exc}")
            collection_error = str(exc)
            context_block = ""
            readme_text = None
            digest = sha256(f"{resolved_ref}\nunavailable".encode()).hexdigest()[:16]
            source_revision = f"snapshot-{digest}"
    return {
        "repo_id": repo["id"],
        "label": repo["label"] or repo["repo_slug"],
        "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
        "context_block": context_block,
        "readme_text": readme_text,
        "source_revision": source_revision,
        "ref": resolved_ref,
        "intelligence_artifacts": intelligence_artifacts,
        "intelligence_stats": intelligence_stats,
        "collection_error": collection_error,
        # The raw RepositoryIndex object (None on collection failure) — the
        # multi-chapter wiki pipeline (wiki_chapters.py) needs the actual
        # Symbol/Relation objects, not just the rendered intelligence_prompt
        # text every other consumer of this dict uses. Not JSON-serialized
        # anywhere this dict itself gets returned as an API response.
        "repository_index": repository_index,
    }


def _repository_material_error(materials: list[dict]) -> str | None:
    """Return an actionable error when no repository yielded real evidence."""
    if not materials or any(material.get("context_block") for material in materials):
        return None
    errors = [str(material.get("collection_error") or "").strip() for material in materials]
    detail = next((error for error in errors if error), None)
    if not detail:
        return "Repository contents could not be retrieved. No wiki was generated from empty data."
    if "429" in detail or "rate limit" in detail.lower():
        return "Bitbucket rate limit exceeded while reading repository contents. Wait for the quota to reset, then retry. No wiki was generated from empty data."
    return f"Repository contents could not be retrieved: {detail}. No wiki was generated from empty data."


def _artifact_sources(repo_materials: list[dict]) -> list[dict]:
    return [
        {
            "label": material["label"],
            "repository": material.get("repo_full_name"),
            "ref": material.get("ref", "HEAD"),
            "revision": material.get("source_revision", "unresolved"),
        }
        for material in repo_materials
    ]


def _combined_revision(repo_materials: list[dict]) -> str:
    evidence = "\n".join(material.get("source_revision", "unresolved") for material in repo_materials)
    return f"snapshot-{sha256(evidence.encode()).hexdigest()[:16]}"


def _combined_intelligence_artifacts(repo_materials: list[dict]) -> dict[str, str]:
    combined: dict[str, str] = {}
    for position, material in enumerate(repo_materials, start=1):
        safe_label = "".join(character if character.isalnum() or character in "-_" else "-" for character in material["label"]).strip("-") or f"repo-{position}"
        for name, content in material.get("intelligence_artifacts", {}).items():
            combined[f"repos/{safe_label}/{name}"] = content
    return combined


# ── Brief from repository ────────────────────────────────────────────────
# Automates the manual workflow prompts/EXTRACT_FROM_REPO.md documents (run a
# shell command, paste the output into an external AI tool, paste the result
# back as a markdown brief): pulls the project's linked repos the same way
# wiki generation does and has the model produce the brief directly, so
# backlog generation is grounded in the actual codebase instead of a
# hand-authored doc.

@router.post("/{project_id}/brief/from-repo")
def generate_project_brief_from_repo_endpoint(project_id: int, request: ProjectBriefFromRepoRequest):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    if not project["repos"]:
        return JSONResponse(status_code=400, content=ValidationError("Link a repository to this project first.").to_dict())

    with ThreadPoolExecutor(max_workers=min(len(project["repos"]), 8)) as pool:
        repo_materials = list(pool.map(lambda repo: _collect_repo_wiki_material(repo, project_id), project["repos"]))

    provider = get_provider()
    generation_started_at = time.monotonic()
    try:
        brief_text = generate_repo_derived_brief(
            provider, project["name"], project["description"] or "", repo_materials, request.existing_brief,
        )
    except (AllProvidersExhaustedError, RepoBriefGenerationError) as e:
        status = 503 if isinstance(e, AllProvidersExhaustedError) else 502
        log_error("RepoBrief", f"Failed generating a repo-derived brief for project {project_id}", exception=e)
        return JSONResponse(status_code=status, content=AppError(message=str(e), severity=ErrorSeverity.WARNING).to_dict())
    except Exception as e:
        log_error("RepoBrief", f"Failed generating a repo-derived brief for project {project_id}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=f"Repo-derived brief generation failed: {e}").to_dict())

    if hasattr(provider, "usage_summary"):
        usage = provider.usage_summary()
        if usage.get("ai_calls"):
            record_token_usage(
                "repo_brief", str(project_id), getattr(provider, "provider_id", None), usage,
                duration_seconds=round(time.monotonic() - generation_started_at, 1),
            )

    log_info("RepoBrief", f"Generated repo-derived brief for project {project_id} from {len(project['repos'])} repo(s)")
    return {"brief_text": brief_text, "repos_used": [m["label"] for m in repo_materials]}


@router.get("/{project_id}/wiki")
def get_project_wiki_endpoint(project_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    return {"project_id": project_id, "pages": list_wiki_pages(project_id)}


@router.post("/{project_id}/wiki/generate")
def generate_project_wiki_endpoint(project_id: int, request: WikiGenerationRequest | None = None):
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
            repo_materials = list(pool.map(lambda repo: _collect_repo_wiki_material(repo, project_id), project["repos"]))
    else:
        repo_materials = []

    material_error = _repository_material_error(repo_materials)
    if material_error:
        return JSONResponse(
            status_code=429 if "rate limit" in material_error.lower() else 502,
            content=AppError(message=material_error, severity=ErrorSeverity.WARNING).to_dict(),
        )

    provider = get_provider()
    generation_started_at = time.monotonic()
    try:
        page = generate_project_wiki(
            provider, project["name"], project["description"] or "", brief_text, repo_materials or None,
            (request.clarification_answers if request else None),
        )
    except Exception as e:
        return _wiki_generation_error_response(e, f"generating the wiki for project {project_id}")
    if page.get("needs_clarification"):
        return JSONResponse(status_code=409, content=page)

    if hasattr(provider, "usage_summary"):
        usage = provider.usage_summary()
        if usage.get("ai_calls"):
            record_token_usage(
                "wiki", str(project_id), getattr(provider, "provider_id", None), usage,
                duration_seconds=round(time.monotonic() - generation_started_at, 1),
            )

    revision = _combined_revision(repo_materials) if repo_materials else "project-only"
    extra_artifacts = _combined_intelligence_artifacts(repo_materials)
    if request and request.clarification_answers:
        import json
        extra_artifacts["business-context.json"] = json.dumps(
            {"clarification_answers": request.clarification_answers}, indent=2, ensure_ascii=False,
        )
    artifact = write_wiki_artifacts(
        get_artifact_store(), project_id=project_id, repo_id=None, source_revision=revision,
        page=page, sources=_artifact_sources(repo_materials), extra_artifacts=extra_artifacts,
    )
    log_info("Wiki", f"Generated project wiki for project {project_id}")
    return upsert_wiki_page(
        project_id, None, page["title"], page["summary"], page["sections"],
        artifact.key, artifact.source_revision, artifact.content_hash,
    )


@router.post("/{project_id}/repos/{repo_id}/wiki/generate")
def generate_repo_wiki_endpoint(project_id: int, repo_id: int, request: WikiGenerationRequest | None = None):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    repo = next((r for r in project["repos"] if r["id"] == repo_id), None)
    if not repo:
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    repo_label = repo["label"] or repo["repo_slug"]
    material = _collect_repo_wiki_material(repo, project_id)
    material_error = _repository_material_error([material])
    if material_error:
        return JSONResponse(
            status_code=429 if "rate limit" in material_error.lower() else 502,
            content=AppError(message=material_error, severity=ErrorSeverity.WARNING).to_dict(),
        )
    context_block = material["context_block"]
    readme_text = material["readme_text"]

    provider = get_provider()
    generation_started_at = time.monotonic()
    try:
        page = generate_repo_wiki(provider, project["name"], repo_label, context_block, readme_text, request.clarification_answers if request else None)
    except Exception as e:
        return _wiki_generation_error_response(e, f"generating the wiki for repo {repo_id} on project {project_id}")
    if page.get("needs_clarification"):
        return JSONResponse(status_code=409, content=page)

    if hasattr(provider, "usage_summary"):
        usage = provider.usage_summary()
        if usage.get("ai_calls"):
            record_token_usage(
                "wiki", f"{project_id}/{repo_id}", getattr(provider, "provider_id", None), usage,
                duration_seconds=round(time.monotonic() - generation_started_at, 1),
            )

    extra_artifacts = dict(material.get("intelligence_artifacts") or {})
    if request and request.clarification_answers:
        import json
        extra_artifacts["business-context.json"] = json.dumps(
            {"clarification_answers": request.clarification_answers}, indent=2, ensure_ascii=False,
        )
    artifact = write_wiki_artifacts(
        get_artifact_store(), project_id=project_id, repo_id=repo_id,
        source_revision=material["source_revision"], page=page, sources=_artifact_sources([material]),
        extra_artifacts=extra_artifacts,
    )
    log_info("Wiki", f"Generated repo wiki for project {project_id} repo {repo_id}")
    return upsert_wiki_page(
        project_id, repo_id, page["title"], page["summary"], page["sections"],
        artifact.key, artifact.source_revision, artifact.content_hash,
    )


def _wiki_generation_job_runner(payload: dict):
    project_id = int(payload["project_id"])
    repo_id = payload.get("repo_id")
    scope = f"repository {repo_id}" if repo_id is not None else "all linked repositories"
    yield "status", {"message": f"Reading and indexing {scope}…"}
    response = (
        generate_repo_wiki_endpoint(project_id, int(repo_id), WikiGenerationRequest(clarification_answers=payload.get("clarification_answers", {})))
        if repo_id is not None
        else generate_project_wiki_endpoint(project_id, WikiGenerationRequest(clarification_answers=payload.get("clarification_answers", {})))
    )
    if isinstance(response, JSONResponse):
        import json
        body = json.loads(response.body)
        if response.status_code == 409 and body.get("needs_clarification"):
            yield "clarification", {"questions": body.get("clarifying_questions", [])}
            return
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        yield "error", {"message": error.get("message") or body.get("message", "Wiki generation failed")}
        return
    yield "status", {"message": "Repository processing and wiki persistence completed."}
    yield "done", {"page": response}


configure_runner("wiki_generation", _wiki_generation_job_runner)


@router.post("/{project_id}/wiki/generate-job", status_code=202)
def start_project_wiki_job(project_id: int, request: WikiGenerationRequest | None = None):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found").to_dict())
    return create_job("wiki_generation", {"project_id": project_id, "clarification_answers": (request.clarification_answers if request else {})})


@router.post("/{project_id}/repos/{repo_id}/wiki/generate-job", status_code=202)
def start_repo_wiki_job(project_id: int, repo_id: int, request: WikiGenerationRequest | None = None):
    project = get_project(project_id)
    if not project or not any(repo["id"] == repo_id for repo in project["repos"]):
        return JSONResponse(status_code=404, content=AppError(message="Project or linked repository not found").to_dict())
    return create_job("wiki_generation", {"project_id": project_id, "repo_id": repo_id, "clarification_answers": (request.clarification_answers if request else {})})


# ── Multi-chapter wiki (phase 1: wiki_chapters.py's Pass 0 + Pass 1) ────────
# Additive alongside the flat wiki endpoints above, which this never
# touches. Gated behind project_settings.chapter_wiki_enabled — the flat
# pipeline stays the default for every project until explicitly opted in
# (see the approved plan's staged-rollout section).

@router.get("/{project_id}/wiki-chapters")
def get_project_chapter_wiki_endpoint(project_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    chapter_set = get_current_chapter_set(project_id)
    if not chapter_set:
        return JSONResponse(status_code=404, content=AppError(
            message="No chapter wiki has been built for this project yet.", severity=ErrorSeverity.INFO,
        ).to_dict())
    return chapter_set


@router.post("/{project_id}/wiki-chapters/generate")
def generate_project_chapter_wiki_endpoint(project_id: int):
    """Synchronous core, mirroring generate_project_wiki_endpoint's shape.
    Exposed as its own route (same dual sync/async pattern as the flat
    wiki's /wiki/generate + /wiki/generate-job) for direct/test callers;
    the job runner below is what the UI should actually use, since chapter
    generation makes ~1 LLM call per top-level chapter rather than the flat
    pipeline's 1 call total and can run considerably longer."""
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    if not get_project_settings(project_id)["chapter_wiki_enabled"]:
        return JSONResponse(status_code=403, content=AppError(
            message="The multi-chapter wiki is not enabled for this project. Enable it in project settings first.",
            severity=ErrorSeverity.WARNING,
        ).to_dict())
    if not project["repos"]:
        return JSONResponse(status_code=502, content=AppError(
            message="No repositories are linked to this project. Link at least one before building a chapter wiki.",
            severity=ErrorSeverity.WARNING,
        ).to_dict())

    with ThreadPoolExecutor(max_workers=min(len(project["repos"]), 8)) as pool:
        repo_materials = list(pool.map(lambda repo: _collect_repo_wiki_material(repo, project_id), project["repos"]))

    material_error = _repository_material_error(repo_materials)
    if material_error:
        return JSONResponse(
            status_code=429 if "rate limit" in material_error.lower() else 502,
            content=AppError(message=material_error, severity=ErrorSeverity.WARNING).to_dict(),
        )

    provider = get_provider()
    try:
        chapter_set = generate_and_persist_chapter_wiki(provider, project_id, project["name"], repo_materials)
    except Exception as e:
        return _wiki_generation_error_response(e, f"building the chapter wiki for project {project_id}")
    if chapter_set is None:
        return JSONResponse(status_code=502, content=AppError(
            message="None of the linked repositories produced an indexable code structure — no chapter wiki was built.",
            severity=ErrorSeverity.WARNING,
        ).to_dict())
    log_info("Wiki", f"Generated chapter wiki for project {project_id}")
    return chapter_set


def _chapter_wiki_job_runner(payload: dict):
    project_id = int(payload["project_id"])
    yield "status", {"message": "Reading and indexing all linked repositories…"}
    response = generate_project_chapter_wiki_endpoint(project_id)
    if isinstance(response, JSONResponse):
        import json
        body = json.loads(response.body)
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        yield "error", {"message": error.get("message") or body.get("message", "Chapter wiki generation failed")}
        return
    yield "status", {"message": "Chapter tree persisted; narrating each chapter…"}
    yield "done", {"chapter_set": response}


configure_runner("chapter_wiki_generation", _chapter_wiki_job_runner)


@router.post("/{project_id}/wiki-chapters/generate-job", status_code=202)
def start_project_chapter_wiki_job(project_id: int):
    if not get_project(project_id):
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found").to_dict())
    return create_job("chapter_wiki_generation", {"project_id": project_id})


# ── Pull requests ────────────────────────────────────────────────────────
# PR listings come live from Bitbucket (source of truth for what's open);
# review status/findings come from the 'bitbucket_review' jobs the webhook
# (app/api/webhooks.py) and the manual trigger (app/api/bitbucket.py)
# schedule — see list_bitbucket_review_jobs's docstring for why jobs are the
# source of truth for review state rather than a separate table.

def _pr_summary(pr: dict, review: dict | None, security_job: dict | None = None) -> dict:
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
        # PR Impact Security Analysis — same _pr_security_scan_result shape
        # the GET .../security-scan/pr/{jobId} endpoint returns, embedded
        # here so a previously-run analysis survives a page refresh instead
        # of only living in the triggering component's local state (which
        # is wiped on remount). None when no such job has ever run for this
        # PR, same "not run yet" convention as review above.
        "security": _pr_security_scan_result(security_job) if security_job else None,
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
    security_scans = list_pr_security_scan_jobs(repo["id"])
    entry["pull_requests"] = [
        _pr_summary(pr, reviews.get(str(pr.get("id"))), security_scans.get(str(pr.get("id"))))
        for pr in prs
    ]
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

    pr_workers = max(1, int(os.getenv("BITBUCKET_PR_FETCH_WORKERS", "2")))
    with ThreadPoolExecutor(max_workers=min(len(project["repos"]), pr_workers)) as pool:
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
            "error": payload.get("error"),
        } for name, payload in seen_tools.items()]
    raw_findings = list(result.get("findings", [])) + list(result.get("scanner_findings", []))
    # One vulnerable package is commonly reported by Trivy, OSV and npm
    # audit. Collapse findings that share any CVE/GHSA identifier so the UI
    # presents remediation tasks rather than three copies of the same root
    # cause. Findings without identifiers retain their scanner fingerprint.
    findings = []
    identifier_owner: dict[str, int] = {}
    fingerprint_owner: dict[str, int] = {}
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        identifiers = {str(value) for value in finding.get("identifiers", []) if value}
        owners = {identifier_owner[value] for value in identifiers if value in identifier_owner}
        fingerprint = str(finding.get("fingerprint") or "")
        if not owners and fingerprint and fingerprint in fingerprint_owner:
            owners.add(fingerprint_owner[fingerprint])
        if owners:
            owner = min(owners)
            existing = findings[owner]
            merged_ids = sorted(set(existing.get("identifiers", [])) | identifiers)
            existing["identifiers"] = merged_ids
            tools = {value for value in str(existing.get("tool") or "").split(", ") if value}
            if finding.get("tool"):
                tools.add(str(finding["tool"]))
            existing["tool"] = ", ".join(sorted(tools))
            # Grouping (here, and again below for same-package advisories)
            # is a presentation dedup only — it must not make the reported
            # severity_counts undercount real, distinct advisories. Track
            # each raw finding's own severity through every merge so the
            # final count reflects actual CVE/GHSA volume, not box volume.
            existing.setdefault("_raw_severities", [existing.get("severity")]).append(finding.get("severity"))
        else:
            owner = len(findings)
            merged = dict(finding)
            merged["_raw_severities"] = [finding.get("severity")]
            findings.append(merged)
        for value in identifiers:
            identifier_owner[value] = owner
        if fingerprint:
            fingerprint_owner[fingerprint] = owner
    # Multiple advisories against the same package are still multiple rows
    # after the identifier merge above — one per distinct CVE/GHSA. Bundle
    # those into a single entry per package so the remediation queue reads
    # as one root cause instead of N near-duplicate cards. Grouped by
    # package ALONE, not package+fixed_version: different advisories for
    # the same package commonly carry different minimum fix versions
    # (e.g. brace-expansion's three DoS advisories require 5.0.7, 5.0.8,
    # and 1.1.18 respectively — different branches, not a typo), so forcing
    # an exact-version match here just produced separate boxes quoting
    # different "Required fix" numbers for the same package, which read as
    # contradictory. Every advisory's own fix version is preserved and
    # shown per-issue in the bundled root-cause text instead of collapsed
    # into one (possibly wrong) number.
    _SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    package_groups: dict[str, int] = {}
    bundled: list[dict] = []
    for finding in findings:
        package = str(finding.get("package") or "").strip().lower()
        if finding.get("category") != "dependency" or not package:
            bundled.append(finding)
            continue
        if package in package_groups:
            existing = bundled[package_groups[package]]
            existing["identifiers"] = sorted(set(existing.get("identifiers", [])) | set(finding.get("identifiers", [])))
            tools = {value for value in str(existing.get("tool") or "").split(", ") if value}
            if finding.get("tool"):
                tools.update(str(finding["tool"]).split(", "))
            existing["tool"] = ", ".join(sorted(tools))
            if _SEVERITY_RANK.get(finding.get("severity"), -1) > _SEVERITY_RANK.get(existing.get("severity"), -1):
                existing["severity"] = finding["severity"]
            issues = existing.setdefault("_bundled_issues", [(existing["comment"], existing.get("fixed_version"))])
            entry = (finding.get("comment"), finding.get("fixed_version"))
            if entry[0] and entry not in issues:
                issues.append(entry)
            existing.setdefault("_raw_severities", [existing.get("severity")]).extend(finding.get("_raw_severities") or [finding.get("severity")])
        else:
            package_groups[package] = len(bundled)
            merged = dict(finding)
            merged["_bundled_issues"] = [(finding["comment"], finding.get("fixed_version"))]
            merged.setdefault("_raw_severities", finding.get("_raw_severities") or [finding.get("severity")])
            bundled.append(merged)
    for finding in bundled:
        issues = finding.pop("_bundled_issues", None)
        if not issues:
            continue
        fix_versions = [version for _, version in issues if version]
        if len(issues) > 1:
            finding["comment"] = (
                f"{finding.get('package')} has {len(issues)} known issues:\n"
                + "\n".join(f"- {comment} (fix: {version or 'see advisory'})" for comment, version in issues)
            )
            # Different advisories for the same package can quote different
            # minimum fix versions (separate maintained major lines) —
            # dumping all of them as "the fix" just makes the reader guess.
            # Pick one concrete answer, same rule as vapt.py's
            # best_fix_version: match the installed major line when
            # possible, else the smallest jump; the rest stay visible as
            # alternatives, not as equally-valid instructions.
            chosen, all_versions = best_fix_version(finding.get("installed_version"), fix_versions)
            alternatives = [v for v in all_versions if v != chosen]
            if chosen and alternatives:
                finding["recommendation"] = f"Upgrade {finding.get('package')} to {chosen}. (Other maintained targets: {', '.join(alternatives)}.)"
            elif chosen:
                finding["recommendation"] = f"Upgrade {finding.get('package')} to {chosen}."
            finding["fixed_version"] = chosen or finding.get("fixed_version")
    findings = bundled
    for finding in findings:
        if finding.get("severity") not in {"critical", "high", "medium", "low"}:
            finding["severity"] = "medium"
    # Count every raw advisory bundled into each box, not one per box —
    # grouping is presentation only and must not make the reported severity
    # totals understate real exposure (four "high" CVEs merged into one
    # react-router card are still four "high" findings, not one).
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        raw_severities = finding.pop("_raw_severities", None) or [finding.get("severity")]
        finding["advisory_count"] = len(raw_severities)
        for severity in raw_severities:
            if severity not in severity_counts:
                severity = finding.get("severity")
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
            "project_id": project_id,
            "label": repo["label"] or repo["repo_slug"],
            "workspace": repo["workspace"],
            "repo_slug": repo["repo_slug"],
            "scan_branch": repo.get("scan_branch"),
        })
    except Exception as e:
        log_error("Projects", f"Failed to schedule security scan for repo {repo_id} on project {project_id}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=str(e)).to_dict())
    return job


# ── PR Impact Security Analysis ──────────────────────────────────────────
# Manual trigger + result retrieval for the PR-specific scan mode (see
# main.py's _stream_pr_security_scan for the orchestration and
# app/services/security/ for each stage). Deliberately separate from the
# existing Full Repository Scan endpoints above — same
# trigger-is-async/read-is-separate split, reusing the existing job system
# rather than a synchronous long-running request.

@router.post("/{project_id}/repos/{repo_id}/security-scan/pr", status_code=202)
def trigger_repo_pr_security_scan_endpoint(project_id: int, repo_id: int, request: PRSecurityScanRequest):
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
        job = create_job("pr_security_scan", {
            "repo_id": repo_id,
            "project_id": project_id,
            "workspace": repo["workspace"],
            "repo_slug": repo["repo_slug"],
            "pull_request_id": request.pull_request_id,
            "scan_branch": repo.get("scan_branch"),
        })
    except Exception as e:
        log_error("Projects", f"Failed to schedule PR security scan for PR #{request.pull_request_id} on repo {repo_id}", exception=e)
        return JSONResponse(status_code=500, content=AppError(message=str(e)).to_dict())
    # scan_id isn't known until the job actually runs (it's created inside
    # _stream_pr_security_scan, after PR metadata is fetched) — the result
    # endpoint below resolves it from the job's own recorded events/result,
    # same as how job status already works everywhere else in this app.
    return {"job_id": job["id"], "status": job["status"]}


def _pr_security_scan_result(job: dict | None) -> dict:
    """Assemble the retrieval response from a 'pr_security_scan' job row —
    live from job_events while queued/running, from the persisted
    security_scans/security_findings rows once the scan_id is known (the
    'done' event always carries it). Never makes the client parse job-event
    logs itself (PHASE 26)."""
    if not job:
        return {"status": "not_scanned"}
    result = job.get("result") or {}
    scan_id = result.get("scan_id")
    response: dict = {
        "job_id": job["id"], "status": job["status"], "error": job.get("error"),
        "updated_at": job.get("updated_at"),
    }
    if job["status"] in {"queued", "running"}:
        # Live progress from job_events, same pattern _security_summary uses.
        stages: dict[str, dict] = {}
        for event in list_events(job["id"]):
            if event["type"] == "status" and event["payload"].get("stage"):
                stages[event["payload"]["stage"]] = event["payload"]
        response["stages"] = list(stages.values())
        return response

    if not scan_id:
        # Job finished but never reached scan creation (e.g. failed before
        # PR metadata could be fetched) — nothing persisted to read back.
        return response

    scan = get_security_scan(scan_id)
    if not scan:
        return response
    findings = list_security_findings(scan_id)
    relation_counts: dict[str, int] = {}
    for finding in findings:
        relation = finding.get("relation_to_pr") or "UNRELATED"
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    response.update({
        "scan": scan,
        "pull_request_id": scan.get("pull_request_id"),
        # Plain-English "what did this PR do" — always present (falls back
        # to a deterministic summary when the LLM review failed/was
        # unavailable), independent of whether any finding was reported.
        # Prefer the job result (freshest); fall back to the persisted
        # scan's own metadata for a result read back without its job.
        "summary": result.get("summary") or (scan.get("metadata") or {}).get("summary"),
        "summary_source": result.get("summary_source") or (scan.get("metadata") or {}).get("summary_source"),
        "changed_files": result.get("changed_files"),
        "changed_symbols": result.get("changed_symbols"),
        "affected_files": result.get("affected_files"),
        "affected_symbols": result.get("affected_symbols"),
        "changed_symbols_detail": result.get("changed_symbols_detail", []),
        "affected_files_detail": result.get("affected_files_detail", []),
        "context_truncated": scan.get("context_truncated"),
        "graph_truncated": scan.get("graph_truncated"),
        "truncation_reasons": result.get("truncation_reasons", []),
        "llm_review_status": scan.get("llm_review_status"),
        "baseline": result.get("baseline"),
        "severity_counts": scan.get("severity_counts"),
        "findings_by_relation": relation_counts,
        "findings": findings,
        "duration_seconds": result.get("duration_seconds"),
    })
    return response


@router.get("/{project_id}/repos/{repo_id}/security-scan/pr/{job_id}")
def get_repo_pr_security_scan_endpoint(project_id: int, repo_id: int, job_id: str):
    project = get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content=AppError(message=f"Project {project_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    if not any(r["id"] == repo_id for r in project["repos"]):
        return JSONResponse(status_code=404, content=AppError(message=f"Repo {repo_id} not found on project {project_id}", severity=ErrorSeverity.WARNING).to_dict())

    job = get_job(job_id)
    if not job or job["kind"] != "pr_security_scan":
        return JSONResponse(status_code=404, content=AppError(message=f"PR security scan job {job_id} not found", severity=ErrorSeverity.WARNING).to_dict())
    return _pr_security_scan_result(job)
