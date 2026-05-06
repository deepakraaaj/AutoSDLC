# Implementation Tasks: AutoSDLC Local MVP

**Epic:** Autonomous SDLC - Phase 0  
**Derived from:** USER_STORIES_autosdlc_mvp.md  
**Total complexity:** 45 base points (critical path) + 16 optional (nice-to-have)

---

## Critical Path: Bootstrap & Foundation

### Task 1.1: Set up project structure and dependencies

**Story:** Story 1 (Bootstrap architecture)  
**Type:** Setup  
**Complexity:** L (low)

**Description:**
Create the local project structure, initialize git, and define all Python dependencies. This is the foundation every other task depends on.

**Requirements:**

- [ ] Create directory structure:
  ```
  autosdlc-mvp/
  ├── bootstrap.py
  ├── retrieval_service.py
  ├── router_agent.py
  ├── eval_router.py
  ├── incremental_update.py
  ├── prompts.py
  ├── schemas.py
  ├── requirements.txt
  ├── README.md
  ├── review_queue/          (local, not in git)
  ├── eval_data/
  │   ├── feature_requests.json
  │   └── expected_routing.json
  ├── eval_results/          (local, not in git)
  └── tests/
      ├── test_bootstrap.py
      ├── test_retrieval.py
      ├── test_router.py
      └── test_eval.py
  ```

- [ ] Initialize git repo with reasonable .gitignore:
  ```
  review_queue/
  eval_results/
  __pycache__/
  .pytest_cache/
  .env
  *.egg-info/
  ```

- [ ] Create requirements.txt with dependencies:
  - google-cloud-aiplatform (Vertex AI SDK)
  - pydantic >= 2.0 (schemas)
  - flask or fastapi (retrieval service)
  - pyyaml (parsing)
  - gitpython (git ops)
  - pytest, pytest-cov (testing)
  - python-dotenv (env vars)
  - pydantic[email] (optional, if schemas need it)

- [ ] Create setup instructions:
  ```bash
  python -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json
  ```

- [ ] Create empty placeholders for all main modules (docstrings only, no implementation)

**Acceptance criteria:**
- [ ] Project structure matches above
- [ ] `pip install -r requirements.txt` succeeds without errors
- [ ] All imports work: `from schemas import *`, `from prompts import *`, etc.
- [ ] Running `python -m pytest tests/ --collect-only` shows 0 tests (stubs exist, no tests yet)

**Effort:** 4 hours  
**Owner:** (You — setup only)

---

### Task 1.2: Define Pydantic schemas for bootstrap output, catalog-info, and architecture

**Story:** Story 1 (Bootstrap)  
**Type:** Foundation  
**Complexity:** L (low)

**Description:**
Define the exact shape of data structures used throughout the system. This is critical because agents need to parse/generate these schemas, and retrieval service needs to serve them. Get this right once and it's locked.

**Requirements:**

Implement in `schemas.py`:

- [ ] **CatalogInfoSchema** — Backstage-compatible service catalog entry
  - name: str
  - namespace: str = "default"
  - description: str
  - owner: str (team or person name)
  - type: str (e.g., "service")
  - lifecycle: str (e.g., "production")
  - dependsOn: list[str] (component names)
  - providesApis: list[str] (API names)
  - dataClassification: str (low/medium/high/critical)
  - links: dict (repo URL, docs URL, etc.)
  - other Backstage fields as needed

- [ ] **ArchitectureSchema** — Arc42 sections as structured fields
  - introduction: str
  - constraints: str
  - context_and_scope: str
  - solution_strategy: str
  - building_block_view: str (this is where C4 diagrams would go, for now prose)
  - runtime_view: str
  - deployment_view: str
  - cross_cutting_concepts: str (error handling, logging, security patterns)
  - architecture_decisions: str (or link to ADRs)
  - quality_requirements: str (optional for MVP)
  - risks_and_technical_debt: str
  - glossary: str (optional)

- [ ] **OpenAPIOutlineSchema** — Outline of OpenAPI spec (human fills in detail later)
  - title: str
  - version: str
  - description: str
  - endpoints: list[dict] with keys: method, path, description, request_body (optional), response_code
  - authentication: str (e.g., "JWT", "OAuth2")
  - rate_limit: str (optional)

