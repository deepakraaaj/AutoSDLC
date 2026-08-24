"""Deterministic VAPT scanner orchestration.

Repository source is fetched into an isolated temporary snapshot without a
working-tree checkout, so repository hooks, filters, and package lifecycle
scripts are never executed. Scanner adapters are read-only and bounded by
timeouts. Missing tools are reported explicitly rather than treated as a
clean scan.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
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


def scanner_capabilities(source: Path | None = None) -> list[dict]:
    files = {p.name for p in source.rglob("*") if p.is_file()} if source else set()
    # ESLint loads JavaScript configuration files, which is executable
    # repository code. Keep it disabled unless an operator explicitly trusts
    # the repository and opts in; the other scanners remain non-executing.
    eslint_config = os.getenv("VAPT_ALLOW_ESLINT_CONFIG", "false").lower() == "true" and any(name in files for name in ("eslint.config.js", "eslint.config.mjs", ".eslintrc", ".eslintrc.js", ".eslintrc.json"))
    executables = {"npm-audit": "npm", "pip-audit": "pip-audit"}
    return [{
        "tool": tool,
        "available": shutil.which(executables.get(tool, tool)) is not None
        and (tool != "eslint" or eslint_config)
        and (tool != "npm-audit" or "package-lock.json" in files)
        and (tool != "pip-audit" or "requirements.txt" in files),
    } for tool in SCANNERS]


def _clone_url(config: BitbucketConfig) -> str:
    parsed = urlsplit(config.base_url)
    if parsed.hostname == "api.bitbucket.org":
        return f"https://bitbucket.org/{config.workspace}/{config.repo_slug}.git"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/scm/{config.workspace}/{config.repo_slug}.git"


def _git_environment(config: BitbucketConfig, isolated_home: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": isolated_home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
    }
    authorization = config._headers().get("Authorization", "")
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: {authorization}"
    return env


def _run(command: list[str], *, cwd: str | None = None, env: dict | None = None, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=cwd, env=env, timeout=timeout, check=False,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _safe_extract(archive_path: Path, destination: Path) -> None:
    total_files = 0
    total_bytes = 0
    root = destination.resolve()
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or member.isdev():
                continue
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("Repository archive attempted path traversal")
            if member.isfile():
                total_files += 1
                total_bytes += max(member.size, 0)
                if total_files > MAX_SNAPSHOT_FILES or total_bytes > MAX_SNAPSHOT_BYTES:
                    raise RuntimeError("Repository snapshot exceeds configured safety limits")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source:
                    with target.open("wb") as output:
                        shutil.copyfileobj(source, output)


def create_repository_snapshot(config: BitbucketConfig, destination: Path) -> str:
    """Create a source snapshot and return the exact scanned commit hash."""
    bare_repo = destination.parent / "repo.git"
    archive_path = destination.parent / "source.tar"
    env = _git_environment(config, str(destination.parent))
    clone = _run(
        ["git", "clone", "--bare", "--depth", "1", "--no-tags", _clone_url(config), str(bare_repo)],
        env=env, timeout=SNAPSHOT_TIMEOUT_SECONDS,
    )
    if clone.returncode != 0:
        # Bitbucket access tokens are valid for the REST API but are not
        # universally accepted by Git-over-HTTPS. Fall back to an API-only
        # materialization; it never invokes Git hooks or package scripts.
        destination.mkdir(parents=True, exist_ok=True)
        # Bitbucket's ``HEAD`` ref is not accepted by the source API for all
        # repositories (notably repositories whose default branch is
        # ``master``). Resolve an explicit branch for the REST fallback.
        ref = os.getenv("BITBUCKET_BRANCH", "master")
        queue = [""]
        seen_dirs = {""}
        paths: list[str] = []
        while queue and len(paths) < MAX_SNAPSHOT_FILES:
            path = queue.pop(0)
            entries = list_repo_files(config, path=path, ref=ref)
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
        total_bytes = 0
        for item in paths:
            content = get_file_content(config, item, ref=ref)
            raw = content.encode("utf-8", errors="ignore")[:MAX_SNAPSHOT_BYTES]
            total_bytes += len(raw)
            if total_bytes > MAX_SNAPSHOT_BYTES:
                break
            target = destination / item
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if not any(destination.rglob("*")):
            raise RuntimeError(f"Repository snapshot failed: {(clone.stderr or clone.stdout).strip()[-500:]}")
        return f"{ref} (Bitbucket API snapshot)"
    revision = _run(["git", "rev-parse", "HEAD"], cwd=str(bare_repo), env=env, timeout=30)
    if revision.returncode != 0:
        raise RuntimeError("Could not resolve repository commit")
    with archive_path.open("wb") as output:
        archive = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"], cwd=str(bare_repo), env=env,
            timeout=SNAPSHOT_TIMEOUT_SECONDS, check=False, stdout=output, stderr=subprocess.PIPE,
        )
    if archive.returncode != 0:
        raise RuntimeError("Could not create safe repository archive")
    destination.mkdir(parents=True, exist_ok=True)
    _safe_extract(archive_path, destination)
    return revision.stdout.strip()


def _severity(value: str | None) -> str:
    normalized = str(value or "medium").lower()
    aliases = {"error": "high", "warning": "medium", "warn": "medium", "info": "low", "unknown": "medium"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"critical", "high", "medium", "low"} else "medium"


def _finding(tool: str, rule_id: str, file: str, line: int | None, severity: str, comment: str, recommendation: str = "", evidence: str = "", identifiers: list[str] | None = None) -> dict:
    identity = f"{tool}|{rule_id}|{file}|{line or 0}|{comment}".encode()
    return {
        "tool": tool, "rule_id": rule_id, "file": file, "line": line,
        "category": "secrets" if tool == "gitleaks" else "other",
        "severity": _severity(severity), "comment": comment,
        "recommendation": recommendation, "evidence": evidence[:1000],
        "identifiers": identifiers or [], "verification": "tool-verified",
        "fingerprint": hashlib.sha256(identity).hexdigest()[:24],
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
            str(extra.get("lines") or ""),
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
            findings.append(_finding(
                "trivy", vuln_id, target, None, vuln.get("Severity"),
                str(vuln.get("Title") or vuln.get("Description") or vuln_id),
                f"Upgrade {vuln.get('PkgName', 'the affected package')} to {vuln.get('FixedVersion') or 'a non-vulnerable version'}.",
                f"Installed: {vuln.get('InstalledVersion', 'unknown')}; fixed: {vuln.get('FixedVersion', 'unknown')}",
                [vuln_id],
            ))
        for misconfiguration in result.get("Misconfigurations") or []:
            findings.append(_finding(
                "trivy", str(misconfiguration.get("ID", "misconfiguration")), target,
                ((misconfiguration.get("CauseMetadata") or {}).get("StartLine")), misconfiguration.get("Severity"),
                str(misconfiguration.get("Title") or misconfiguration.get("Message") or "Infrastructure misconfiguration"),
                str(misconfiguration.get("Resolution") or "Apply the scanner's recommended secure configuration."),
                str(misconfiguration.get("Message") or ""),
            ))
        for secret in result.get("Secrets") or []:
            findings.append(_finding(
                "trivy", str(secret.get("RuleID", "secret")), target, secret.get("StartLine"), "high",
                str(secret.get("Title") or "Potential secret detected"),
                "Revoke and rotate the secret, then remove it from repository history.", str(secret.get("Match") or ""),
            ))
    return findings


def _parse_osv(data: dict) -> list[dict]:
    findings = []
    for result in data.get("results", []):
        source = (result.get("source") or {}).get("path", "dependency manifest")
        for package_entry in result.get("packages", []):
            package = package_entry.get("package") or {}
            for vuln in package_entry.get("vulnerabilities") or []:
                vuln_id = str(vuln.get("id", "OSV"))
                severity = "high" if any(str(s.get("score", "")).startswith(("8", "9", "10")) for s in vuln.get("severity") or []) else "medium"
                findings.append(_finding(
                    "osv-scanner", vuln_id, str(source), None, severity,
                    f"{package.get('name', 'Dependency')} {package.get('version', '')} is affected by {vuln_id}.",
                    "Upgrade to a fixed version listed by the advisory.",
                    str(vuln.get("summary") or vuln.get("details") or ""),
                    [vuln_id, *[str(alias) for alias in vuln.get("aliases") or []]],
                ))
    return findings


def _parse_npm_audit(data: dict) -> list[dict]:
    findings = []
    for package, advisory in (data.get("vulnerabilities") or {}).items():
        for via in advisory.get("via") or []:
            if not isinstance(via, dict):
                continue
            identifier = str(via.get("url") or via.get("source") or "npm-advisory")
            findings.append(_finding("npm-audit", identifier, "package-lock.json", None, via.get("severity"), f"{package} is affected: {via.get('title', identifier)}.", f"Upgrade {package} to {advisory.get('fixAvailable', {}).get('version') if isinstance(advisory.get('fixAvailable'), dict) else 'a fixed version'}.", str(via.get("url") or ""), [identifier]))
    return findings


def _parse_pip_audit(data: list | dict) -> list[dict]:
    entries = data if isinstance(data, list) else data.get("dependencies", [])
    return [_finding("pip-audit", str(v.get("id", "PYSEC")), "requirements.txt", None, "high", f"{v.get('name', 'Python dependency')} {v.get('version', '')} is vulnerable.", f"Upgrade to {','.join(v.get('fix_versions', [])) or 'a fixed version'}.", str(v.get("description", "")), [str(v.get("id", "PYSEC"))]) for v in entries if v.get("vulns") or v.get("id")]


def _scanner_command(tool: str, source: Path, work: Path) -> tuple[list[str], Path | None]:
    if tool == "semgrep":
        return [tool, "scan", "--config", "p/security-audit", "--json", "--quiet", str(source)], None
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
    return [_finding("eslint", str(item.get("ruleId", "eslint")), str(item.get("filePath", "")), (item.get("line", 0) or 0), "medium", str(item.get("message", "ESLint security finding")), "Fix the ESLint rule violation.") for item in (data if isinstance(data, list) else []) if item.get("errorCount", 0)]


def run_deterministic_scan(config: BitbucketConfig) -> Iterator[tuple[str, dict]]:
    """Yield scanner_status events followed by deterministic_complete."""
    yield "scanner_status", {"stage": "snapshot", "status": "running", "message": "Creating isolated repository snapshot"}
    with tempfile.TemporaryDirectory(prefix="autosdlc-vapt-") as temp:
        work = Path(temp)
        source = work / "source"
        commit = create_repository_snapshot(config, source)
        snapshot_files = sum(1 for item in source.rglob("*") if item.is_file())
        yield "scanner_status", {"stage": "snapshot", "status": "completed", "commit": commit, "files": snapshot_files}
        capabilities = scanner_capabilities(source)
        all_findings = []
        tool_results = []
        for capability in capabilities:
            tool = capability["tool"]
            if not capability["available"]:
                result = {"tool": tool, "status": "unavailable", "findings_count": 0, "duration_seconds": 0}
                tool_results.append(result)
                yield "scanner_status", result
                continue
            yield "scanner_status", {"tool": tool, "status": "running", "findings_count": 0}
            started = time.monotonic()
            try:
                command, report_path = _scanner_command(tool, source, work)
                completed = _run(command, cwd=str(source), timeout=SCANNER_TIMEOUT_SECONDS)
                raw = report_path.read_text(errors="replace") if report_path and report_path.exists() else completed.stdout
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
            "partial": any(item["status"] != "completed" for item in tool_results),
        }
