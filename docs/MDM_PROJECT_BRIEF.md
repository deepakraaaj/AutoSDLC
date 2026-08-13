# Project: Enterprise Master Data Management (MDM) Hub

## Executive Summary
A multi-domain Master Data Management platform that ingests raw records for Customer, Product, and Vendor/Supplier entities from source systems, resolves them into trusted "golden records" via automated match/merge, and publishes those golden records to downstream systems via API and events. Data Stewards drive the match/merge review workflow, resolving ambiguous matches and enforcing survivorship rules so every consuming system works off a single trusted source of truth.

---

## Problem Statement
Customer, product, and vendor data lives fragmented across multiple source systems (CRM, ERP, procurement, e-commerce), each with its own identifiers, formats, and quality levels. The same customer or vendor can exist as 3-5 duplicate records across systems, with no reliable way to tell which is authoritative. Downstream systems and reports consume this inconsistent data directly, producing conflicting counts, failed vendor payments, duplicate outreach to the same customer, and hours of manual reconciliation whenever discrepancies surface. There is no governed, auditable process for deciding which version of a record wins, and no single API that downstream systems can trust as the source of truth.

---

## Goals
- Establish one authoritative golden record per entity (Customer, Product, Vendor) across all source systems
- Automate match/merge decisions for high-confidence duplicates, cutting manual reconciliation effort by 80%
- Give Data Stewards a governed review queue for ambiguous matches, with full audit trail of every merge/split decision
- Publish golden records to downstream systems via API/events with predictable, low-latency delivery
- Achieve 95%+ match precision (no incorrect auto-merges) on production data within the first quarter

---

## Success Metrics
- **Match/merge automation rate**: 80%+ of duplicate pairs auto-resolved without steward review (high-confidence matches only)
- **Match precision**: 95%+ (auto-merged pairs later confirmed correct on audit)
- **Steward review time**: <5 minutes per ambiguous match case
- **Golden record publish latency**: <60 seconds from merge decision to downstream API/event availability
- **Data steward adoption**: 100% of flagged match candidates reviewed within 24 hours

---

## Target Users

### Data Steward (primary)
- **Who:** Data governance team member responsible for reviewing match candidates, resolving conflicts, and maintaining golden record quality across Customer, Product, and Vendor domains.
- **Need:** A prioritized review queue showing match confidence, a side-by-side comparison of candidate records, and one-click approve/merge/reject/split actions — with every decision logged for audit.
- **Success:** Can clear the daily review queue in under an hour; trusts that auto-merged records didn't need their attention; can trace any golden record back to its source records and the decision that created it.

### IT/Data Engineer
- **Who:** Engineer responsible for connecting source systems (CRM, ERP, procurement) to the MDM hub and consuming golden records downstream.
- **Need:** Reliable ingestion feeds with clear error handling, and a stable API/event contract for publishing golden records out.
- **Success:** Source feeds run unattended with alerting on failures; downstream teams can integrate against a documented, versioned API without breaking changes.

### Governance Admin
- **Who:** Owns match rules, survivorship rules, and confidence thresholds across domains.
- **Need:** Configure how records are compared and merged (which fields, which weighting, which thresholds trigger auto-merge vs. steward review) without needing engineering changes.
- **Success:** Can tune match sensitivity per domain and see the immediate effect on the steward review queue volume.

---

## MVP Scope

### Must-Have Features (In Scope)
- Ingest raw entity records (Customer, Product, Vendor) from source system feeds (batch file and API) into a staging area
- Automated match/merge engine: score candidate duplicate pairs, auto-merge above a configurable high-confidence threshold, route below-threshold pairs to a steward review queue
- Data Steward review queue: side-by-side record comparison, confidence score, approve/merge/reject/split actions, full decision audit trail
- Golden record store: one authoritative record per entity, with lineage back to every contributing source record
- Publish golden records to downstream consumers via a versioned REST API and change events (create/update/merge/retire)

### Nice-to-Have (Out of Scope / v2)
- Self-service data quality dashboards and completeness scoring per domain
- Search & 360-degree view UI for business users/data consumers
- Hierarchy management (org charts, product bundles, vendor parent/child relationships)

