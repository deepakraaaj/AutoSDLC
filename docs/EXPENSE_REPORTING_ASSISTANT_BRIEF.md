# Project: Expense Reporting Assistant

## Executive Summary

Build a web-based expense reporting assistant for employees, approvers, and finance teams. The product must turn receipt images into structured expense claims, apply company policy automatically, route submissions to the right approver, and give finance a clear audit trail from receipt to reimbursement.

The MVP is designed for organisations with 100–2,000 employees that currently rely on spreadsheets, shared inboxes, and manual reimbursement checks. It should reduce the time employees spend filing expenses, surface policy exceptions before approval, and allow finance to close a reimbursement period without reconciling disconnected data sources.

---

## Problem Statement

Expense claims are slow and error-prone when employees type receipt details manually and finance teams check every line item by hand. Missing receipts, duplicate claims, incorrect currencies, late submissions, and unclear approval ownership create delayed reimbursements and poor visibility into business spend. Managers also lack a simple way to approve a batch of legitimate expenses while paying attention to exceptions that need review.

---

## Goals

- Let an employee create and submit an expense claim from a desktop or mobile browser in under five minutes.
- Extract merchant, date, amount, currency, and tax from uploaded receipts with a human-review step for low-confidence fields.
- Apply company policies before submission and clearly explain any warning or blocking violation.
- Support manager approval, finance review, and reimbursement-ready exports.
- Maintain an immutable audit record for each claim decision and policy override.

## Success Metrics

- 80% of receipt fields are accepted without manual correction after the first three months.
- Median claim submission time is under five minutes.
- 95% of compliant claims are approved or returned within two business days.
- Duplicate reimbursement attempts detected before payment: at least 98%.
- Finance can export an approved reimbursement batch for a selected pay period in under two minutes.

---

## Target Users

### Employee

Creates claims, uploads receipts, corrects extracted fields, and tracks reimbursement status. Employees can see only their own claims unless they are also an approver.

### Line Manager

Reviews claims from direct reports, approves compliant expenses, returns incomplete claims with comments, and escalates policy exceptions where needed.

### Finance Reviewer

Performs final review, handles exceptions and overrides, prepares approved claims for payment, and produces audit reports.

### Finance Administrator

Configures categories, spending limits, approval rules, mileage rates, reimbursement periods, and integrations. This role can manage policy versions but cannot silently alter historical decisions.

---

## MVP Scope

### In Scope

- Email/password login with role-based access control; SSO is optional if an identity provider is available.
- Receipt upload from JPEG, PNG, HEIC, and PDF files, with image validation and virus scanning.
- OCR extraction of merchant, transaction date, subtotal, tax, total, currency, and receipt number where available.
- Manual expense entry for mileage, per diem, or receipts that cannot be scanned.
- Claim creation with multiple expense lines, categories, project/cost-centre assignment, and notes.
- Policy checks for receipt requirements, category limits, duplicate claims, allowable dates, and manager approval thresholds.
- Employee submission, manager approval/return, finance approval/reject/override, and reimbursement-ready status.
- Notifications in-app and Slack for submitted, returned, approved, rejected, and overdue claims.
- Finance dashboard, searchable audit log, and CSV export of approved claims.

### Out of Scope for MVP

- Direct reimbursement payments or payroll execution.
- Corporate card transaction import and automatic card-to-receipt matching.
- Travel booking and itinerary management.
- Native iOS or Android applications; the web experience must be mobile responsive.
- Multi-entity tax reporting and country-specific tax reclaim workflows beyond configurable tax fields.

---

## Core User Journeys

### 1. Employee submits a receipt-backed claim

1. Employee starts a new claim and selects a reimbursement period.
2. They upload one or more receipt images or PDFs.
3. The system extracts fields and flags any low-confidence values for confirmation.
4. Employee selects an expense category, cost centre, and optional project, then adds a business purpose.
5. The system runs policy and duplicate checks.
6. The employee corrects warnings or provides a justification for a permitted exception.
7. Employee submits the claim; the assigned manager receives a notification.

### 2. Manager reviews a claim

1. Manager opens their approval queue and sees compliant claims separately from exceptions.
2. They inspect receipt images, entered data, policy warnings, and employee justification.
3. They approve, return with a required comment, or escalate the claim to finance.
4. The employee is notified of the decision and can revise returned claims.

### 3. Finance closes a reimbursement batch

1. Finance filters claims by approved status and reimbursement period.
2. A reviewer resolves any remaining policy exceptions or marks a claim as rejected.
3. The system generates a payment-ready CSV containing employee, bank-reference placeholder, approved amount, currency, and claim ID.
4. Finance marks exported claims as sent to payroll/payment, preserving the export timestamp and user identity.

