# Story Generator

AutoSDLC web app for turning a project brief into a structured backlog of epics, stories, and tasks.
It includes a FastAPI backend, a browser UI, local SQLite persistence, Excel export, and Redmine project/issue integration.

## Recent Improvements (May 2026)

### ✅ 3-Phase Generation Pipeline
**Replaced** single-pass + unreliable expansion with a deterministic 3-phase system:
- **Phase 1:** Extract 10-20 epics from brief (1 call)
- **Phase 2:** Generate 5-8 stories per epic (1 call/epic)
- **Phase 3:** Generate 4-6 tasks per story (1 call/epic)

**Result:** Guaranteed deep backlogs (10+ epics, 50+ stories, 200+ tasks) instead of shallow output.

### ✅ Fixed Critical Format String Bug
**Problem:** Python's `str.format()` was breaking Phase 2/3 by interpreting JSON examples as placeholders (`KeyError: '\n  "title"'`)

**Solution:** Escaped braces in system prompts: `{` → `{{` and `}` → `}}`

**Impact:** Phase 2/3 now work flawlessly. No more silent failures.

### ✅ Smart Rate Limit Handling
Added exponential backoff retry logic when hitting API rate limits (429):
- Retry 1: wait 5s
- Retry 2: wait 10s  
- Retry 3: wait 20s

**Result:** Gracefully handles Groq's rate limits without wasting tokens.

### ✅ Enhanced Error Logging & Validation
- Per-phase debug logs (what was parsed, what failed, why)
- Epic title/description validation
- Empty array detection with retries
- Provider error messages with context

### ✅ LMStudio Provider Added
Local LLM support as fallback (no rate limits):
```bash
AI_PROVIDER=lmstudio LMSTUDIO_BASE_URL=http://localhost:1234 uvicorn main:app --reload
```

---

## What it does

- Compiles structured briefs into epics, stories, and tasks
- Generates backlogs from free-form input or uploaded documents
- Lets you review and edit work in the browser
- Stores generations locally in SQLite
- Exports the backlog to Excel
- Lists Redmine projects and pushes generated issues into Redmine

## Project layout

- `main.py` - FastAPI app and HTTP endpoints
- `static/index.html` - Browser UI
- `rule_based_generator.py` - Deterministic backlog compiler
- `prompt.py` - Prompt assembly and brief preparation
- `export.py` - Excel export
- `redmine.py` - Redmine workspace and issue integration
- `database.py` - SQLite persistence
- `redmine-local/` - Local Redmine stack and project provisioning helpers

## Documentation

- `README.md` is the repo entry point.
- Active documentation belongs in [`docs/`](docs/README.md).
- `main` is the documentation source of truth for this repo.
- Do not use a long-lived separate documentation branch.

## Preparing project input

- For a brand-new project, start from [`docs/PROJECT_BRIEF_TEMPLATE.md`](docs/PROJECT_BRIEF_TEMPLATE.md).
- If you only have a rough idea, use [`prompts/IDEA_TO_PROJECT_BRIEF.md`](prompts/IDEA_TO_PROJECT_BRIEF.md) in an AI tool to turn it into the standard brief format.
- If you already have documents such as a PRD, spec, README, or notes, use [`prompts/EXTRACT_FROM_DOCS.md`](prompts/EXTRACT_FROM_DOCS.md).
- If you want to derive the brief from an existing codebase, use [`prompts/EXTRACT_FROM_REPO.md`](prompts/EXTRACT_FROM_REPO.md).

## Local setup

```bash
cd story-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Redmine setup

If you want to push work into Redmine, configure these values in `.env`:

```bash
REDMINE_URL=https://your-redmine.example.com
REDMINE_API_KEY=your_api_key_here
REDMINE_PROJECT_ID=your_project_identifier
REDMINE_EPIC_TRACKER_ID=Epic
REDMINE_STORY_TRACKER_ID=Story
REDMINE_TASK_TRACKER_ID=Task
```

For a local Redmine environment, see [`redmine-local/README.md`](redmine-local/README.md).

## Token Usage & Cost

For a typical document (e.g., MDM system brief with 13 epics):

| Phase | Calls | Output/Call | Total |
|-------|-------|------------|-------|
| Phase 1 (Epics) | 1 | ~2,000 tokens | ~2,000 tokens |
| Phase 2 (Stories) | 13 | ~3,000 tokens | ~39,000 tokens |
| Phase 3 (Tasks) | 13 | ~4,000 tokens | ~52,000 tokens |
| **TOTAL** | **27** | - | **~93,000 output tokens** |

**Input tokens:** ~80-100K  
**Total:** ~170-190K tokens per document

**Cost estimate** (Groq pricing):
- Output: $0.30 per 1M tokens → ~$0.028
- Input: $0.075 per 1M tokens → ~$0.006
- **Total: ~$0.03-0.04 per document (3-4 cents)**

### Optimize Token Usage
- Use shorter briefs → fewer tokens
- Test with Phase 1 only → ~$0.002 (gets epic structure)
- Reuse generation results → save on re-runs

## Tests

```bash
pytest
```