### Explicitly Out of Scope
- Real-time (sub-second) match/merge — batch/near-real-time is acceptable for MVP
- Automated fraud/anomaly detection on source data
- Direct write-back to source systems (MDM is consume-and-publish only, not bidirectional sync, for MVP)

---

## Core User Journeys

### Journey 1: Automated Match/Merge on Ingestion
**Actor:** System (triggered by source feed ingestion)

1. Source system feed delivers a batch of raw Customer/Product/Vendor records into staging
2. Match engine standardizes and scores each new record against existing golden records and other staged records
3. Pairs scoring above the auto-merge threshold are merged automatically into an updated golden record; the decision and source lineage are logged
4. Pairs scoring in the ambiguous band are queued for Data Steward review with their confidence score and comparison detail
5. Pairs scoring below the match threshold are treated as new golden records
6. Updated/new golden records are published to downstream systems via API/event

### Journey 2: Data Steward Resolves an Ambiguous Match
**Actor:** Data Steward

1. Steward opens the MDM app → Review Queue
2. Sees pending match candidates across their assigned domain(s), each with a confidence score and source system(s)
3. Filters by domain (Customer/Product/Vendor), confidence band, or source system
4. Opens a candidate pair; sees a side-by-side field comparison highlighting conflicts
5. Chooses: Merge (select surviving values per field), Reject (keep as separate records), or Split (undo a prior incorrect merge)
6. Decision is recorded with steward identity, timestamp, and rationale notes
7. Golden record store updates; downstream publish is triggered automatically

---

## Functional Requirements

### Ingestion
- Accept batch file (CSV) and API-based record submission per domain (Customer, Product, Vendor)
- Validate incoming records against required-field rules per domain; reject/quarantine malformed records with a reason
- Track full lineage: which source system and source record ID contributed to each golden record

### Match/Merge Engine
- Score candidate pairs using configurable field-weighted matching (e.g., name, email/tax ID, address) per domain
- Auto-merge threshold and steward-review threshold are configurable per domain by a Governance Admin
- Survivorship rules determine which field values win on merge (e.g., most recent, most complete, source-system priority) — configurable per field
- Every merge/split decision (automatic or steward-driven) is logged with before/after state

### Data Steward Review Queue
- List pending match candidates sorted by confidence score (lowest confidence/highest ambiguity first, configurable)
- Filter by domain, confidence band, source system, date queued
- Side-by-side comparison view with conflicting fields visually highlighted
- Approve/merge, reject, and split actions, each requiring the steward to confirm surviving field values on merge
- Full audit trail: who decided, when, what changed, and why (optional notes field)

### Publishing / Downstream API
- Versioned REST API exposing golden records per domain (read-only for MVP)
- Change events emitted on create, update, merge, and retire for downstream systems to subscribe to
- Publish latency target: under 60 seconds from decision to availability

---

## Business Rules & Constraints
- Auto-merge only occurs above the configured high-confidence threshold (default 95%); anything below routes to steward review
- A steward-rejected match must not be re-suggested for auto-merge without a change in source data or rules
- Every merge is reversible via a "split" action, which restores the original source records as separate golden records
- Golden records are never deleted, only marked retired, to preserve audit history
- Match thresholds and survivorship rules are configurable per domain, not global — Customer, Product, and Vendor may need different sensitivity

---

## Non-Functional Requirements

### Performance
- Ingestion-to-golden-record processing: under 5 minutes for a batch of 10,000 records
- Steward review queue load: under 2 seconds
- Golden record publish latency: under 60 seconds from decision to downstream availability
- Support 50+ concurrent Data Stewards across domains

### Security & Compliance
- All data encrypted in transit (HTTPS) and at rest
- Support SSO (Okta, Google Workspace)
- Full audit log: who changed what, when, and from where, retained indefinitely
- Role-based access: Stewards scoped to assigned domain(s); Governance Admins have cross-domain config access

### Platform & Availability
- Web app: Chrome, Firefox, Safari (latest 2 versions)
- 99.5% uptime SLA for the review queue and publish API
- Ingestion and match/merge processing can run as scheduled/batch jobs; steward UI must be available during business hours at minimum

