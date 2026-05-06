# Feature Brief: AutoSDLC Local MVP

**Requested by:** You (Engineering Lead)  
**Date:** 2026-04-29  
**Status:** Approved for Phase 0 (Data Layer + Router Validation)  
**Priority:** Critical (blocking Phase 1)

---

## What are we building?

A local, runnable proof-of-concept for autonomous SDLC that validates two things:
1. **Data layer:** Can we automatically generate and maintain accurate architecture documentation from code?
2. **Routing logic:** Can an AI agent make good decisions about who should do work, with sound reasoning?

This MVP has no production infrastructure, no Redmine/Bitbucket integration, and no code generation yet. It's entirely local Python on your machine, calling Gemini via Vertex AI, with human review at every gate.

---

## Why this matters

- **Prerequisite for Phase 1:** Phase 1 (Intake + Story + Task agents) needs a living architecture map to ground story generation. You can't write good stories without knowing what the system actually does.

- **Validation of routing:** The entire system depends on the Router Agent making safe, trustworthy decisions about what work goes to agents vs humans. If routing is bad, everything downstream is bad. Better to test this in isolation before unleashing the Coder Agent.

- **Proof point for the company:** "Here's how we keep our architecture docs current without humans updating them" is a concrete win even if you ship nothing else.

---

## What success looks like

**By end of MVP (target: 1 week):**

1. ✅ You've bootstrapped 3–5 real services from your codebase
2. ✅ Each service has: `catalog-info.yaml`, `docs/architecture.md` (arc42 format), `docs/openapi.yaml` outline, all in git
3. ✅ You've made a code change to one service and verified incremental docs update works
4. ✅ Retrieval service runs locally and serves service context via REST
5. ✅ Router Agent takes a feature request + service context and makes a routing decision (agent vs human, which human, risks)
6. ✅ You've tested Router Agent against 10 real feature requests; decisions pass human smell test
7. ✅ Eval harness in place to measure routing quality; you understand what "good" looks like

**Concrete artifact to show stakeholders:**
- A service from your codebase with auto-generated docs that are accurate, formatted as arc42, and you can point to them and say "this was AI-generated, human-reviewed once, and stays current automatically"

---

## Constraints & non-negotiables

- **Local only:** No AWS, no Redmine, no Bitbucket webhooks yet. All Python on your machine.
- **Vertex AI only:** Uses Google Gemini via Vertex AI SDK (not consumer Gemini API). You need GCP project + service account credentials locally.
- **Human-reviewed bootstrap:** Every bootstrapped architecture doc is reviewed by a human before commit. Baseline quality is a human responsibility.
- **Production-quality code:** Even though it's MVP, code is typed, tested, logged, and documented. Not throwaway.
- **Arc42 + Backstage-compatible formats:** Output formats are industry standard (not custom), so migration to Backstage/production infra is mechanical later.

---

## Scope definition: What's IN

**In scope for MVP:**

1. `bootstrap.py` — samples a repo, calls Gemini 2.5 Pro, produces catalog-info.yaml + architecture.md outline + openapi outline + gaps list. Outputs to local review queue.

2. Incremental update Lambda equivalent — `incremental_update.py` — diffs a commit, calls Gemini, produces patches to catalog-info and architecture.md, prompts for human review.

3. `retrieval_service.py` — Flask app exposing REST endpoints:
   - `GET /api/services` — list all services
   - `GET /api/services/{name}/context` — full service context (catalog + architecture + openapi)
   - `GET /api/services/{name}/catalog-info` — just the catalog
   - `GET /api/dependency-graph` — cross-service dependency map
   - `GET /api/affected-services?changed=[...]` — upstream/downstream impact analysis

4. `router_agent.py` — Gemini 2.5 Flash agent that takes:
   - Feature request (unstructured text from user)
   - Service context from retrieval service
   - Developer roster + recent work + skill levels (simulated locally)
   - Returns routing decision: agent/human, which human, risks, growth opportunity flags

5. Eval harness (`eval_router.py`) — tests Router Agent against 10 real feature requests, measures:
   - Agreement with human on agent vs human call
   - Quality of reasoning
   - Risk detection accuracy

