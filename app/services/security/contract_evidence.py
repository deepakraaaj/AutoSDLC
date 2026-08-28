"""Deterministic API-contract evidence for PR review context.

This module is intentionally cheap: it uses snippets plus the existing
RepositoryIndex symbols instead of embeddings. Its job is not to prove every
runtime contract; it gives the LLM explicit evidence so it can downgrade
"maybe the backend does not support this" from a fake bug to a contract risk.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.repo_intelligence import RepositoryIndex, Symbol


PATH_LITERAL = re.compile(r"""["'`]((?:/[A-Za-z0-9_./:{}-]+){2,})(?:[?"'`]|$)""")
METHOD_PATH = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(.+)$")


@dataclass
class EndpointEvidence:
    method: str | None
    path: str
    changed_file: str
    backend_matches: list[str]
    frontend_call_matches: list[str]
    classification: str


def _normalize_path(path: str) -> str:
    path = path.split("?", 1)[0].strip()
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    path = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "{}", path)
    path = re.sub(r"\{[^}/]+\}", "{}", path)
    return re.sub(r"/+", "/", path).rstrip("/") or "/"


def _symbol_method_path(symbol: Symbol) -> tuple[str | None, str | None]:
    match = METHOD_PATH.match(symbol.name)
    if match:
        return match.group(1), _normalize_path(match.group(2))
    route_match = re.search(r"\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]", symbol.signature)
    if route_match:
        return route_match.group(1).upper(), _normalize_path(route_match.group(2))
    return None, None


def _extract_changed_paths(snippets: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for changed_file, text in snippets.items():
        for match in PATH_LITERAL.finditer(text):
            path = _normalize_path(match.group(1))
            if len(path) < 2 or "." in path.rsplit("/", 1)[-1]:
                continue
            key = (changed_file, path)
            if key in seen:
                continue
            seen.add(key)
            found.append((changed_file, path))
    return found


def collect_contract_evidence(
    *,
    snippets: dict[str, str] | None,
    indexes: list[RepositoryIndex],
    max_items: int = 30,
) -> list[EndpointEvidence]:
    if not snippets or not indexes:
        return []

    backend_routes: list[tuple[str | None, str, Symbol]] = []
    frontend_calls: list[tuple[str | None, str, Symbol]] = []
    for index in indexes:
        for symbol in index.symbols:
            method, path = _symbol_method_path(symbol)
            if not path:
                continue
            if symbol.kind == "api_route":
                backend_routes.append((method, path, symbol))
            elif symbol.kind == "api_call_site":
                frontend_calls.append((method, path, symbol))

    evidence: list[EndpointEvidence] = []
    for changed_file, raw_path in _extract_changed_paths(snippets)[:max_items]:
        path = _normalize_path(raw_path)
        backend_matches = [
            f"{method or '*'} {symbol.path}:{symbol.line}"
            for method, route_path, symbol in backend_routes
            if route_path == path
        ][:8]
        frontend_matches = [
            f"{method or '*'} {symbol.path}:{symbol.line}"
            for method, call_path, symbol in frontend_calls
            if call_path == path and symbol.path != changed_file
        ][:8]
        if backend_matches:
            classification = "verified_backend_route"
        elif frontend_matches:
            classification = "frontend_pattern_only"
        else:
            classification = "contract_risk_unverified_route"
        evidence.append(EndpointEvidence(None, path, changed_file, backend_matches, frontend_matches, classification))
    return evidence


def render_contract_evidence(evidence: list[EndpointEvidence]) -> list[str]:
    if not evidence:
        return []
    lines = [f"\n## Branch/contract evidence ({len(evidence)} endpoint candidate(s))"]
    for item in evidence:
        lines.append(f"- {item.path} from {item.changed_file}: {item.classification}")
        if item.backend_matches:
            lines.append(f"  backend route evidence: {', '.join(item.backend_matches)}")
        if item.frontend_call_matches:
            lines.append(f"  matching frontend call sites: {', '.join(item.frontend_call_matches)}")
        if not item.backend_matches:
            lines.append("  review guidance: report as a contract risk only; do not call it a verified backend bug without route/schema evidence")
    return lines
