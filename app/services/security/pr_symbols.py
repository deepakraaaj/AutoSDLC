"""Map a PullRequestDiff onto a head-revision RepositoryIndex: which
indexed symbols did the PR actually touch, and which changed files carry no
source-code symbol at all (dependency manifests, infra/CI config) but still
matter for security impact.

Output (`PRImpactSeed` list) is the seed set security/impact_graph.py's
existing `build_impact_graph` traverses from — this module does no graph
traversal of its own.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.repo_intelligence import RepositoryIndex, Symbol, symbol_id
from app.services.security.pr_diff import PullRequestDiff, PullRequestFileChange

SEED_SYMBOL = "SYMBOL"
SEED_DEPENDENCY = "DEPENDENCY"
SEED_CONFIGURATION = "CONFIGURATION"
SEED_INFRASTRUCTURE = "INFRASTRUCTURE"
SEED_SECURITY_CONFIG = "SECURITY_CONFIG"

_DEPENDENCY_BASENAMES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "pipfile", "pipfile.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pom.xml", "build.gradle", "build.gradle.kts", "gradle.lockfile",
    "gemfile", "gemfile.lock", "go.mod", "go.sum", "cargo.toml", "cargo.lock",
}
_INFRASTRUCTURE_BASENAMES = {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
_INFRASTRUCTURE_SUFFIXES = {".tf", ".tfvars"}
_INFRASTRUCTURE_PATH_MARKERS = ("k8s/", "kubernetes/", "/k8s/", "/helm/", "helm/")
_SECURITY_CONFIG_BASENAMES = {".env.example", "security.yml", "security.yaml"}
_CI_PATH_MARKERS = (".github/workflows/", ".gitlab-ci", "jenkinsfile", "bitbucket-pipelines.yml")


def classify_non_code_file(path: str) -> str | None:
    """None for an ordinary source file (handled by the symbol-overlap path
    instead); one of DEPENDENCY/INFRASTRUCTURE/SECURITY_CONFIG/CONFIGURATION
    for the file categories called out in the brief that don't map to a
    function/class symbol at all."""
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    suffix = f".{name.rsplit('.', 1)[-1]}" if "." in name else ""
    if name in _DEPENDENCY_BASENAMES:
        return SEED_DEPENDENCY
    if name in _SECURITY_CONFIG_BASENAMES:
        return SEED_SECURITY_CONFIG
    if name in _INFRASTRUCTURE_BASENAMES or suffix in _INFRASTRUCTURE_SUFFIXES or any(marker in lower for marker in _INFRASTRUCTURE_PATH_MARKERS):
        return SEED_INFRASTRUCTURE
    if any(marker in lower for marker in _CI_PATH_MARKERS):
        return SEED_CONFIGURATION
    return None


@dataclass
class PRImpactSeed:
    seed_type: str  # SYMBOL | DEPENDENCY | CONFIGURATION | INFRASTRUCTURE | SECURITY_CONFIG
    file: str
    symbol_id: str | None
    symbol_name: str | None
    change_status: str  # ADDED | MODIFIED | DELETED
    detail: str = ""


def _touched_lines(file_change: PullRequestFileChange) -> set[int]:
    """The specific new-file line numbers a hunk actually changed — added
    lines verbatim; for a hunk that only removes lines (no new-file
    coordinates exist for what's gone), the single new-file point the
    removal happened at. Deliberately *not* the hunk's full context span:
    unified diffs pad each hunk with a few unchanged context lines on
    either side, and treating those as "touched" would flag a neighboring,
    untouched function merely for appearing in the same hunk's context
    window."""
    lines: set[int] = set()
    for hunk in file_change.hunks:
        if hunk.added_lines:
            lines.update(hunk.added_lines)
        elif hunk.removed_lines:
            lines.add(hunk.new_start)
    return lines


def map_pr_changes_to_symbols(diff: PullRequestDiff, index: RepositoryIndex) -> list[PRImpactSeed]:
    """The PR's changed-code seed set: one PRImpactSeed per indexed symbol
    whose line range overlaps a changed hunk, plus non-code seeds for
    dependency/infra/config files and a file-level seed for anything that
    changed but matched no indexed symbol (module-level statements,
    unsupported languages, deleted files no longer in the head index).
    Nothing is silently dropped — every changed file produces at least one
    seed unless it's a binary file (no meaningful text-level impact)."""
    seeds: list[PRImpactSeed] = []
    symbols_by_path: dict[str, list[Symbol]] = {}
    for symbol in index.symbols:
        symbols_by_path.setdefault(symbol.path, []).append(symbol)

    for file_change in diff.files:
        if file_change.status == "BINARY":
            continue

        non_code_category = classify_non_code_file(file_change.path)
        if non_code_category:
            seeds.append(PRImpactSeed(
                seed_type=non_code_category, file=file_change.path, symbol_id=None, symbol_name=None,
                change_status=file_change.status, detail=f"{non_code_category.replace('_', ' ').title()} file changed",
            ))
            continue

        if file_change.status == "DELETED":
            # The head snapshot/index no longer contains this file — cannot
            # resolve which symbols it held, but the deletion itself is
            # still a real PR change worth carrying forward (e.g. a removed
            # auth check is exactly the kind of thing that matters here).
            seeds.append(PRImpactSeed(
                seed_type=SEED_SYMBOL, file=file_change.path, symbol_id=None, symbol_name=None,
                change_status="DELETED", detail="File deleted; not resolvable against the head index",
            ))
            continue

        file_symbols = symbols_by_path.get(file_change.path, [])
        if not file_symbols:
            if file_change.hunks or file_change.status == "ADDED":
                seeds.append(PRImpactSeed(
                    seed_type=SEED_SYMBOL, file=file_change.path, symbol_id=None, symbol_name=None,
                    change_status=file_change.status, detail="No indexed symbols for this file",
                ))
            continue

        added_line_set = set(file_change.added_lines)
        touched_lines = _touched_lines(file_change)
        matched_any = False
        for symbol in file_symbols:
            overlaps = any(symbol.line <= line <= symbol.end_line for line in touched_lines)
            if not overlaps:
                continue
            matched_any = True
            status = "ADDED" if file_change.status == "ADDED" or symbol.line in added_line_set else "MODIFIED"
            seeds.append(PRImpactSeed(
                seed_type=SEED_SYMBOL, file=file_change.path, symbol_id=symbol_id(symbol), symbol_name=symbol.name,
                change_status=status, detail=f"{symbol.kind} {symbol.name}",
            ))

        if not matched_any and touched_lines:
            seeds.append(PRImpactSeed(
                seed_type=SEED_SYMBOL, file=file_change.path, symbol_id=None, symbol_name=None,
                change_status="MODIFIED", detail="Changed lines did not overlap an indexed symbol (module-level change)",
            ))

    return seeds


def build_fallback_change_summary(diff: PullRequestDiff, seeds: list[PRImpactSeed]) -> str:
    """A deterministic, non-LLM summary of what a PR changed — used when the
    LLM review is unavailable/failed, so a manager reading the result still
    gets a plain answer to "what did this PR actually do" instead of a
    security-only report that's silent when there's nothing to flag."""
    added = sum(1 for f in diff.files if f.status == "ADDED")
    modified = sum(1 for f in diff.files if f.status == "MODIFIED")
    deleted = sum(1 for f in diff.files if f.status == "DELETED")
    renamed = sum(1 for f in diff.files if f.status == "RENAMED")
    binary = sum(1 for f in diff.files if f.status == "BINARY")

    parts = [f"{diff.info.title}." if diff.info.title else "This PR"]
    counts = []
    if added:
        counts.append(f"{added} file(s) added")
    if modified:
        counts.append(f"{modified} file(s) modified")
    if deleted:
        counts.append(f"{deleted} file(s) deleted")
    if renamed:
        counts.append(f"{renamed} file(s) renamed")
    if binary:
        counts.append(f"{binary} binary/asset file(s)")
    if counts:
        parts.append("Changes: " + ", ".join(counts) + ".")

    named_symbols = [s.symbol_name for s in seeds if s.seed_type == "SYMBOL" and s.symbol_name][:8]
    if named_symbols:
        parts.append("Touches: " + ", ".join(named_symbols) + (", …" if len([s for s in seeds if s.symbol_name]) > 8 else "") + ".")

    non_code = {s.seed_type for s in seeds if s.seed_type != "SYMBOL"}
    if non_code:
        parts.append("Also changes: " + ", ".join(sorted(item.replace("_", " ").lower() for item in non_code)) + " file(s).")

    return " ".join(parts)
