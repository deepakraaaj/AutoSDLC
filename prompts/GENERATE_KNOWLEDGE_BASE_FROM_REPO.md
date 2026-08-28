# Generate Knowledge Base from Repo — Claude Code Prompt

## What this is for

Use this prompt directly inside Claude Code, run from a workspace that has this project's frontend and
backend repos checked out (e.g. `fits-ui` and `fits-service`, or whatever this project's two repos are
named). Claude Code has git and file access here that a chatbot pasted a document doesn't — it can check
out the right branch and actually read the code, so this produces the knowledge base straight from
ground truth instead of from a document that might be stale or might not exist.

The output is one `.md` file. Save it, then upload it on this app's project **Knowledge Base** tab
(Upload template) — it gets parsed into review-ready candidates across all 15 SDLC-relevant fact
categories, organized and shown properly, nothing saved until you approve it.

## Step 1: Paste this into Claude Code, in a workspace with both repos checked out

You are cataloguing this project's domain knowledge directly from its source code, for a team that
doesn't have (or can't rely on) a legacy engineer to explain it by hand. Do the following:

1. Find every repository checked out in or below the current working directory (a frontend and a
   backend, or however many this project has). For each one:
   - Run `git fetch origin` then `git checkout dev` (fall back to `develop` or the repo's default branch
     if `dev` doesn't exist — say which branch you actually used for each repo).
   - Pull the latest: `git pull`.
2. Read the actual code — routes/controllers, validation logic, models/schemas, RBAC/permission checks,
   config files and environment variable usage, migrations, enums/status constants, README and any docs
   folder, existing tests. Do not skim file names only; open and read the files that matter.
3. Extract every fact you find into ONE of these four kinds — never invent one you can't point at real
   code for:
   - **Glossary** — domain terms, entity/model names, acronyms, field meanings, status/enum values.
   - **Rule** — validation logic, business rules, workflows/state transitions, approval/escalation
     logic, RBAC/permission rules, calculation formulas — with the real numbers/thresholds/role names
     the code actually uses.
   - **Decision** — an architectural or technical choice actually evidenced in the code or its comments/
     ADRs (a specific DB, a specific auth approach, a specific integration pattern) — never a guess at
     why something was built a certain way if the code doesn't say.
   - **Constraint** — hard limits evidenced in code/config: rate limits, timeouts, size/pagination caps,
     retention periods, required env vars, deployment/environment constraints.
4. Organize what you find under these 15 SDLC areas — skip an area entirely if the code has nothing to
   say about it, do not pad it out with filler. Each line states what belongs there AND, after the dash,
   what commonly gets miscategorized into it — read both halves, the wrong-fit examples are real,
   observed mistakes, not hypotheticals:
   - **Business Context** — objectives/scope/stakeholders stated explicitly in config, feature flags, or
     comments. NOT a schema migration, a new module/class, or a code comment describing what a feature
     does — that's Functional Requirements, Data Domain, or Business Processes depending on what it
     actually shows, never Business Context just because it's the first area listed. Every Business
     Context fact must be one of exactly seven kinds — use the matching heading prefix, not `Glossary:`/
     `Rule:`/`Decision:`/`Constraint:`: `Problem Statement:` (what problem the project exists to solve —
     only when the README/comments genuinely state it, never invented), `Competitive Landscape:` (how this
     differs from alternatives — only when the material actually says so), `Proposed Solution:` (what was
     built to address the problem), `Objective:` (a stated goal), `Stakeholder:` (a person/team/role
     impacted by or influencing the project), `Scope Boundary:` (what's explicitly in or out of scope),
     `Success Metric:` (a KPI or measure of success). Problem Statement and Competitive Landscape rarely
     have real code evidence — skip them entirely rather than guess. If a code-derived fact doesn't fit
     one of these seven kinds, it isn't Business Context — put it in whichever area above it actually
     matches.
   - **Domain & Glossary** — domain terms, entity names, acronyms defined or used in code.
   - **Actors & Roles** — role/permission constants, RBAC checks, who is authorized to do what.
   - **Business Processes** — state machines, status transitions, workflow/approval sequences.
   - **Business Rules** — validation logic, calculation formulas, thresholds, eligibility checks.
   - **Functional Requirements** — what an endpoint/handler actually does. A new table/migration or a new
     domain concept appearing in code belongs here (or Data Domain), not Business Context.
   - **Non-Functional Requirements** — rate limits, timeouts, pagination caps, size limits.
   - **Architecture Decisions** — a real choice actually evidenced in code/config, only when the evidence
     actually shows a decision, never a guess at why.
   - **System Architecture** — integration points, service boundaries, middleware. A specific
     library/class choice for one concern (e.g. which mail-sending library, which config prefix scheme)
     belongs here, not Business Context.
   - **Data Domain** — entities/fields and their real meaning, uniqueness constraints, retention logic.
   - **APIs & Integrations** — external API calls, their timeouts/retries, rate limits, contracts.
   - **Security & Compliance** — auth/encryption logic, PII handling, role-gated data access.
   - **Testing Knowledge** — edge cases and invariants evidenced in existing tests.
   - **Deployment & Release** — deployment config, environment variables, rollback logic.
   - **Operations & Production** — retry/backoff, alerting thresholds, health checks.

   If a fact doesn't clearly belong to a specific area after reading the above, that's itself a signal
   it's implementation detail with no business meaning — leave it out entirely rather than defaulting it
   into Business Context (or any other area) just to have somewhere to put it.
5. If something is genuinely unclear or contradictory between the two repos (e.g. frontend and backend
   disagree on a validation rule, or a permission check references a role that's never defined), still
   write the fact, but start its body with exactly `TBD:` followed by what's unresolved. Never guess.

**Write every fact for a reader who has never opened this codebase and never will — a PM, a new hire, an
auditor.** This is the single most important rule and the one most often broken:
- The BODY of every fact must be plain business English. NO class names, file names, function names,
  variable names, SQL, config keys, or backtick-wrapped code of any kind in the body — if you catch
  yourself writing a backtick in a body sentence, stop and rewrite that sentence in plain words instead.
  "The system sends invigilator instructions and exam session details by email, using separate mail
  settings for general notices, management reports, and one-time passcodes" — not "`FacilityApplication`
  defines three `JavaMailSender` beans bound to `spring.mail`/`spring.mail.mis`/`spring.mail.otp`."
- Translate the code into what it MEANS for the business: what a user can do, what rule is enforced,
  what limit exists, what was decided and why — never how it's implemented.
- The one place code identifiers belong is a separate "Source:" line at the very end of the body (see
  the shape below) — that's the citation, not part of the explanation.

## Step 2: Write the output file

Write a single file named `KNOWLEDGE_BASE.md` with one `##` heading per fact, in this exact shape —
match it precisely, this is what gets parsed:

```
## Problem Statement: [Short name] (Business Context)
[2-4 plain-English sentences — what problem the project exists to solve. Only if the material genuinely states it.]
Source: path/to/file.ext

## Competitive Landscape: [Short name] (Business Context)
[2-4 plain-English sentences — how this differs from alternatives. Only if the material genuinely says so.]
Source: path/to/file.ext

## Proposed Solution: [Short name] (Business Context)
[2-4 plain-English sentences — what was built to address the problem.]
Source: path/to/file.ext

## Objective: [Short name] (Business Context)
[2-4 plain-English sentences — the goal itself, no code identifiers.]
Source: path/to/file.ext

## Stakeholder: [Short name] (Business Context)
[2-4 plain-English sentences — who they are and how they're impacted by or influence the project.]
Source: path/to/file.ext

## Scope Boundary: [Short name] (Business Context)
[2-4 plain-English sentences — what's explicitly in or out of scope.]
Source: path/to/file.ext

## Success Metric: [Short name] (Business Context)
[2-4 plain-English sentences — the measurable KPI and its target.]
Source: path/to/file.ext

## Glossary: [Term] (Domain & Glossary)
[2-4 plain-English sentences — what it means to someone using or managing the product, no code identifiers.]
Source: path/to/file.ext

## Rule: [Short name] (Business Rules)
[2-4 plain-English sentences — the real rule, with real numbers/thresholds/role names, no code identifiers.]
Source: path/to/file.ext

## Decision: [Short name] (Architecture Decisions)
[2-4 plain-English sentences — what was chosen and, if evidenced, why it matters for the business/team.]
Source: path/to/file.ext

## Constraint: [Short name] (Non-Functional Requirements)
[2-4 plain-English sentences — the real hard limit and what it means in practice.]
Source: path/to/file.ext
```

Rules for the file:
- Every heading starts with exactly `Glossary:`, `Rule:`, `Decision:`, or `Constraint:` — EXCEPT a
  Business Context fact, which instead starts with one of its 7 kind labels: `Problem Statement:`,
  `Competitive Landscape:`, `Proposed Solution:`, `Objective:`, `Stakeholder:`, `Scope Boundary:`, or
  `Success Metric:` (see step 4's Business Context bullet). Either way: label, then a short specific
  name, then the SDLC area in parentheses from the 15 listed above (exact spelling matters — it's how
  the app groups facts on review).
- The `Source:` line is mandatory on every fact and must be a real path from the repo (add `:line` if
  useful) — it's what makes the fact checkable, but it stays out of the explanatory sentences above it.
- Cover as many of the 15 areas as the code actually supports — for two real repos (frontend + backend)
  expect dozens of facts across most areas, not a token one-liner per area.
- No commentary before, after, or between sections — the file is nothing but `##` sections.
- At the very top of the file, before the first `##` heading, add one line noting which branch was
  actually used per repo, e.g. `<!-- fits-ui: dev @ a1b2c3d, fits-service: dev @ e4f5g6h -->` — this line
  is ignored by the parser but useful for the human reviewing the result.

Before you write the file, re-read your own draft facts and rewrite any that still contain a class name,
file name, config key, or backtick — a fact that reads like a code comment has failed the point of this
exercise, which is to make the legacy engineer's knowledge available to someone who will never read the
code at all.

## Step 3: Bring it back

Save `KNOWLEDGE_BASE.md`, then paste/upload it into this app's **Knowledge Base** tab → Upload template.
Everything gets parsed, organized by the 15 areas, and shown for review — nothing saves until approved.
