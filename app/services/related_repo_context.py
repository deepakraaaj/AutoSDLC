"""Diff-aware context from a *related* repository (a project's second/third
linked repo — e.g. a backend for a PR touching only the frontend) for the
Bitbucket PR code-review path (main.py's _stream_bitbucket_review).

Deliberately clone-then-grep, not an API file-walk: build_repo_context_block
(bitbucket/client.py) fetches file trees and content one Bitbucket REST call
at a time, which is fine for its original one-repo generic-brief use case but
turns into O(files) API calls once you need to search file *content* for
diff-derived terms across a second repo — exactly the kind of burst that
trips Bitbucket's rate limits. A single `git clone`/`git fetch` is one
network op regardless of repo size, so this module clones each related repo
once and searches the resulting local working tree with plain string
matching — no embeddings, no semantic search.

Persistent, not ephemeral: each related repo gets a real, permanent working
clone on disk (_repo_dir), kept in sync with `git fetch` + fast-forward
before every use (_sync_repo) rather than re-cloned from scratch each
review or expired on a TTL. A repo under active review pays a full clone
exactly once; every later review just fetches whatever changed since. A
per-key lock keeps concurrent reviews on the same repo from fetching it
twice in parallel. There is no time-based eviction — a clone is only ever
removed by evict_repo_cache, called when a repo is unlinked from a project
(app/api/projects.py's delete endpoint), since that is the only point at
which "no project can possibly need this again" is actually knowable."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path

from app.services.vapt import _clone_url, _git_environment
from app.utils.error_handler import log_warning
from bitbucket.client import BitbucketConfig

# Same ignore list spirit as create_repository_snapshot's REST fallback and
# bitbucket/client.py's _IGNORED_REPO_DIRECTORIES — generated/vendor trees
# are large, never hand-authored, and never what a diff term should match.
_IGNORED_DIRECTORIES = {".git", "node_modules", "dist", "build", ".venv", "vendor", "target", "__pycache__"}
_MAX_FILE_BYTES = 500_000  # skip anything large enough to not be hand-authored source
MAX_MATCHED_FILES = 6
SNIPPET_LINES_OF_CONTEXT = 4
GIT_TIMEOUT_SECONDS = max(30, int(os.getenv("RELATED_REPO_GIT_TIMEOUT_SECONDS", "120")))

# Same override pattern as app/services/database.py's DB_PATH: an env var
# for deployments that want the cache elsewhere (e.g. a mounted volume),
# defaulting to a path relative to this package.
CACHE_DIR = Path(os.getenv("RELATED_REPO_CACHE_DIR") or (Path(__file__).parent / "related_repo_cache"))

_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


def _repo_key(workspace: str, repo_slug: str) -> str:
    # Hash rather than use workspace/repo_slug as a path directly — slugs
    # can contain characters that aren't safe/portable as directory names,
    # and hashing sidesteps that entirely rather than trying to sanitize it.
    # Keyed by repo only (not branch): one persistent clone per repo, with
    # branch selected via checkout at use time — a second, separate clone
    # per branch would defeat the point of not re-cloning.
    return hashlib.sha256(f"{workspace}/{repo_slug}".encode()).hexdigest()[:24]


def _repo_dir(workspace: str, repo_slug: str) -> Path:
    return CACHE_DIR / _repo_key(workspace, repo_slug)


def _lock_for(key: str) -> threading.Lock:
    with _repo_locks_guard:
        return _repo_locks.setdefault(key, threading.Lock())


def _run(command: list[str], *, cwd: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=cwd, env=env, timeout=GIT_TIMEOUT_SECONDS, check=False,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _sync_repo(config: BitbucketConfig, branch: str | None) -> Path:
    """Ensures a persistent, up-to-date working clone of config's repo
    exists on disk and returns its path. First call for a repo does a full
    clone; every later call does a fetch + fast-forward reset instead of
    re-cloning — the whole point of keeping this around across reviews."""
    repo_dir = _repo_dir(config.workspace, config.repo_slug)
    env = _git_environment(config, str(repo_dir.parent))
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not (repo_dir / ".git").is_dir():
        # First time seeing this repo: clone into a staging path and
        # atomically swap it in, so a concurrent reader elsewhere never
        # sees a half-written clone.
        staging = repo_dir.parent / f"{repo_dir.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        shutil.rmtree(staging, ignore_errors=True)
        clone_command = ["git", "clone", "--no-tags"]
        if branch:
            clone_command += ["--branch", branch]
        result = _run([*clone_command, _clone_url(config), str(staging)], cwd=str(repo_dir.parent), env=env)
        if result.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError(f"git clone failed: {(result.stderr or result.stdout).strip()[-500:]}")
        shutil.rmtree(repo_dir, ignore_errors=True)
        staging.rename(repo_dir)
        return repo_dir

    # Already cloned: fetch + fast-forward whatever branch is checked out
    # (or the requested one) instead of re-cloning. A failed fetch (offline,
    # token revoked, repo renamed) leaves the existing clone in place and
    # still searchable — degraded/stale context beats none.
    fetch = _run(["git", "fetch", "--prune", "origin"], cwd=str(repo_dir), env=env)
    if fetch.returncode != 0:
        log_warning(
            "RelatedRepoContext",
            f"git fetch failed for {config.workspace}/{config.repo_slug}, using existing clone as-is: "
            f"{(fetch.stderr or fetch.stdout).strip()[-300:]}",
        )
        return repo_dir

    target_ref = f"origin/{branch}" if branch else "origin/HEAD"
    checkout = _run(["git", "checkout", "-B", branch or "HEAD-tracking", target_ref], cwd=str(repo_dir), env=env)
    if checkout.returncode != 0 and branch:
        # Branch may not exist on origin (e.g. a scan_branch that was
        # renamed/deleted) — fall back to the repo's default branch rather
        # than failing the whole lookup.
        _run(["git", "checkout", "-B", "HEAD-tracking", "origin/HEAD"], cwd=str(repo_dir), env=env)
    return repo_dir


def evict_repo_cache(workspace: str, repo_slug: str) -> None:
    """Removes a repo's persistent clone. Call this when a repo is unlinked
    from every project it was linked to (app/api/projects.py's delete-repo
    endpoint) — that is the only point at which "no review can possibly
    need this again" is actually true, since there is no time-based
    expiry otherwise."""
    shutil.rmtree(_repo_dir(workspace, repo_slug), ignore_errors=True)


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRECTORIES for part in path.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _grep(root: Path, terms: list[str], max_files: int) -> list[tuple[str, str]]:
    """Plain substring search (case-insensitive) across the snapshot's
    files. Returns (relative_path, snippet) for the first max_files files
    that match any term, snippet built from the first matching line plus a
    little surrounding context — enough for the LLM to see real usage, not
    the whole file."""
    lowered_terms = [t.lower() for t in terms if t]
    if not lowered_terms:
        return []
    results: list[tuple[str, str]] = []
    for path in _iter_source_files(root):
        if len(results) >= max_files:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower_text = text.lower()
        if not any(term in lower_text for term in lowered_terms):
            continue
        lines = text.splitlines()
        hit_line = next(
            (i for i, line in enumerate(lines) if any(term in line.lower() for term in lowered_terms)),
            0,
        )
        start = max(0, hit_line - SNIPPET_LINES_OF_CONTEXT)
        end = min(len(lines), hit_line + SNIPPET_LINES_OF_CONTEXT + 1)
        numbered = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        results.append((str(path.relative_to(root)), numbered))
    return results


def build_related_repo_context_block(
    config: BitbucketConfig, terms: list[str], *, label: str = "", branch: str | None = None,
    max_files: int = MAX_MATCHED_FILES,
) -> str:
    """A persistent local clone of config's repo (cloned once, fetched
    thereafter — see _sync_repo), grepped locally for `terms`. Best-effort
    like build_repo_context_block: any failure (auth, network, no matches)
    degrades to an empty string rather than blocking the PR review it feeds
    into."""
    if not config.is_configured() or not terms:
        return ""
    key = _repo_key(config.workspace, config.repo_slug)
    try:
        with _lock_for(key):
            source = _sync_repo(config, branch)
        matches = _grep(source, terms, max_files)
    except Exception as e:
        log_warning("RelatedRepoContext", f"Sync/grep failed for {config.workspace}/{config.repo_slug}: {e}")
        return ""
    if not matches:
        return ""
    repo_label = label or f"{config.workspace}/{config.repo_slug}"
    lines = [f"## Related repository: {repo_label}", f"(matched on: {', '.join(terms[:8])})"]
    for path, snippet in matches:
        lines.append(f"\n--- {path} ---")
        lines.append(snippet)
    return "\n".join(lines)