---

## Functional Requirements

### Receipt Ingestion and Extraction

- Store the original uploaded receipt and a normalized preview.
- Reject unsupported file types and files larger than 10 MB with a clear error.
- Run OCR asynchronously and show a processing state.
- Keep the original OCR value and confidence score for each extracted field.
- Require employee confirmation when merchant, date, total, or currency confidence is below the configured threshold.

### Claims and Expenses

- A claim contains one or more expense lines and belongs to one employee.
- An expense line includes date, merchant, amount, currency, tax, category, business purpose, cost centre, project, receipt reference, and optional notes.
- Employees can save drafts, edit drafts, and withdraw submitted claims until manager action begins.
- The system calculates claim totals by original currency and, where an exchange-rate source is configured, the company reporting currency.

### Workflow

- Claim states: Draft, Submitted, Returned, Manager Approved, Finance Review, Approved for Reimbursement, Rejected, Exported.
- The employee cannot approve their own claim.
- Approval routing uses the employee’s active manager; if no manager exists, route to the finance queue.
- A returned or rejected claim requires a human-readable reason.
- Finance overrides require a reason and must be visible in the audit trail.

### Policy and Risk Checks

- Block submission when a receipt is required but missing.
- Warn or block when category limits are exceeded based on policy configuration.
- Detect potential duplicates using employee, merchant, transaction date, amount, currency, and receipt number where present.
- Flag expenses submitted more than 90 days after the transaction date unless the policy allows an exception.
- Flag expenses for restricted merchants or categories for finance review.

### Administration and Reporting

- Administrators can configure categories, receipt rules, per-category limits, approval thresholds, cost centres, and project codes.
- Policies are versioned; each claim records the policy version evaluated at submission time.
- Finance can search claims by employee, merchant, category, status, date range, cost centre, project, and policy outcome.
- Export approved claims as CSV with an export ID, selected period, and a list of included claim IDs.

---

## Business Rules

- A receipt is mandatory for any expense over the configured threshold; default threshold is USD 25 or equivalent.
- A claim may contain expenses in multiple currencies, but each line must identify its original currency.
- Duplicate-risk findings do not automatically reject a claim; they prevent automatic approval and require reviewer action.
- Only Finance Reviewers and Finance Administrators can apply a policy override.
- Exported claims are immutable. Corrections must be recorded as a new adjustment claim linked to the original claim.
- All timestamps are stored in UTC and displayed in the user’s configured timezone.

---

## Non-Functional Requirements

### Performance

- Claim list and approval queue load in under two seconds for 10,000 claims.
- Receipt upload should acknowledge within three seconds on a typical broadband connection.
- OCR processing should complete within 30 seconds for a single receipt under 10 MB; show retry guidance if it fails.
- CSV export for up to 5,000 claims should complete in under two minutes.

### Security and Privacy

- Encrypt data in transit and at rest.
- Enforce role-based access at the API level, not only in the UI.
- Store uploaded receipts in private object storage with time-limited access URLs.
- Record actor, timestamp, before/after values, and reason for every approval, status change, and policy override.
- Retain receipts and audit records for seven years by default, configurable by organisation policy.

### Reliability and Accessibility

- 99.5% monthly availability target for employee submission and approval workflows.
- Retry failed OCR jobs safely without creating duplicate expense lines.
- Meet WCAG 2.1 AA for keyboard navigation, focus visibility, labels, and status announcements.

---

## Data Entities

### Expense Claim

Claim ID, employee ID, manager ID, status, reimbursement period, totals by currency, reporting-currency total, policy version, submitted/approved/exported timestamps, and audit references.

### Expense Line

Expense line ID, claim ID, merchant, transaction date, amount, currency, tax, category, business purpose, cost centre, project code, source type, and policy results.

### Receipt

Receipt ID, expense line ID, original file reference, normalized preview reference, OCR extraction fields, confidence scores, processing status, and duplicate fingerprint.

### Policy

Policy ID, version, effective date, category limits, receipt thresholds, prohibited categories, late-submission rules, and approval thresholds.

### Audit Event

Audit event ID, entity type/ID, actor, event type, timestamp, changed fields, decision reason, and policy version.

---

## Integrations

- OCR provider for receipt extraction.
- Slack for workflow notifications and reminders.
- Identity provider for optional SSO and employee/manager directory sync.
- Exchange-rate provider for reporting-currency conversion.
- Payroll or accounts-payable export destination via CSV in MVP; API integration is a later phase.
