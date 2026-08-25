"""Central limits for PR impact analysis — one place every stage (impact
graph, security-context enrichment, snippet collection, LLM prompt
assembly) reads its caps from, instead of each hardcoding its own. Mirrors
vapt.py's env-var-configurable-with-floor pattern (`max(floor, int(getenv))`)
so operators tune this the same way they already tune VAPT_* / WIKI_INDEX_*.

Nothing here truncates anything itself — each stage applies its own
relevant fields and is responsible for recording truncation on its own
output (e.g. ImpactGraph.truncated, PullRequestDiff.truncated). This module
only defines what "too much" means.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


def _int_env(name: str, default: str, floor: int = 1) -> int:
    return max(floor, int(os.getenv(name, default)))


@dataclass(frozen=True)
class ContextBudget:
    max_changed_files: int = 200
    max_changed_symbols: int = 300

    max_graph_depth: int = 3
    max_graph_nodes: int = 200
    max_graph_files: int = 100

    max_security_matches: int = 500

    max_snippets: int = 40
    max_snippet_lines: int = 60
    max_code_bytes: int = 60_000

    max_scanner_findings: int = 500

    max_llm_input_chars: int = 40_000


def default_budget() -> ContextBudget:
    return ContextBudget(
        max_changed_files=_int_env("PR_BUDGET_MAX_CHANGED_FILES", "200"),
        max_changed_symbols=_int_env("PR_BUDGET_MAX_CHANGED_SYMBOLS", "300"),
        max_graph_depth=_int_env("PR_BUDGET_MAX_GRAPH_DEPTH", "3"),
        max_graph_nodes=_int_env("PR_BUDGET_MAX_GRAPH_NODES", "200"),
        max_graph_files=_int_env("PR_BUDGET_MAX_GRAPH_FILES", "100"),
        max_security_matches=_int_env("PR_BUDGET_MAX_SECURITY_MATCHES", "500"),
        max_snippets=_int_env("PR_BUDGET_MAX_SNIPPETS", "40"),
        max_snippet_lines=_int_env("PR_BUDGET_MAX_SNIPPET_LINES", "60"),
        max_code_bytes=_int_env("PR_BUDGET_MAX_CODE_BYTES", "60000"),
        max_scanner_findings=_int_env("PR_BUDGET_MAX_SCANNER_FINDINGS", "500"),
        max_llm_input_chars=_int_env("PR_BUDGET_MAX_LLM_INPUT_CHARS", "40000"),
    )


@dataclass
class TruncationRecord:
    """Accumulated truncation flags for one PR scan — surfaced to the API
    result and, per the brief, never silently dropped. `reasons` carries a
    short human-readable note per truncation for observability/debugging."""
    diff_truncated: bool = False
    changed_files_truncated: bool = False
    changed_symbols_truncated: bool = False
    graph_truncated: bool = False
    security_matches_truncated: bool = False
    scanner_findings_truncated: bool = False
    llm_input_truncated: bool = False
    reasons: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []

    def note(self, field: str, reason: str) -> None:
        setattr(self, field, True)
        self.reasons.append(reason)

    @property
    def any_truncated(self) -> bool:
        return any([
            self.diff_truncated, self.changed_files_truncated, self.changed_symbols_truncated,
            self.graph_truncated, self.security_matches_truncated, self.scanner_findings_truncated,
            self.llm_input_truncated,
        ])

    def as_dict(self) -> dict:
        return {
            "diff_truncated": self.diff_truncated,
            "changed_files_truncated": self.changed_files_truncated,
            "changed_symbols_truncated": self.changed_symbols_truncated,
            "graph_truncated": self.graph_truncated,
            "security_matches_truncated": self.security_matches_truncated,
            "scanner_findings_truncated": self.scanner_findings_truncated,
            "llm_input_truncated": self.llm_input_truncated,
            "context_truncated": self.any_truncated,
            "reasons": self.reasons,
        }
