"""Classify each deterministic/LLM security finding's relationship to a PR.

Inputs are the outputs of the rest of this package — PullRequestDiff
(pr_diff.py), the seed set (pr_symbols.py), and the ImpactGraph
(impact_graph.py) — plus one normalized finding at a time (vapt.py's
`_finding()` dict shape, or an LLM finding normalized to the same shape).
Nothing here re-runs a scanner or re-walks the repository; this module is
pure classification over data the earlier stages already produced.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.services.security.impact_graph import ImpactGraph
from app.services.security.pr_diff import PullRequestDiff
from app.services.security.pr_symbols import PRImpactSeed

RELATION_DIRECT = "DIRECT"
RELATION_INDIRECT = "INDIRECT"
RELATION_DEPENDENCY = "DEPENDENCY"
RELATION_EXISTING_RELEVANT = "EXISTING_RELEVANT"
RELATION_EXISTING_NEWLY_EXPOSED = "EXISTING_NEWLY_EXPOSED"
RELATION_UNRELATED = "UNRELATED"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

_DEPENDENCY_SCANNER_TOOLS = {"trivy", "osv-scanner", "npm-audit", "pip-audit"}


@dataclass
class CorrelatedFinding:
    finding: dict
    fingerprint: str
    relation_to_pr: str
    relation_confidence: str
    affected_path: list[str] = field(default_factory=list)
    reason: str = ""


def _hunk_new_line_ranges(diff: PullRequestDiff) -> dict[str, list[tuple[int, int]]]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    for file_change in diff.files:
        if file_change.status in {"DELETED", "BINARY"}:
            continue
        ranges[file_change.path] = [
            (hunk.new_start, hunk.new_start + max(hunk.new_lines, 1) - 1) for hunk in file_change.hunks
        ]
    return ranges


def _line_in_ranges(line: int | None, ranges: list[tuple[int, int]]) -> bool:
    if line is None:
        return True  # a finding with no line number "overlaps" a changed file as a whole
    return any(start <= line <= end for start, end in ranges)


def _reconstruct_path(graph: ImpactGraph, seed_ids: set[str], target_id: str) -> list[str]:
    """Node names from whichever seed reaches `target_id` in the fewest
    hops, via BFS predecessor tracking over the graph's own edges — the
    "execution path" shown as evidence (UserController.get_user() ->
    UserService.get_user() -> UserRepository.find_by_id())."""
    if target_id not in graph.nodes:
        return []
    if target_id in seed_ids:
        return [graph.nodes[target_id].name]
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.kind in {"calls", "inherits"}:
            adjacency.setdefault(edge.source, []).append(edge.target)
    parents: dict[str, str] = {}
    visited: set[str] = set(seed_ids)
    queue: deque[str] = deque(seed_ids)
    while queue:
        current = queue.popleft()
        if current == target_id:
            break
        for neighbor in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            parents[neighbor] = current
            queue.append(neighbor)
    if target_id not in visited:
        return []
    path_ids = [target_id]
    while path_ids[-1] not in seed_ids:
        parent = parents.get(path_ids[-1])
        if parent is None:
            break
        path_ids.append(parent)
    path_ids.reverse()
    return [graph.nodes[node_id].name for node_id in path_ids if node_id in graph.nodes]


def correlate_finding(
    finding: dict,
    fingerprint: str,
    *,
    diff: PullRequestDiff,
    seeds: list[PRImpactSeed],
    graph: ImpactGraph,
) -> CorrelatedFinding:
    """Classify one normalized finding's relationship to the PR. See the
    module docstring for RELATION_* definitions; PHASE 14 of the plan for
    the confidence rationale summarized inline below."""
    file_path = str(finding.get("file") or "")
    line = finding.get("start_line") if finding.get("start_line") is not None else finding.get("line")

    # 1. DEPENDENCY — a dependency-scanner finding when the PR touched a
    # dependency manifest. Checked before DIRECT: dependency-scanner
    # findings (Trivy/OSV/npm-audit/pip-audit) are commonly package-level
    # with no meaningful line number, and vapt.py's own parsers reflect
    # that (line=None) — without this ordering, "no line number" would
    # fall through to DIRECT's "overlaps the file as a whole" rule and
    # misreport every dependency finding as DIRECT instead of DEPENDENCY.
    # Can't reliably tell "newly introduced by this PR" from "pre-existing
    # in an unchanged part of the lockfile" without diffing resolved
    # versions (out of scope here) — MEDIUM confidence, HIGH only when the
    # finding's own file is the exact file the PR changed.
    dependency_files = {seed.file for seed in seeds if seed.seed_type == "DEPENDENCY"}
    tool = str(finding.get("tool") or finding.get("source") or "").lower()
    if dependency_files and tool in _DEPENDENCY_SCANNER_TOOLS:
        exact_file_match = file_path in dependency_files
        return CorrelatedFinding(
            finding, fingerprint, RELATION_DEPENDENCY,
            CONFIDENCE_HIGH if exact_file_match else CONFIDENCE_MEDIUM,
            affected_path=sorted(dependency_files),
            reason=(
                f"{tool} finding in the dependency manifest the PR changed ({file_path})."
                if exact_file_match else
                f"{tool} reports a dependency vulnerability while the PR changed {', '.join(sorted(dependency_files))}; "
                "not confirmed as newly introduced by this change (no version-level diff performed)."
            ),
        )

    # 2. DIRECT — the finding's location overlaps a hunk the PR itself
    # changed. Unambiguous: this is text-range overlap, not inference.
    direct_ranges = _hunk_new_line_ranges(diff)
    if file_path in direct_ranges and _line_in_ranges(line, direct_ranges[file_path]):
        return CorrelatedFinding(
            finding, fingerprint, RELATION_DIRECT, CONFIDENCE_HIGH,
            affected_path=[file_path],
            reason=f"Finding at {file_path}{f':{line}' if line else ''} overlaps code the PR directly modified.",
        )

    # 3. Graph-reachable — the finding's location matches a node the
    # impact graph reached from a changed symbol (depth > 0, i.e. not
    # itself a seed). Split INDIRECT vs EXISTING_NEWLY_EXPOSED by whether
    # the reaching seed added new code (a genuinely new execution path)
    # versus merely modified something already on an existing path.
    seed_ids = {seed.symbol_id for seed in seeds if seed.symbol_id}
    matching_nodes = [
        node for node in graph.nodes.values()
        if node.path == file_path and node.id not in seed_ids
        and (line is None or node.depth > 0)
    ]
    if matching_nodes:
        target = matching_nodes[0]
        path_names = _reconstruct_path(graph, seed_ids, target.id)
        # Does the path originate from newly added code (a genuinely new
        # execution path), rather than an existing one the PR merely
        # touched? _reconstruct_path always starts from whichever seed the
        # BFS reached the target from first, so checking its first element
        # against the set of ADDED seed names is enough.
        added_seed_names = {seed.symbol_name for seed in seeds if seed.change_status == "ADDED" and seed.symbol_name}
        originates_from_added_code = bool(path_names) and path_names[0] in added_seed_names

        if originates_from_added_code:
            return CorrelatedFinding(
                finding, fingerprint, RELATION_EXISTING_NEWLY_EXPOSED, CONFIDENCE_MEDIUM,
                affected_path=path_names or [file_path],
                reason=(
                    f"Pre-existing finding at {file_path} is reachable from newly added code "
                    f"({' -> '.join(path_names) if path_names else 'new execution path'}) — "
                    "the PR appears to newly expose it rather than merely touch it."
                ),
            )
        return CorrelatedFinding(
            finding, fingerprint, RELATION_INDIRECT, CONFIDENCE_MEDIUM,
            affected_path=path_names or [file_path],
            reason=(
                f"Finding at {file_path} lies on an existing execution path reachable from PR-changed code "
                f"({' -> '.join(path_names) if path_names else 'via the repository call graph'})."
            ),
        )

    # 4. EXISTING_RELEVANT — same file/security-context surfaced by the
    # impact graph's file set (e.g. via ast-grep security-context tagging)
    # but no confirmed call-graph edge connects it. Weakest signal kept.
    if file_path in graph.files:
        return CorrelatedFinding(
            finding, fingerprint, RELATION_EXISTING_RELEVANT, CONFIDENCE_LOW,
            affected_path=[file_path],
            reason=f"{file_path} is part of the PR's security-relevant impact context, but no confirmed call path connects it to the change.",
        )

    # 5. UNRELATED — no connection found by any of the above.
    return CorrelatedFinding(
        finding, fingerprint, RELATION_UNRELATED, CONFIDENCE_LOW,
        reason="No connection to the PR's changed files, impact graph, or dependency changes was found.",
    )


def correlate_findings(
    findings_with_fingerprints: list[tuple[dict, str]],
    *,
    diff: PullRequestDiff,
    seeds: list[PRImpactSeed],
    graph: ImpactGraph,
) -> list[CorrelatedFinding]:
    return [
        correlate_finding(finding, fingerprint, diff=diff, seeds=seeds, graph=graph)
        for finding, fingerprint in findings_with_fingerprints
    ]


_CONFIDENCE_RANK = {CONFIDENCE_LOW: 0, CONFIDENCE_MEDIUM: 1, CONFIDENCE_HIGH: 2}
_CONFIDENCE_BY_RANK = {value: key for key, value in _CONFIDENCE_RANK.items()}


def merge_correlated_findings(correlated: list[CorrelatedFinding]) -> list[CorrelatedFinding]:
    """Deduplicate by fingerprint ONLY — never by similar-looking titles
    (PHASE 22 is explicit about this). When the same fingerprint was
    produced independently by more than one source (e.g. a deterministic
    scanner and the LLM PR review both flag the same code), keep one
    finding, record every contributing source, and raise confidence one
    step (capped at HIGH) — independent agreement is itself evidence, but
    still bounded, not an automatic HIGH regardless of what either source
    reported alone."""
    by_fingerprint: dict[str, CorrelatedFinding] = {}
    order: list[str] = []
    for item in correlated:
        existing = by_fingerprint.get(item.fingerprint)
        if existing is None:
            by_fingerprint[item.fingerprint] = item
            order.append(item.fingerprint)
            continue
        existing_sources = {str(existing.finding.get("source") or existing.finding.get("tool") or "")}
        new_source = str(item.finding.get("source") or item.finding.get("tool") or "")
        if new_source and new_source not in existing_sources:
            merged_sources = sorted(existing_sources | {new_source} - {""})
            existing.finding = {**existing.finding, "sources": merged_sources}
            best_rank = max(_CONFIDENCE_RANK.get(existing.relation_confidence, 0), _CONFIDENCE_RANK.get(item.relation_confidence, 0))
            existing.relation_confidence = _CONFIDENCE_BY_RANK[min(best_rank + 1, 2)]
            existing.reason = f"{existing.reason} Independently corroborated by {new_source}."
    return [by_fingerprint[fp] for fp in order]
