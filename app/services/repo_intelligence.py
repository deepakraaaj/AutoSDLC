"""Deterministic repository indexing used to ground generated documentation
and — as of INDEX_VERSION 3 — security/PR-impact analysis.

Everything here is static parsing (`ast` for Python, regex for JS/TS/Java);
nothing in this module executes repository code, installs dependencies, or
runs a build. Callers are expected to hand it a path already produced by a
safe, non-executing snapshot (e.g. vapt.py's create_repository_snapshot).
"""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re

import bitbucket.client as bitbucket_client


SOURCE_EXTENSIONS = {".py", ".java", ".js", ".jsx", ".ts", ".tsx"}
CONFIG_NAMES = {"package.json", "pyproject.toml", "requirements.txt", "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env.example"}
IGNORED = {".git", ".venv", "venv", "node_modules", "dist", "build", "coverage", "vendor", "target", "__pycache__"}
MAX_INDEX_FILES = max(100, int(os.getenv("WIKI_INDEX_MAX_FILES", "5000")))
MAX_INDEX_BYTES = max(1_000_000, int(os.getenv("WIKI_INDEX_MAX_BYTES", "30000000")))
# Bumped from 2 -> 3: the index now carries `calls` relations and cross-file
# resolution (Relation.resolved/resolved_target/target_name/target_object).
# A stale cached index at the old version has none of that — callers that
# gate on this (app/api/projects.py's get_repository_index cache check) must
# treat it as missing rather than silently serving a call-graph-free index.
INDEX_VERSION = 3


def _is_vendored(path: Path, root: Path) -> bool:
    """Exclude checked-in third-party bundles from first-party intelligence."""
    relative = path.relative_to(root).as_posix().lower()
    name = path.name.lower()
    if ".min." in name or any(part in {"vendor", "vendors", "third_party", "third-party"} for part in Path(relative).parts):
        return True
    known_bundles = (
        "bootstrap", "jquery", "markerclusterer", "datatables", "datepicker",
        "font-awesome", "fontawesome", "popper",
    )
    return relative.startswith("public/markerclusterer") or (
        "/asset/" in f"/{relative}" and name.startswith(known_bundles)
    )


@dataclass
class Symbol:
    path: str
    name: str
    kind: str
    line: int
    end_line: int
    signature: str = ""
    parent: str | None = None


@dataclass
class Relation:
    source: str
    target: str
    kind: str
    path: str
    line: int
    # Populated for kind == "calls" (best-effort — see _python_call_target /
    # the JS/Java regex extraction below). target_object/target_name split
    # "service.get_user" into ("service", "get_user") so the resolution pass
    # has something more specific than the raw dotted text to match against.
    target_name: str | None = None
    target_object: str | None = None
    # Set by resolve_relations() when a `calls` target could be linked to a
    # specific indexed Symbol with reasonable confidence. Left unresolved
    # (resolved=False, resolved_target=None) rather than guessing — the raw
    # target/target_name/target_object are always kept either way, so an
    # unresolved call is never silently dropped.
    resolved_target: str | None = None
    resolved: bool = False


@dataclass
class RepositoryIndex:
    revision: str
    files: list[dict]
    symbols: list[Symbol]
    relations: list[Relation]
    artifacts: dict[str, str]
    stats: dict

    def as_dict(self) -> dict:
        return {
            "revision": self.revision,
            "files": self.files,
            "symbols": [asdict(item) for item in self.symbols],
            "relations": [asdict(item) for item in self.relations],
            "artifacts": self.artifacts,
            "stats": self.stats,
        }


def symbol_id(symbol: Symbol) -> str:
    """A symbol's stable identifier within one RepositoryIndex: file + name +
    declaration line. Line is included because names alone collide often
    (overloaded methods across classes, same helper name in two files) —
    this is what `calls` relations' resolved_target points at, and what
    get_callers/get_callees/get_related_symbols key off of."""
    return f"{symbol.path}::{symbol.name}@{symbol.line}"


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(args)})"


