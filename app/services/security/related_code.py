"""Structural security-context search over a repository snapshot, using
ast-grep-py — the open-source-evaluation-selected supplement to
repo_intelligence.py, NOT a replacement for it and NOT a call graph.

repo_intelligence.py answers "what calls what" (symbols/calls/imports/
inherits). This module answers a different question: "where in the
repository does security-relevant *structure* appear" — auth checks,
database access, outbound HTTP, filesystem/command execution, and so on —
so the PR impact context builder can tag graph nodes/files with that
information instead of asking the LLM to rediscover it from raw source
(see PHASE 8 of the PR-impact-analysis plan).

Integration choice: the `ast-grep-py` Python binding (MIT license, mature —
see the open-source evaluation), not the `ast-grep` CLI over subprocess.
Every other scanner in this codebase (vapt.py) shells out to a CLI because
that's the only interface those tools expose; ast-grep-py ships a first-class
Python API, so going through subprocess here would just add process-spawn
overhead and stdout/JSON parsing for no benefit. It performs pure static
parsing — it does not execute the file it parses, install anything, or run a
build — consistent with vapt.py's "never execute repository content" rule.
This module still bounds its own work (file count, per-file size, total
matches, wall-clock deadline) since a pathological or adversarial file could
otherwise make parsing slow even without ever executing.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time
from pathlib import Path

from ast_grep_py import SgRoot

# Mirrors repo_intelligence.py's IGNORED set — kept as its own copy rather
# than importing it, since this module owns its own scan boundary
# independent of the code-intelligence indexer.
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "coverage", "vendor", "target", "__pycache__"}
_LANGUAGE_BY_SUFFIX = {".py": "python", ".java": "java", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "tsx"}

MAX_FILES = max(50, int(os.getenv("SECURITY_CONTEXT_MAX_FILES", "3000")))
MAX_BYTES_PER_FILE = max(10_000, int(os.getenv("SECURITY_CONTEXT_MAX_FILE_BYTES", "500000")))
MAX_MATCHES = max(50, int(os.getenv("SECURITY_CONTEXT_MAX_MATCHES", "2000")))
TIMEOUT_SECONDS = max(5, int(os.getenv("SECURITY_CONTEXT_TIMEOUT_SECONDS", "60")))

CATEGORIES = (
    "AUTHENTICATION", "AUTHORIZATION", "DATABASE", "EXTERNAL_HTTP", "FILESYSTEM",
    "COMMAND_EXECUTION", "DESERIALIZATION", "CRYPTOGRAPHY", "ROUTES",
    "TENANT_SECURITY", "INPUT_VALIDATION",
)

# (keyword, category) — matched as a case-insensitive substring of one
# structural match's text (a call `$FUNC($$$ARGS)` or, for Python, a
# decorator `@$DEC`). First match in this list wins. Deliberately a small,
# reviewable table rather than one ast-grep rule per framework/library per
# the brief's "do not create hundreds of rules initially" — ast-grep
# supplies the structural matching (real call/decorator expressions, not
# arbitrary substrings of the file), this table supplies the classification.
# More specific keywords are ordered first so they aren't shadowed by a
# broader one later in the list.
_KEYWORD_CATEGORIES: list[tuple[str, str]] = [
    ("checkpermission", "AUTHORIZATION"), ("check_permission", "AUTHORIZATION"),
    ("has_role", "AUTHORIZATION"), ("hasrole", "AUTHORIZATION"),
    ("has_permission", "AUTHORIZATION"), ("haspermission", "AUTHORIZATION"),
    ("is_admin", "AUTHORIZATION"), ("require_role", "AUTHORIZATION"), ("requirerole", "AUTHORIZATION"),
    ("requires_permission", "AUTHORIZATION"), ("permission_required", "AUTHORIZATION"),
    ("can_access", "AUTHORIZATION"), ("preauthorize", "AUTHORIZATION"), ("rbac", "AUTHORIZATION"),
    ("ownership", "AUTHORIZATION"),

    ("tenant", "TENANT_SECURITY"), ("workspace_id", "TENANT_SECURITY"), ("org_id", "TENANT_SECURITY"),

    ("jwt.decode", "AUTHENTICATION"), ("decode_token", "AUTHENTICATION"), ("verify_token", "AUTHENTICATION"),
    ("login_required", "AUTHENTICATION"), ("authenticate", "AUTHENTICATION"), ("oauth", "AUTHENTICATION"),
    ("passport", "AUTHENTICATION"), ("bearer", "AUTHENTICATION"), ("authorization_header", "AUTHENTICATION"),
    ("current_user", "AUTHENTICATION"), ("securitycontext", "AUTHENTICATION"), ("jwt", "AUTHENTICATION"),

    ("pickle.load", "DESERIALIZATION"), ("yaml.load", "DESERIALIZATION"), ("marshal.loads", "DESERIALIZATION"),
    ("objectinputstream", "DESERIALIZATION"), ("unserialize", "DESERIALIZATION"), ("readobject", "DESERIALIZATION"),

    ("hashlib", "CRYPTOGRAPHY"), ("md5", "CRYPTOGRAPHY"), ("sha1", "CRYPTOGRAPHY"), ("cipher", "CRYPTOGRAPHY"),
    ("encrypt", "CRYPTOGRAPHY"), ("decrypt", "CRYPTOGRAPHY"), ("messagedigest", "CRYPTOGRAPHY"),

    ("subprocess", "COMMAND_EXECUTION"), ("os.system", "COMMAND_EXECUTION"), ("os.popen", "COMMAND_EXECUTION"),
    ("runtime.exec", "COMMAND_EXECUTION"), ("runtime.getruntime", "COMMAND_EXECUTION"),
    ("processbuilder", "COMMAND_EXECUTION"), ("child_process", "COMMAND_EXECUTION"), ("shell_exec", "COMMAND_EXECUTION"),

    ("requests.", "EXTERNAL_HTTP"), ("httpx.", "EXTERNAL_HTTP"), ("urlopen", "EXTERNAL_HTTP"),
    ("fetch(", "EXTERNAL_HTTP"), ("axios.", "EXTERNAL_HTTP"), ("httpclient", "EXTERNAL_HTTP"),
    ("resttemplate", "EXTERNAL_HTTP"), ("webclient", "EXTERNAL_HTTP"),

    ("readfile", "FILESYSTEM"), ("writefile", "FILESYSTEM"), ("files.read", "FILESYSTEM"),
    ("files.write", "FILESYSTEM"), ("createreadstream", "FILESYSTEM"), ("createwritestream", "FILESYSTEM"),
    ("open(", "FILESYSTEM"),

    ("validate", "INPUT_VALIDATION"), ("sanitize", "INPUT_VALIDATION"), ("escape", "INPUT_VALIDATION"),

    (".execute(", "DATABASE"), (".executemany(", "DATABASE"), (".query(", "DATABASE"),
    ("find_by_id", "DATABASE"), ("findbyid", "DATABASE"), (".filter(", "DATABASE"),
    (".save(", "DATABASE"), (".insert(", "DATABASE"), (".update(", "DATABASE"),
    ("cursor.", "DATABASE"), ("session.query", "DATABASE"), ("raw_sql", "DATABASE"), ("rawquery", "DATABASE"),
]


@dataclass
class RelatedCodeMatch:
    category: str
    language: str
    file: str
    line: int
    symbol: str | None
    snippet: str
    pattern: str


def _classify(text: str) -> str | None:
    lowered = text.lower()
    for keyword, category in _KEYWORD_CATEGORIES:
        if keyword in lowered:
            return category
    return None


def _nearest_symbol_name(candidates: list, line: int) -> str | None:
    """`candidates` is one file's symbols, pre-sorted by line — same
    nearest-preceding-declaration heuristic repo_intelligence.py uses to
    attribute a regex-extracted call to its enclosing scope."""
    enclosing = None
    for candidate in candidates:
        if candidate.line <= line:
            enclosing = candidate
        else:
            break
    return enclosing.name if enclosing else None


def find_security_context(
    root: Path,
    *,
    index=None,
    max_files: int = MAX_FILES,
    max_matches: int = MAX_MATCHES,
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> list[RelatedCodeMatch]:
    """Scan a repository snapshot for security-relevant structural patterns.

    `index`, when given a repo_intelligence.RepositoryIndex, is used only to
    attribute a match to its nearest enclosing symbol name (best-effort,
    same heuristic as the JS/Java call extraction) — this function never
    reads or mutates the index itself.

    Static parsing only: no repository code is executed, no dependency is
    installed, no build runs. Bounded by file count, per-file byte size,
    total match count, and a wall-clock deadline, the same operational
    posture as every scanner in vapt.py — a pathological or adversarial
    snapshot degrades to a partial/truncated result, never an unbounded scan.
    """
    symbols_by_path: dict[str, list] = {}
    if index is not None:
        for symbol in sorted(index.symbols, key=lambda item: item.line):
            symbols_by_path.setdefault(symbol.path, []).append(symbol)

    deadline = time.monotonic() + timeout_seconds
    matches: list[RelatedCodeMatch] = []
    scanned = 0
    for path in sorted(root.rglob("*")):
        if scanned >= max_files or len(matches) >= max_matches or time.monotonic() > deadline:
            break
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.lower() in IGNORED_DIRS for part in relative_parts[:-1]):
            continue
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if not language:
            continue
        try:
            if path.stat().st_size > MAX_BYTES_PER_FILE:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            sg_root = SgRoot(text, language)
        except Exception:
            # A file ast-grep's parser chokes on (encoding oddity, a
            # language edge case, a truncated file) is skipped, not fatal —
            # same "best-effort per file" posture as vapt.py's snapshot
            # fallback fetch.
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        node = sg_root.root()
        # `$FUNC($$$ARGS)` matches both bare calls (foo()) and attribute
        # calls (service.foo()) as one node in Python/JS/TS's grammars, but
        # Java's `method_invocation` node only binds $FUNC for the bare
        # form — `object.method(...)` needs the separate two-part pattern
        # below to be found at all (verified empirically; not documented
        # ast-grep behavior we can rely on going in).
        patterns = ["$FUNC($$$ARGS)"]
        if language == "java":
            patterns.append("$OBJ.$METHOD($$$ARGS)")
        elif language == "python":
            patterns.append("@$DEC")
        for pattern in patterns:
            if len(matches) >= max_matches:
                break
            try:
                found = node.find_all(pattern=pattern)
            except Exception:
                continue
            for match in found:
                if len(matches) >= max_matches:
                    break
                snippet = match.text()
                category = _classify(snippet)
                if not category:
                    continue
                line = match.range().start.line + 1
                matches.append(RelatedCodeMatch(
                    category=category, language=language, file=relative, line=line,
                    symbol=_nearest_symbol_name(symbols_by_path.get(relative, []), line),
                    snippet=snippet[:240], pattern=pattern,
                ))
        if time.monotonic() > deadline:
            break
    return matches