6. `prompts.py` — system prompts for:
   - Bootstrap architecture generation (produces arc42 structure)
   - Incremental architecture update (patch-based, not rewrites)
   - Router Agent routing logic

7. Local test data:
   - Sample feature requests (10 real ones from your backlog, or synthetic realistic ones)
   - Sample developer roster with historical data
   - 3–5 real service repos you'll bootstrap

---

## Scope definition: What's OUT

**Not in MVP:**

- Code generation (Coder Agent) — Phase 3
- Code review (Reviewer Agent) — Phase 3
- Story generation (Story Agent) — Phase 2
- Task generation (Task Agent) — Phase 2
- Intake agent (Intake Agent) — Phase 1
- Redmine integration
- Bitbucket integration / webhooks
- AWS deployment (Step Functions, Lambda, etc.)
- Backstage UI
- ADR generation (you'll write ADRs manually for now)
- Runbooks, threat models, SLO definitions (future phases)

---

## Technical approach

**Bootstrap flow:**
1. User runs: `python bootstrap.py --repo /path/to/service`
2. Script samples code (entry points, top-changed files, schemas, config)
3. Sends sample to Gemini 2.5 Pro with arc42 system prompt
4. Saves structured output to `./review_queue/service.json`
5. User reviews output, fills gaps, approves
6. Script writes `catalog-info.yaml`, `docs/architecture.md`, `docs/openapi.yaml` to repo, commits

**Incremental update flow:**
1. User runs: `python incremental_update.py --repo service --commit abc123`
2. Script diffs the commit, reads current docs
3. Sends to Gemini with incremental prompt: "What needs to update? Only patches, no rewrites."
4. Outputs patch to `./review_queue/service-patch.json`
5. User approves, script applies patch, commits

**Retrieval service flow:**
1. User runs: `python retrieval_service.py --port 5000`
2. Service discovers all repos with `catalog-info.yaml` in configured directories
3. Parses and caches all YAML/Markdown files
4. Exposes REST API that agents (or humans) query for service context

**Router Agent flow:**
1. User provides feature request: "Add discount codes to checkout"
2. Router Agent retrieves checkout service context from retrieval service
3. Analyzes: complexity, risk (payments involved?), ownership, recent changes, junior opportunities
4. Returns: routing decision (human vs agent), specific person, reasoning, risk flags
5. Human approves or overrides routing decision

**Eval flow:**
1. Load 10 test feature requests + expected routing decisions (human-annotated)
2. Run Router Agent on each
3. Compare actual vs expected (agent/human call, specific person, reasoning quality)
4. Compute metrics: precision/recall on "agent vs human," agreement on person assignment, etc.
5. Surface failures for prompt iteration

---

## Success criteria (measurable)

- **Architecture docs accuracy:** Human reviewer finds <5% factual errors in bootstrap output (first pass), no errors after incremental updates
- **Retrieval latency:** API responds in <200ms for any service context query
- **Router Agent agreement:** >80% agreement with human on "can agent handle this?" call for test set
- **Router Agent reasoning:** Senior engineer reads reasoning and says "yes, this makes sense" for >80% of decisions
- **Bus factor detection:** Router Agent correctly identifies single-owner modules >90% of the time
- **Zero hallucination:** No services, endpoints, or dependencies invented that don't exist in code
- **Incremental update safety:** Every incremental patch is conservative (additions only, no deletions/rewrites without high confidence)

---

## Effort estimate

Based on complexity features:
- File I/O + git ops: moderate
- Gemini API calls + prompt engineering: moderate-high (quality bar is high here)
- Flask REST service: low
- Prompt iteration (eval harness feedback): moderate-high
- Test coverage: moderate

**Estimated effort: 40–60 engineering hours**

If one person, full-time: 1 week (with iteration)  
If split with code review/iteration: 1.5 weeks

---

## Dependencies

**External:**
- Vertex AI SDK (google-cloud-aiplatform)
- Flask or FastAPI
- Pydantic (for schemas)
- GitPython (for git ops)
- PyYAML (for parsing)
- All on PyPI, no issues

**Human:**
- GCP project with Vertex AI API enabled
- Service account credentials (locally, in `GOOGLE_APPLICATION_CREDENTIALS`)
- 3–5 real service repos to bootstrap
- 10 real feature requests for Router Agent eval (can be synthetic if real backlog unavailable)

---

## Risks & mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Gemini hallucination in bootstrap | Baseline docs are wrong, pollutes future updates | Human review gate is mandatory; confidence scoring on output |
| Incremental updates drift docs away from reality | Docs become misleading over time | Conservative patch strategy; high confidence threshold before auto-commit; gaps section highlighted |
| Router Agent makes bad routing decisions | Agents take on unsafe work, or good work is blocked | Eval harness with human annotation; iterate prompt until >80% agreement |
| Large repos sample badly | Bootstrap output misses critical modules | Set sampling cap; refuse repos that are too large; ask human to specify subdirectory |
| Parsing failures on unusual YAML/Markdown | Crashes when service context is malformed | Defensive parsing, fallback to raw content if structured parse fails |

---

## Phasing

**Phase 0 (this MVP): Data layer + routing validation**
- Bootstrap architecture docs
- Retrieval service
- Router Agent + eval harness
- Ready for Phase 1

**Phase 1: Full planning automation (4–6 weeks after MVP)**
- Intake Agent (clarifying questions → Feature Brief)
- Story Agent (stories from brief)
- Task Agent (tasks from stories)
- Integration with Redmine

**Phase 2: Human-trusted code assignment (6–8 weeks after Phase 1)**
- Integration with Bitbucket
- Human code review approval gates
- Deployment to staging

**Phase 3: Code generation (8–12 weeks after Phase 2)**
- Coder Agent (bug fixes, simple CRUD on proven tasks only)
- Reviewer Agent (security + correctness review)
- Deployment to production

---

## Notes for implementation

- **Prompt quality is 80% of success here.** Spend time on the arc42 bootstrap prompt and the router reasoning prompt. These are not one-shot — you'll iterate them 5+ times based on eval harness feedback.

- **Eval harness is not optional.** You cannot tell if routing is good without measuring it. Build this early, use it to drive prompt iteration.

- **Start with one service.** Bootstrap checkout or payments or user-service (something you know deeply), get it perfect, then do the other 3–4. Don't try to do five at once.

- **The retrieval service is boring, make it boring.** No fancy caching optimizations yet. Just read from disk, parse, return. Fast enough for local MVP.

- **Incremental updates are hard.** Get bootstrap working first. Incremental is the 80/20 work — bootstrap is the foundation.

- **Save prompts to git.** Version control the system prompts themselves. You'll iterate them. Future you will want to see why you changed them.

---

## Deliverables

**Code artifacts:**
- `bootstrap.py` with full sampling + Gemini integration
- `incremental_update.py` with patch generation
- `retrieval_service.py` Flask app
- `router_agent.py` with routing logic
- `eval_router.py` test harness
- `prompts.py` with all system prompts
- `schemas.py` Pydantic models for catalog-info, architecture, routing decision
- `requirements.txt`
- Tests for each module

**Documentation artifacts:**
- `README.md` — how to run locally, what each script does
- Example bootstrapped service with real `catalog-info.yaml` + `architecture.md`
- Eval results: Router Agent accuracy on test set, sample routing decisions with reasoning

**Process artifacts:**
- Decision log: what prompts were tested, what changed, why
- Lessons learned: what's easy, what's hard, what surprised you

---

## Timeline

- **Week 1, days 1–2:** Setup + bootstrap.py (sampling + Gemini call)
- **Week 1, days 3–4:** Retrieval service + review queue for bootstrap
- **Week 1, days 5:** Router Agent + eval harness
- **Week 2, day 1–2:** Incremental update (if time allows; not critical for MVP validation)
- **Week 2, day 3:** Eval iteration + prompt tuning
- **Week 2, day 4–5:** Documentation + handoff

Actual timeline will be driven by eval harness results. If routing is bad, you iterate prompts; if sampling is wrong, you revise bootstrap logic.

---

## Sign-off

**Approved by:** You  
**Estimated start:** Today (2026-04-29)  
**Target completion:** 2026-05-06 (1 week) to 2026-05-13 (2 weeks if eval iteration needed)

This Feature Brief is the source of truth for MVP scope. Any changes to scope (adding Story Agent, adding Redmine integration, etc.) require a new brief.