### Data & Integrations
- Ingest from source systems via batch file (CSV) and REST API
- Publish golden records via REST API and change events (webhook or message queue) to downstream consumers
- Connect to company identity system (SSO) for steward/admin login

---

## Data Entities

### Source Record
- **ID**: Unique identifier (source system + source record ID)
- **Fields**: Domain (Customer/Product/Vendor), raw field values, source_system, ingested_at
- **States**: Staged, Matched, Merged, Quarantined
- **Owner**: Source system feed

### Golden Record
- **ID**: Unique identifier (per domain)
- **Fields**: Domain, canonical field values, confidence_score, lineage (contributing source record IDs), last_merged_at
- **States**: Active, Retired
- **Owner**: MDM system (created via match/merge, edited only through steward decisions)

### Match Candidate
- **ID**: Unique identifier
- **Fields**: Record pair references, confidence_score, matched_fields, conflicting_fields, status, decision, decided_by, decided_at, notes
- **States**: Pending, Auto-Merged, Steward-Approved, Rejected, Split
- **Owner**: Match engine (auto) or Data Steward (reviewed)

---

## External Integrations

### Source Systems (CRM / ERP / Procurement)
- Deliver raw Customer, Product, and Vendor records via batch file or API
- Provide source system identifiers for lineage tracking

### Downstream Consumers
- Consume golden records via versioned REST API
- Subscribe to change events (create/update/merge/retire) for near-real-time sync

### Okta / SSO
- SSO login for Data Stewards and Governance Admins
- Pull user roles and domain assignments

---

## Technology Preferences

### Frontend
- React + TypeScript
- TailwindCSS for styling

### Backend
- FastAPI (Python)
- PostgreSQL for data (golden records, match candidates, audit log)
- Async job processing for ingestion and match/merge batches

### Infrastructure
- AWS (EC2/ECS for app, RDS for database)
- Docker containers
- GitHub Actions for CI/CD

---

## Phased Rollout

### Phase 1 (MVP, Month 1-2)
- Customer domain ingestion, match/merge, and steward review queue
- Golden record publish API (read-only) for Customer domain
- Target: Pilot with one business unit's customer data

### Phase 2 (Month 3)
- Extend to Product and Vendor domains
- Change event publishing (webhooks/queue) for downstream sync
- Okta SSO integration

### Phase 3 (Month 4+)
- Data quality dashboards and completeness scoring
- Search & 360-degree view UI for business users
- Hierarchy management (org/parent-child relationships)

---

## Risks & Assumptions

### Risks
- **Match precision below target**: Mitigation — start with a conservative (high) auto-merge threshold and lower it gradually as precision is validated against steward-confirmed outcomes
- **Source system data quality varies widely**: Mitigation — per-source validation rules and a quarantine queue instead of silently ingesting bad data
- **Downstream systems built against an unstable API**: Mitigation — version the publish API from day one; deprecate old versions on a published timeline

### Assumptions
- Source systems can provide stable identifiers for lineage tracking
- Data Stewards are assigned per domain and available to clear the review queue within 24 hours
- Company uses Okta for identity management
- Near-real-time (minutes, not seconds) publish latency is acceptable to downstream consumers for MVP

---

## Dependencies & Constraints
- Access/credentials to source systems (CRM, ERP, procurement) needed before ingestion can begin
- Okta SSO setup must be complete before steward/admin login can launch
- Governance team must define initial match rules and survivorship rules per domain before go-live
- Downstream teams must agree on the golden record API contract before Phase 1 pilot

---

## Open Questions
- [ ] What are the specific source systems for Customer, Product, and Vendor data in Phase 1?
- [ ] What auto-merge confidence threshold should default per domain? (Assumed 95%, needs governance sign-off)
- [ ] Should downstream publishing be webhook-based, message-queue-based, or both?
- [ ] Is a nightly batch ingestion cadence acceptable for MVP, or is more frequent ingestion required?
- [ ] Who owns match rule configuration day-to-day — Governance Admin role, or engineering?

---

## Document Info
- **Created**: 2026-08-13
- **Owner**: Product Team
- **Status**: Ready for review
