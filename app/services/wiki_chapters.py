"""Pass 0 of the multi-chapter wiki pipeline: deterministic, no-LLM chapter
derivation and cross-repo edge resolution. See the approved plan at
~/.claude/plans/eventual-twirling-thacker.md for the full design; this
module implements sections 1 (cross-repo entity graph) and 2 (chapter/
community derivation).

Nothing here calls an LLM or touches the network — it's pure computation
over already-indexed RepositoryIndex objects (app/services/repo_intelligence.py),
which is what makes it fully unit-testable and why it's kept separate from
Pass 1 (per-chapter LLM narrative generation, which belongs in
wiki_generator.py alongside the citation-grounding machinery it reuses).

Two responsibilities:

1. Cross-repo edge resolution — matches a frontend API-client call site
   (Symbol.kind == "api_call_site", extracted by repo_intelligence.py's
   _extract_js_api_calls) against a backend route handler
   (Symbol.kind == "api_route") by HTTP method + normalized path template.
   This is the one cross-repo edge type that's both common and mechanically
   detectable without a shared AST/runtime between repos — see
   resolve_cross_repo_edges(). Conservative by design: exact method + exact
   normalized-path match only, no fuzzy/partial matching. A missed edge is
   invisible; a wrong edge silently corrupts a cross-service narrative that
   the citation-grounding checker can't catch (both ends are individually
   real symbols, just wrongly paired) — precision over recall.

2. Chapter/community derivation — no clustering library is used (none is
   installed, and this app's per-repo symbol graphs are small/sparse enough
   that Louvain-style modularity optimization isn't worth the dependency).
   Instead: seed candidates from api_route/class/data_model symbols, run the
   existing build_impact_graph() BFS (app/services/security/impact_graph.py)
   from each seed, and union-find merge seeds whose neighborhoods
   substantially overlap. Every symbol not reached by any seed's BFS goes
   into a catch-all "Other / Supporting Code" chapter — never silently
   dropped, which is what the discarded `capability_areas` field in the
   flat wiki pipeline (wiki_generator.py) tried and failed to guarantee.

Clustering is strictly single-repo (build_impact_graph doesn't span repos);
cross-repo edges are recorded as chapter-set-level metadata for the phase 2
synthesis pass (personas/loops/activity stats), not used to force-merge
chapters across repos in phase 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.services.database import create_chapter, create_chapter_set, get_current_chapter_set, list_knowledge_entries, update_chapter_content
from app.services.repo_intelligence import RepositoryIndex, Symbol, chapter_intelligence_prompt, symbol_id
from app.services.security.impact_graph import build_impact_graph

# A repo with fewer than this many api_route/class/data_model symbols is too
# small to meaningfully cluster — callers should keep serving that repo's
# existing flat wiki page instead (plan §2's fallback). cluster_repo_chapters
# returns [] for such a repo rather than one degenerate mega-chapter.
MIN_SEEDS_FOR_CHAPTERING = 3

# BFS depth per seed when building its neighborhood for overlap comparison.
# Small on purpose: this is "what's immediately around this seed," not a
# full reachability sweep — a deep BFS would make nearly everything overlap
# with everything else in a densely-connected codebase.
CHAPTER_MAX_DEPTH = 2

# Two seeds merge into one chapter when their neighborhoods share at least
# this many nodes, OR this fraction of the smaller neighborhood, whichever
# is smaller (so two small neighborhoods that are mostly identical still
# merge, without requiring 3 shared nodes out of only 2).
MERGE_MIN_SHARED_NODES = 3
MERGE_MIN_SHARED_FRACTION = 0.3

# Hard cap on top-level chapters — beyond this, the smallest chapters (by
# member count) are merged into one "Other" chapter rather than paginating
# further. Sized for this app's actual scale (single-digit-to-low-teens
# api_route/class/data_model seeds per repo in practice), not a
# competitor's 66-sub-chapter target.
MAX_TOP_LEVEL_CHAPTERS = 12


# ── Path template normalization ─────────────────────────────────────────

_PLACEHOLDER = re.compile(r"\{[^}/]+\}|\$\{[^}/]+\}|:[A-Za-z_]\w*")


def normalize_path_template(path: str) -> tuple[str, ...]:
    """Collapse `{id}`/`${id}`/`:id`-style placeholders into one canonical
    token per segment, then split into segments. Two paths differing only in
    placeholder spelling normalize identically; a real segment-count or
    literal-segment difference does not (tuple equality on the result is
    the actual match test in resolve_cross_repo_edges — no separate
    length check is needed, tuple equality already requires equal length)."""
    cleaned = path.split("?", 1)[0].strip()
    cleaned = _PLACEHOLDER.sub("{param}", cleaned)
    return tuple(segment for segment in cleaned.split("/") if segment)


_DECORATOR_ROUTE = re.compile(r"\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_METHOD_PATH_NAME = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(\S.*)$", re.IGNORECASE)


def route_from_symbol(symbol: Symbol) -> tuple[str, str] | None:
    """(method, path) for an api_route Symbol, regardless of which
    language's indexer produced it. JS/Java routes store "METHOD /path" as
    the symbol name directly (repo_intelligence.py's JS_ROUTE/JAVA_ROUTE);
    Python's FastAPI-decorator routes instead store the function name as
    `name` and the decorator source (e.g. `router.post("/x")`) as
    `signature` (repo_intelligence.py's _visit_function) — parse that shape
    too, since this app's own backend is exactly this case."""
    match = _METHOD_PATH_NAME.match(symbol.name)
    if match:
        return match.group(1).upper(), match.group(2)
    match = _DECORATOR_ROUTE.search(symbol.signature or "")
    if match:
        return match.group(1).upper(), match.group(2)
    return None


def call_site_from_symbol(symbol: Symbol) -> tuple[str, str] | None:
    """(method, path) for an api_call_site Symbol — always "METHOD /path"
    as the name (see repo_intelligence.py's _extract_js_api_calls)."""
    match = _METHOD_PATH_NAME.match(symbol.name)
    return (match.group(1).upper(), match.group(2)) if match else None


def global_symbol_id(repo_id: int, symbol: Symbol) -> str:
    """Repo-qualified id used only in this cross-repo layer — the
    underlying repo_intelligence.symbol_id() stays repo-local on purpose
    (single-repo indexing/caching depends on that), so this is a thin
    wrapper composed only where multiple repos' symbols get compared."""
    return f"{repo_id}::{symbol_id(symbol)}"


# ── Cross-repo edge resolution ───────────────────────────────────────────

@dataclass
class CrossRepoEdge:
    kind: str
    source_repo_id: int
    target_repo_id: int
    source: str  # global_symbol_id of the frontend call site
    target: str  # global_symbol_id of the backend route
    source_path: str
    source_line: int
    target_path: str
    target_line: int
    method: str
    path_template: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source_repo_id": self.source_repo_id, "target_repo_id": self.target_repo_id,
            "source": self.source, "target": self.target,
            "source_path": self.source_path, "source_line": self.source_line,
            "target_path": self.target_path, "target_line": self.target_line,
            "method": self.method, "path_template": self.path_template,
        }


def resolve_cross_repo_edges(indexes: dict[int, RepositoryIndex]) -> list[CrossRepoEdge]:
    """Frontend call site -> backend route, matched by exact method + exact
    normalized path template, across DIFFERENT repos only (same-repo
    call/route relationships are already handled by repo_intelligence.py's
    own intra-repo resolve_relations()). See the module docstring for why
    this is deliberately conservative rather than fuzzy."""
    routes: list[tuple[int, Symbol, str, tuple[str, ...]]] = []
    call_sites: list[tuple[int, Symbol, str, tuple[str, ...]]] = []
    for repo_id, index in indexes.items():
        for sym in index.symbols:
            if sym.kind == "api_route":
                parsed = route_from_symbol(sym)
                if parsed:
                    routes.append((repo_id, sym, parsed[0], normalize_path_template(parsed[1])))
            elif sym.kind == "api_call_site":
                parsed = call_site_from_symbol(sym)
                if parsed:
                    call_sites.append((repo_id, sym, parsed[0], normalize_path_template(parsed[1])))

    edges: list[CrossRepoEdge] = []
    for call_repo_id, call_sym, call_method, call_template in call_sites:
        for route_repo_id, route_sym, route_method, route_template in routes:
            if route_repo_id == call_repo_id:
                continue
            if call_method != route_method or call_template != route_template:
                continue
            edges.append(CrossRepoEdge(
                kind="cross_repo_calls",
                source_repo_id=call_repo_id, target_repo_id=route_repo_id,
                source=global_symbol_id(call_repo_id, call_sym), target=global_symbol_id(route_repo_id, route_sym),
                source_path=call_sym.path, source_line=call_sym.line,
                target_path=route_sym.path, target_line=route_sym.line,
                method=call_method, path_template="/".join(call_template),
            ))
    return edges


# ── Chapter/community derivation ─────────────────────────────────────────

@dataclass
class ChapterNode:
    repo_id: int
    seed_symbol_ids: list[str]  # global ids of the seed(s) folded into this chapter
    member_symbol_ids: set[str] = field(repr=False, default_factory=set)  # repo-local ids, for overlap/coverage math only — not persisted
    children: list["ChapterNode"] = field(default_factory=list)


def _seed_symbols(index: RepositoryIndex) -> list[Symbol]:
    return [s for s in index.symbols if s.kind in {"api_route", "class", "data_model"}]


def cluster_repo_chapters(repo_id: int, index: RepositoryIndex) -> list[ChapterNode]:
    """Deterministic chapter derivation for one repo's symbols (module
    docstring, point 2). Returns top-level ChapterNodes (each may hold
    sub-chapter children); returns [] when the repo has too few seeds to
    meaningfully cluster (MIN_SEEDS_FOR_CHAPTERING) — the caller should fall
    back to the existing flat single-page wiki for that repo."""
    seeds = _seed_symbols(index)
    if len(seeds) < MIN_SEEDS_FOR_CHAPTERING:
        return []

    seed_ids = [symbol_id(s) for s in seeds]
    seed_by_id = {symbol_id(s): s for s in seeds}
    neighborhoods: dict[str, set[str]] = {
        sid: set(build_impact_graph(index, [sid], max_depth=CHAPTER_MAX_DEPTH).nodes.keys())
        for sid in seed_ids
    }

    parent: dict[str, str] = {sid: sid for sid in seed_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(seed_ids):
        for b in seed_ids[i + 1:]:
            shared = neighborhoods[a] & neighborhoods[b]
            smaller = min(len(neighborhoods[a]), len(neighborhoods[b])) or 1
            threshold = min(MERGE_MIN_SHARED_NODES, max(1, int(MERGE_MIN_SHARED_FRACTION * smaller)))
            if len(shared) >= threshold:
                union(a, b)

    groups: dict[str, list[str]] = {}
    for sid in seed_ids:
        groups.setdefault(find(sid), []).append(sid)

    chapters: list[ChapterNode] = []
    covered: set[str] = set()
    for members in groups.values():
        member_symbol_ids: set[str] = set()
        for sid in members:
            member_symbol_ids |= neighborhoods[sid]
        covered |= member_symbol_ids
        if len(members) == 1:
            chapters.append(ChapterNode(
                repo_id=repo_id, seed_symbol_ids=[global_symbol_id(repo_id, seed_by_id[members[0]])],
                member_symbol_ids=member_symbol_ids,
            ))
        else:
            sub_chapters = [
                ChapterNode(
                    repo_id=repo_id, seed_symbol_ids=[global_symbol_id(repo_id, seed_by_id[sid])],
                    member_symbol_ids=neighborhoods[sid],
                )
                for sid in members
            ]
            chapters.append(ChapterNode(
                repo_id=repo_id,
                seed_symbol_ids=[global_symbol_id(repo_id, seed_by_id[sid]) for sid in members],
                member_symbol_ids=member_symbol_ids, children=sub_chapters,
            ))

    if len(chapters) > MAX_TOP_LEVEL_CHAPTERS:
        chapters.sort(key=lambda c: len(c.member_symbol_ids), reverse=True)
        keep, overflow = chapters[:MAX_TOP_LEVEL_CHAPTERS - 1], chapters[MAX_TOP_LEVEL_CHAPTERS - 1:]
        overflow_seeds = [sid for chapter in overflow for sid in chapter.seed_symbol_ids]
        overflow_members: set[str] = set()
        for chapter in overflow:
            overflow_members |= chapter.member_symbol_ids
        chapters = keep + [ChapterNode(repo_id=repo_id, seed_symbol_ids=overflow_seeds, member_symbol_ids=overflow_members)]

    all_symbol_ids = {symbol_id(s) for s in index.symbols}
    orphaned = all_symbol_ids - covered
    if orphaned:
        # Catch-all — see module docstring. seed_symbol_ids intentionally
        # empty: nothing "seeded" this chapter, it's whatever was left over.
        chapters.append(ChapterNode(repo_id=repo_id, seed_symbol_ids=[], member_symbol_ids=orphaned))
    return chapters


def build_chapter_set(project_id: int, repo_indexes: dict[int, RepositoryIndex]) -> int:
    """Orchestrates Pass 0 for one project: cross-repo edge resolution +
    per-repo chapter clustering, persisted via database.create_chapter_set/
    create_chapter. Returns the new chapter_set id. A repo whose
    cluster_repo_chapters() returns [] contributes no chapters here —
    callers should keep serving that repo's existing flat wiki page."""
    cross_repo_edges = resolve_cross_repo_edges(repo_indexes) if len(repo_indexes) >= 2 else []
    source_revisions = {str(repo_id): index.revision for repo_id, index in repo_indexes.items()}
    chapter_set_id = create_chapter_set(project_id, source_revisions, [edge.as_dict() for edge in cross_repo_edges])

    order_index = 0
    for repo_id, index in repo_indexes.items():
        for chapter in cluster_repo_chapters(repo_id, index):
            _persist_chapter(chapter_set_id, chapter, parent_id=None, order_index=order_index)
            order_index += 1
    return chapter_set_id


def _persist_chapter(chapter_set_id: int, node: ChapterNode, *, parent_id: int | None, order_index: int) -> int:
    chapter_id = create_chapter(
        chapter_set_id, parent_id=parent_id, repo_id=node.repo_id,
        seed_symbol_ids=node.seed_symbol_ids, order_index=order_index,
    )
    for i, child in enumerate(node.children):
        _persist_chapter(chapter_set_id, child, parent_id=chapter_id, order_index=i)
    return chapter_id


# ── Pass 1 orchestration (one LLM call per top-level chapter) ───────────

def chapter_scope_symbol_ids(index: RepositoryIndex, global_seed_ids: list[str], repo_id: int) -> set[str]:
    """Repo-local symbol_id() strings for one chapter's neighborhood —
    re-derives the same BFS Pass 0 used from the chapter's persisted seeds
    (stripping their repo qualifier back off) rather than storing it, since
    it's cheap and deterministic to recompute. The "Other" catch-all
    chapter has no seeds (nothing seeded it, see cluster_repo_chapters) —
    its scope is simply every symbol in the repo; slightly more context
    than strictly needed, but correct and simple."""
    if not global_seed_ids:
        return {symbol_id(s) for s in index.symbols}
    prefix = f"{repo_id}::"
    local_seed_ids = [gid[len(prefix):] for gid in global_seed_ids if gid.startswith(prefix)]
    scope: set[str] = set()
    for sid in local_seed_ids:
        scope |= set(build_impact_graph(index, [sid], max_depth=CHAPTER_MAX_DEPTH).nodes.keys())
    return scope


def generate_and_persist_chapter_wiki(provider, project_id: int, project_name: str, repo_materials: list[dict]) -> dict | None:
    """Full Pass 0 + Pass 1 for one project. `repo_materials` is the same
    list app/api/projects.py's generate_project_wiki_endpoint already builds
    via _collect_repo_wiki_material — each dict's "repo_id"/"label"/
    "repository_index" keys are what this needs. Returns
    database.get_current_chapter_set()'s shape, or None if no repo yielded
    a usable RepositoryIndex (nothing to build from — same graceful-
    degradation contract the flat pipeline uses for an unreachable repo).

    One LLM call per top-level chapter (generate_chapter_wiki in
    wiki_generator.py, batched with that chapter's sub-chapters) — a repo
    too small to cluster (cluster_repo_chapters returned [] for it in
    build_chapter_set) simply contributes no chapters and no calls here."""
    repo_indexes = {m["repo_id"]: m["repository_index"] for m in repo_materials if m.get("repository_index") is not None}
    if not repo_indexes:
        return None
    label_by_repo_id = {m["repo_id"]: m["label"] for m in repo_materials}

    build_chapter_set(project_id, repo_indexes)
    stored = get_current_chapter_set(project_id)
    top_level = [c for c in stored["chapters"] if c["parent_id"] is None]
    children_by_parent = {}
    for c in stored["chapters"]:
        if c["parent_id"] is not None:
            children_by_parent.setdefault(c["parent_id"], []).append(c)

    # Local import: wiki_generator.py has no import of this module, so this
    # isn't a real cycle — kept local anyway so wiki_chapters.py (pure Pass
    # 0 logic + this orchestration) doesn't need wiki_generator's LangChain/
    # provider imports just to be imported for its deterministic pieces
    # (e.g. by tests that only exercise clustering).
    from app.services.wiki_generator import generate_chapter_wiki

    knowledge_entries = list_knowledge_entries(project_id)

    for chapter in top_level:
        repo_id = chapter["repo_id"]
        index = repo_indexes.get(repo_id)
        if index is None:
            continue
        scope = chapter_scope_symbol_ids(index, chapter["seed_symbol_ids"], repo_id)
        context = chapter_intelligence_prompt(index, scope)
        children = children_by_parent.get(chapter["id"], [])
        try:
            generated = generate_chapter_wiki(
                provider, project_name, label_by_repo_id.get(repo_id, "repository"), context, len(children),
                knowledge_entries=knowledge_entries,
            )
        except Exception:
            # One chapter failing (provider exhaustion, unrecoverable
            # grounding failure) shouldn't sink the rest of the chapter
            # set — same best-effort-per-unit spirit as
            # _collect_repo_wiki_material's per-repo try/except.
            continue
        if "sub_chapters" in generated:
            update_chapter_content(chapter["id"], generated["title"], generated["summary"], [])
            for child, sub in zip(children, generated["sub_chapters"]):
                update_chapter_content(child["id"], sub["title"], sub["summary"], sub["sections"])
        else:
            update_chapter_content(chapter["id"], generated["title"], generated["summary"], generated["sections"])
    return get_current_chapter_set(project_id)
