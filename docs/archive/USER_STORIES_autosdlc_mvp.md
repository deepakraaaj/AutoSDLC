# User Stories: AutoSDLC Local MVP

**Epic:** Autonomous SDLC - Phase 0 (Data Layer + Routing Validation)  
**Linked Feature Brief:** FEATURE_BRIEF_autosdlc_mvp.md  
**Release:** MVP / 2026-05-06

---

## Story 1: Bootstrap an existing service's architecture documentation from code samples

**As a** developer bootstrapping the system  
**I want to** run a single command that reads a service's code, generates a structured architecture document, and outputs it for review  
**So that** I can quickly generate first-pass architecture docs without manual writing

**Acceptance Criteria:**

- [ ] Running `python bootstrap.py --repo /path/to/service` succeeds without errors
- [ ] Script detects language (Python, JavaScript, Go) automatically
- [ ] Script samples ~80 files (entry points, top-changed, schemas, config) without exceeding 150K tokens
- [ ] Script calls Gemini 2.5 Pro with arc42 system prompt and code sample
- [ ] Output is saved to `./review_queue/{service}.json` with structure: catalog_info, architecture, openapi_outline, gaps, confidence
- [ ] Output includes "gaps" section with at least 3 items (what could not be inferred from code)
- [ ] All claims in architecture section are cited with file paths (e.g., "see: src/api/routes.py")
- [ ] Confidence score is present and accurate (0.0–1.0 based on how certain the agent was)
- [ ] Script logs all Gemini calls to stdout (tokens used, cost, latency)
- [ ] Script handles errors gracefully (repo not found, Gemini API error, malformed repo) with helpful messages
- [ ] Bootstrap output for a real service (checkout, payments, user-service) is accurate enough that a human reviewer finds <5% factual errors

**Definition of Done:**

- Code is typed (Pydantic models for input/output)
- Unit tests for: file sampling logic, output schema validation, error handling
- Integration test on a real service repo
- Prompt version is recorded (git commit hash of prompts.py)
- Cost per bootstrap is <$1.00 (token efficiency is tracked)

**Effort:** M (medium)  
**Size:** 8 points  
**Priority:** P0 (blocking retrieval service)

**Dependencies:** None (can start immediately)

**Notes:**
- File sampling is the quality bottleneck. Spend time getting this right: entry points must be first, top-changed files must be recent (git log), schema files must be detected.
- Gemini 2.5 Pro is intentional (not Flash) because this is one-time and accuracy matters.
- Arc42 format is specified; do not use custom format. If output is not valid arc42, automation downstream breaks.

---

## Story 2: Review and approve bootstrapped architecture documents

**As a** developer who knows a service well  
**I want to** review the generated bootstrap output, fill in gaps, and approve it for commit  
**So that** the first architecture doc is accurate and grounded in reality before it becomes canonical

**Acceptance Criteria:**

- [ ] Running `python bootstrap.py --list-pending` shows all pending reviews in order (oldest first)
- [ ] Reviewing a pending doc shows: original gaps list, confidence score, and full generated output
- [ ] I can edit the JSON to fix errors, add missing information, or mark gaps as "human will handle later"
- [ ] Running `python bootstrap.py --approve {service}` validates the edited JSON against schema
- [ ] If validation fails, script shows exactly which fields are invalid and why
- [ ] On approval, script generates git commit with message: "docs: bootstrap architecture for {service} [AutoSDLC]"
- [ ] Script commits three files to the repo: catalog-info.yaml, docs/architecture.md, docs/openapi.yaml
- [ ] YAML files are properly formatted and valid (can be parsed by `yaml.safe_load`)
- [ ] Markdown is valid (reasonable indentation, proper heading hierarchy)
- [ ] Commit is authored as current git user (script uses `git config user.name`)
- [ ] All three files appear in the service repo's git history after approval

**Definition of Done:**

- Code is typed
- Unit tests for: JSON validation, file generation, git commit logic
- Integration test on a real service repo
- The three output files (catalog-info.yaml, architecture.md, openapi.yaml) are examples in the repo

**Effort:** S (small)  
**Size:** 5 points  
**Priority:** P0 (blocks retrieval service)

**Dependencies:** Story 1 (bootstrap generation)

**Notes:**
- This is the human quality gate. Don't skip it. Every baseline architecture doc must be reviewed by someone who knows the service.
- The review queue is just local JSON files; no database needed yet.
- Markdown + YAML generation should not have parsing errors — if they do, the approval step catches them.

---

