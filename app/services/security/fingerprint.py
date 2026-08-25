"""Stable finding identity — deliberately NOT line-number-based.

vapt.py's own per-scanner `_finding()` fingerprint (app/services/vapt.py)
includes the line number, which is fine for that module's own same-scan
in-memory dedup (its only current use) but breaks the moment a later scan's
line numbers shift — exactly the case baseline comparison (security/
baseline.py) and PR-vs-repository correlation (security/correlation.py)
both depend on. This module is the fingerprint those two actually use;
vapt.py's own fingerprint is left untouched (no behavior change to the
working VAPT dedup logic it already has).
"""
from __future__ import annotations

import hashlib
import re


def normalize_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/").lstrip("./")


def normalize_context(text: str) -> str:
    """Collapse whitespace and case so a reformatted (but semantically
    identical) line of code, or a snippet re-captured with slightly
    different surrounding whitespace, still normalizes to the same string."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def compute_fingerprint(
    *,
    tool: str,
    rule_id: str,
    path: str,
    symbol: str | None = None,
    context: str = "",
    cwe: str | None = None,
    cve: str | None = None,
) -> str:
    """A finding's identity: tool + rule + normalized file path + symbol
    (when known) + normalized code context + CWE/CVE (when known).
    Deliberately excludes line number — a finding that only moved because
    unrelated lines above it shifted must keep the same identity, which is
    the entire point of fingerprinting over "tool+file+line"."""
    parts = [
        str(tool or ""), str(rule_id or ""), normalize_path(path),
        str(symbol or ""), normalize_context(context),
        str(cwe or ""), str(cve or ""),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:24]


def fingerprint_finding(finding: dict, symbol: str | None = None) -> str:
    """compute_fingerprint() from a vapt.py-shaped finding dict (tool,
    rule_id, file, evidence, identifiers, comment) — the common shape both
    deterministic scanner findings and normalized LLM findings are expected
    to carry (see security/correlation.py). CVE/CWE-style identifiers, when
    present, take priority over free-text evidence for the context
    component since they're the more stable signal (an advisory ID doesn't
    reformat the way a code snippet might)."""
    identifiers = finding.get("identifiers") or []
    cve = next((str(item) for item in identifiers if str(item).upper().startswith(("CVE-", "GHSA-"))), None)
    context = finding.get("evidence") or finding.get("comment") or ""
    if not context and identifiers:
        context = ",".join(str(item) for item in identifiers)
    return compute_fingerprint(
        tool=str(finding.get("tool") or finding.get("source") or ""),
        rule_id=str(finding.get("rule_id") or ""),
        path=str(finding.get("file") or ""),
        symbol=symbol or finding.get("symbol"),
        context=context,
        cwe=finding.get("cwe"),
        cve=cve,
    )
