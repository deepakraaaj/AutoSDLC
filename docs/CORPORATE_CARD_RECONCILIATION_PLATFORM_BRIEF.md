# Project: Corporate Card Reconciliation Platform

## Executive Summary

Build a corporate-card reconciliation platform for finance teams and cardholders. The product ingests card transactions from issuing banks, matches them to receipts and expense reports, applies company spending policy, and gives finance a controlled workflow to resolve unmatched or suspicious transactions before the accounting close.

It complements an expense-reporting assistant: employees use the expense application to submit receipts and business context, while this platform ensures every corporate-card transaction is accounted for without requiring employees to manually recreate a payment they made with a company card.

---

## Problem Statement

Finance teams often receive card feeds days after a purchase and reconcile them in spreadsheets. A transaction may lack a receipt, be assigned to the wrong cost centre, appear twice, or be mixed with a personal expense. Employees do not know which transactions need action, managers cannot see unresolved spend in their teams, and finance has no reliable view of close readiness.

The platform must replace manual reconciliation with a transaction-to-receipt workflow, clear ownership, automated matching, policy checks, and an auditable export to the accounting system.

---

## Goals

- Ingest daily transactions from supported corporate-card providers.
- Automatically match eligible transactions to expense lines and receipts.
- Give cardholders a simple queue for missing receipts and business purpose details.
- Let finance resolve exceptions with an auditable decision trail.
- Provide a close-readiness view that shows unreconciled spend by owner, age, entity, and cost centre.

## Success Metrics

- At least 75% of card transactions automatically matched within 24 hours of feed ingestion.
- 90% of transactions reconciled within 10 business days of transaction date.
- Finance close preparation time reduced by 40% within two quarters.
- Fewer than 1% of exported transactions require a post-export correction.
- Cardholders resolve receipt requests within two business days on average.

---

## Target Users

### Cardholder

Views assigned card transactions, uploads missing receipts, supplies a business purpose, splits a transaction across categories or cost centres, and disputes personal or incorrect charges.

### Finance Analyst

Monitors exceptions, reviews matches, resolves duplicates, manages transaction ownership, and prepares reconciled entries for export.

### Finance Controller

Monitors close readiness, approves high-value write-offs or policy exceptions, and reviews audit evidence.

### Card Programme Administrator

Configures card providers, cardholder mappings, merchant/category rules, reminder schedules, accounting mappings, and user access.

---

## MVP Scope

### In Scope

- Daily transaction-feed ingestion from one card provider through API or SFTP import.
- Cardholder and card mapping from the company directory.
- Transaction list, transaction detail, and status filters.
- Automatic matching against expense-report expense lines using amount, currency, merchant, date, and receipt fingerprint.
- Manual match, unmatch, split, annotate, dispute, and mark-as-personal actions.
- Receipt request and reminder workflow for unmatched transactions.
- Configurable policy checks for merchant category, transaction amount, receipt requirement, and late reconciliation.
- Finance exception queue, close-readiness dashboard, audit log, and CSV accounting export.
- Webhooks or API callbacks to update linked expense-report entries with the card transaction reference.

### Out of Scope for MVP

- Issuing virtual cards or changing card spending limits in real time.
- Direct general-ledger posting; MVP exports validated CSV files.
- Multi-provider real-time streaming ingestion.
- Employee reimbursement payments.
- Travel booking, procurement approvals, and invoice processing.

---

## Core User Journeys

### 1. Transaction is automatically matched

1. The platform imports a transaction from the card provider.
2. It normalizes merchant, amount, currency, and transaction date.
3. A matching engine finds an eligible expense line with a corresponding receipt.
4. The system records a high-confidence match and updates the transaction to **Matched**.
5. The linked expense report displays the card reference and no reimbursement is created for that line.

### 2. Cardholder resolves a missing receipt

1. A transaction remains unmatched after the configured grace period.
2. The cardholder receives an in-app and Slack reminder.
3. They open the transaction, upload a receipt, select a category/cost centre, and add a business purpose.
4. The platform checks policy and proposes a match to an existing expense line or creates a draft card-expense record.
5. Finance is notified only if the transaction still violates policy or exceeds review thresholds.

### 3. Finance closes the monthly period

1. Finance selects an entity and accounting period.
2. The dashboard shows totals by transaction status: matched, pending cardholder, finance review, disputed, personal, and export-ready.
3. Finance resolves or documents all blocking exceptions.
4. The system validates required accounting fields and generates an export batch.
5. Exported transactions become immutable; corrections use a linked adjustment record.

