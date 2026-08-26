# Multi-Chapter, Graph-Based Wiki — Phased Plan & Status

## Context

The wiki used to be one flat AI-generated page per project/repo. A competitor's
product showed a DeepWiki/GraphRAG-style wiki instead: a sidebar tree of
chapters/sub-chapters, a persona table ("Who uses this product"), per-persona
reading paths, named cross-service "loops" grounded in real call/data edges, a
cross-service activity stat table, and a "What's NOT in this wiki (and why)"
section. This doc tracks the redesign toward that shape.

Full original plan (exploration notes, alternatives considered, detailed
rationale): `~/.claude/plans/eventual-twirling-thacker.md` (outside the repo —
copy it in if you need the full reasoning; this doc is the day-to-day
continuation reference).

**Architecture**: two-pass, **code-clustered / LLM-summarized**. Clustering
and cross-repo edge-matching are deterministic code (cheap, fast, fully
testable). LLM calls are reserved for per-chapter narrative prose (Pass 1)
and — in phase 2 — one cross-chapter synthesis pass. This keeps LLM call
volume proportional to chapter count (~7–13 calls for a typical 2-repo
project), not proportional to symbol count.

The existing flat wiki (`app/services/wiki_generator.py`, `project_wiki_pages`
table) is **never removed** — it's the permanent default and the fallback for
small repos.

---

## Phase 1 — DONE ✅ (backend + frontend, 529 backend tests passing, frontend builds clean)

### Backend
- **`app/services/wiki_chapters.py`** (new) — Pass 0, fully deterministic, no LLM:
  - `resolve_cross_repo_edges()` — matches frontend `api_call_site` symbols to
    backend `api_route` symbols by HTTP method + normalized path template
    (exact match only, no fuzzy matching — precision over recall)
  - `cluster_repo_chapters()` — seeds from `api_route`/`class`/`data_model`
    symbols, union-find merge over `build_impact_graph()` neighborhoods, an
    "Other / Supporting Code" catch-all so nothing is silently dropped, a
    `MIN_SEEDS_FOR_CHAPTERING` fallback (repo too small → no chapters, keep
    serving its flat page)
  - `build_chapter_set()` / `generate_and_persist_chapter_wiki()` — Pass 0 +
    Pass 1 orchestration, persists via new DB CRUD
- **`app/services/repo_intelligence.py`**:
  - New `api_call_site` symbol extraction for JS/TS (`_extract_js_api_calls`,
    covers `getJSON`/`postJSON`/etc., `axios.*`, `fetch(...)`)
  - `chapter_intelligence_prompt()` — same budgeted-artifact rendering as
    `intelligence_prompt()`, scoped to one chapter's symbol subset
  - `INDEX_VERSION` bumped 4 → 5 (cached indexes need `api_call_site` data)
- **`app/services/wiki_generator.py`**:
  - `generate_chapter_wiki()` (Pass 1) — one LLM call per top-level chapter,
    batched with its sub-chapters. **Reuses the exact same
    `_grounding_violations`/`_grounded_sections` citation-validation
    machinery as the flat wiki** — same anti-hallucination guarantee, no new
    trust surface.
  - `CHAPTER_WIKI_SYSTEM` / `build_chapter_wiki_message()` in `prompt.py`