- [ ] **BootstrapOutputSchema** — Full output from Gemini on bootstrap
  - catalog_info: CatalogInfoSchema
  - architecture: ArchitectureSchema
  - openapi_outline: OpenAPIOutlineSchema
  - gaps: list[str] (what could not be inferred)
  - confidence: float (0.0–1.0)
  - source: dict with keys: files_sampled (int), tokens_used (int), cost (float), timestamp (ISO string)

- [ ] **RoutingDecisionSchema** — Router Agent output
  - can_auto_route: bool
  - recommended_human: str (name, or "N/A" if auto)
  - confidence: float
  - reasoning: str (1–2 paragraphs explaining the decision)
  - risk_flags: list[str] (e.g., ["single_owner", "payment_system", "new_dependency"])
  - growth_opportunity: bool
  - suggested_pairing: str (optional, junior developer name)

- [ ] **PatchSchema** — One patch to a doc
  - file: str (e.g., "catalog-info.yaml")
  - section: str (e.g., "dependsOn")
  - action: str (one of: add, update, delete)
  - value_or_content: Union[str, dict, list]
  - reason: str
  - confidence: float

- [ ] **IncrementalUpdateOutputSchema** — Result of incremental update
  - patches: list[PatchSchema]
  - confidence: float (overall)
  - gaps: list[str]
  - auto_apply: bool (true if all patches have confidence >0.85, false if human review needed)

- [ ] **EvalResultSchema** — One test case result
  - feature_request: str
  - expected_routing: RoutingDecisionSchema
  - actual_routing: RoutingDecisionSchema
  - agent_vs_human_correct: bool
  - person_correct: bool (only if human; true if names match or both are "auto")
  - risk_detection_correct: bool (all expected risks present?)
  - notes: str (why it passed/failed)

- [ ] **EvalReportSchema** — Full eval results
  - timestamp: datetime
  - test_cases: list[EvalResultSchema]
  - metrics: dict with keys: agent_vs_human_accuracy, person_assignment_accuracy, risk_detection_accuracy, sample_size
  - failures_by_category: dict (e.g., {"missed_risk": 2, "wrong_person": 1})

All schemas should:
- Use Pydantic >= 2.0 syntax
- Have docstrings on each field
- Use Field() for constraints (e.g., Field(min=0.0, max=1.0) for confidence)
- Be JSON-serializable (for saving to review_queue/ and eval_results/)

**Acceptance criteria:**
- [ ] All schemas above are defined and importable
- [ ] Each schema has a docstring explaining its purpose
- [ ] Can instantiate each schema with valid data
- [ ] Can serialize/deserialize to JSON without errors
- [ ] Unit tests for each schema: valid data passes, invalid data raises ValidationError

**Effort:** 4 hours  
**Owner:** (You)

---

### Task 1.3: Implement file sampling logic for bootstrap

**Story:** Story 1 (Bootstrap)  
**Type:** Implementation  
**Complexity:** M (medium)

**Description:**
Implement the core sampling logic that reads a repo and selects ~80 files for Gemini. This is critical because sampling quality directly impacts output quality.

**Requirements:**

Implement `bootstrap.py` module with class `RepoSampler`:

- [ ] `__init__(repo_path: str, max_files: int = 80, max_tokens: int = 150000)`
  - Validates repo_path exists and is a git repo
  - Initializes GitPython repo object

- [ ] `detect_language() -> str`
  - Returns detected primary language: "python", "javascript", "go", "rust", etc.
  - Logic: count files by extension, return most common

- [ ] `get_entry_points() -> list[str]`
  - Finds entry points: main.py, index.js, index.ts, app.py, server.go, Cargo.toml, go.mod, etc.
  - Returns absolute paths

- [ ] `get_frequently_changed_files(days: int = 90) -> list[tuple[str, int]]`
  - Uses git log to find top N files changed in last N days
  - Returns list of (path, change_count) sorted by change_count descending
  - Skips vendored dirs (node_modules, vendor/, dist/, build/, __pycache__)
  - Skips test files (*.test.js, *_test.py, test_*.py, spec files)
  - Returns top 20

- [ ] `get_schema_files() -> list[str]`
  - Finds files that define data models/schemas
  - Patterns: *schema.py, *model.py, *models/, database/*, orm.py, migrations/, src/**/schema.*, types.ts, interfaces.ts
  - Returns absolute paths

