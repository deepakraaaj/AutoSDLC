"""Deterministic cleanup for LLM code-review findings.

The review prompt and verifier reduce noise, but they are still model calls.
This module is the hard backstop for recurring false-positive classes that
can be rejected from the review input itself.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "code_review_filter_rules.json"
RULES_PATH = Path(os.getenv("CODE_REVIEW_FILTER_RULES_PATH", str(DEFAULT_RULES_PATH)))
_MANIFEST_RE = re.compile(r"(?:^|\n)(?:--- |\+\+\+ |diff --git .*?)(?:[ab]/)?(?:package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml)\b", re.I)

_FALLBACK_POLICY = {
    "version": 1,
    "rules": [
        {
            "id": "unsupported_missing_dependency_claim",
            "text_any": [
                r"\b(?:not|isn'?t|missing|absent|without)\b.{0,80}\b(?:dependenc|package\.json|lockfile|installed|listed)\b",
                r"\bimport(?:ed)?\b.{0,80}\bmay not be installed\b",
            ],
            "requires_absent_context": "manifest_present",
        },
        {
            "id": "style_only_visual_speculation",
            "text_any": [r"\b(?:text-shadow|shadow|tooltip width|truncate|truncation|line-clamp|wrapping|visual inconsistency|polish|align properly|may not align)\b"],
            "text_none": [r"\b(?:accessib|keyboard|screen reader|aria|overlap|unreadable|unclickable|invalid dom|focus|contrast|fallback|overflow hidden)\b"],
        },
        {
            "id": "false_order_by_for_aggregate_determinism",
            "text_all": [
                r"\b(?:max|min)\s*\(|\bgroup by\b",
                r"\border by\b.{0,100}\bdetermin|determin.{0,100}\border by\b|lacks? an order by|without an order by",
            ],
            "text_none": [r"\b(?:non-grouped|non grouped|not grouped|non-aggregated|not aggregated|multiply rows|duplicates rows|monotonic|created_at|updated_at|business time|latest)\b"],
        },
        {
            "id": "endpoint_missing_claim_contradicted_by_contract_evidence",
            "text_any": [r"\b(?:backend|route|endpoint|api)\b.{0,120}\b(?:may not|might not|does not|not support|missing|not found)\b"],
            "requires_context": "matched_contract_path_in_finding",
        },
        {
            "id": "unsupported_id_recency_assumption_claim",
            "text_any": [
                r"\b(?:id order|MAX\(id\)|max id|id)\b.{0,160}\b(?:not monotonically increasing|not monotonic|does not reflect recency|stale|outdated|most recent|latest)\b",
                r"\b(?:location_level_id|MAX\(location_level_id\)|max location_level_id)\b.{0,160}\b(?:not monotonically increasing|not monotonic|does not reflect recency|stale|outdated|most recent|latest)\b",
            ],
            "requires_absent_context": "temporal_ordering_evidence_present",
        },
        {
            "id": "unsupported_timezone_claim_without_contract",
            "text_any": [
                r"\b(?:timezone|time zone|utc|local time|server time|day-end|day end|timestamp)\b.{0,220}\b(?:incorrect|invalid|wrong|block valid|allow invalid|different timezone|different time zone)\b",
                r"\b(?:incorrect|invalid|wrong|block valid|allow invalid)\b.{0,220}\b(?:timezone|time zone|utc|local time|server time|day-end|day end|timestamp)\b",
            ],
            "requires_context": "temporal_ui_context_present",
            "requires_absent_context": "timezone_contract_present",
        },
        {
            "id": "unproved_dynamic_label_requirement",
            "text_any": [
                r"\b(?:hardcoded|static)\b.{0,160}\b(?:label|title|tooltip|text|copy)\b.{0,160}\b(?:may not reflect|might not reflect|should vary|should be parameterized|intended dynamic)\b",
                r"\b(?:label|title|tooltip|text|copy)\b.{0,160}\b(?:should vary|should be parameterized|intended dynamic)\b",
            ],
            "text_none": [r"\b(?:requirement|spec|i18n|locali[sz]ation|translation|accessib|aria|wrong value|undefined|empty)\b"],
        },
        {
            "id": "unproved_pointer_events_speculation",
            "text_any": [
                r"\bpointer-events-(?:none|auto)\b.{0,220}\b(?:can cause|could cause|may cause|might cause|subtle interaction|captures pointer|capture pointer)\b",
                r"\b(?:can cause|could cause|may cause|might cause|subtle interaction|captures pointer|capture pointer)\b.{0,220}\bpointer-events-(?:none|auto)\b",
            ],
            "text_none": [r"\b(?:unclickable|cannot click|can't click|lost click|hover fails|keyboard|focus|disabled|covered|overlay|z-index)\b"],
        },
        {
            "id": "unproved_default_value_product_expectation",
            "text_any": [
                r"\bdefault\b.{0,180}\b(?:may not match|might not match|user expectations|product requirements|intended default|broader|historical)\b",
                r"\b(?:user expectations|product requirements|intended default)\b.{0,180}\bdefault\b",
            ],
            "text_none": [r"\b(?:requirement|spec|ticket|acceptance criteria|regression|previous default|before this change|crash|security|authorization)\b"],
        },
        {
            "id": "unproved_tostring_type_guard_claim",
            "text_any": [
                r"\btoString\(\).{0,320}\b(?:type is not verified|not verified|type guard|validation|could cause runtime errors|may cause runtime errors|incorrect behavior)\b",
                r"\b(?:type is not verified|not verified|type guard|validation|could cause runtime errors|may cause runtime errors|incorrect behavior)\b.{0,320}\btoString\(\)\b",
            ],
            "text_none": [r"\b(?:null|undefined|optional|unknown|any|union|number\s*\|\s*string|cannot read|TypeError|crash|test fixture|schema|interface|type alias)\b"],
        },
        {
            "id": "backend_claim_without_related_service_evidence",
            "text_any": [
                r"\b(?:backend|server|api|endpoint|route|contract|response shape|request parameter)\b.{0,220}\b(?:may not|might not|does not|not support|missing|not found|not confirmed|verify|confirm|unverified|compatible|compatibility|mismatch)\b",
                r"\b(?:may not|might not|does not|not support|missing|not found|not confirmed|verify|confirm|unverified|compatible|compatibility|mismatch)\b.{0,220}\b(?:backend|server|api|endpoint|route|contract|response shape|request parameter)\b",
            ],
            "requires_absent_context": "related_service_evidence_present",
            "text_none": [r"\b(?:throws|crash|TypeError|undefined is not|cannot read|test fixture|schema|dto|response model|controller|router|mapping)\b"],
        },
    ],
}


def _finding_text(finding: dict) -> str:
    values = [
        finding.get("comment"), finding.get("evidence"), finding.get("title"),
        finding.get("recommendation"), finding.get("verification"),
    ]
    return "\n".join(str(value) for value in values if value is not None)


def _matched_contract_paths(review_input: str) -> set[str]:
    paths: set[str] = set()
    for line in review_input.splitlines():
        line = line.strip()
        if not line.startswith("- ") or "matched in related-service evidence" not in line:
            continue
        path = line[2:].split(":", 1)[0].strip()
        if path.startswith("/"):
            paths.add(path)
    return paths


@lru_cache(maxsize=4)
def load_review_filter_policy(path: str | None = None) -> dict:
    target = Path(path) if path else RULES_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _FALLBACK_POLICY
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return _FALLBACK_POLICY
    return data


@lru_cache(maxsize=256)
def _compiled(pattern: str):
    return re.compile(pattern, re.I | re.S)


def _any_match(patterns: list[str], text: str) -> bool:
    return any(_compiled(pattern).search(text) for pattern in patterns)


def _all_match(patterns: list[str], text: str) -> bool:
    return all(_compiled(pattern).search(text) for pattern in patterns)


def _context_flags(review_input: str, text: str) -> dict[str, bool]:
    matched_paths = _matched_contract_paths(review_input)
    return {
        "manifest_present": bool(_MANIFEST_RE.search(review_input)),
        "matched_contract_path_in_finding": bool(matched_paths and any(path in text for path in matched_paths)),
        "temporal_ordering_evidence_present": bool(re.search(r"\b(?:created_at|updated_at|createdon|updatedon|modified_at|timestamp|event_time|transaction_time|effective_from|effective_to)\b", f"{review_input}\n{text}", re.I)),
        "temporal_ui_context_present": bool(re.search(r"\b(?:date|time|datetime|timestamp|calendar|picker|moment|dayjs|luxon)\b", review_input, re.I)),
        "timezone_contract_present": bool(re.search(r"\b(?:moment\.utc|utc\(|tz\(|moment-timezone|server timezone|server time zone|backend timezone|backend time zone|tenant timezone|tenant time zone|user timezone|user time zone|stored in utc|converted to utc|timezone offset|time zone offset)\b", review_input, re.I)),
        "related_service_evidence_present": "Related service repository evidence (read-only cross-check):" in review_input and "## Related repository:" in review_input,
    }


def _rule_matches(rule: dict, text: str, context: dict[str, bool]) -> bool:
    text_any = rule.get("text_any") if isinstance(rule.get("text_any"), list) else []
    text_all = rule.get("text_all") if isinstance(rule.get("text_all"), list) else []
    text_none = rule.get("text_none") if isinstance(rule.get("text_none"), list) else []
    if text_any and not _any_match(text_any, text):
        return False
    if text_all and not _all_match(text_all, text):
        return False
    if text_none and _any_match(text_none, text):
        return False
    required = rule.get("requires_context")
    if isinstance(required, str) and not context.get(required, False):
        return False
    absent = rule.get("requires_absent_context")
    if isinstance(absent, str) and context.get(absent, False):
        return False
    return bool(text_any or text_all)


def filter_code_review_findings(findings: list[dict], review_input: str) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    removed: list[dict] = []
    rules = load_review_filter_policy().get("rules", [])

    for finding in findings:
        text = _finding_text(finding)
        reason = None
        context = _context_flags(review_input, text)
        for rule in rules:
            if isinstance(rule, dict) and isinstance(rule.get("id"), str) and _rule_matches(rule, text, context):
                reason = rule["id"]
                break

        if reason:
            removed.append({**finding, "filtered_reason": reason})
        else:
            kept.append(finding)
    return kept, removed
