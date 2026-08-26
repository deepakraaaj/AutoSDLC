"""Deterministic VAPT scanner orchestration.

Repository source is fetched into an isolated temporary snapshot without a
working-tree checkout, so repository hooks, filters, and package lifecycle
scripts are never executed. Scanner adapters are read-only and bounded by
timeouts. Missing tools are reported explicitly rather than treated as a
clean scan.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Iterator
from urllib.parse import urlsplit

from bitbucket.client import BitbucketConfig
from bitbucket.client import get_file_content, list_repo_files


SCANNERS = ("semgrep", "gitleaks", "trivy", "osv-scanner", "eslint", "npm-audit", "pip-audit")
SCANNER_TIMEOUT_SECONDS = max(30, int(os.getenv("VAPT_SCANNER_TIMEOUT_SECONDS", "300")))
SNAPSHOT_TIMEOUT_SECONDS = max(30, int(os.getenv("VAPT_SNAPSHOT_TIMEOUT_SECONDS", "180")))
MAX_SNAPSHOT_FILES = max(100, int(os.getenv("VAPT_MAX_SNAPSHOT_FILES", "10000")))
MAX_SNAPSHOT_BYTES = max(1_000_000, int(os.getenv("VAPT_MAX_SNAPSHOT_BYTES", "100000000")))
# Bounded, not unlimited: the REST-API snapshot fallback (git-over-HTTPS auth
# unavailable) fetches one file per request, and too much concurrency just
# trades a slow scan for a thundering-herd 429 from Bitbucket. Individual
# 429s are retried with backoff (bitbucket.client._get_with_rate_limit_retry)
# — this cap keeps the herd small enough for that backoff to actually help.
SNAPSHOT_FETCH_WORKERS = max(1, int(os.getenv("VAPT_SNAPSHOT_FETCH_WORKERS", "4")))
_WIKI_SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".dart", ".go", ".graphql", ".h", ".hpp",
    ".html", ".java", ".js", ".json", ".jsx", ".kt", ".kts", ".md", ".php", ".proto",
    ".py", ".rb", ".rs", ".scss", ".sh", ".sql", ".svelte", ".swift", ".toml", ".ts",
    ".tsx", ".vue", ".xml", ".yaml", ".yml",
}
_WIKI_SOURCE_NAMES = {
    "dockerfile", "gemfile", "makefile", "procfile", "requirements.txt",
}

def _which(name: str) -> str | None:
    """Find tools even when uvicorn was launched without activating venv."""
    return shutil.which(name) or (str(Path(sys.prefix) / "bin" / name) if (Path(sys.prefix) / "bin" / name).exists() else None)


def scanner_capabilities(source: Path | None = None) -> list[dict]:
    files = {p.name for p in source.rglob("*") if p.is_file()} if source else set()
    # ESLint loads JavaScript configuration files, which is executable
    # repository code. Keep it disabled unless an operator explicitly trusts
    # the repository and opts in; the other scanners remain non-executing.
    eslint_opted_in = os.getenv("VAPT_ALLOW_ESLINT_CONFIG", "false").lower() == "true"
    has_eslint_config = any(name in files for name in ("eslint.config.js", "eslint.config.mjs", ".eslintrc", ".eslintrc.js", ".eslintrc.json"))
    executables = {"npm-audit": "npm", "pip-audit": "pip-audit"}
    capabilities = []
    for tool in SCANNERS:
        installed = _which(executables.get(tool, tool)) is not None or (tool in {"gitleaks", "trivy", "osv-scanner"} and _which("docker") is not None)
        status, reason = "available", None
        if tool == "npm-audit" and "package-lock.json" not in files:
            status, reason = "not_applicable", "No package-lock.json was found in this repository snapshot."
        elif tool == "pip-audit" and "requirements.txt" not in files:
            status, reason = "not_applicable", "No requirements.txt was found in this repository snapshot."
        elif tool == "eslint" and not has_eslint_config:
            status, reason = "not_applicable", "No supported ESLint configuration was found in this repository snapshot."
        elif tool == "eslint" and not eslint_opted_in:
            status, reason = "disabled", "Disabled because repository ESLint configuration can execute code. Set VAPT_ALLOW_ESLINT_CONFIG=true only for trusted repositories."
        elif not installed:
            status, reason = "unavailable", f"{executables.get(tool, tool)} is not installed and no supported container runtime fallback is available."
        capabilities.append({"tool": tool, "available": status == "available", "status": status, "reason": reason})
    return capabilities


def _clone_url(config: BitbucketConfig) -> str:
    parsed = urlsplit(config.base_url)
    if parsed.hostname == "api.bitbucket.org":
        return f"https://bitbucket.org/{config.workspace}/{config.repo_slug}.git"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/scm/{config.workspace}/{config.repo_slug}.git"


def _git_environment(config: BitbucketConfig, isolated_home: str) -> dict[str, str]:
    # Git-over-HTTPS does not consistently honor an Authorization extraHeader
    # during Bitbucket's authentication challenge/redirect flow. Supplying a
    # non-interactive credential helper lets Git answer that challenge without
    # putting the token in the clone URL, argv, or logs. For bearer-style repo
    # tokens Bitbucket accepts the conventional ``x-token-auth`` username.
    credential_helper = (
        '!f() { if [ "$1" = get ]; then '
        'printf "%s\\n" "username=$AUTOSDLC_BITBUCKET_GIT_IDENTITY" '
        '"password=$AUTOSDLC_BITBUCKET_GIT_TOKEN"; fi; }; f'
    )
    git_identity = os.getenv("BITBUCKET_GIT_USERNAME", "").strip()
    if not git_identity:
        # Atlassian API tokens (the ATATT... form) use this fixed identity for
        # Git, even though the REST API uses account-email Basic auth.
        git_identity = "x-bitbucket-api-token-auth" if config.access_token.startswith("ATATT") else (config.email or "x-token-auth")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": isolated_home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": credential_helper,
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
        "AUTOSDLC_BITBUCKET_GIT_IDENTITY": git_identity,
        "AUTOSDLC_BITBUCKET_GIT_TOKEN": config.access_token,
    }
    return env


def _run(command: list[str], *, cwd: str | None = None, env: dict | None = None, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=cwd, env=env, timeout=timeout, check=False,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _safe_extract(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int = MAX_SNAPSHOT_FILES,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
    strict_limits: bool = True,
) -> None:
    total_files = 0
    total_bytes = 0
    root = destination.resolve()
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or member.isdev():
                continue
            parts = Path(member.name).parts
            if any(part.lower() in {".git", "node_modules", "dist", "build", ".venv", "vendor", "target"} for part in parts[:-1]):
                continue
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("Repository archive attempted path traversal")
            if member.isfile():
                member_bytes = max(member.size, 0)
                if not strict_limits:
                    name = Path(member.name).name.lower()
                    suffix = Path(name).suffix.lower()
                    if (suffix not in _WIKI_SOURCE_SUFFIXES and name not in _WIKI_SOURCE_NAMES) or member_bytes > 1_000_000:
                        continue
                if total_files + 1 > max_files or total_bytes + member_bytes > max_bytes:
                    if strict_limits:
                        raise RuntimeError("Repository snapshot exceeds configured safety limits")
                    continue
                total_files += 1
                total_bytes += member_bytes
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source:
                    with target.open("wb") as output:
                        shutil.copyfileobj(source, output)


def create_repository_snapshot(
    config: BitbucketConfig,
    destination: Path,
    branch: str | None = None,
    timeout_seconds: int | None = None,
    *,
    commit_sha: str | None = None,
    max_files: int = MAX_SNAPSHOT_FILES,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
    strict_limits: bool = True,
) -> str:
    """Create a source snapshot and return the exact scanned commit hash.

    ``branch`` pins the scan to a specific branch (e.g. a repo whose
    Bitbucket-configured default branch is stale/near-empty) — falls back
    to the repo's own default branch (bare clone's HEAD; ``BITBUCKET_BRANCH``
    or ``master`` for the REST fallback) when unset.

    ``commit_sha`` pins the scan to one exact commit (PR impact analysis
    needs the PR's recorded head_commit_sha, which the source branch's tip
    may have already moved past by the time the scan runs) rather than
    "whatever HEAD/branch currently resolves to". When set, ``branch`` is
    still used as a hint for the initial shallow clone (the commit is
    normally that branch's recent history), but the archived/returned
    revision is always ``commit_sha`` itself — with one deepening re-fetch
    attempt if the shallow clone's single commit isn't it."""
    timeout_limit = timeout_seconds if timeout_seconds is not None else SNAPSHOT_TIMEOUT_SECONDS
    bare_repo = destination.parent / "repo.git"
    archive_path = destination.parent / "source.tar"
    env = _git_environment(config, str(destination.parent))
    clone_command = ["git", "clone", "--bare", "--depth", "1", "--no-tags"]
    if branch:
        clone_command += ["--branch", branch, "--single-branch"]
    clone = _run(
        [*clone_command, _clone_url(config), str(bare_repo)],
        env=env, timeout=timeout_limit,
    )
    if clone.returncode != 0:
        # Bitbucket access tokens are valid for the REST API but are not
        # universally accepted by Git-over-HTTPS. Fall back to an API-only
        # materialization; it never invokes Git hooks or package scripts.
        destination.mkdir(parents=True, exist_ok=True)
        # Bitbucket's ``HEAD`` ref is not accepted by the source API for all
        # repositories (notably repositories whose default branch is
        # ``master``). Resolve an explicit ref for the REST fallback — an
        # exact commit_sha (Bitbucket's src API accepts a full commit hash
        # as a revision, same as a branch name) takes priority when given.
        ref = commit_sha or branch or os.getenv("BITBUCKET_BRANCH", "master")
        queue = [""]
        seen_dirs = {""}
        paths: list[str] = []
        # Unlike the git-clone path above, nothing here was otherwise bounded
        # by SNAPSHOT_TIMEOUT_SECONDS — a large repo tree walked and fetched
        # one HTTP request at a time (worse under Bitbucket's rate limiting,
        # observed in practice pushing a scan past 5+ minutes) could run
        # indefinitely. One shared deadline covers both phases below.
        fallback_deadline = time.monotonic() + timeout_limit
        while queue and len(paths) < MAX_SNAPSHOT_FILES and time.monotonic() < fallback_deadline:
            path = queue.pop(0)
            # Wiki/VAPT snapshot callers already own an overall deadline.
            # Do not spend up to 30 seconds backing off for every directory
            # in a rate-limited repository; surface the 429 immediately so
            # the job can report an actionable failure to the UI.
            entries = list_repo_files(config, path=path, ref=ref, max_attempts=1)
            for entry in entries:
                item = str(entry.get("path") or "").strip("/")
                if not item:
                    continue
                if entry.get("type") == "commit_directory":
                    name = item.rsplit("/", 1)[-1].lower()
                    if name not in {".git", "node_modules", "dist", "build", ".venv", "vendor", "target"} and item not in seen_dirs:
                        seen_dirs.add(item)
                        queue.append(item)
                elif entry.get("type") == "commit_file":
                    paths.append(item)
                    if len(paths) >= MAX_SNAPSHOT_FILES:
                        break

        def _fetch(item: str) -> bytes | None:
            # Best-effort per file: one file Bitbucket won't serve (rate
            # limited past _get_with_rate_limit_retry's own retries, a
            # transient error, whatever) shouldn't sink the whole snapshot —
            # skip it and keep the rest, same spirit as the directory walk's
            # ignored-folder list above.
            try:
                return get_file_content(config, item, ref=ref, max_attempts=2).encode("utf-8", errors="ignore")[:MAX_SNAPSHOT_BYTES]
            except Exception:
                return None

        total_bytes = 0
        pool = ThreadPoolExecutor(max_workers=min(SNAPSHOT_FETCH_WORKERS, len(paths)) or 1)
        try:
            futures = {pool.submit(_fetch, item): item for item in paths}
            try:
                for future in as_completed(futures, timeout=max(fallback_deadline - time.monotonic(), 0)):
                    item = futures[future]
                    raw = future.result()
                    if raw is None:
                        continue
                    total_bytes += len(raw)
                    if total_bytes > MAX_SNAPSHOT_BYTES:
                        break
                    target = destination / item
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
            except FutureTimeoutError:
                # Deadline hit mid-fetch — keep whatever landed on disk so
                # far rather than block until every last file finishes
                # (Bitbucket rate-limiting alone has run this past 15+
                # minutes in practice); still a real, if partial, snapshot.
                pass
        finally:
            # Do not use the executor as a context manager here: __exit__
            # performs shutdown(wait=True), which previously made the nominal
            # snapshot deadline meaningless while rate-limited requests and
            # queued files continued for many minutes.
            pool.shutdown(wait=False, cancel_futures=True)
        if not any(destination.rglob("*")):
            raise RuntimeError(f"Repository snapshot failed: {(clone.stderr or clone.stdout).strip()[-500:]}")
        return commit_sha if commit_sha else f"{ref} (Bitbucket API snapshot)"
    target_ref = commit_sha or "HEAD"
    revision = _run(["git", "rev-parse", "--verify", f"{target_ref}^{{commit}}"], cwd=str(bare_repo), env=env, timeout=30)
    if revision.returncode != 0 and commit_sha:
        # The shallow clone's one commit isn't the exact SHA the PR recorded
        # as its head (the branch moved on since) — fetch that commit
        # directly rather than silently scanning the wrong revision.
        fetch = _run(
            ["git", "fetch", "--depth", "1", "--no-tags", _clone_url(config), commit_sha],
            cwd=str(bare_repo), env=env, timeout=timeout_limit,
        )
        if fetch.returncode == 0:
            revision = _run(["git", "rev-parse", "--verify", f"{commit_sha}^{{commit}}"], cwd=str(bare_repo), env=env, timeout=30)
    if revision.returncode != 0:
        raise RuntimeError(f"Could not resolve repository commit {target_ref!r}")
    resolved_sha = revision.stdout.strip()
    with archive_path.open("wb") as output:
        archive = subprocess.run(
            ["git", "archive", "--format=tar", resolved_sha], cwd=str(bare_repo), env=env,
            timeout=timeout_limit, check=False, stdout=output, stderr=subprocess.PIPE,
        )
    if archive.returncode != 0:
        raise RuntimeError("Could not create safe repository archive")
    destination.mkdir(parents=True, exist_ok=True)
    _safe_extract(
        archive_path, destination, max_files=max_files, max_bytes=max_bytes,
        strict_limits=strict_limits,
    )
    return resolved_sha


def _severity(value: str | None) -> str:
    normalized = str(value or "medium").lower()
    aliases = {"error": "high", "warning": "medium", "warn": "medium", "info": "low", "unknown": "medium"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"critical", "high", "medium", "low"} else "medium"


# Each scanner reports the same advisory ID in a different shape —
# npm-audit gives a full GitHub advisory URL, osv-scanner/trivy give the
# bare "GHSA-xxxx"/"CVE-YYYY-NNNNN" form. Without normalizing, the same
# vulnerability from two tools never shares an exact identifier string, so
# the cross-tool dedup in app/api/projects.py's _security_summary (and the
# same-scan dedup below in run_deterministic_scan) silently fails to merge
# them — the remediation queue shows the same CVE/GHSA twice.
_ADVISORY_URL_RE = re.compile(r"^https?://github\.com/advisories/(.+)$", re.IGNORECASE)


def _normalize_identifier(value: str) -> str:
    value = str(value or "").strip()
    match = _ADVISORY_URL_RE.match(value)
    if match:
        value = match.group(1)
    return value.upper()


def _parse_semver(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    parts = re.findall(r"\d+", str(value).split("-")[0])[:3]
    if not parts:
        return None
    numbers = [int(p) for p in parts] + [0, 0, 0]
    return (numbers[0], numbers[1], numbers[2])


def best_fix_version(installed: str | None, candidates: list[str]) -> tuple[str | None, list[str]]:
    """A package can have several actively-patched major lines at once —
    e.g. uuid deprecated its 9.x/10.x lines outright, so 8.x users are
    offered 11.1.1/12.0.1/13.0.1 as equally-valid "the fix", forcing the
    reader to guess which applies to them. Pick one instead of listing all
    of them as the answer: prefer the candidate on the same major version
    as installed (smallest patch/minor bump — least likely to break
    anything), else the lowest-numbered candidate overall (smallest jump
    when a major bump can't be avoided). Returns (chosen, deduped
    candidates actually parseable as versions) so callers can still show
    the rest as alternatives rather than silently drop them."""
    parsed = [(candidate, _parse_semver(candidate)) for candidate in dict.fromkeys(c for c in candidates if c)]
    parsed = [(candidate, version) for candidate, version in parsed if version]
    if not parsed:
        return (candidates[0] if candidates else None, [c for c in candidates if c])
    installed_version = _parse_semver(installed)
    if installed_version:
        same_major = [item for item in parsed if item[1][0] == installed_version[0]]
        if same_major:
            chosen = min(same_major, key=lambda item: item[1])[0]
            return chosen, [candidate for candidate, _ in parsed]
    chosen = min(parsed, key=lambda item: item[1])[0]
    return chosen, [candidate for candidate, _ in parsed]


def _finding(tool: str, rule_id: str, file: str, line: int | None, severity: str, comment: str, recommendation: str = "", evidence: str = "", identifiers: list[str] | None = None, category: str | None = None, package: str | None = None, fixed_version: str | None = None, installed_version: str | None = None) -> dict:
    identity = f"{tool}|{rule_id}|{file}|{line or 0}|{comment}".encode()
    return {
        "tool": tool, "rule_id": rule_id, "file": file, "line": line,
        "category": category or ("secrets" if tool == "gitleaks" else "other"),
        "severity": _severity(severity), "comment": comment,
        "recommendation": recommendation, "evidence": evidence[:1000],
        "identifiers": sorted({_normalize_identifier(i) for i in (identifiers or []) if str(i or "").strip()}),
        "verification": "tool-verified",
        "fingerprint": hashlib.sha256(identity).hexdigest()[:24],
        # Dependency findings only: lets multiple distinct CVEs/advisories
        # against the same package get bundled into one remediation entry
        # (app/api/projects.py's _security_summary) instead of one card per
        # advisory for what is, in practice, a single "bump the version"
        # action. installed_version feeds best_fix_version's same-major-line
        # matching, both here and in that bundling step.
        "package": package or None, "fixed_version": fixed_version or None,
        "installed_version": installed_version or None,
    }


def _parse_semgrep(data: dict) -> list[dict]:
    findings = []
    for item in data.get("results", []):
        extra = item.get("extra") or {}
        metadata = extra.get("metadata") or {}
        findings.append(_finding(
            "semgrep", str(item.get("check_id", "semgrep")), str(item.get("path", "")),
            ((item.get("start") or {}).get("line")), metadata.get("severity") or extra.get("severity"),
            str(extra.get("message") or "Semgrep rule matched"),
            str(metadata.get("fix") or metadata.get("recommendation") or "Review and remediate the matched insecure pattern."),
            str(extra.get("lines") or ""), category="code",
        ))
    return findings


def _parse_gitleaks(data: list) -> list[dict]:
    return [_finding(
        "gitleaks", str(item.get("RuleID", "secret")), str(item.get("File", "")), item.get("StartLine"),
        "high", str(item.get("Description") or "Potential secret detected"),
        "Revoke exposed credentials, remove them from source, and rotate affected secrets.",
        str(item.get("Match") or item.get("Secret") or "")[:120],
    ) for item in data if isinstance(item, dict)]


def _parse_trivy(data: dict) -> list[dict]:
    findings = []
    for result in data.get("Results", []):
        target = str(result.get("Target", ""))
        for vuln in result.get("Vulnerabilities") or []:
            vuln_id = str(vuln.get("VulnerabilityID", "unknown"))
            package_name = vuln.get("PkgName", "the affected package")
            installed = vuln.get("InstalledVersion")
            # Trivy's FixedVersion is sometimes a comma-separated list when
            # a package has multiple actively-patched major lines (e.g.
            # uuid: 8.x users are offered "11.1.1, 12.0.1, 13.0.1" since
            # 9.x/10.x were deprecated) — pick the smallest safe upgrade
            # rather than presenting all of them as equally "the fix".
            candidates = [c.strip() for c in str(vuln.get("FixedVersion") or "").split(",") if c.strip()]
            chosen, all_candidates = best_fix_version(installed, candidates)
            recommendation = f"Upgrade {package_name} to {chosen}." if chosen else f"Upgrade {package_name} to a non-vulnerable version."
            alternatives = [c for c in all_candidates if c != chosen]
            if alternatives:
                recommendation += f" (Other maintained targets: {', '.join(alternatives)}.)"
            findings.append(_finding(
                "trivy", vuln_id, target, None, vuln.get("Severity"),
                str(vuln.get("Title") or vuln.get("Description") or vuln_id),
                recommendation,
                f"Installed: {installed or 'unknown'}; fixed: {vuln.get('FixedVersion', 'unknown')}",
                [vuln_id], category="dependency",
                package=package_name, fixed_version=chosen, installed_version=installed,
            ))
        for misconfiguration in result.get("Misconfigurations") or []:
            findings.append(_finding(
                "trivy", str(misconfiguration.get("ID", "misconfiguration")), target,
                ((misconfiguration.get("CauseMetadata") or {}).get("StartLine")), misconfiguration.get("Severity"),
                str(misconfiguration.get("Title") or misconfiguration.get("Message") or "Infrastructure misconfiguration"),
                str(misconfiguration.get("Resolution") or "Apply the scanner's recommended secure configuration."),
                str(misconfiguration.get("Message") or ""), category="misconfiguration",
            ))
        for secret in result.get("Secrets") or []:
            findings.append(_finding(
                "trivy", str(secret.get("RuleID", "secret")), target, secret.get("StartLine"), "high",
                str(secret.get("Title") or "Potential secret detected"),
                "Revoke and rotate the secret, then remove it from repository history.", str(secret.get("Match") or ""),
                category="secrets",
            ))
    return findings


def _osv_fixed_versions(vuln: dict) -> list[str]:
    """Best-effort: osv-scanner's per-vulnerability record lists affected
    ranges/events rather than a single "fixed" field the way Trivy does.
    Collects every "fixed" event across every affected range — a package
    can have several actively-patched major lines at once, each with its
    own fixed event. Returns them all so the caller can pick the one
    closest to the installed version instead of the first one found (which
    might not even apply to this installation's major line). Falls back to
    an empty list if the shape doesn't match what's expected; never
    raises."""
    versions = []
    for affected in vuln.get("affected") or []:
        for range_entry in affected.get("ranges") or []:
            for event in range_entry.get("events") or []:
                fixed = event.get("fixed")
                if fixed:
                    versions.append(str(fixed))
    return versions


def _parse_osv(data: dict) -> list[dict]:
    findings = []
    for result in data.get("results", []):
        source = (result.get("source") or {}).get("path", "dependency manifest")
        for package_entry in result.get("packages", []):
            package = package_entry.get("package") or {}
            installed = package.get("version")
            for vuln in package_entry.get("vulnerabilities") or []:
                vuln_id = str(vuln.get("id", "OSV"))
                severity = "high" if any(str(s.get("score", "")).startswith(("8", "9", "10")) for s in vuln.get("severity") or []) else "medium"
                chosen, all_candidates = best_fix_version(installed, _osv_fixed_versions(vuln))
                recommendation = f"Upgrade {package.get('name', 'the affected package')} to {chosen}." if chosen else "Upgrade to a fixed version listed by the advisory."
                alternatives = [c for c in all_candidates if c != chosen]
                if alternatives:
                    recommendation += f" (Other maintained targets: {', '.join(alternatives)}.)"
                findings.append(_finding(
                    "osv-scanner", vuln_id, str(source), None, severity,
                    f"{package.get('name', 'Dependency')} {installed or ''} is affected by {vuln_id}.",
                    recommendation,
                    str(vuln.get("summary") or vuln.get("details") or ""),
                    [vuln_id, *[str(alias) for alias in vuln.get("aliases") or []]],
                    category="dependency",
                    package=package.get("name"), fixed_version=chosen, installed_version=installed,
                ))
    return findings


def _parse_npm_audit(data: dict) -> list[dict]:
    findings = []
    for package, advisory in (data.get("vulnerabilities") or {}).items():
        for via in advisory.get("via") or []:
            if not isinstance(via, dict):
                continue
            identifier = str(via.get("url") or via.get("source") or "npm-advisory")
            fix_available = advisory.get("fixAvailable")
            fixed_version = fix_available.get("version") if isinstance(fix_available, dict) else None
            installed = advisory.get("version")
            findings.append(_finding("npm-audit", identifier, "package-lock.json", None, via.get("severity"), f"{package} is affected: {via.get('title', identifier)}.", f"Upgrade {package} to {fixed_version or 'a fixed version'}.", str(via.get("url") or ""), [identifier], category="dependency", package=package, fixed_version=fixed_version, installed_version=installed))
    return findings


def _parse_pip_audit(data: list | dict) -> list[dict]:
    entries = data if isinstance(data, list) else data.get("dependencies", [])
    findings = []
    for v in entries:
        if not (v.get("vulns") or v.get("id")):
            continue
        installed = v.get("version")
        chosen, all_candidates = best_fix_version(installed, v.get("fix_versions") or [])
        recommendation = f"Upgrade to {chosen}." if chosen else "Upgrade to a fixed version."
        alternatives = [c for c in all_candidates if c != chosen]
        if alternatives:
            recommendation += f" (Other maintained targets: {', '.join(alternatives)}.)"
        findings.append(_finding("pip-audit", str(v.get("id", "PYSEC")), "requirements.txt", None, "high", f"{v.get('name', 'Python dependency')} {v.get('version', '')} is vulnerable.", recommendation, str(v.get("description", "")), [str(v.get("id", "PYSEC"))], category="dependency", package=v.get("name"), fixed_version=chosen, installed_version=installed))
    return findings


# Registry rulesets stacked onto every semgrep run (`--config` may repeat;
# semgrep unions the rulesets and dedupes overlapping rules itself).
# p/secrets is deliberately excluded: gitleaks/trivy already cover secret
# detection, and unlike CVE/GHSA-bearing findings, secret findings carry no
# `identifiers` — the cross-tool dedup in run_deterministic_scan only merges
# on `identifiers`, so a secrets ruleset here would show as a second,
# un-merged finding for the same exposed secret rather than corroborating it.
_SEMGREP_BASE_CONFIGS = ("p/security-audit", "p/secure-defaults")
_AI_SDK_MARKERS = (
    "openai", "anthropic", "langchain", "llama-index", "llama_index",
    "llamaindex", "cohere", "google-generativeai", "google.generativeai",
    "mistralai", "ollama", "huggingface", "transformers", "vertexai",
)


def _semgrep_config_args(source: Path) -> list[str]:
    """Stack-conditional rulesets on top of the always-on base configs, so a
    Python-only or Go repo isn't paying for JS-specific rules it can never
    match. Detection reads actual manifest content (not just filenames,
    which scanner_capabilities already checks) — presence of a dependency
    name, not just a manifest's existence, is what p/ai-best-practices in
    particular needs to be meaningful."""
    configs = list(_SEMGREP_BASE_CONFIGS)
    manifest_texts: list[str] = []
    package_jsons = list(source.rglob("package.json"))[:50]
    has_express = False
    for manifest in package_jsons:
        try:
            text = manifest.read_text(errors="replace")
        except OSError:
            continue
        manifest_texts.append(text)
        if '"express"' in text:
            has_express = True
    if package_jsons:
        configs += ["p/javascript", "p/nodejs"]
    if has_express:
        configs.append("p/expressjs")
    for requirements in list(source.rglob("requirements.txt"))[:50]:
        try:
            manifest_texts.append(requirements.read_text(errors="replace"))
        except OSError:
            continue
    combined = "\n".join(manifest_texts).lower()
    if any(marker in combined for marker in _AI_SDK_MARKERS):
        configs.append("p/ai-best-practices")
    return configs


def _scanner_command(tool: str, source: Path, work: Path) -> tuple[list[str], Path | None]:
    executable = _which({"npm-audit": "npm", "pip-audit": "pip-audit"}.get(tool, tool)) or tool
    if executable == tool and tool in {"gitleaks", "trivy", "osv-scanner"} and _which("docker"):
        mount = f"{source}:/src:ro"
        if tool == "gitleaks":
            return ["docker", "run", "--rm", "-v", mount, "zricethezav/gitleaks:latest", "detect", "--source", "/src", "--no-git", "--report-format", "json"], None
        if tool == "trivy":
            return ["docker", "run", "--rm", "-v", mount, "aquasec/trivy:latest", "fs", "--format", "json", "/src"], None
        return ["docker", "run", "--rm", "-v", mount, "ghcr.io/google/osv-scanner:latest", "scan", "source", "-r", "--format", "json", "/src"], None
    if tool == "semgrep":
        config_args = [arg for config in _semgrep_config_args(source) for arg in ("--config", config)]
        return [executable, "scan", *config_args, "--json", "--quiet", str(source)], None
    if tool == "gitleaks":
        report = work / "gitleaks.json"
        return [tool, "detect", "--source", str(source), "--no-git", "--report-format", "json", "--report-path", str(report)], report
    if tool == "trivy":
        return [tool, "fs", "--format", "json", "--scanners", "vuln,misconfig,secret", "--quiet", str(source)], None
    if tool == "osv-scanner":
        return [tool, "scan", "source", "--recursive", "--format", "json", str(source)], None
    if tool == "eslint":
        return [tool, str(source), "--format", "json"], None
    if tool == "npm-audit":
        return ["npm", "audit", "--json", "--package-lock-only", "--ignore-scripts"], None
    return [tool, "-f", "json", "-r", str(source / "requirements.txt")], None


def _parse_tool(tool: str, raw: str) -> list[dict]:
    data = json.loads(raw or "{}")
    if tool == "semgrep": return _parse_semgrep(data)
    if tool == "gitleaks": return _parse_gitleaks(data if isinstance(data, list) else [])
    if tool == "trivy": return _parse_trivy(data)
    if tool == "osv-scanner": return _parse_osv(data)
    if tool == "npm-audit": return _parse_npm_audit(data)
    if tool == "pip-audit": return _parse_pip_audit(data)
    return [_finding("eslint", str(item.get("ruleId", "eslint")), str(item.get("filePath", "")), (item.get("line", 0) or 0), "medium", str(item.get("message", "ESLint security finding")), "Fix the ESLint rule violation.", category="code") for item in (data if isinstance(data, list) else []) if item.get("errorCount", 0)]


def run_deterministic_scan(
    config: BitbucketConfig, branch: str | None = None, commit_sha: str | None = None,
    *, source: Path | None = None, commit: str | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield scanner_status events followed by deterministic_complete.

    ``commit_sha``, when given, pins the snapshot the scanners run against
    to that exact commit (see create_repository_snapshot) — used by PR
    impact analysis so the deterministic scanners analyze the same head
    revision the repository index/ast-grep/LLM context were built from,
    not "whatever the branch currently resolves to".

    ``source``/``commit``, when BOTH given, reuse an already-fetched
    snapshot instead of fetching a fresh one — the same directory (and its
    resolved commit) some earlier step (e.g. PR impact analysis building
    its repository-intelligence index) already materialized via
    create_repository_snapshot. Without this, PR analysis fetched the
    entire repository from Bitbucket twice per scan (once for the index,
    once again here) — doubling network cost and, more importantly,
    doubling the request volume against Bitbucket's own rate limits for
    the same token, which is what actually caused snapshot failures under
    repeated PR-scan testing. The scanners themselves are unaffected
    either way — only where the snapshot comes from changed."""
    reused_snapshot = source is not None and commit is not None
    with tempfile.TemporaryDirectory(prefix="autosdlc-vapt-") as temp:
        work = Path(temp)
        if reused_snapshot:
            snapshot_files = sum(1 for item in source.rglob("*") if item.is_file())
            yield "scanner_status", {"stage": "snapshot", "status": "completed", "commit": commit, "files": snapshot_files, "reused": True}
        else:
            yield "scanner_status", {"stage": "snapshot", "status": "running", "message": "Creating isolated repository snapshot"}
            source = work / "source"
            commit = create_repository_snapshot(config, source, branch=branch, commit_sha=commit_sha)
            snapshot_files = sum(1 for item in source.rglob("*") if item.is_file())
            yield "scanner_status", {"stage": "snapshot", "status": "completed", "commit": commit, "files": snapshot_files}
        capabilities = scanner_capabilities(source)
        all_findings = []
        tool_results = []
        for capability in capabilities:
            tool = capability["tool"]
            if not capability["available"]:
                result = {"tool": tool, "status": capability.get("status", "unavailable"), "findings_count": 0, "duration_seconds": 0, "error": capability.get("reason")}
                tool_results.append(result)
                yield "scanner_status", result
                continue
            yield "scanner_status", {"tool": tool, "status": "running", "findings_count": 0}
            started = time.monotonic()
            try:
                command, report_path = _scanner_command(tool, source, work)
                completed = _run(command, cwd=str(source), timeout=SCANNER_TIMEOUT_SECONDS)
                raw = report_path.read_text(errors="replace") if report_path and report_path.exists() else completed.stdout
                # osv-scanner exits 128 and writes this banner to stderr (no
                # JSON on stdout) when the snapshot has no manifest it
                # recognizes — a clean "nothing to check" result, not a
                # scanner failure.
                if tool == "osv-scanner" and completed.returncode not in {0, 1} and "No package sources found" in (completed.stdout or "") + (completed.stderr or ""):
                    findings = []
                    all_findings.extend(findings)
                    result = {"tool": tool, "status": "completed", "findings_count": 0, "duration_seconds": round(time.monotonic() - started, 1)}
                    tool_results.append(result)
                    yield "scanner_status", result
                    continue
                # A flat eslint.config.js can `import` plugin packages
                # (eslint-plugin-*, @typescript-eslint/*, ...) resolved
                # relative to the config file — which needs node_modules
                # next to it. Snapshots deliberately exclude node_modules
                # (size, and to avoid executing install scripts), so Node's
                # ESM loader throws before eslint scans a single file on
                # basically any real-world plugin-based config. That's a
                # structural gap in what a source-only snapshot can lint,
                # not a scanner failure — surface it as a clean "nothing we
                # can check" result instead of a raw JS stack trace.
                eslint_output = (completed.stdout or "") + (completed.stderr or "")
                if tool == "eslint" and completed.returncode not in {0, 1} and (
                    "ERR_MODULE_NOT_FOUND" in eslint_output or "Cannot find package" in eslint_output
                ):
                    result = {
                        "tool": tool, "status": "not_applicable", "findings_count": 0,
                        "duration_seconds": round(time.monotonic() - started, 1),
                        "error": "ESLint configuration imports plugins that aren't installed in this snapshot (node_modules is excluded from scans).",
                    }
                    tool_results.append(result)
                    yield "scanner_status", result
                    continue
                # Security scanners commonly return 1 when findings exist.
                if completed.returncode not in {0, 1}:
                    raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-500:])
                findings = _parse_tool(tool, raw)
                all_findings.extend(findings)
                result = {"tool": tool, "status": "completed", "findings_count": len(findings), "duration_seconds": round(time.monotonic() - started, 1)}
            except subprocess.TimeoutExpired:
                result = {"tool": tool, "status": "failed", "findings_count": 0, "duration_seconds": round(time.monotonic() - started, 1), "error": "Scanner timed out"}
            except Exception as exc:
                result = {"tool": tool, "status": "failed", "findings_count": 0, "duration_seconds": round(time.monotonic() - started, 1), "error": str(exc)[:500]}
            tool_results.append(result)
            yield "scanner_status", result

        deduped = {}
        for finding in all_findings:
            key = tuple(sorted(finding.get("identifiers") or [])) or (finding["fingerprint"],)
            deduped.setdefault(key, finding)
        yield "deterministic_complete", {
            "commit": commit, "snapshot_files": snapshot_files, "tools": tool_results, "findings": list(deduped.values()),
            "partial": any(item["status"] in {"unavailable", "disabled", "failed"} for item in tool_results),
        }
