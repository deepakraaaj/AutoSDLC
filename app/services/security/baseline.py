"""Baseline selection + fingerprint comparison for PR security analysis.

Baseline priority (never "latest full scan globally" — that can belong to
an unrelated commit/branch and would misreport NEW/EXISTING):

  1. a successful FULL_REPOSITORY scan of the PR's exact base_commit_sha
  2. else the latest successful FULL_REPOSITORY scan of the PR's
     destination branch
  3. else no reliable baseline — comparison state is UNKNOWN, never a
     fabricated NEW/EXISTING claim.

baseline_state (NEW/EXISTING/UNKNOWN, this module) and relation_to_pr
(DIRECT/INDIRECT/.../EXISTING_NEWLY_EXPOSED, security/correlation.py) are
deliberately two separate dimensions — see the module-level note in
correlation.py and the plan's PHASE 18. A finding can be baseline_state
EXISTING and relation_to_pr EXISTING_NEWLY_EXPOSED at the same time; this
module only ever answers "was this fingerprint present in the baseline
scan", nothing about why it matters to the PR.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.database import (
    get_latest_full_repository_scan_for_branch,
    get_latest_full_repository_scan_for_commit,
    list_security_findings,
)

SOURCE_EXACT_BASE_COMMIT = "EXACT_BASE_COMMIT"
SOURCE_DESTINATION_BRANCH_LATEST = "DESTINATION_BRANCH_LATEST"
SOURCE_NONE = "NONE"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_NONE = "NONE"

STATE_NEW = "NEW"
STATE_EXISTING = "EXISTING"
STATE_RESOLVED = "RESOLVED"
STATE_UNKNOWN = "UNKNOWN"


@dataclass
class BaselineSelection:
    scan_id: int | None
    commit_sha: str | None
    source: str
    confidence: str


def select_baseline(repo_id: int, *, base_commit_sha: str | None, destination_branch: str | None) -> BaselineSelection:
    if base_commit_sha:
        exact = get_latest_full_repository_scan_for_commit(repo_id, base_commit_sha)
        if exact:
            return BaselineSelection(exact["id"], exact["commit_sha"], SOURCE_EXACT_BASE_COMMIT, CONFIDENCE_HIGH)
    if destination_branch:
        branch_scan = get_latest_full_repository_scan_for_branch(repo_id, destination_branch)
        if branch_scan:
            return BaselineSelection(branch_scan["id"], branch_scan["commit_sha"], SOURCE_DESTINATION_BRANCH_LATEST, CONFIDENCE_MEDIUM)
    return BaselineSelection(None, None, SOURCE_NONE, CONFIDENCE_NONE)


def baseline_fingerprints(baseline: BaselineSelection) -> set[str] | None:
    """None means "no reliable baseline exists" — distinct from an empty
    set (a real baseline scan that happened to find nothing). Callers must
    treat None as "comparison state is UNKNOWN", not "nothing existed"."""
    if baseline.scan_id is None:
        return None
    return {item["fingerprint"] for item in list_security_findings(baseline.scan_id) if item.get("fingerprint")}


def classify_against_baseline(fingerprint: str, fingerprints: set[str] | None) -> str:
    """NEW/EXISTING when a real baseline was available, UNKNOWN otherwise —
    never claim NEW with no baseline to compare against."""
    if fingerprints is None:
        return STATE_UNKNOWN
    return STATE_EXISTING if fingerprint in fingerprints else STATE_NEW


def resolved_fingerprints(baseline_fps: set[str] | None, current_fps: set[str]) -> set[str]:
    """Fingerprints present in the baseline but absent from the current
    scan — issues that appear to have been fixed. Empty (not meaningful)
    when there's no reliable baseline."""
    if baseline_fps is None:
        return set()
    return baseline_fps - current_fps