## Story 3: Run a local retrieval service that serves service context via REST API

**As an** AI agent  
**I want to** call a REST API to get current architecture context for any service  
**So that** I can ground my decisions in real, up-to-date information about the system

**Acceptance Criteria:**

- [ ] Running `python retrieval_service.py --port 5000` starts a Flask/FastAPI server on localhost:5000
- [ ] Server discovers all services with `catalog-info.yaml` in configured directories (e.g., ~/code/)
- [ ] GET `/api/services` returns list of all services with name, description, owner
- [ ] GET `/api/services/{name}/context` returns full service context: catalog-info fields + architecture sections + openapi spec + last updated timestamp
- [ ] GET `/api/services/{name}/catalog-info` returns just the parsed catalog-info.yaml as JSON
- [ ] GET `/api/services/{name}/architecture` returns architecture.md sections as structured JSON (introduction, constraints, context, etc.)
- [ ] GET `/api/services/{name}/openapi` returns openapi.yaml as JSON
- [ ] GET `/api/dependency-graph` returns cross-service dependency map (services + their dependencies + dependents)
- [ ] GET `/api/affected-services?changed=[service1,service2]` returns all upstream/downstream services that could be affected by changes
- [ ] All responses include HTTP 200 on success, 404 if service not found, 500 if parsing fails
- [ ] Error responses include helpful error messages (e.g., "Service 'checkout' not found in configured dirs")
- [ ] Response times for `/context` are <200ms even with 10+ services
- [ ] Service caches parsed docs in memory (reloads on file change, or on request with ?reload=true flag)
- [ ] Server logs all requests to stdout: timestamp, method, path, response code, latency
- [ ] Server can be stopped cleanly with Ctrl+C

**Definition of Done:**

- Code is typed
- Unit tests for: parsing catalog-info, parsing architecture.md, building dependency graph, serving responses
- Integration test with 3+ real services
- Example requests/responses documented in README

**Effort:** M (medium)  
**Size:** 8 points  
**Priority:** P0 (blocking Router Agent)

**Dependencies:** Stories 1 & 2 (services must be bootstrapped first)