- **`app/services/database.py`** — new tables (additive, `project_wiki_pages`
  untouched):
  - `wiki_chapter_sets` (one project-level build, versioned via `is_current`)
  - `wiki_chapters` (self-referencing tree, `parent_id` NULL = top-level,
    `sections_json` reuses the flat page's `{heading,body,evidence}` shape)
  - `wiki_synthesis` (schema only — phase 2 populates this)
  - `project_settings.chapter_wiki_enabled` (default `false`, per-project opt-in)
- **`app/api/projects.py`**:
  - `GET /projects/{id}/wiki-chapters` — fetch the current chapter tree (404
    if never built)
  - `POST /projects/{id}/wiki-chapters/generate` (sync) and
    `/generate-job` (background job, reuses existing job/SSE infra) — 403 if
    `chapter_wiki_enabled` is off, 502 if no repos linked

### Frontend
- **`frontend/src/components/projects/ChapterWikiSection.tsx`** (new) —
  self-gating (renders `null` when `chapter_wiki_enabled` is off) recursive
  tree-nav, mounted unconditionally next to the existing flat `WikiSection` in
  `App.tsx`
- **`frontend/src/components/projects/ProjectSettingsModal.tsx`** — new
  "Wiki" settings section with the enable/disable checkbox
- New types in `frontend/src/types/index.ts`: `WikiChapter`,
  `ProjectWikiChapterSet`, `CrossRepoEdge`; `WikiPageSection.evidence?`;
  `ProjectSettings.chapter_wiki_enabled`
- New API client functions in `frontend/src/api/client.ts`:
  `getProjectChapterWiki`, `generateProjectChapterWiki`

### Verified
- 529 backend tests pass (`python -m pytest -q`), including new
  `tests/test_wiki_chapters.py`, `tests/test_wiki_chapter_generation.py`,
  `tests/test_wiki_chapters_api.py`
- `tsc -b && vite build` succeeds clean (also fixed a stale `Coins` type
  reference in `UsageTab.tsx` left over from an earlier fix that was
  silently breaking the production build — `npm run build`, not just
  `tsc --noEmit`, is what catches that class of issue)

### Not yet done from phase 1's own scope
- **Never run against a real project end-to-end** (only synthetic fixtures +
  API-layer tests with a stub provider). Before trusting this for real:
  enable `chapter_wiki_enabled` on a real project with 2+ linked repos and
  actually hit `POST /wiki-chapters/generate` against a real LLM provider —
  the same live-verification rigor used earlier in this session on the flat
  wiki (that's how the `dataTables`-folder vendor-citation false positive
  and the `INDEX_VERSION` cache-staleness issues got caught, not test
  fixtures alone). **Do this first tomorrow.**

---

## Phase 2 — NOT STARTED

Synthesis pass (`wiki_synthesis` table, schema already exists):

1. **`generate_wiki_synthesis()`** (new, in `wiki_generator.py`) — one LLM
   call per project. Input: every chapter/sub-chapter's *title + summary
   only* (not full bodies — keep this call small), plus the real
   `cross_repo_edges` from `wiki_chapter_sets` (already computed in Pass 0,
   not model-generated). Output: `{personas, cross_service_loops, not_covered}`.
2. **Personas + reading paths** — model reasons over chapter titles/summaries,
   references chapter ids for `reading_path`; validate every referenced id
   actually exists (deterministic post-check, same repair-on-mismatch pattern
   as `_repair_invalid_json`).
3. **Cross-service loops** — model narrates the *real* `cross_repo_edges`
   (closed-world set from Pass 0), grounding check = "every cited edge is a
   subset of the real edge list" (stronger and cheaper than free-text
   citation regex matching).
4. **Activity stats table** — **not LLM-generated at all**: a pure
   `GROUP BY (edge_kind, source_repo, target_repo) COUNT(*)` over the Pass-0
   edge list, computed in code.
5. **"What's NOT in this wiki"** — seed the prompt with code-derived
   exclusions (repos with zero seeds, known unresolved cross-repo edge types
   from phase 1's stated limitations — cross-repo data-model matching,
   cross-repo `imports`) as must-include items; let the model add narrative
   judgment on top.
6. **Frontend**: `WikiPersona`/`WikiCrossServiceLoop`/`WikiActivityStat`/
   `WikiSynthesis` types (sketched in the original plan, not yet added),
   persona table component, reading-path component, cross-service-loops
   component, "not covered" callout — all additive to `ChapterWikiSection.tsx`.
7. **Incremental regeneration** — diff `seed_symbol_ids_json` against the
   current index; only re-run Pass 1 for chapters whose seeds actually
   changed. Reduces steady-state regen cost well below a full rebuild.

## Phase 3 — stretch, not committed

- Confidence-tiered cross-repo matching beyond exact method+path match
  (fuzzy/partial matches with a "possible" tag)
- Cross-repo data-model/shared-type matching (e.g. a TS interface ↔ a
  Pydantic model)
- Backfill tooling for existing flat-only projects (currently: no forced
  backfill, opt-in only)
- Tuning `MERGE_MIN_SHARED_NODES`/`MERGE_MIN_SHARED_FRACTION`/
  `MAX_TOP_LEVEL_CHAPTERS` from real usage data once phase 1 has run against
  a handful of real projects

---

## Quick resume checklist for tomorrow

1. `git status` / `git diff` to reload context on exactly what changed.
2. `python -m pytest -q` (expect 529 passing) and
   `cd frontend && npm run build` (expect clean) — confirm nothing drifted.
3. Enable `chapter_wiki_enabled` on a real project (2+ linked repos) and run
   a real end-to-end generation — the verification gap noted above.
4. Only after that: start phase 2 (`generate_wiki_synthesis`).