---

## Functional Requirements

### Transaction Ingestion

- Import transaction ID, card token, posted date, transaction date, merchant, merchant category code, amount, currency, country, and feed status.
- Make imports idempotent using provider transaction ID and account/card identifier.
- Show ingestion errors separately from business exceptions.
- Support pending-to-posted transaction updates without creating duplicate records.

### Matching and Reconciliation

- Match only when currency and amount are equal unless a configured exchange-rate tolerance applies.
- Use a configurable date window; default is plus or minus seven days.
- Rank possible matches by amount, date, merchant similarity, receipt fingerprint, and cardholder identity.
- Automatically apply only high-confidence matches; medium-confidence matches require cardholder or finance confirmation.
- Allow finance to split a transaction across multiple cost centres or expense categories while retaining the original amount and transaction ID.

### Exceptions and Cardholder Tasks

- Statuses: Imported, Matched, Awaiting Cardholder, Finance Review, Disputed, Personal Expense, Export Ready, Exported.
- Require a reason for unmatching, marking personal, disputing, or overriding policy.
- Send reminders after 3, 7, and 10 business days, configurable by administrator.
- Escalate unresolved transactions to the cardholder’s manager after the final reminder.

### Accounting Export

- Require legal entity, cost centre, account code, tax treatment, period, and transaction owner before export.
- Produce a CSV with export batch ID, transaction ID, posting date, amount, currency, account code, cost centre, project code, tax code, and memo.
- Prevent a transaction from appearing in more than one successful export batch.
- Allow a cancelled export only before file download/acknowledgement; retain the cancellation reason.

### Integration with Expense Reporting

- Store a link between a card transaction and the corresponding expense claim/expense line.
- Show linked transaction status in the expense-reporting product.
- Prevent a card-funded expense from being included in an employee reimbursement total.
- When a receipt is attached in either system, make it available to the other through a secure shared reference.

---

## Business Rules

- A corporate-card transaction must have exactly one final disposition: matched, personal, disputed, or exported with an approved accounting allocation.
- A cardholder cannot mark their own transaction as a policy override; Finance approval is required.
- Transactions over the configurable high-value threshold default to Finance Review even when automatically matched.
- A personal expense requires a repayment reference before it can leave the exception queue.
- A disputed transaction remains excluded from the accounting export until the provider’s final status is received.
- Transaction and audit history must never be deleted; corrections are additive events.

---

## Non-Functional Requirements

### Performance and Reliability

- Process a daily file containing 100,000 transactions within 30 minutes.
- Transaction search and exception queues load within two seconds for a 12-month history.
- Matching jobs are retryable and idempotent.
- 99.5% monthly availability for cardholder and finance workflows.

### Security and Compliance

- Never store full primary account numbers; use provider tokens and masked last-four display only.
- Encrypt transaction and receipt data in transit and at rest.
- Apply role-based access: cardholders see their own cards; managers see assigned-team exceptions; finance has organisation-wide access scoped by entity.
- Log every match, allocation, override, export, and status transition with actor, timestamp, previous value, new value, and reason.
- Retain records according to the organisation’s financial-retention policy; default to seven years.

### Accessibility

- Meet WCAG 2.1 AA for keyboard interaction, focus management, form labels, and error messages.
- Provide clear, non-colour-only states for transaction status and policy severity.

---

## Data Entities

### Card Transaction

Provider transaction ID, card token, cardholder ID, merchant, merchant category, transaction/posting dates, amount, currency, status, dispute state, and source-feed metadata.

### Reconciliation Record

Transaction ID, linked expense-line IDs, confidence score, match method, reviewer, final disposition, policy results, and resolution notes.

### Accounting Allocation

Transaction ID, legal entity, account code, cost centre, project code, tax code, allocation amount, period, and export batch ID.

### Cardholder Task

Transaction ID, assigned user, task type, due date, reminder count, completion status, and submitted evidence.

### Audit Event

Entity type/ID, actor, event type, timestamp, before/after values, reason, and related policy/export IDs.

---

## External Integrations

- Corporate-card provider API or SFTP feed.
- Expense Reporting Assistant for receipt and expense-line linking.
- Company identity provider for cardholder/manager mapping and authentication.
- Slack for reminders and escalations.
- Accounting or ERP system via CSV export in MVP, with a future API-based posting integration.