**Notes:**
- This is the integration point between documentation layer and agent layer. It must be reliable and fast.
- Parsing YAML/Markdown from files is straightforward; the complexity is in building the dependency graph (walk all services' catalog-info, extract dependsOn, stitch edges).
- Caching is important for performance but keep it simple (in-memory dict, reload on access if file mtime changed).

---

## Story 4: The Router Agent makes safe routing decisions: agent vs human, which human, risk assessment

**As a** product manager or developer  
**I want to** submit a feature request and get a routing decision: "this can be auto-assigned to Agent/code generation" or "this needs Human: Alice (reason)"  
**So that** I can decide how to staff the feature and what level of autonomy to enable

**Acceptance Criteria:**

- [ ] Router Agent accepts input: feature request (unstructured text), list of services affected (or "detect from feature text")
- [ ] Agent retrieves service context for affected services from the retrieval service
- [ ] Agent retrieves developer roster: names, recent repos changed, skill level, current workload (simulated locally)
- [ ] Agent analyzes and returns routing decision with fields: can_auto_route (bool), recommended_human (string), confidence (0.0–1.0), reasoning (prose), risk_flags (list), growth_opportunity (bool), suggested_pairing (optional)
- [ ] Routing decisions correctly identify "critical path" features: auth, payments, PII (routes to human regardless of complexity)
- [ ] Routing decisions correctly identify low-risk features: simple CRUD, bug fixes with reproducer, dependency updates (routes to agent if code base is proven)
- [ ] Risk flags include: "single-owner module," "new external dependency," "touches 10+ files," "affects payment flow," etc.
- [ ] Growth opportunities are flagged for junior developers: "Alice owns this module — Ethan (junior) could own this task with pairing"
- [ ] Reasoning is clear enough that a human disagrees with it or overrides it based on the stated logic
- [ ] Agent correctly identifies bus-factor risk: "X module is owned by one person who has touched it in the last 90 days" → flag for pairing
- [ ] Agent reasoning never hallucinates: no made-up dependencies, endpoints, or developer names

**Definition of Done:**

- Code is typed
- Router Agent uses Gemini 2.5 Flash (cost optimization for repeated calls)
- System prompt for router is in prompts.py, versioned in git
- Unit test for: parsing feature request, calling retrieval service, formatting decision output
- Integration test: manual test on 3 real feature requests with human validation of routing decisions

**Effort:** M (medium)  
**Size:** 8 points  
**Priority:** P1 (blocking eval harness)

**Dependencies:** Story 3 (retrieval service must be working)

**Notes:**
- This is the validation point for the whole system. If routing is bad, everything downstream is bad.
- Use Gemini 2.5 Flash here, not Pro (it's cheaper and this will run many times). Pro goes to bootstrap (one-time).
- The "developer roster" is simulated locally (hardcoded or loaded from JSON). Real integration with Redmine/git happens in Phase 1.
- "Critical path" list (auth, payments, PII) is explicit in the prompt, not learned.

---

## Story 5: Evaluate Router Agent routing decisions against human judgment

**As a** system designer  
**I want to** test the Router Agent against real feature requests and measure its agreement with humans on routing decisions  
**So that** I can iterate the prompt until the agent is trustworthy enough for production

**Acceptance Criteria:**

- [ ] Eval harness loads 10 real feature requests from `eval_data/feature_requests.json`
- [ ] For each request, eval harness also loads expected routing decision (human-annotated ground truth): agent/human, specific person, key risks expected
- [ ] Eval harness runs Router Agent on each request
- [ ] Results are scored on:
  - Agent-vs-human accuracy: % of requests where agent correctly identifies whether this is agent-assignable (precision/recall)
  - Person assignment accuracy: % where agent correctly identifies the right human (if applicable)
  - Risk detection accuracy: % where all expected risk flags are present in agent output
  - Reasoning quality: qualitative—does the reasoning make sense?
- [ ] Eval harness outputs a report: scores per request, aggregate metrics, failure analysis
- [ ] Failures are grouped by category (missed risk, wrong person, wrong agent/human call) so you can see pattern
- [ ] Report is saved to `./eval_results/latest.json` and to `./eval_results/YYYY-MM-DD.json` (timestamped)
- [ ] Comparison view: `python eval_router.py --compare` shows diffs between last two runs (which requests got worse/better)
- [ ] Threshold for success: >80% agreement on agent-vs-human call, >70% on specific person, >85% on risk detection

**Definition of Done:**

- Code is typed
- Test data includes: 10 real feature requests (or realistic synthetic ones), ground truth annotations
- Harness is automated (no manual prompting—just runs, outputs report)
- Example report in repo showing passing eval
- Script in repo: `python eval_router.py` runs full eval; `python eval_router.py --compare` shows before/after; `python eval_router.py --iterate-prompt` reruns with updated prompt from prompts.py

**Effort:** M (medium)  
**Size:** 8 points  
**Priority:** P1 (blocks sign-off on Router Agent)

**Dependencies:** Story 4 (Router Agent must be implemented)

**Notes:**
- This is the feedback loop that drives prompt iteration. Build it early, use it to drive quality.
- Ground truth annotation is manual (you or a senior engineer reads each feature request and decides what the right routing should be). Not perfect, but good enough for eval.
- Failure analysis is key: if 3 requests fail because the agent misses a "payment" risk, that's actionable (prompt tweak). If failures are random, that suggests the agent is unstable.

---

## Story 6: Generate patches to keep architecture docs current as code changes

**As a** developer who merged code  
**I want to** run a single command that analyzes what I changed and proposes updates to the architecture docs  
**So that** the living map stays current without manual doc maintenance

**Acceptance Criteria:**

- [ ] Running `python incremental_update.py --repo service --commit abc123def` succeeds
- [ ] Script diffs the commit (using git show), reads the current catalog-info.yaml and docs/architecture.md
- [ ] Script calls Gemini with incremental prompt: "Here's what changed. Here's the current docs. What needs to update?"
- [ ] Output is a set of patches (not a rewrite): "add component X to catalog-info," "update architecture section Y," etc.
- [ ] Each patch includes: file, section, action (add/update/delete), proposed change, confidence, reason
- [ ] If confidence >0.85, patch can be auto-committed (with human approval flag still)
- [ ] If confidence <0.85 or action is "delete", patch goes to review queue instead (human must approve)
- [ ] Patches are never rewrites of sections—only targeted additions/updates
- [ ] Running `python incremental_update.py --review service` shows all pending patches for human review
- [ ] Running `python incremental_update.py --apply service` applies approved patches and commits

**Definition of Done:**

- Code is typed
- Prompt is conservative (patches only, no rewrites)
- Unit tests for: diffing commits, parsing diffs, formatting patches
- Integration test on a real service repo (make a code change, verify patch is proposed)
- Prompt version is recorded

**Effort:** M (medium)  
**Size:** 8 points  
**Priority:** P2 (nice-to-have for MVP, but can be skipped if time is tight)

**Dependencies:** Stories 1, 2, 3 (retrieval service and bootstrap must work)

**Notes:**
- This is the hardest part because the incremental prompt needs to be very conservative. It's easy to accidentally rewrite docs instead of patch them.
- For MVP, if time is short, you can do incremental updates manually (edit the files yourself, commit). The automation can be added in Phase 1.
- The prompt should explicitly say: "Only output patches. Do not rewrite sections. Do not delete content unless you are very confident it is wrong."

---

## Story 7: Document the system with README and usage examples

**As a** future developer or a reviewer of this code  
**I want to** read a README that explains how each script works, how to run it, and what the outputs are  
**So that** I don't have to reverse-engineer the system from code

**Acceptance Criteria:**

- [ ] README.md exists at root with: overview, setup (GCP creds, Python deps), how to run each script
- [ ] Each script section includes: what it does, inputs, outputs, example usage
- [ ] Detailed sections for: bootstrap.py, retrieval_service.py, router_agent.py, eval_router.py, incremental_update.py
- [ ] Prompt section explains: why arc42 format, how to update prompts, how to version them
- [ ] Example output: one bootstrapped service with real catalog-info.yaml, architecture.md, openapi.yaml shown in repo
- [ ] Example eval results: Router Agent eval report showing passing test case
- [ ] Troubleshooting section: common errors (Gemini API limits, git errors, parsing errors) and fixes
- [ ] Architecture diagram or flowchart showing: bootstrap → review → commit → retrieval service → router agent → eval
- [ ] All file paths and examples are correct (tested when README is written)

**Definition of Done:**

- README is complete and accurate
- All scripts have inline docstrings ("""...""" on functions)
- Code examples in README actually work when copy-pasted
- Architecture diagram is readable (Mermaid or ASCII)

**Effort:** S (small)  
**Size:** 5 points  
**Priority:** P2 (documentation)

**Dependencies:** All other stories (write README last)

**Notes:**
- This is not optional. Code without docs is code nobody can maintain.
- Include a "decision log" section: why Vertex AI instead of consumer Gemini, why arc42 format, why Gemini 2.5 Pro for bootstrap, etc.

---

## Story 8 (Optional): Handle large or unusual repos gracefully in bootstrap

**As a** developer working on a monorepo or a service with generated code  
**I want to** get helpful errors when bootstrap can't sample the repo properly  
**So that** I can fix the issue or manually specify which subdirectory is "the service"

**Acceptance Criteria:**

- [ ] Bootstrap detects if a repo is too large to sample (>10K files) and refuses gracefully
- [ ] Error message suggests: "This repo is very large. Please specify --subdir src/ to focus on one service"
- [ ] Bootstrap can accept `--subdir` flag to scope sampling to one directory
- [ ] Bootstrap detects generated code (e.g., node_modules, vendor dirs, __pycache__) and skips them automatically
- [ ] Bootstrap skips vendored dependencies and large test data automatically
- [ ] If sampling fails for any reason (all selected files are binary, unreadable, etc.), error is clear and actionable

**Definition of Done:**

- Code is typed
- Unit tests for: directory size detection, skip logic, subdir handling
- Integration test on a real monorepo or large service

**Effort:** S (small)  
**Size:** 3 points  
**Priority:** P3 (nice to have; can be done if time allows)

**Dependencies:** Story 1

**Notes:**
- This can be done last if time is tight. For MVP, you can manually handle large repos.

---

## Summary table

| Story | Title | Size | Priority | Dependencies |
|-------|-------|------|----------|--------------|
| 1 | Bootstrap architecture from code | 8 | P0 | — |
| 2 | Review and approve bootstrap output | 5 | P0 | 1 |
| 3 | Retrieval service REST API | 8 | P0 | 1, 2 |
| 4 | Router Agent routing decisions | 8 | P1 | 3 |
| 5 | Eval harness for Router Agent | 8 | P1 | 4 |
| 6 | Incremental architecture updates | 8 | P2 | 1, 2, 3 |
| 7 | Documentation & README | 5 | P2 | All |
| 8 | Handle large repos gracefully | 3 | P3 | 1 |

**MVP Critical Path:** 1 → 2 → 3 → 4 → 5  
**Total MVP size:** 45 points (Stories 1–5)  
**If time allows, add:** 6, 7  
**If very constrained, drop:** 6, 8

---

## Next step

Convert these stories into tasks with specific implementation requirements, then start building.

