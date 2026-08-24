from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.schemas.models import GenerationOutput


DEFAULT_BASE_URL = "https://api.bitbucket.org/2.0"

# Repo files are pulled into LLM prompt context (generation and, in Phase 3,
# the code-review agent) — an unbounded file would blow the ~8000-token
# completion budget the providers are capped at (app/services/providers.py)
# before the model even sees the brief. Same intent as TASKS_PER_TEST_BATCH
# in app/services/generators.py: keep each unit of context small enough that
# one call comfortably fits it.
MAX_FILE_BYTES = 200_000


def validate_bitbucket_url(raw_url: str) -> str:
    """Validate and normalize a user-supplied Bitbucket origin.

    Near-verbatim copy of redmine/client.py's validate_redmine_url — Bitbucket
    calls originate from this backend too, so an unvalidated URL is the same
    SSRF primitive. Kept as a separate function rather than a shared helper
    so a bug in one integration's validation can't silently affect the other
    (see the plan's "duplicates, not shares" cross-cutting decision).
    """
    value = str(raw_url or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Bitbucket URL must use http:// or https://")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Bitbucket URL must be an origin without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Bitbucket URL must not contain a query string or fragment")

    production = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
    allow_private_default = "false" if production else "true"
    allow_private = os.getenv("ALLOW_PRIVATE_BITBUCKET_URLS", allow_private_default).strip().lower() == "true"
    if production and parsed.scheme != "https" and not allow_private:
        raise ValueError("Bitbucket URL must use HTTPS in production")

    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ValueError("Bitbucket hostname could not be resolved") from exc

    if not allow_private and any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("Bitbucket URL resolves to a private or restricted network address")

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


class BitbucketConfig:
    """Bitbucket Cloud connection settings. Mirrors redmine/client.py's
    RedmineConfig — env-var-backed, with is_configured()-gated graceful
    degradation everywhere this is used (never a hard failure just because
    Bitbucket isn't set up)."""

    def __init__(
        self,
        base_url: str = "",
        workspace: str = "",
        repo_slug: str = "",
        access_token: str = "",
    ):
        self.base_url = (base_url or os.getenv("BITBUCKET_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.workspace = workspace or os.getenv("BITBUCKET_WORKSPACE", "")
        self.repo_slug = repo_slug or os.getenv("BITBUCKET_REPO_SLUG", "")
        self.access_token = access_token or os.getenv("BITBUCKET_ACCESS_TOKEN", "")

    @classmethod
    def from_env(cls) -> "BitbucketConfig":
        return cls(
            base_url=os.getenv("BITBUCKET_BASE_URL", DEFAULT_BASE_URL),
            workspace=os.getenv("BITBUCKET_WORKSPACE", ""),
            repo_slug=os.getenv("BITBUCKET_REPO_SLUG", ""),
            access_token=os.getenv("BITBUCKET_ACCESS_TOKEN", ""),
        )

    def is_configured(self) -> bool:
        return bool(self.base_url and self.workspace and self.repo_slug and self.access_token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _repo_url(self, *parts: str) -> str:
        segments = "/".join(str(p).strip("/") for p in parts if p)
        return f"{self.base_url}/repositories/{self.workspace}/{self.repo_slug}" + (f"/{segments}" if segments else "")


def _extract_bitbucket_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
        elif error:
            return str(error)

    text = response.text.strip()
    return text or f"HTTP {response.status_code}"


# ── Read-only functions (Phase 1) ───────────────────────────────────────────
# Same style as redmine/client.py: plain module-level functions taking an
# explicit config, best-effort where a miss is acceptable (return [] / {}),
# raising RuntimeError with the extracted API error where it isn't.

def get_repo_metadata(config: BitbucketConfig) -> dict:
    """Fetch the configured repo's own metadata — used as a connectivity/
    config health-check the same way describe_redmine_workspace is."""
    response = httpx.get(config._repo_url(), headers=config._headers(), timeout=15)
    if response.is_error:
        raise RuntimeError(f"Bitbucket repo lookup failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    return response.json()


def list_repo_files(config: BitbucketConfig, path: str = "", ref: str = "HEAD") -> list[dict]:
    """List the tree at `path` (empty = repo root) at the given ref/branch."""
    url = config._repo_url("src", ref, path.strip("/"))
    entries: list[dict[str, Any]] = []
    params: dict[str, Any] = {"pagelen": 100}
    while url:
        response = httpx.get(url, headers=config._headers(), params=params, timeout=15)
        if response.is_error:
            raise RuntimeError(f"Bitbucket file listing failed ({response.status_code}): {_extract_bitbucket_error(response)}")
        data = response.json()
        entries.extend(data.get("values", []))
        url = data.get("next")
        params = {}  # `next` is already a fully-formed URL with its own query string
    return entries


def get_file_content(config: BitbucketConfig, path: str, ref: str = "HEAD") -> str:
    """Fetch one file's raw content, truncated at MAX_FILE_BYTES so a large
    generated/vendored file can't blow the prompt budget of whatever agent
    consumes it (see the module docstring's MAX_FILE_BYTES note)."""
    url = config._repo_url("src", ref, path.strip("/"))
    response = httpx.get(url, headers=config._headers(), timeout=15)
    if response.is_error:
        raise RuntimeError(f"Bitbucket file fetch failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    content = response.text
    if len(content.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
        content = content.encode("utf-8", errors="ignore")[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
        content += "\n\n… [truncated]"
    return content


def get_pull_request(config: BitbucketConfig, pr_id: int | str) -> dict:
    url = config._repo_url("pullrequests", str(pr_id))
    response = httpx.get(url, headers=config._headers(), timeout=15)
    if response.is_error:
        raise RuntimeError(f"Bitbucket PR lookup failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    return response.json()


def get_pull_request_diff(config: BitbucketConfig, pr_id: int | str) -> str:
    url = config._repo_url("pullrequests", str(pr_id), "diff")
    response = httpx.get(url, headers=config._headers(), timeout=20)
    if response.is_error:
        raise RuntimeError(f"Bitbucket PR diff fetch failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    return response.text


def list_pull_request_comments(config: BitbucketConfig, pr_id: int | str) -> list[dict]:
    url = config._repo_url("pullrequests", str(pr_id), "comments")
    comments: list[dict[str, Any]] = []
    params: dict[str, Any] = {"pagelen": 100}
    while url:
        response = httpx.get(url, headers=config._headers(), params=params, timeout=15)
        if response.is_error:
            raise RuntimeError(f"Bitbucket PR comments fetch failed ({response.status_code}): {_extract_bitbucket_error(response)}")
        data = response.json()
        comments.extend(data.get("values", []))
        url = data.get("next")
        params = {}
    return comments


# ── Write functions (Phase 3) ───────────────────────────────────────────────

def post_pr_comment(config: BitbucketConfig, pr_id: int | str, body: str, inline: dict | None = None) -> dict:
    """Post one comment on a PR. `inline` = {"path": ..., "line": ...} for a
    line-anchored comment; omitted for a general PR comment."""
    payload: dict[str, Any] = {"content": {"raw": body}}
    if inline:
        payload["inline"] = inline
    url = config._repo_url("pullrequests", str(pr_id), "comments")
    response = httpx.post(
        url,
        json=payload,
        headers={**config._headers(), "Content-Type": "application/json"},
        timeout=15,
    )
    if response.is_error:
        raise RuntimeError(f"Bitbucket PR comment failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    return response.json()


def create_bitbucket_issue(
    config: BitbucketConfig,
    title: str,
    description: str = "",
    kind: str = "task",
    priority: str = "minor",
) -> dict:
    """Create one ad-hoc Bitbucket issue — the issue tracker must be enabled
    on the repo (Bitbucket returns 404 on this endpoint otherwise)."""
    payload = {
        "title": title,
        "content": {"raw": description},
        "kind": kind,
        "priority": priority,
    }
    url = config._repo_url("issues")
    response = httpx.post(
        url,
        json=payload,
        headers={**config._headers(), "Content-Type": "application/json"},
        timeout=15,
    )
    if response.is_error:
        raise RuntimeError(f"Bitbucket issue create failed ({response.status_code}): {_extract_bitbucket_error(response)}")
    return response.json()


# Priority labels this app uses (critical/high/medium/low) don't exist on
# Bitbucket's issue tracker (trivial/minor/major/critical/blocker) — map the
# closest equivalent rather than passing an invalid value straight through.
_BITBUCKET_PRIORITY_MAP = {
    "critical": "blocker",
    "high": "major",
    "medium": "minor",
    "low": "trivial",
}


def push_backlog_to_bitbucket(
    output: GenerationOutput,
    config: BitbucketConfig,
    existing_issue_ids: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Push missing backlog items to Bitbucket's issue tracker. Structurally
    mirrors redmine/client.py's push_to_redmine: same created/skipped/
    warnings result shape, same per-item try/except-and-continue so one
    failure doesn't abort the sync. Unlike Redmine, Bitbucket issues have no
    native parent/child linking — epic/story/task hierarchy is represented
    as a "Parent: [S-0012] ..." backlink in the issue description instead.
    """
    if not config.is_configured():
        raise ValueError(
            "Bitbucket not configured. Set BITBUCKET_BASE_URL, BITBUCKET_WORKSPACE, "
            "BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN in .env"
        )

    existing_issue_ids = existing_issue_ids or {}
    created_issues: list[dict] = []
    skipped_issues: list[dict] = []
    warnings: list[str] = []

    def already_synced(item_type: str, ai_id: str) -> str | None:
        return existing_issue_ids.get(item_type, {}).get(ai_id)

    def record_skipped(item_type: str, ai_id: str, issue_id: str) -> None:
        skipped_issues.append({
            "ai_id": ai_id, "type": item_type, "bitbucket_id": issue_id,
            "url": f"{config.base_url}/repositories/{config.workspace}/{config.repo_slug}/issues/{issue_id}",
            "status": "skipped", "reason": "Already synced to this Bitbucket repo",
        })

    def create_and_record(item_type: str, ai_id: str, display_id: str, title: str, description: str, priority: str) -> None:
        try:
            issue = create_bitbucket_issue(
                config, title=f"[{display_id}] {title}", description=description,
                priority=_BITBUCKET_PRIORITY_MAP.get(priority, "minor"),
            )
            issue_id = str(issue.get("id"))
            created_issues.append({
                "ai_id": ai_id, "display_id": display_id, "type": item_type,
                "bitbucket_id": issue_id,
                "url": f"{config.base_url}/repositories/{config.workspace}/{config.repo_slug}/issues/{issue_id}",
                "status": "created",
            })
        except Exception as e:
            created_issues.append({"ai_id": ai_id, "display_id": display_id, "type": item_type, "error": str(e)})

    for epic in output.epics:
        existing_id = already_synced("epic", epic.id)
        if existing_id:
            record_skipped("epic", epic.id, existing_id)
            continue
        create_and_record(
            "epic", epic.id, epic.id, epic.title,
            f"{epic.description}\n\nFeature Area: {epic.feature_area}",
            epic.priority,
        )

    for story in output.stories:
        existing_id = already_synced("story", story.id)
        if existing_id:
            record_skipped("story", story.id, existing_id)
            continue
        ac_text = "\n".join(f"- {ac}" for ac in story.acceptance_criteria)
        description = (
            f"As a {story.as_a}\nI want {story.i_want}\nSo that {story.so_that}\n\n"
            f"Acceptance Criteria:\n{ac_text}\n\n"
            + (f"Parent: [{story.epic_id}]" if story.epic_id else "")
        )
        create_and_record("story", story.id, story.id, story.title, description, story.priority)

    for task in output.tasks:
        existing_id = already_synced("task", task.id)
        if existing_id:
            record_skipped("task", task.id, existing_id)
            continue
        deps_text = ", ".join(task.dependencies) if task.dependencies else "None"
        description = (
            f"{task.description}\n\nDefinition of Done: {task.definition_of_done}\n"
            f"Dependencies: {deps_text}\n\n"
            + (f"Parent: [{task.story_id}]" if task.story_id else "")
        )
        create_and_record("task", task.id, task.id, task.title, description, task.priority)

    result = {"created_issues": created_issues, "skipped_issues": skipped_issues}
    if skipped_issues:
        warnings.append(f"Skipped {len(skipped_issues)} item(s) already synced to this repo.")
    if warnings:
        result["warnings"] = warnings
    return result


def build_repo_context_block(config: BitbucketConfig, path: str = "", ref: str = "HEAD", max_files: int = 15) -> str:
    """Bounded-size 'Repository Context' text block (file tree + a handful
    of file snippets) for feeding into generation as extra brief context —
    the Phase 1c hook GenerateRequest.bitbucket_repo triggers. Best-effort:
    any failure here degrades to an empty string rather than blocking
    generation, matching is_configured()'s graceful-degradation pattern."""
    if not config.is_configured():
        return ""
    try:
        entries = list_repo_files(config, path=path, ref=ref)
    except Exception:
        return ""

    file_paths = [e.get("path", "") for e in entries if e.get("type") == "commit_file"][:max_files]
    if not file_paths:
        return ""

    lines = ["## Repository Context", "", "Files:"]
    lines.extend(f"- {p}" for p in file_paths)
    return "\n".join(lines)
