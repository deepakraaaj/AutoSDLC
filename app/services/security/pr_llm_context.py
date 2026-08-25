"""Assemble the curated, budget-bounded text handed to run_pr_security_review
(app/services/langgraph_pipeline.py). Pure text assembly — no file I/O, no
network calls; the caller (main.py's PR scan orchestration) supplies
whatever source snippets it already read from the snapshot.

This is the one place PHASE 21's "do not send the entire repository to the
LLM" is enforced for the PR path — every section below is capped by
ContextBudget before being joined, and the whole result is capped again as
a final backstop.
"""
from __future__ import annotations

from app.services.security.baseline import BaselineSelection
from app.services.security.context_budget import ContextBudget, TruncationRecord
from app.services.security.correlation import RELATION_UNRELATED, CorrelatedFinding
from app.services.security.impact_graph import ImpactGraph
from app.services.security.pr_diff import PullRequestDiff
from app.services.security.pr_symbols import PRImpactSeed


def _execution_paths(graph: ImpactGraph, *, limit: int) -> list[str]:
    """One "A -> B -> C" string per seed showing what it reaches, built
    directly from the graph's own edges — the same paths correlation.py
    reconstructs per-finding, shown here at the seed level so the LLM sees
    the shape of the impact graph even before any specific finding."""
    seed_ids = set(graph.seeds)
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.kind in {"calls", "inherits"}:
            adjacency.setdefault(edge.source, []).append(edge.target)

    paths: list[str] = []
    for seed_id in graph.seeds:
        if seed_id not in graph.nodes:
            continue
        chain = [seed_id]
        visited = {seed_id}
        current = seed_id
        while len(chain) < 6:
            neighbors = [n for n in adjacency.get(current, []) if n not in visited]
            if not neighbors:
                break
            current = neighbors[0]
            visited.add(current)
            chain.append(current)
        if len(chain) > 1:
            paths.append(" -> ".join(graph.nodes[node_id].name for node_id in chain if node_id in graph.nodes))
        if len(paths) >= limit:
            break
    return paths


def build_pr_review_context(
    *,
    diff: PullRequestDiff,
    seeds: list[PRImpactSeed],
    graph: ImpactGraph,
    correlated_findings: list[CorrelatedFinding],
    baseline: BaselineSelection,
    budget: ContextBudget,
    truncation: TruncationRecord,
    snippets: dict[str, str] | None = None,
) -> str:
    """Curated text for PR_SECURITY_REVIEW_SYSTEM. Sections, in order: PR
    metadata, changed files/symbols, execution/security paths, security
    context tags, deterministic+correlated findings (excluding UNRELATED —
    per PHASE 20 the reviewer shouldn't see noise it's explicitly told not
    to report on), baseline note, changed code snippets."""
    lines: list[str] = []

    lines.append(f"## Pull Request #{diff.info.pull_request_id}: {diff.info.title or '(no title)'}")
    if diff.info.description:
        lines.append(diff.info.description[:2000])
    lines.append(f"{diff.info.source_branch} -> {diff.info.destination_branch} | base={diff.info.base_sha[:12]} head={diff.info.head_sha[:12]}")

    changed_files = [f for f in diff.files if f.status != "BINARY"][: budget.max_changed_files]
    if len(diff.files) > len(changed_files):
        truncation.note("changed_files_truncated", f"{len(diff.files) - len(changed_files)} changed file(s) omitted from LLM context")
    lines.append(f"\n## Changed files ({len(changed_files)})")
    for file_change in changed_files:
        lines.append(f"- [{file_change.status}] {file_change.path}" + (f" (was {file_change.old_path})" if file_change.old_path else ""))

    symbol_seeds = [s for s in seeds if s.seed_type == "SYMBOL" and s.symbol_name][: budget.max_changed_symbols]
    if symbol_seeds:
        lines.append(f"\n## Changed symbols ({len(symbol_seeds)})")
        for seed in symbol_seeds:
            lines.append(f"- [{seed.change_status}] {seed.file}: {seed.symbol_name} ({seed.detail})")

    non_code_seeds = [s for s in seeds if s.seed_type != "SYMBOL"]
    if non_code_seeds:
        lines.append(f"\n## Non-code changes ({len(non_code_seeds)})")
        for seed in non_code_seeds:
            lines.append(f"- [{seed.seed_type}] {seed.file}: {seed.detail}")

    paths = _execution_paths(graph, limit=min(20, budget.max_graph_nodes))
    if paths:
        lines.append(f"\n## Execution/security paths from changed code ({len(paths)})")
        lines.extend(f"- {path}" for path in paths)
    if graph.truncated:
        lines.append("(impact graph traversal was truncated by size limits — some deeper relationships may be missing)")

    security_tags = {node.name: sorted(node.tags) for node in graph.nodes.values() if node.tags}
    if security_tags:
        lines.append(f"\n## Security-relevant context ({len(security_tags)} symbols)")
        for name, tags in list(security_tags.items())[:60]:
            lines.append(f"- {name}: {', '.join(tags)}")

    relevant_findings = [item for item in correlated_findings if item.relation_to_pr != RELATION_UNRELATED][: budget.max_scanner_findings]
    if len(correlated_findings) > len(relevant_findings) + sum(1 for f in correlated_findings if f.relation_to_pr == RELATION_UNRELATED):
        truncation.note("scanner_findings_truncated", "some correlated deterministic findings omitted from LLM context")
    if relevant_findings:
        lines.append(f"\n## Deterministic scanner findings correlated to this PR ({len(relevant_findings)})")
        for item in relevant_findings:
            location = f"{item.finding.get('file', '?')}" + (f":{item.finding.get('start_line') or item.finding.get('line')}" if item.finding.get("start_line") or item.finding.get("line") else "")
            lines.append(
                f"- [{item.relation_to_pr}/{item.relation_confidence}] {item.finding.get('tool', 'scanner')} "
                f"{item.finding.get('rule_id', '')} at {location}: {item.finding.get('comment') or item.finding.get('title', '')} "
                f"| path: {' -> '.join(item.affected_path) if item.affected_path else 'n/a'} | {item.reason}"
            )

    lines.append(f"\n## Baseline\nSource: {baseline.source} | confidence: {baseline.confidence}" + (f" | commit: {baseline.commit_sha}" if baseline.commit_sha else ""))
    if baseline.source == "NONE":
        lines.append("No reliable baseline scan exists — do not claim a finding is newly introduced with certainty.")

    if snippets:
        lines.append(f"\n## Changed code")
        used = 0
        for path, text in snippets.items():
            if used >= budget.max_snippets:
                truncation.note("llm_input_truncated", "some code snippets omitted from LLM context")
                break
            clipped_lines = text.splitlines()[: budget.max_snippet_lines]
            lines.append(f"\n--- {path} ---")
            lines.append("\n".join(clipped_lines))
            used += 1

    text = "\n".join(lines)
    if len(text) > budget.max_llm_input_chars:
        text = text[: budget.max_llm_input_chars] + "\n\n[... truncated to fit context budget ...]"
        truncation.note("llm_input_truncated", "PR review context exceeded max_llm_input_chars and was truncated")
    return text
