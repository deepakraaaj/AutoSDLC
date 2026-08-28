/** The "paste into any AI tool" portion of prompts/EXTRACT_KNOWLEDGE_BASE.md
 * (Step 2 only — not the surrounding instructions, which only make sense
 * read in the repo file). Kept here as a literal string, not fetched from
 * the backend, so copying it needs no network round trip and works the
 * instant the Knowledge Base tab loads.
 *
 * If you edit the wording, keep prompts/EXTRACT_KNOWLEDGE_BASE.md in sync —
 * that file is the canonical copy (also readable straight from the repo, no
 * app required); this is a convenience mirror of its Step 2 for the UI's
 * "Copy extraction prompt" button. */
export const KNOWLEDGE_BASE_EXTRACTION_PROMPT = `You are a senior business analyst cataloguing an enterprise project's domain knowledge, sourced from
documents spanning all 15 SDLC areas below. I will give you one or more internal documents, each labeled
with what it is. For each area that your source material actually covers, extract facts in the exact
style shown in the "Example facts" column — this specific, not a vague paraphrase:

| # | SDLC Area | Key Documents / Inputs | Example facts to extract |
| --- | --- | --- | --- |
| 01 | Business Context | Business Case/Charter, BRD, Stakeholder Analysis, Project Objectives, KPIs | Problem Statement: Manual approval takes 5 business days on average, delaying operations. Competitive Landscape: Competing tools handle facility and asset tracking separately. Proposed Solution: A unified platform combining facility hierarchy, asset tracking, and approvals. Stakeholder: Head of Operations – owns the go-live decision. Objective: Reduce manual approval time by 40% within two quarters. Scope Boundary: Mobile app support is out of scope for phase-1. Success Metric: 95% of users onboarded within 30 days of launch. |
| 02 | Domain & Glossary | Glossary Document, Acronyms List, Domain Manuals, Industry Standards | Glossary: Customer Account – commercial relationship with a customer. Glossary: TAT – Turn Around Time (maximum allowed processing time). |
| 03 | Actors & Roles | Role Catalog, RBAC Matrix, Responsibility Matrix, Approval Hierarchy | Rule: Maker-Checker separation must be followed for all financial transactions. Rule: The creator of a request cannot approve the same request. |
| 04 | Business Processes | Process Flows, BPMN Diagrams, SOPs, Workflow Documents | Rule: Orders > ₹10L require CFO approval. Constraint: A request must be approved within 48 hours. |
| 05 | Business Rules | Business Rules Document, Policy Documents, Validation Rules, Calculation Sheets | Rule: Invoice > ₹5,00,000 requires Finance Manager and CFO approval. Rule: Discount cannot exceed 20% of invoice value. |
| 06 | Functional Requirements | SRS/FRD, Use Cases, User Stories, Acceptance Criteria | Rule: System shall send email notification on order approval. Constraint: System must support bulk upload of up to 10,000 records. |
| 07 | Non-Functional Requirements | NFR Document, Performance Benchmarks, Security Requirements, Compliance Requirements | Constraint: API response time must be < 2 seconds for 95% of requests. Constraint: Data must be stored in India. |
| 08 | Architecture Decisions | ADRs, Design Review Notes, Technical RFCs | Decision: PostgreSQL selected as primary DB for ACID compliance. Decision: Kafka not adopted due to low event volume and complexity. |
| 09 | System Architecture | HLD, LLD, C4 Diagrams, Deployment Diagrams | Decision: API Gateway will be used for all external integrations. Constraint: No direct DB access from application servers. |
| 10 | Data Domain | ER Diagrams, Data Dictionary, Data Lineage, Retention Policies | Glossary: Order – customer purchase request captured in the system. Constraint: Order data must be retained for 7 years. |
| 11 | APIs & Integrations | API Specs (OpenAPI), Interface Agreements, Vendor Documents, Integration Design | Constraint: Payment API timeout is 30 seconds. Constraint: Max 100 requests per minute to external API. |
| 12 | Security & Compliance | Security Requirements, IAM Matrix, Threat Model, Compliance Policies | Rule: PII data must be encrypted at rest and in transit. Constraint: System must comply with GDPR. |
| 13 | Testing Knowledge | Test Strategy, Test Cases, UAT Cases, Defect Reports | Rule: System must prevent duplicate active orders with the same reference. Rule: System must handle up to 10,000 concurrent users. |
| 14 | Deployment & Release | Release Plan, Environment Matrix, Deployment Runbooks, Rollback Plan | Constraint: Rollback must be possible within 30 minutes. Decision: Blue-Green deployment chosen for zero-downtime. |
| 15 | Operations & Production | SLA/SLO, Runbooks, Monitoring Rules, DR/BCP Plans, Incident/RCA Reports | Constraint: RTO is 2 hours in case of disaster. Rule: Critical incidents must be acknowledged within 15 minutes. |

Output ALL extracted facts in the following format — one \`##\` heading per fact, nothing folded together.

Rules:
- Every heading MUST start with exactly one of these words, matching the fact's category:
  \`Glossary:\`, \`Rule:\`, \`Decision:\`, or \`Constraint:\` — followed by a short, specific name for the fact.
  EXCEPTION: a Business Context fact (area 01) instead starts with one of its 7 kind labels:
  \`Problem Statement:\`, \`Competitive Landscape:\`, \`Proposed Solution:\`, \`Objective:\`, \`Stakeholder:\`,
  \`Scope Boundary:\`, or \`Success Metric:\` — never \`Glossary:\`/\`Rule:\`/\`Decision:\`/\`Constraint:\` for
  that area. Optionally end the heading with the SDLC area in parentheses, e.g.
  "## Rule: Maker-Checker separation (Actors & Roles)" — this is for a human reviewer's benefit only and
  does not change how the fact is categorized.
- Each section's body must be 2-4 sentences of real, specific detail with actual numbers, thresholds,
  role names, and exceptions where the source gives them — copy the concreteness of the example facts
  above (real currency amounts, percentages, timeouts, RTO/RPO numbers), never a vague paraphrase like
  "various approval rules apply."
- If the source material states something OUTRIGHT AMBIGUOUSLY or leaves it unresolved (two documents
  disagree, a policy is referenced but never defined, an acronym is never expanded), still write the
  heading, but put exactly \`TBD:\` at the start of the body followed by what's missing. Never guess or
  invent a resolution — an explicit gap is more useful than a confident-sounding fabrication.
- Skip anything that's implementation detail with no business meaning (code style, file layout) — this
  is a business/domain knowledge base, not a repo README.
- Do not add commentary before, after, or between sections. Output nothing but the sections themselves.

Output exactly this shape (repeat as many sections as the material supports — for a real enterprise
project spanning multiple SDLC areas, dozens is expected, this is not capped at a handful):

---

## Problem Statement: [Short name] (Business Context)
[What problem the project exists to solve.]

## Competitive Landscape: [Short name] (Business Context)
[How this differs from alternatives.]

## Proposed Solution: [Short name] (Business Context)
[What was proposed to address the problem.]

## Objective: [Short name] (Business Context)
[The goal itself, specific enough to measure progress against.]

## Stakeholder: [Short name] (Business Context)
[Who they are and how they're impacted by or influence the project.]

## Scope Boundary: [Short name] (Business Context)
[What's explicitly in or out of scope.]

## Success Metric: [Short name] (Business Context)
[The measurable KPI and its target.]

## Glossary: [Term] (optional SDLC area)
[What it means, in this project's specific context — not a generic dictionary definition.]

## Glossary: [Another term]
[...]

## Rule: [Short name for the rule] (optional SDLC area)
[The rule itself, specific enough to act on — numbers, thresholds, exceptions, who it applies to.]

## Decision: [Short name for the decision] (optional SDLC area)
[What was decided, and — if the source says so — why, and what alternative was rejected.]

## Constraint: [Short name for the constraint] (optional SDLC area)
[The hard limit itself — a number, a platform requirement, a compliance requirement, a deadline.]

---

[PASTE YOUR SOURCE MATERIAL BELOW THIS LINE — label each document with what it is, e.g. "=== BRD ===", "=== ADR-014 ===", "=== IAM Matrix ==="]
`