- [ ] `get_config_files() -> list[str]`
  - Finds config: .env*, config.*, setup.py, pyproject.toml, package.json, go.mod, Dockerfile, docker-compose.yml, etc.
  - Returns absolute paths

- [ ] `sample() -> dict`
  - Orchestrates sampling: entry points → frequently changed → schemas → config
  - Builds combined list, deduplicates
  - Reads files in priority order until hitting token limit (estimate: ~1500 tokens per file)
  - Stops before exceeding max_tokens
  - Returns dict:
    ```python
    {
      "files_included": [...],
      "files_skipped": [...],
      "total_tokens": int,
      "language": str,
      "sample": str  # concatenated file contents with delimiters
    }
    ```

- [ ] Error handling:
  - If repo not found: raise FileNotFoundError with helpful message
  - If repo not git repo: raise ValueError
  - If <10 files found: warning log + continue (unusual but possible)
  - If all files are binary/unreadable: raise ValueError("Cannot sample binary-only repo")

**Acceptance criteria:**
- [ ] RepoSampler works on 3 real service repos (python, javascript, go or similar)
- [ ] Sample size is within [70, 80] files (or as close as possible)
- [ ] Token count is accurate (use tiktoken or Gemini's token counting API to validate)
- [ ] Entry points are found correctly (function returns real files)
- [ ] Recently changed files are found (git log works)
- [ ] Config files are found
- [ ] Files with sensitive data (secrets, keys) trigger a warning

**Effort:** 6 hours  
**Owner:** (You)

---

### Task 1.4: Implement bootstrap Gemini call and output parsing

**Story:** Story 1 (Bootstrap)  
**Type:** Implementation  
**Complexity:** M (medium)

**Description:**
Call Gemini 2.5 Pro with the sampled code and the arc42 bootstrap prompt. Parse the response into BootstrapOutputSchema.

**Requirements:**

Implement in `bootstrap.py`, function `generate_bootstrap()`:

- [ ] `generate_bootstrap(sample: dict, service_name: str) -> BootstrapOutputSchema`
  - Reads system prompt from `prompts.BOOTSTRAP_ARCHITECTURE_PROMPT`
  - Builds user message: service metadata + file list + sample contents (as provided by RepoSampler)
  - Calls Vertex AI via google-cloud-aiplatform SDK:
    ```python
    from vertexai.generative_models import GenerativeModel
    model = GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(...)
    ```
  - Gemini settings: temperature=0.2 (low, this is documentation not creative)
  - Parses response as JSON (model instructed to output valid JSON)
  - Validates response against BootstrapOutputSchema
  - If validation fails, extract the JSON and try again (sometimes Gemini wraps JSON in markdown)
  - Logs to stdout: service name, tokens sent, tokens received, cost estimate, latency
  - Returns BootstrapOutputSchema instance

- [ ] Error handling:
  - If API auth fails: raise clear error about GOOGLE_APPLICATION_CREDENTIALS
  - If response is not valid JSON: raise ValueError with the raw response for debugging
  - If response fails schema validation: show which fields are invalid
  - Retry logic: 3 retries on transient errors (429, 503)

- [ ] Cost tracking:
  - Estimate cost using: input_tokens * $1.25/1M + output_tokens * $10/1M (Gemini 2.5 Pro rates)
  - Log to stdout

**Acceptance criteria:**
- [ ] generate_bootstrap() works on a real repo
- [ ] Output is valid BootstrapOutputSchema (all fields present and correct type)
- [ ] Confidence score is present (0.0–1.0, not NaN)
- [ ] Gaps section has at least 2–3 items (not empty)
- [ ] All architecture claims cite files (no unsourced statements)
- [ ] Error messages are helpful (human can debug issues)

**Effort:** 5 hours  
**Owner:** (You)

---

### Task 1.5: Implement review queue and approval workflow

**Story:** Story 2 (Review and approve)  
**Type:** Implementation  
**Complexity:** M (medium)

**Description:**
Implement the local review queue (JSON files) and approval workflow. When bootstrap completes, save to review_queue/. When human approves, convert to actual files and commit to repo.

**Requirements:**

Implement in `bootstrap.py`, functions/classes:

- [ ] `ReviewQueueManager` class:
  - `save_pending(service_name: str, output: BootstrapOutputSchema) -> str`
    - Writes to `./review_queue/{service_name}.json`
    - Returns path to saved file
  - `list_pending() -> list[dict]`
    - Returns list of pending reviews (service name, output, confidence, timestamp)
  - `load_pending(service_name: str) -> BootstrapOutputSchema`
    - Loads from review_queue/ and parses
  - `approve(service_name: str, edited_json: dict) -> None`
    - Validates edited JSON against BootstrapOutputSchema
    - If invalid, print error and raise ValidationError
  - `reject(service_name: str, reason: str) -> None`
    - Removes file from review_queue/

- [ ] `GitCommitter` class (or function):
  - `commit_bootstrap(repo_path: str, output: BootstrapOutputSchema) -> dict`
    - Takes bootstrap output and creates three files in the repo:
      1. `catalog-info.yaml` — serialized catalog_info as valid YAML
      2. `docs/architecture.md` — architecture sections formatted as Markdown with arc42 headings
      3. `docs/openapi.yaml` — openapi_outline as valid YAML (incomplete, human will fill in detail)
    - Creates `docs/` directory if it doesn't exist
    - Uses GitPython to stage and commit
    - Commit message: `"docs: bootstrap architecture for {service_name} [AutoSDLC]"`
    - Commit author: current git user (git config user.name)
    - Returns dict: {committed_files: [...], commit_sha: "abc123..."}

- [ ] CLI entrypoints in main (or in if __name__ == "__main__":):
  - `python bootstrap.py --repo /path/to/service` → runs full bootstrap, saves to review_queue
  - `python bootstrap.py --list-pending` → shows all pending with confidence/gaps
  - `python bootstrap.py --approve {service_name}` → prompts for edits, validates, commits
  - `python bootstrap.py --reject {service_name} --reason "..."` → removes from queue
  - `python bootstrap.py --edit {service_name}` → opens in $EDITOR for human to fill in gaps

**Acceptance criteria:**
- [ ] bootstrap.py --repo /path/to/real/service succeeds and saves to review_queue
- [ ] bootstrap.py --list-pending shows pending reviews
- [ ] bootstrap.py --approve {service} validates JSON and commits files to repo
- [ ] Committed files are valid: YAML parses, Markdown is readable, Markdown headings match arc42 structure
- [ ] Commit appears in git log with correct message
- [ ] Files don't exist before approval, do exist after approval

**Effort:** 5 hours  
**Owner:** (You)

---

### Task 2.1: Implement retrieval service Flask app

**Story:** Story 3 (Retrieval service)  
**Type:** Implementation  
**Complexity:** M (medium)

**Description:**
Build a lightweight Flask app that discovers all bootstrapped services and exposes their context via REST endpoints.

**Requirements:**

Implement `retrieval_service.py`:

- [ ] `ServiceRegistry` class:
  - `__init__(repo_dirs: list[str])` — e.g., ["/home/user/code"]
  - `discover_services() -> list[str]` — walks directories, finds all `catalog-info.yaml` files, returns service names
  - `load_service(name: str) -> dict` — loads catalog-info.yaml + architecture.md + openapi.yaml, parses, returns structured dict
  - `get_dependency_graph() -> dict` — stitches all `dependsOn` fields from all catalog-info files, returns graph

- [ ] Flask app with routes:
  - `GET /api/services` — returns list of all service names with brief metadata
  - `GET /api/services/{name}/context` — returns full service context (catalog + architecture + openapi + last_updated)
  - `GET /api/services/{name}/catalog-info` — returns catalog-info as JSON
  - `GET /api/services/{name}/architecture` — returns architecture sections (as JSON dict)
  - `GET /api/services/{name}/openapi` — returns openapi outline as JSON
  - `GET /api/dependency-graph` — returns full dependency graph
  - `GET /api/affected-services?changed=[service1,service2]` — returns services that depend on or are depended on by the changed services
  - `GET /health` — returns 200 OK (for monitoring)

- [ ] Error handling:
  - 404 if service not found
  - 500 if parsing fails (with error message)
  - All errors include helpful message

- [ ] Logging:
  - All requests logged to stdout: timestamp, method, path, status, latency
  - Parsing errors logged to stderr with full traceback

- [ ] Caching:
  - Load all services into memory on startup
  - Reload if file mtime changes (simple check on each request, or use watchdog)
  - Can force reload with ?reload=true query param

- [ ] Startup:
  - `if __name__ == "__main__":` block that runs Flask dev server
  - `python retrieval_service.py --port 5000` starts on localhost:5000
  - Discovers services from configured directories (env var or CLI arg)

**Acceptance criteria:**
- [ ] Flask app starts without errors
- [ ] GET /health returns 200
- [ ] GET /api/services returns list (even if empty)
- [ ] After bootstrapping a service, GET /api/services/{name}/context returns full context
- [ ] Response times <200ms for any request
- [ ] Errors return helpful messages
- [ ] Can parse catalog-info.yaml and architecture.md without crashing on edge cases

**Effort:** 6 hours  
**Owner:** (You)

---

### Task 3.1: Implement Router Agent with Gemini 2.5 Flash

**Story:** Story 4 (Router Agent)  
**Type:** Implementation  
**Complexity:** M (medium)

**Description:**
Implement the Router Agent that takes a feature request, retrieves service context, and makes a routing decision.

**Requirements:**

Implement `router_agent.py`:

- [ ] `DeveloperRoster` class (simulated, hardcoded for MVP):
  - Attributes: developers (list of dicts) with keys: name, recent_repos (list), skill_level ("junior"/"mid"/"senior"), current_workload (int, estimated hours)
  - `get_expert(module_name: str) -> str` — returns developer who has most recently touched this module
  - `get_available() -> list[str]` — returns developers with low workload
  - `get_junior_opportunities() -> list[tuple[str, str]]` — returns (junior_name, module_name) pairs for growth

- [ ] `RoutingAgent` class:
  - `__init__(retrieval_service_url: str = "http://localhost:5000")`
  - `route(feature_request: str, affected_services: list[str] = None) -> RoutingDecisionSchema`
    - If affected_services is None, extract from feature request text (simple heuristic: "checkout", "payments", etc.)
    - Call retrieval service to get context for each affected service
    - Build context string summarizing: purposes, dependencies, data sensitivity, key modules, recent changes
    - Call Gemini 2.5 Flash with router prompt from prompts.ROUTER_PROMPT
    - Prompt includes: feature request + service context + developer roster + critical path list (auth, payments, PII)
    - Gemini returns JSON with routing decision (agent/human, which human, risks, growth opportunity)
    - Parse response into RoutingDecisionSchema
    - Return decision

- [ ] Prompts (in prompts.py):
  - `ROUTER_PROMPT` — system prompt for Gemini
    - Explains: agent can only handle low-risk, well-tested work (simple CRUD, bug fixes, dependency upgrades)
    - Humans always handle: auth, payments, PII, new external dependencies, major refactors
    - Bus factor: flag if one person owns >70% of a module
    - Growth: flag if a junior could own this with pairing
    - Reason clearly: state which risk factors led to which decision
    - Never hallucinate: no made-up endpoints or developers

- [ ] Error handling:
  - If retrieval service is down: raise ConnectionError with helpful message
  - If feature request is empty: raise ValueError
  - If Gemini returns invalid JSON: show error and retry

**Acceptance criteria:**
- [ ] RoutingAgent.route() works on a real feature request
- [ ] Routing decision has all required fields (can_auto_route, recommended_human, reasoning, risk_flags, confidence)
- [ ] Critical path features (auth, payments, PII) always route to human
- [ ] Simple features (e.g., "add a new endpoint that returns hardcoded JSON") can route to agent
- [ ] Bus factor risk is detected (single-owner modules flagged)
- [ ] Growth opportunities are identified
- [ ] Reasoning is clear enough to override if needed

**Effort:** 5 hours  
**Owner:** (You)

---

### Task 4.1: Create eval test data and implement eval harness

**Story:** Story 5 (Eval harness)  
**Type:** Testing  
**Complexity:** M (medium)

**Description:**
Create ground truth test data (real/realistic feature requests with expected routing) and implement the eval harness to measure Router Agent accuracy.

**Requirements:**

- [ ] Create `eval_data/feature_requests.json`:
  ```json
  [
    {
      "id": 1,
      "request": "Add discount codes to checkout",
      "expected_routing": {
        "can_auto_route": false,
        "recommended_human": "alice",
        "key_risks": ["payment_system", "database_schema_change"],
        "growth_opportunity": false
      }
    },
    {
      "id": 2,
      "request": "Upgrade express.js to latest version and run tests",
      "expected_routing": {
        "can_auto_route": true,
        "recommended_human": null,
        "key_risks": [],
        "growth_opportunity": false
      }
    },
    // ... 8 more
  ]
  ```
  - 10 total test cases
  - Mix: 4 should auto-route, 6 should go to humans
  - Include realistic examples from your backlog or domain

- [ ] Implement `eval_router.py`:
  - `run_eval() -> EvalReportSchema`
    - For each test case: run Router Agent, collect decision
    - Compare actual vs expected:
      - `agent_vs_human_correct = (actual.can_auto_route == expected.can_auto_route)`
      - `person_correct = (actual.recommended_human == expected.recommended_human or both are None)`
      - `risk_detection_correct = (all expected risks are in actual.risk_flags)`
    - Compute metrics: accuracy = count(correct) / total
    - Save report to `eval_results/{timestamp}.json` and `eval_results/latest.json`
    - Print summary to stdout

  - CLI:
    - `python eval_router.py --run` — runs eval, saves results
    - `python eval_router.py --compare` — compares latest vs previous run
    - `python eval_router.py --show-failures` — prints detailed failure analysis

**Acceptance criteria:**
- [ ] eval_data/feature_requests.json has 10 valid test cases
- [ ] eval_router.py runs without errors
- [ ] Produces report with: per-test results, metrics, failure analysis
- [ ] Reports are saved to eval_results/
- [ ] Metrics include: agent_vs_human_accuracy, person_assignment_accuracy, risk_detection_accuracy
- [ ] Can compare two eval runs to see what improved/regressed

**Effort:** 4 hours  
**Owner:** (You)

---

### Task 5.1: Implement prompts for bootstrap and router

**Story:** Stories 1 & 4  
**Type:** Implementation  
**Complexity:** H (high) — quality-critical

**Description:**
Write the system prompts for Gemini. These are load-bearing; quality here directly impacts output quality everywhere.

**Requirements:**

Implement in `prompts.py`:

- [ ] `BOOTSTRAP_ARCHITECTURE_PROMPT` — for Gemini 2.5 Pro
  - Instructs Gemini to produce arc42-structured architecture documentation
  - Key sections:
    - "Do not invent: if not in provided code, do not claim it"
    - "Cite evidence: every claim must reference a file"
    - "Flag uncertainty: when inferring, say so"
    - Specific format for output (JSON with fields: introduction, constraints, context, etc.)
    - Request gaps section (what could not be inferred)
    - Request confidence score
  - ~800–1000 tokens

- [ ] `ROUTER_PROMPT` — for Gemini 2.5 Flash
  - Instructs Gemini on routing decisions
  - Key sections:
    - "Agent can handle: simple CRUD, bug fixes with reproducer tests, dependency upgrades, documentation fixes"
    - "Humans always handle: auth, payments, PII, new external integrations, major refactors, security changes"
    - "Bus factor: if one person owns >70% of a module, flag and suggest pairing"
    - "Growth: flag if a junior could own this with pairing from a senior"
    - "Reasoning: explain your decision clearly"
    - "No hallucination: reference only services/modules mentioned in context"
  - Format: return JSON with fields: can_auto_route, recommended_human, reasoning, risk_flags, confidence, growth_opportunity, suggested_pairing
  - ~800–1000 tokens

- [ ] `INCREMENTAL_UPDATE_PROMPT` — for Gemini 2.5 Flash (Story 6, optional for MVP)
  - Instructs Gemini to patch docs, not rewrite
  - Key sections:
    - "Only output patches. Do not rewrite sections."
    - "Only add or update content. Do not delete."
    - "For each change: state which file, which section, what changed, why, and your confidence"
    - "If confidence <0.85, mark for human review"
  - ~600–800 tokens

All prompts:
- [ ] Are stored as module-level constants (strings)
- [ ] Are versioned in git (when you change a prompt, commit the change)
- [ ] Are documented with comments explaining key sections
- [ ] Specify temperature (0.2 for deterministic tasks, 0.5 if needed for creativity)
- [ ] Specify max_tokens (2000 for bootstrap, 1000 for router)

**Acceptance criteria:**
- [ ] Bootstrap prompt produces valid arc42 structure
- [ ] Router prompt produces valid routing decisions with clear reasoning
- [ ] Confidence scores make sense (high when certain, low when uncertain)
- [ ] No hallucinations in outputs (claims reference real files/services)

**Effort:** 6 hours (includes iteration based on eval results)  
**Owner:** (You)

---

### Task 6.1: Documentation and README (Optional, but recommended)

**Story:** Story 7 (Documentation)  
**Type:** Documentation  
**Complexity:** L (low)

**Description:**
Write a comprehensive README explaining the system, how to use it, and how it all fits together.

**Requirements:**

Implement `README.md` with sections:

- [ ] **Overview** — what is AutoSDLC MVP, what does it do, why it matters
- [ ] **Architecture diagram** — ASCII or Mermaid showing flow: bootstrap → review → commit → retrieval → router → eval
- [ ] **Quick start** — setup instructions, one real example from start to finish
- [ ] **Scripts reference** — for each script (bootstrap.py, retrieval_service.py, etc.):
  - What it does (one sentence)
  - How to run it (with example flags)
  - Inputs and outputs
  - Common errors and fixes
- [ ] **Prompts section** — explains arc42 format, why Gemini 2.5 Pro for bootstrap, why Flash for router, how to iterate prompts
- [ ] **Eval harness** — how to run eval, what the metrics mean, how to interpret results
- [ ] **Example output** — screenshot or actual output showing:
  - One bootstrapped service (real or realistic)
  - One Router Agent routing decision with reasoning
  - One eval report with metrics
- [ ] **Troubleshooting** — common errors:
  - "GOOGLE_APPLICATION_CREDENTIALS not set" → how to fix
  - "Gemini API rate limited" → what to do
  - "Parsing error on YAML" → debug steps
  - "Service not found in retrieval service" → check discovery
- [ ] **Decision log** — short section on key decisions:
  - Why Vertex AI (not consumer Gemini API)
  - Why arc42 (not custom format)
  - Why Gemini 2.5 Pro for bootstrap (not Flash)
  - Why local MVP (not cloud)
- [ ] **Next steps** — brief mention of Phase 1 (Story Agent, Task Agent, etc.)

**Acceptance criteria:**
- [ ] README is complete and accurate (all sections present)
- [ ] Examples in README are tested (actually work when copy-pasted)
- [ ] Architecture diagram is clear
- [ ] Someone unfamiliar with the codebase can run the system from the README

**Effort:** 3 hours  
**Owner:** (You)

---

## Optional / Nice-to-Have

### Task 6.1: Implement incremental architecture updates

(Same as Story 6 — patch-based updates to keep docs current)

**Effort:** 6 hours (after critical path is working)

### Task 8.1: Handle large/unusual repos gracefully

(Graceful errors for monorepos, generated code, etc.)

**Effort:** 3 hours (if time allows)

---

## Work breakdown summary

**Critical Path (must do):**
1. Setup (Task 1.1) — 4h
2. Schemas (Task 1.2) — 4h
3. Sampling (Task 1.3) — 6h
4. Bootstrap Gemini (Task 1.4) — 5h
5. Review queue (Task 1.5) — 5h
6. Retrieval service (Task 2.1) — 6h
7. Router Agent (Task 3.1) — 5h
8. Eval harness (Task 4.1) — 4h
9. Prompts (Task 5.1) — 6h

**Subtotal critical path: ~45 hours**

**Optional (if time allows):**
- Documentation (Task 6.1) — 3h
- Incremental updates (Task 6.2) — 6h

**Estimated timeline (1 person full-time):**
- Days 1–2: Setup + Schemas (8h)
- Days 3–4: Sampling + Bootstrap Gemini (11h)
- Days 4–5: Review queue (5h)
- Days 5–6: Retrieval service (6h)
- Days 6–7: Router Agent (5h)
- Days 7–8: Eval harness + Prompts (10h)
- Day 8–9: Testing + iteration (6h)

**Total: 1.5 weeks for critical path, 2 weeks with docs + incremental updates**

---

## Test strategy

Each task has unit tests (test_*.py). Integration tests:
1. Bootstrap a real service → verify files are committed to repo
2. Call retrieval service → verify all endpoints work
3. Run Router Agent on 10 eval cases → verify metrics meet threshold (>80%)

No mocking of Gemini API (use real calls in testing, budget ~$5–10 for MVP test runs).

---

## Next step

Review this breakdown. Pick a start date. Begin with Task 1.1 (setup).

