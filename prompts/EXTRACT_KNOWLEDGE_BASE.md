# AutoSDLC Knowledge Base Extraction Prompt

## Instructions

Use this for an enterprise-scale project where hand-typing glossary terms, business rules, decisions,
and constraints one at a time isn't realistic. Point an AI tool at whatever source material you already
have across the SDLC — not just a single brief or README — and it will extract everything into one file
in the exact format AutoSDLC's Knowledge Base upload expects.

The output is heading-per-fact on purpose: AutoSDLC splits the file by `##` heading into one knowledge
base entry per section (no AI call on AutoSDLC's side — this parsing step is deliberately deterministic,
so it can't itself invent anything). Keep each heading's content short and single-purpose rather than
folding several facts into one section.

## Step 1: Gather your source material

An enterprise project's real knowledge is scattered across every SDLC phase, not just one brief. Pull
together whatever you actually have across as many of these 15 areas as apply — you don't need all of
them, and it's fine if some rows have nothing to contribute. The last column shows the exact style of
fact to extract from each area — match that specificity, not a vague paraphrase:

| # | SDLC Area | Key Documents / Inputs | Example facts to extract |
| --- | --- | --- | --- |
| 01 | Business Context | Business Case/Charter, BRD, Stakeholder Analysis, Project Objectives, KPIs | **Problem Statement:** Manual approval of routine requests takes an average of 5 business days, delaying operations. **Competitive Landscape:** Competing tools handle facility and asset tracking separately, requiring manual reconciliation. **Proposed Solution:** A unified platform combining facility hierarchy, asset tracking, and approvals. **Stakeholder:** Head of Operations – owns the go-live decision. **Objective:** Reduce manual approval time by 40% within the first two quarters. **Scope Boundary:** Mobile app support is explicitly out of scope for phase-1. **Success Metric:** 95% of users onboarded within 30 days of launch. |
| 02 | Domain & Glossary | Glossary Document, Acronyms List, Domain Manuals, Industry Standards | **Glossary:** Customer Account – commercial relationship with a customer. **Glossary:** Active Status – account is usable and not closed. **Glossary:** TAT – Turn Around Time (maximum allowed processing time). |
| 03 | Actors & Roles | Role Catalog, RBAC Matrix, Responsibility Matrix, Approval Hierarchy | **Rule:** Maker-Checker separation must be followed for all financial transactions. **Rule:** The creator of a request cannot approve the same request. **Glossary:** Approver – user authorized to approve a pending request. |
| 04 | Business Processes | Process Flows, BPMN Diagrams, SOPs, Workflow Documents | **Rule:** Orders > ₹10L require CFO approval. **Rule:** If payment fails, order status must be 'Payment Failed'. **Constraint:** A request must be approved within 48 hours. |
| 05 | Business Rules | Business Rules Document, Policy Documents, Validation Rules, Calculation Sheets | **Rule:** Invoice > ₹5,00,000 requires Finance Manager and CFO approval. **Rule:** Discount cannot exceed 20% of invoice value. **Rule:** Customer account number must be unique across all records. |
| 06 | Functional Requirements | SRS/FRD, Use Cases, User Stories, Acceptance Criteria | **Rule:** System shall allow user to create a sales order. **Rule:** System shall send email notification on order approval. **Constraint:** System must support bulk upload of up to 10,000 records. |
| 07 | Non-Functional Requirements | NFR Document, Performance Benchmarks, Security Requirements, Compliance Requirements | **Constraint:** API response time must be < 2 seconds for 95% of requests. **Constraint:** System availability must be 99.9% monthly. **Constraint:** Data must be stored in India. |
| 08 | Architecture Decisions | ADRs, Design Review Notes, Technical RFCs | **Decision:** PostgreSQL selected as primary DB for ACID compliance. **Decision:** Kafka not adopted due to low event volume and complexity. **Decision:** Monolith chosen for phase-1; microservices in phase-2. |
| 09 | System Architecture | HLD, LLD, C4 Diagrams, Deployment Diagrams | **Decision:** API Gateway will be used for all external integrations. **Constraint:** All services must run in a private subnet. **Constraint:** No direct DB access from application servers. |
| 10 | Data Domain | ER Diagrams, Data Dictionary, Data Lineage, Retention Policies | **Glossary:** Order – customer purchase request captured in the system. **Rule:** Order number must be unique. **Constraint:** Order data must be retained for 7 years. |
| 11 | APIs & Integrations | API Specs (OpenAPI), Interface Agreements, Vendor Documents, Integration Design | **Constraint:** Payment API timeout is 30 seconds. **Rule:** On timeout, transaction status must be 'Pending'. **Constraint:** Max 100 requests per minute to external API. |
| 12 | Security & Compliance | Security Requirements, IAM Matrix, Threat Model, Compliance Policies | **Rule:** PII data must be encrypted at rest and in transit. **Rule:** Users with 'Support' role cannot access financial data. **Constraint:** System must comply with GDPR. |
| 13 | Testing Knowledge | Test Strategy, Test Cases, UAT Cases, Defect Reports | **Rule:** System must prevent duplicate active orders with the same reference. **Rule:** Date cannot be in the future for back-dated transactions. **Rule:** System must handle up to 10,000 concurrent users. |
| 14 | Deployment & Release | Release Plan, Environment Matrix, Deployment Runbooks, Rollback Plan | **Constraint:** Production deployments only during the maintenance window. **Constraint:** Rollback must be possible within 30 minutes. **Decision:** Blue-Green deployment chosen for zero-downtime. |
| 15 | Operations & Production | SLA/SLO, Runbooks, Monitoring Rules, DR/BCP Plans, Incident/RCA Reports | **Constraint:** RTO is 2 hours in case of disaster. **Constraint:** RPO is 15 minutes. **Rule:** Critical incidents must be acknowledged within 15 minutes. |

Paste in as much as you have — the more real documentation you give it, the fewer sections come back
thin. Multiple documents from multiple areas are fine; paste them all after the prompt below, each
clearly labeled with which document it is.

## Step 2: Paste this prompt + your source material into any AI tool

You are a senior business analyst cataloguing an enterprise project's domain knowledge, sourced from
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

Output ALL extracted facts in the following format — one `##` heading per fact, nothing folded together.

Rules:
- Every heading MUST start with exactly one of these words, matching the fact's category:
  `Glossary:`, `Rule:`, `Decision:`, or `Constraint:` — followed by a short, specific name for the fact.
  EXCEPTION: a Business Context fact (area 01) instead starts with one of its 7 kind labels:
  `Problem Statement:`, `Competitive Landscape:`, `Proposed Solution:`, `Objective:`, `Stakeholder:`,
  `Scope Boundary:`, or `Success Metric:` — never `Glossary:`/`Rule:`/`Decision:`/`Constraint:` for that
  area. Optionally end the heading with the SDLC area in parentheses, e.g.
  "## Rule: Maker-Checker separation (Actors & Roles)" — this is for a human reviewer's benefit only and
  does not change how the fact is categorized.
- Each section's body must be 2-4 sentences of real, specific detail with actual numbers, thresholds,
  role names, and exceptions where the source gives them — copy the concreteness of the example facts
  above (real currency amounts, percentages, timeouts, RTO/RPO numbers), never a vague paraphrase like
  "various approval rules apply."
- If the source material states something OUTRIGHT AMBIGUOUSLY or leaves it unresolved (two documents
  disagree, a policy is referenced but never defined, an acronym is never expanded), still write the
  heading, but put exactly `TBD:` at the start of the body followed by what's missing. Never guess or
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

## Step 3: Paste the result back

Save the AI's output as a `.md` file and upload it on the project's **Knowledge Base** tab (Upload
template). Every section becomes a candidate entry; anything the AI marked `TBD:` — or that's too short
to stand on its own — is flagged for you to fill in or drop before anything is saved.
