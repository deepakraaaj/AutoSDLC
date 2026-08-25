"""Generic, bounded impact-graph traversal over a repo_intelligence
RepositoryIndex.

Not PR-specific: this module answers "starting from these symbols, what
else in the repository is reachable via calls/imports/inherits, within a
bounded depth/size budget" — a primitive reusable by PR impact analysis,
architecture questions, or any future agent that needs "what does changing
this affect." PR-specific framing (changed vs affected, DIRECT/INDIRECT/
etc.) belongs in a later PR-analysis module, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.repo_intelligence import (
    RepositoryIndex,
    Relation,
    Symbol,
    get_callees,
    get_callers,
    symbol_by_id,
    symbol_id,
)

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_NODES = 200
DEFAULT_MAX_FILES = 100


@dataclass
class ImpactNode:
    id: str
    path: str
    name: str
    kind: str
    depth: int
    # Populated later by security-context enrichment (see
    # enrich_with_security_context) — e.g. {"DATABASE", "AUTHORIZATION"}.
    tags: set[str] = field(default_factory=set)


@dataclass
class ImpactEdge:
    source: str
    target: str
    kind: str  # "calls" | "called_by" | "inherits" | "inherited_by"
    path: str
    line: int


@dataclass
class ImpactGraph:
    seeds: list[str]
    nodes: dict[str, ImpactNode]
    edges: list[ImpactEdge]
    files: set[str]
    truncated: bool  # hit max_nodes/max_files before the frontier was exhausted


def _inherit_neighbors(index: RepositoryIndex, node: Symbol) -> list[tuple[Symbol, str, Relation]]:
    """Same-file inherits partners for one symbol, as (neighbor, edge_kind,
    relation) triples — inherits relations record plain class-name text
    (see repo_intelligence.py), so matching stays file-scoped, same
    trade-off get_related_symbols already accepts."""
    found = []
    for relation in index.relations:
        if relation.kind != "inherits" or relation.path != node.path:
            continue
        if relation.source == node.name:
            for candidate in index.symbols:
                if candidate.name == relation.target:
                    found.append((candidate, "inherits", relation))
        elif relation.target == node.name:
            for candidate in index.symbols:
                if candidate.name == relation.source:
                    found.append((candidate, "inherited_by", relation))
    return found


def build_impact_graph(
    index: RepositoryIndex,
    seed_symbol_ids: list[str],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_files: int = DEFAULT_MAX_FILES,
) -> ImpactGraph:
    """Breadth-first traversal from `seed_symbol_ids` over calls (both
    directions) and same-file inherits, bounded by `max_depth`/`max_nodes`/
    `max_files`. Deterministic and terminating: a visited-set keyed by
    symbol id prevents both cycles (A -> B -> C -> A) and redundant
    re-traversal of a node reached by more than one path — each symbol is
    expanded at most once, at the depth it was first reached.
    """
    nodes: dict[str, ImpactNode] = {}
    edges: list[ImpactEdge] = []
    files: set[str] = set()
    truncated = False

    frontier: list[tuple[str, int]] = []
    for sid in seed_symbol_ids:
        symbol = symbol_by_id(index, sid)
        if not symbol or sid in nodes:
            continue
        nodes[sid] = ImpactNode(sid, symbol.path, symbol.name, symbol.kind, 0)
        files.add(symbol.path)
        frontier.append((sid, 0))

    head = 0
    while head < len(frontier):
        current_id, depth = frontier[head]
        head += 1
        if depth >= max_depth:
            continue
        current_symbol = symbol_by_id(index, current_id)
        if not current_symbol:
            continue

        neighbors: list[tuple[Symbol | None, str, str, str, int]] = []
        for relation in get_callers(index, current_id):
            source_symbol = symbol_by_id(index, relation.source)
            if source_symbol:
                neighbors.append((source_symbol, symbol_id(source_symbol), "called_by", relation.path, relation.line))
        for relation in get_callees(index, current_id):
            if relation.resolved and relation.resolved_target:
                target_symbol = symbol_by_id(index, relation.resolved_target)
                if target_symbol:
                    neighbors.append((target_symbol, relation.resolved_target, "calls", relation.path, relation.line))
        for neighbor_symbol, edge_kind, relation in _inherit_neighbors(index, current_symbol):
            neighbors.append((neighbor_symbol, symbol_id(neighbor_symbol), edge_kind, relation.path, relation.line))

        for neighbor_symbol, neighbor_id, edge_kind, path, line in neighbors:
            if len(nodes) >= max_nodes or len(files) >= max_files:
                truncated = True
                break
            edges.append(ImpactEdge(current_id, neighbor_id, edge_kind, path, line))
            if neighbor_id in nodes:
                continue
            nodes[neighbor_id] = ImpactNode(neighbor_id, neighbor_symbol.path, neighbor_symbol.name, neighbor_symbol.kind, depth + 1)
            files.add(neighbor_symbol.path)
            frontier.append((neighbor_id, depth + 1))
        if len(nodes) >= max_nodes or len(files) >= max_files:
            truncated = True
            break

    return ImpactGraph(seeds=list(seed_symbol_ids), nodes=nodes, edges=edges, files=files, truncated=truncated)


def enrich_with_security_context(graph: ImpactGraph, matches: list) -> None:
    """Tag graph nodes with security categories from
    related_code.find_security_context results (RelatedCodeMatch). A match
    tags a node when it's in the same file and, when the match carries a
    resolved `symbol` name, that name equals the node's own name — so a
    file-wide match (symbol=None, e.g. a module-level decorator) still
    tags every node in that file, while a symbol-attributed match only
    tags the specific node it was found inside. Mutates `graph.nodes` in
    place; does not ask the LLM to (re)discover any of this from raw source.
    """
    by_file: dict[str, list] = {}
    for match in matches:
        by_file.setdefault(match.file, []).append(match)
    for node in graph.nodes.values():
        for match in by_file.get(node.path, []):
            if match.symbol is None or match.symbol == node.name:
                node.tags.add(match.category)
