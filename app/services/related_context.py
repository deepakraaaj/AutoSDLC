"""Cross-project retrieval — the part of the system that lets the generation
agent know what already exists elsewhere before it starts, without a
separate graph database. Queries the existing `epics`/`generations` SQLite
tables directly (app/services/database.py); there's nothing to sync,
because SQLite is already the durable store of every epic/story/task —
this module only ever reads.

(Previously backed by a Neo4j knowledge graph — dropped in favor of this:
the actual requirement was "the LLM knows what's already there," not a
graph database or a visualization, and that's fully achievable as a plain
SQL query with zero extra infrastructure.)
"""
from __future__ import annotations

import re
from collections import Counter

from app.services.database import get_connection
from app.utils.error_handler import log_debug, log_warning

# Small, deliberately short stopword list — this is keyword overlap for
# cross-project retrieval, not real NLP, so it only needs to filter out the
# words common enough to produce noise matches.
_STOPWORDS = {
    "about", "after", "before", "being", "between", "could", "every",
    "first", "should", "their", "there", "these", "those", "which",
    "while", "would", "system", "using", "where", "based", "other",
}


def _extract_keywords(text: str, limit: int = 8) -> list[str]:
    """Lightweight keyword extraction — no NLP dependency, just the most
    frequent non-trivial words. Good enough for a SQL LIKE match against
    epic titles/feature areas; a real embedding-based similarity search is
    a reasonable future upgrade but a materially bigger addition."""
    words = re.findall(r"[a-zA-Z]{5,}", text.lower())
    words = [w for w in words if w not in _STOPWORDS]
    if not words:
        return []
    return [word for word, _ in Counter(words).most_common(limit)]


def query_related_context(text: str, exclude_generation_id: int | None = None, limit: int = 10) -> list[dict]:
    """Cross-project by design (no project filter unless excluding the
    current generation on a re-run) — this is exactly the "does the system
    know about work elsewhere" query the LangGraph pipeline's
    graph_context node calls before generation. Fail-open: any DB error
    degrades to an empty result, never raises — this must never block
    generation."""
    keywords = _extract_keywords(text)
    if not keywords:
        return []

    like_conditions = " OR ".join(["(lower(e.title) LIKE ? OR lower(e.feature_area) LIKE ?)"] * len(keywords))
    params: list = []
    for keyword in keywords:
        pattern = f"%{keyword}%"
        params.extend([pattern, pattern])

    query = f"""
        SELECT DISTINCT g.id AS generation_id, g.project_name, e.ai_id, e.title, e.feature_area
        FROM epics e
        JOIN generations g ON g.id = e.generation_id
        WHERE ({like_conditions})
    """
    if exclude_generation_id is not None:
        query += " AND g.id != ?"
        params.append(exclude_generation_id)
    query += " LIMIT ?"
    params.append(limit)

    try:
        conn = get_connection()
        try:
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()
    except Exception as e:
        log_warning("RelatedContext", f"Query failed ({type(e).__name__}): {e}")
        return []

    log_debug("RelatedContext", f"query_related_context: {len(keywords)} keyword(s) -> {len(rows)} match(es)")
    return rows