def _python_call_target(func: ast.expr) -> tuple[str | None, str | None, str | None]:
    """(raw_text, method_name, object_text) for a Call node's `func`
    expression. Handles the shapes the brief calls out: foo(), service.foo(),
    self.foo(), ClassName.foo(), module.foo(). Anything else that still
    round-trips through ast.unparse (e.g. a chained a.b.c()) is kept as raw
    text with no object/method split rather than discarded; a call whose
    target genuinely can't be rendered (exotic node shapes) is skipped."""
    if isinstance(func, ast.Name):
        return func.id, func.id, None
    if isinstance(func, ast.Attribute):
        try:
            text = ast.unparse(func)
        except Exception:
            text = func.attr
        object_text = None
        if isinstance(func.value, (ast.Name, ast.Attribute)):
            try:
                object_text = ast.unparse(func.value)
            except Exception:
                object_text = None
        return text, func.attr, object_text
    try:
        return ast.unparse(func), None, None
    except Exception:
        return None, None, None


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.symbols: list[Symbol] = []
        self.relations: list[Relation] = []
        self.parents: list[str] = []
        # Mirrors `parents` but holds each enclosing class/function's own
        # symbol_id (not just its name) — this is the "source" a call made
        # inside that scope is attributed to.
        self._scope_ids: list[str] = []

    def _symbol(self, node, kind: str, signature: str = "") -> Symbol:
        symbol = Symbol(self.path, node.name, kind, node.lineno, getattr(node, "end_lineno", node.lineno), signature, self.parents[-1] if self.parents else None)
        self.symbols.append(symbol)
        return symbol

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(base) for base in node.bases]
        kind = "data_model" if any(base.rsplit(".", 1)[-1] in {"Base", "BaseModel", "Model"} for base in bases) else "class"
        symbol = self._symbol(node, kind, f"class {node.name}({', '.join(bases)})")
        for base in bases:
            self.relations.append(Relation(node.name, base, "inherits", self.path, node.lineno))
        self.parents.append(node.name)
        self._scope_ids.append(symbol_id(symbol))
        self.generic_visit(node)
        self._scope_ids.pop()
        self.parents.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        decorators = [ast.unparse(item) for item in node.decorator_list]
        route = next((item for item in decorators if re.search(r"\.(get|post|put|patch|delete)\(", item)), None)
        symbol = self._symbol(node, "api_route" if route else ("method" if self.parents else "function"), route or _signature(node))
        self.parents.append(node.name)
        self._scope_ids.append(symbol_id(symbol))
        self.generic_visit(node)
        self._scope_ids.pop()
        self.parents.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Import(self, node: ast.Import) -> None:
        for name in node.names:
            self.relations.append(Relation(self.path, name.name, "imports", self.path, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        self.relations.append(Relation(self.path, module, "imports", self.path, node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        target_text, target_name, target_object = _python_call_target(node.func)
        if target_text:
            source = self._scope_ids[-1] if self._scope_ids else f"{self.path}::<module>"
            self.relations.append(Relation(
                source, target_text, "calls", self.path, node.lineno,
                target_name=target_name, target_object=target_object,
            ))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # `self.service = UserService(...)` — records what type an
        # instance attribute holds so resolve_relations can later work out
        # what `self.service.get_user()` actually calls (a call through an
        # attribute is otherwise indistinguishable from a call on an
        # unrelated local named "service"). Heuristic: only a Call whose
        # target reads as a class name (starts uppercase) is treated as a
        # constructor; not a type checker, just enough signal to link
        # `self.<attr>.<method>()` chains that vastly dominate real code.
        if isinstance(node.value, ast.Call):
            call_text, _, _ = _python_call_target(node.value.func)
            if call_text and call_text[:1].isupper():
                owner = self.parents[0] if self.parents else "<module>"
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in {"self", "cls"}:
                        self.relations.append(Relation(owner, call_text, "assigns_type", self.path, node.lineno, target_name=target.attr))
        self.generic_visit(node)


JS_SYMBOL = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
JS_ARROW = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^\n]*\)\s*=>", re.MULTILINE)
JS_IMPORT = re.compile(r"^\s*import(?:[\s\S]*?from\s*)?[\"']([^\"']+)[\"']", re.MULTILINE)
JS_ROUTE = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)[\"']", re.MULTILINE)
# Best-effort call detection: `foo(`, `service.foo(`, `a.b.foo(`. Deliberately
# not a JS parser (per the brief: "useful, not perfect") — false positives are
# filtered by excluding control-flow/declaration keywords and the position
# immediately after `function`/`class` (a declaration head, not a call).
JS_CALL = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(", re.MULTILINE)
_JS_CALL_STOPWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof",
    "new", "super", "import", "export", "constructor", "await", "yield",
    "in", "of", "instanceof", "throw", "delete", "void", "async",
}
JAVA_TYPE = re.compile(r"\b(?:public\s+)?(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.MULTILINE)
JAVA_ROUTE = re.compile(
    r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']",
    re.MULTILINE,
)
# `userService.getUser(`, `this.foo(` — lowerCamel object per Java field/local
# naming convention, or `this`. Static calls (ClassName.foo()) and calls on
# expressions aren't attempted; this is a heuristic, not a type resolver.
JAVA_CALL = re.compile(r"\b((?:this|[a-z][A-Za-z0-9_]*))\.([a-zA-Z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _nearest_scope_id(path: str, line: int, scope_candidates: list[Symbol]) -> str:
    """The last declared symbol (function/class, sorted by line) at or
    before `line` — the best available approximation of "what scope is this
    call inside" without real block-scope tracking. Falls back to a
    per-file module-level pseudo id when nothing precedes it, same as the
    Python visitor's `<module>` fallback."""
    enclosing: Symbol | None = None
    for candidate in scope_candidates:
        if candidate.line <= line:
            enclosing = candidate
        else:
            break
    return symbol_id(enclosing) if enclosing else f"{path}::<module>"


def _index_js(path: str, text: str) -> tuple[list[Symbol], list[Relation]]:
    symbols = [Symbol(path, match.group(1), "symbol", _line(text, match.start()), _line(text, match.start())) for pattern in (JS_SYMBOL, JS_ARROW) for match in pattern.finditer(text)]
    relations = [Relation(path, match.group(1), "imports", path, _line(text, match.start())) for match in JS_IMPORT.finditer(text)]
    for match in JS_ROUTE.finditer(text):
        line = _line(text, match.start())
        symbols.append(Symbol(path, f"{match.group(1).upper()} {match.group(2)}", "api_route", line, line, match.group(0)))

    scope_candidates = sorted((item for item in symbols if item.kind == "symbol"), key=lambda item: item.line)
    for match in JS_CALL.finditer(text):
        full = match.group(1)
        head = full.split(".", 1)[0].lower()
        if head in _JS_CALL_STOPWORDS:
            continue
        prefix = text[max(0, match.start() - 40):match.start()]
        if re.search(r"\b(?:function|class)\s*$", prefix):
            continue
        line = _line(text, match.start())
        target_object, separator, target_name = full.rpartition(".")
        relations.append(Relation(
            _nearest_scope_id(path, line, scope_candidates), full, "calls", path, line,
            target_name=target_name if separator else full, target_object=target_object or None,
        ))
    return symbols, relations


def _index_java(path: str, text: str) -> tuple[list[Symbol], list[Relation]]:
    symbols = [
        Symbol(path, match.group(1), "data_model" if "/model/" in f"/{path.lower()}" else "class", _line(text, match.start()), _line(text, match.start()))
        for match in JAVA_TYPE.finditer(text)
    ]
    relations = [Relation(path, match.group(1), "imports", path, _line(text, match.start())) for match in JAVA_IMPORT.finditer(text)]
    for match in JAVA_ROUTE.finditer(text):
        verb = "ANY" if match.group(1) == "Request" else match.group(1).upper()
        line = _line(text, match.start())
        symbols.append(Symbol(path, f"{verb} {match.group(2) or '/'}", "api_route", line, line, match.group(0)))

    scope_candidates = sorted((item for item in symbols if item.kind in {"class", "data_model"}), key=lambda item: item.line)
    for match in JAVA_CALL.finditer(text):
        target_object, target_name = match.group(1), match.group(2)
        line = _line(text, match.start())
        relations.append(Relation(
            _nearest_scope_id(path, line, scope_candidates), f"{target_object}.{target_name}", "calls", path, line,
            target_name=target_name, target_object=target_object,
        ))
    return symbols, relations


def _citation(symbol: Symbol) -> str:
    return f"{symbol.path}:{symbol.line}"


def _render_artifacts(files: list[dict], symbols: list[Symbol], relations: list[Relation]) -> dict[str, str]:
    modules = sorted({item["path"].split("/", 1)[0] for item in files})
    architecture = ["# Architecture", "", f"Indexed {len(files)} files across: {', '.join(modules[:20]) or 'repository root'}.", "", "## Key symbols"]
    for symbol in symbols[:80]:
        architecture.append(f"- `{symbol.name}` ({symbol.kind}) — `{_citation(symbol)}`")
    routes = [item for item in symbols if item.kind == "api_route"]
    api = ["# API reference", ""] + ([f"- `{item.name}` — `{_citation(item)}`" for item in routes] or ["No statically recognizable routes were found."])
    models = [item for item in symbols if item.kind == "data_model"]
    data = ["# Data model", ""] + ([f"- `{item.signature or item.name}` — `{_citation(item)}`" for item in models] or ["No statically recognizable data models were found."])
    dependencies = ["# Dependencies", ""] + [f"- `{item.source}` → `{item.target}` ({item.kind}) — `{item.path}:{item.line}`" for item in relations[:150]]
    source_index = json.dumps({"files": files, "symbols": [asdict(item) for item in symbols], "relations": [asdict(item) for item in relations]}, indent=2)
    return {"architecture.md": "\n".join(architecture) + "\n", "api-reference.md": "\n".join(api) + "\n", "data-model.md": "\n".join(data) + "\n", "dependencies.md": "\n".join(dependencies) + "\n", "source-index.json": source_index}


def _class_name_guess(identifier: str) -> str:
    """`userService` -> `UserService`. A naming-convention heuristic, not a
    type resolver — used only to propose resolution candidates, never to
    force one when it doesn't actually match an indexed symbol."""
    return identifier[:1].upper() + identifier[1:] if identifier else identifier


def resolve_relations(symbols: list[Symbol], relations: list[Relation]) -> None:
    """Best-effort cross-file linking of `calls` targets to indexed symbols.

    Mutates each `calls` Relation's resolved/resolved_target in place using,
    in order: the enclosing class for self/this calls (via the calling
    symbol's own `parent`), a class-name guess from the call's object text
    (`userService.getUser` -> class `UserService`, method `getUser`), and —
    for a bare call with no object — same-file symbols before repository-wide
    ones. Multiple remaining candidates are narrowed using the caller's
    file's `imports` relations as a tie-breaker. Anything still ambiguous is
    left unresolved (resolved=False) rather than guessed — this is the
    "prefer resolved=false over choosing the wrong symbol" contract the
    impact graph and caller/callee queries rely on.
    """
    by_id = {symbol_id(item): item for item in symbols}
    by_name: dict[str, list[Symbol]] = {}
    by_qualified: dict[tuple[str, str], list[Symbol]] = {}
    for item in symbols:
        by_name.setdefault(item.name, []).append(item)
        if item.parent:
            by_qualified.setdefault((item.parent, item.name), []).append(item)
    imports_by_path: dict[str, set[str]] = {}
    # (owning_class, attribute_name) -> constructed class name, from
    # `self.<attr> = ClassName(...)` assignments (_PythonVisitor.visit_Assign)
    # — what makes `self.service.get_user()` resolvable at all.
    attr_types: dict[tuple[str, str], str] = {}
    for relation in relations:
        if relation.kind == "imports":
            imports_by_path.setdefault(relation.path, set()).add(relation.target)
        elif relation.kind == "assigns_type" and relation.target_name:
            attr_types[(relation.source, relation.target_name)] = relation.target

    for relation in relations:
        if relation.kind != "calls" or not relation.target_name:
            continue
        candidates: list[Symbol] = []
        object_parts = relation.target_object.split(".") if relation.target_object else []
        if relation.target_object in {"self", "this"}:
            enclosing = by_id.get(relation.source)
            class_name = enclosing.parent if enclosing else None
            if class_name:
                candidates = by_qualified.get((class_name, relation.target_name), [])
        elif len(object_parts) == 2 and object_parts[0] in {"self", "this", "cls"}:
            # self.<attr>.<method>() — resolve <attr>'s constructed type
            # (attr_types) within the calling method's own class, then look
            # up <method> on that type. Left unresolved if the attribute's
            # type was never seen (e.g. assigned outside __init__ in a way
            # the heuristic doesn't cover, or attribute injected externally).
            enclosing = by_id.get(relation.source)
            class_name = enclosing.parent if enclosing else None
            attr_class = attr_types.get((class_name, object_parts[1])) if class_name else None
            if attr_class:
                candidates = by_qualified.get((attr_class, relation.target_name), [])
        elif relation.target_object:
            guess = _class_name_guess(relation.target_object)
            candidates = by_qualified.get((guess, relation.target_name), []) or by_qualified.get((relation.target_object, relation.target_name), [])
        else:
            same_file = [item for item in by_name.get(relation.target_name, []) if item.path == relation.path]
            candidates = same_file or list(by_name.get(relation.target_name, []))

        if len(candidates) > 1:
            imported = imports_by_path.get(relation.path, set())
            narrowed = [
                candidate for candidate in candidates
                if candidate.path == relation.path
                or any(token and (token in candidate.path or candidate.path.rsplit("/", 1)[-1].split(".")[0] == token.rsplit(".", 1)[-1]) for token in imported)
            ]
            if len(narrowed) == 1:
                candidates = narrowed

        if not candidates and relation.target_object:
            # No method-level match — JS/Java indexing doesn't extract
            # per-method symbols the way Python's AST visitor does, so
            # `userService.getUser` will never find a (class, "getUser")
            # pair there. Fall back to resolving at class granularity
            # (userService -> the UserService class itself) when that's
            # unambiguous — coarser than a method-level link, but it still
            # gives the impact graph real connectivity ("UserController
            # relates to UserService") instead of nothing.
            class_guess = _class_name_guess(object_parts[-1] if object_parts else relation.target_object)
            class_candidates = [item for item in by_name.get(class_guess, []) if item.kind in {"class", "data_model"}]
            if len(class_candidates) == 1:
                relation.resolved_target = symbol_id(class_candidates[0])
                relation.resolved = True
            continue

        if len(candidates) == 1:
            relation.resolved_target = symbol_id(candidates[0])
            relation.resolved = True


def symbol_by_id(index: RepositoryIndex, sid: str) -> Symbol | None:
    return next((item for item in index.symbols if symbol_id(item) == sid), None)


def get_callers(index: RepositoryIndex, sid: str) -> list[Relation]:
    """Resolved `calls` relations whose target is this symbol. Unresolved
    calls that *might* be callers are intentionally excluded — see
    resolve_relations' resolved=false contract."""
    return [item for item in index.relations if item.kind == "calls" and item.resolved and item.resolved_target == sid]


def get_callees(index: RepositoryIndex, sid: str) -> list[Relation]:
    """`calls` relations made from inside this symbol — resolved and
    unresolved alike (an unresolved callee is still evidence this symbol
    calls *something*, useful even without a linked target)."""
    return [item for item in index.relations if item.kind == "calls" and item.source == sid]


def get_related_symbols(index: RepositoryIndex, sid: str) -> list[Symbol]:
    """One-hop related symbols: resolved callers, resolved callees,
    same-file inherits partners, and same-file imports whose target's last
    path segment matches another indexed file's module name. Generic and
    reusable — no PR-specific logic — meant as the seed-expansion primitive
    for security analysis, code understanding, and impact analysis alike."""
    origin = symbol_by_id(index, sid)
    if not origin:
        return []
    related: dict[str, Symbol] = {}
    for relation in get_callers(index, sid):
        source_symbol = symbol_by_id(index, relation.source)
        if source_symbol:
            related[symbol_id(source_symbol)] = source_symbol
    for relation in get_callees(index, sid):
        if relation.resolved and relation.resolved_target:
            target_symbol = symbol_by_id(index, relation.resolved_target)
            if target_symbol:
                related[symbol_id(target_symbol)] = target_symbol
    for relation in index.relations:
        if relation.kind != "inherits" or relation.path != origin.path:
            continue
        counterpart_name = relation.target if relation.source == origin.name else (relation.source if relation.target == origin.name else None)
        if not counterpart_name:
            continue
        for candidate in index.symbols:
            if candidate.name == counterpart_name:
                related[symbol_id(candidate)] = candidate
    for relation in index.relations:
        if relation.kind != "imports" or relation.path != origin.path:
            continue
        module_hint = relation.target.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
        if not module_hint:
            continue
        for candidate in index.symbols:
            if candidate.path != origin.path and candidate.parent is None and candidate.path.rsplit("/", 1)[-1].split(".")[0] == module_hint:
                related[symbol_id(candidate)] = candidate
    return list(related.values())


def index_repository(root: Path, revision: str) -> RepositoryIndex:
    files: list[dict] = []
    symbols: list[Symbol] = []
    relations: list[Relation] = []
    total_bytes = 0
    failures = 0
    candidates = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and not any(part.lower() in IGNORED for part in path.relative_to(root).parts)
        and not _is_vendored(path, root)
    )
    for path in candidates[:MAX_INDEX_FILES]:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if total_bytes + size > MAX_INDEX_BYTES:
            continue
        total_bytes += size
        files.append({"path": relative, "size": size, "kind": "source" if path.suffix.lower() in SOURCE_EXTENSIONS else "config" if path.name.lower() in CONFIG_NAMES else "other"})
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".py":
                visitor = _PythonVisitor(relative)
                visitor.visit(ast.parse(text, filename=relative))
                symbols.extend(visitor.symbols)
                relations.extend(visitor.relations)
            elif path.suffix.lower() == ".java":
                found_symbols, found_relations = _index_java(relative, text)
                symbols.extend(found_symbols)
                relations.extend(found_relations)
            else:
                found_symbols, found_relations = _index_js(relative, text)
                symbols.extend(found_symbols)
                relations.extend(found_relations)
        except (OSError, SyntaxError, ValueError):
            failures += 1

    resolve_relations(symbols, relations)
    artifacts = _render_artifacts(files, symbols, relations)
    calls = [item for item in relations if item.kind == "calls"]
    stats = {
        "index_version": INDEX_VERSION, "files": len(files), "symbols": len(symbols),
        "relations": len(relations), "calls": len(calls),
        "resolved_calls": sum(1 for item in calls if item.resolved),
        "parse_failures": failures, "bytes": total_bytes,
    }
    return RepositoryIndex(revision, files, symbols, relations, artifacts, stats)


def snapshot_repository(config, destination: Path, ref: str = "HEAD") -> str:
    """Fetch a bounded, non-executing Bitbucket snapshot and return its content fingerprint."""
    queue = [""]
    seen = {""}
    paths: list[str] = []
    while queue and len(paths) < MAX_INDEX_FILES:
        current = queue.pop(0)
        for entry in bitbucket_client.list_repo_files(config, path=current, ref=ref):
            item = str(entry.get("path") or "").strip("/")
            if not item:
                continue
            if entry.get("type") == "commit_directory":
                if item.rsplit("/", 1)[-1].lower() not in IGNORED and item not in seen:
                    seen.add(item)
                    queue.append(item)
            elif entry.get("type") == "commit_file":
                paths.append(item)
                if len(paths) >= MAX_INDEX_FILES:
                    break

    total = 0
    fetched: dict[str, bytes] = {}
    workers = min(max(1, int(os.getenv("WIKI_INDEX_FETCH_WORKERS", "6"))), len(paths)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(bitbucket_client.get_file_content, config, path, ref): path for path in paths}
        for future in as_completed(futures):
            path = futures[future]
            try:
                raw = future.result().encode("utf-8", errors="replace")
            except Exception:
                continue
            if total + len(raw) > MAX_INDEX_BYTES:
                continue
            total += len(raw)
            fetched[path] = raw
    digest = __import__("hashlib").sha256()
    for path, raw in sorted(fetched.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(raw)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    if not fetched:
        raise RuntimeError("Repository snapshot contained no readable files")
    return f"snapshot-{digest.hexdigest()[:16]}"


def repository_index_from_dict(data: dict) -> RepositoryIndex:
    return RepositoryIndex(
        data["revision"], data["files"],
        [Symbol(**item) for item in data["symbols"]],
        [Relation(**item) for item in data["relations"]],
        data["artifacts"], data["stats"],
    )


def intelligence_prompt(index: RepositoryIndex, max_chars: int = 12000) -> str:
    parts = ["Deterministically extracted repository intelligence (claims include source citations):"]
    for name in ("architecture.md", "api-reference.md", "data-model.md", "dependencies.md"):
        parts.extend([f"\n## {name}", index.artifacts[name]])
    return "\n".join(parts)[:max_chars]
