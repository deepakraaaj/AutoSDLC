# Project: Expense Reporting Assistant

## Executive Summary
An AI-powered expense reporting tool for team leads that automates receipt scanning, categorization, and compliance checks. Reduces approval time from 2 days to 15 minutes. Built for mid-market companies with 50+ employees.

---

## Problem Statement
Expense approval is manual: receipts are emailed, managers spend 30 mins/week categorizing, and compliance errors delay reimbursement by 3+ days. This frustrates employees and creates admin overhead.

---

## Goals
- Reduce manual categorization effort by 80%
- Enable employees to self-serve receipts without manager review for <$100
- Achieve 95% compliance accuracy on first submission
- Increase employee satisfaction with reimbursement process

---

## Success Metrics
- **Approval time**: 15 minutes or less (vs. 2 days today)
- **Compliance pass rate**: 95%+ on first submission
- **User adoption**: 80% of team leads within 3 months
- **Processing cost**: <$0.50 per receipt

---

## Target Users

### Manager
- **Who:** Team lead or department head responsible for approving expenses
- **Need:** Quick approval process with automated compliance checks; low risk of fraud
- **Success:** Can review 20 reports in 10 minutes instead of 90 minutes; confident all expenses are compliant

### Employee
- **Who:** Individual contributor who submits expense reports
- **Need:** Fast reimbursement; don't want to manually fill out expense forms
- **Success:** Submit receipt, get auto-categorized result in real time; reimbursed within 3 days

### Finance Manager
- **Who:** Finance/accounting team responsible for GL coding and audit
- **Need:** Accurate categorization aligned with company chart of accounts
- **Success:** 95%+ auto-categorization accuracy; auditability of all decisions

---

## MVP Scope

### Must-Have Features (In Scope)
- Upload receipt image (JPG, PNG) or PDF; extract date, merchant, amount
- Auto-categorize expense into 6 categories (Travel, Meals, Equipment, Software, Training, Other)
- Manager dashboard showing pending reports with extraction confidence scores
- One-click approval for confident submissions
- Slack notification when report is approved

### Nice-to-Have (Out of Scope / v2)
- Mobile app with camera capture
- QuickBooks integration for GL syncing
- Advanced fraud detection (unusual amounts, duplicate patterns)

### Explicitly Out of Scope
- Mileage reimbursement (different workflow)
- Peer-to-peer expense splitting
- Multi-currency support

---

## Core User Journeys

### Journey 1: Employee Submits Expense
**Actor:** Employee

1. Employee opens app and taps "New Expense"
2. Employee takes photo of receipt or uploads image file
3. System extracts date, merchant, amount using OCR; shows confidence score
4. Employee reviews extraction (green = confident, yellow = review, red = manual)
5. Employee selects category (system suggests based on merchant)
6. Employee adds notes if needed (e.g., "Client dinner - Q3 planning")
7. Employee submits; gets confirmation message
8. Manager receives Slack notification of pending report

### Journey 2: Manager Approves Expenses
**Actor:** Manager

1. Manager opens app → Dashboard tab
2. Sees list of pending reports from their team
3. Each report shows: employee name, total amount, # of receipts, confidence score
4. Click on report to review details
5. For low-confidence items, can override extracted values
6. Approve or reject (with reason if rejected)
7. Approved report triggers Slack notification to employee + Finance team

---

## Functional Requirements

### Receipt Processing
- Accept JPG, PNG, PDF file formats up to 10MB
- Extract: date, merchant name, amount, receipt number (if present)
- Confidence score for extracted data: show ≥90% as green, 70-89% as yellow, <70% as red
- Allow manual override on any field after extraction
- Store original image + extracted metadata

### Categorization
- Provide 6 categories: Travel, Meals, Equipment, Software, Training, Other
- Auto-suggest category based on merchant name and amount
- Remember user's past categorizations (e.g., "Uber" → Travel)
- Show confidence score for category suggestion

### Manager Dashboard
- Show all reports submitted in last 7 days
- Filter by: employee, status (pending/approved/rejected), amount range
- Flag reports with low extraction confidence or unusual amounts
- Allow bulk-approve up to 5 reports at once
- Show approval time metrics

### Notifications
- Slack message when report submitted (tagged to manager)
- Slack message when report approved (tagged to employee)
- Daily digest of pending approvals (if >5 waiting)

---

## Business Rules & Constraints
- Expenses >$500 require VP approval before processing
- Only expenses within 30 days of receipt date are eligible for reimbursement
- Duplicate submissions (same merchant, same day, same amount) are flagged for review
- Monthly spend cap per employee: $2,000 (configurable by department)
- Meal expenses capped at $50 per person, unless marked as client entertainment (requires notes)

---

## Non-Functional Requirements

### Performance
- Receipt upload and extraction: <3 seconds
- Dashboard load: <1 second
- Support 1000+ concurrent users
- 99.5% uptime SLA

### Security & Compliance
- All data encrypted in transit (HTTPS) and at rest
- Support SSO (Okta, Google Workspace)
- Audit log: who approved what, when, from where
- GDPR compliant: users can request data deletion
- SOC 2 Type II certified (target)

### Platform & Availability
- Web app: Chrome, Firefox, Safari (latest 2 versions)
- Mobile: iOS and Android apps (React Native)
- Works online and offline (queue submissions to sync when online)

### Data & Integrations
- Integrate with Slack: post approval notifications
- Integrate with QuickBooks: sync approved expenses as journal entries
- Connect to company's identity system (LDAP, Okta, Google Workspace)
- API for third-party integrations (future)

---

## Data Entities

### Receipt
- **ID**: Unique identifier
- **Fields**: Date, merchant, amount, category, confidence_score, image_url, notes, user_id, submitted_at
- **States**: Uploaded, Extracted, Pending-Review, Approved, Rejected, Reimbursed
- **Owner**: Employee who submitted

### Expense Report
- **ID**: Unique identifier
- **Fields**: Created_date, submitted_date, approval_date, approver_id, total_amount, status, rejection_reason
- **Contains**: 1+ receipts grouped by submission
- **States**: Draft, Submitted, Approved, Rejected, Paid

### User Profile
- **Fields**: Name, email, role (employee/manager/admin), department, cost_center, manager_id
- **Preferences**: Default category, notification_channel (Slack/Email/Both)

---

## External Integrations

### Slack
- Send approval notifications to team channels
- Notify employee when report is approved
- Daily digest of pending reports in finance channel

### QuickBooks
- Sync approved expenses to GL accounts based on category
- Map expense categories to QB account numbers
- Bi-weekly batch sync (automatic)

### Okta
- SSO login via Okta
- Pull user roles and departments from Okta
- Sync user deactivations

### AWS S3
- Store receipt images (encrypted, with 7-year retention policy)
- Use CloudFront CDN for fast image delivery

---

## Technology Preferences

### Frontend
- React + TypeScript
- TailwindCSS for styling
- Redux for state management

### Backend
- FastAPI (Python)
- PostgreSQL for data
- Celery for async OCR processing

### Infrastructure
- AWS (EC2 for app, RDS for database, S3 for images)
- Docker containers, deployed on ECS
- GitHub Actions for CI/CD

### Key Libraries
- **Tesseract** for OCR (receipt text extraction)
- **python-dotenv** for config
- **psycopg2** for PostgreSQL
- **slack-sdk** for Slack integration

---

## Phased Rollout

### Phase 1 (MVP, Month 1-2)
- Receipt upload and OCR extraction
- Basic categorization (6 categories)
- Manager dashboard and approval workflow
- Slack notifications
- Target: Deploy to 1 pilot team (20 employees)

### Phase 2 (Month 3)
- Mobile app (iOS + Android)
- Okta SSO integration
- Bulk approval feature
- Target: Roll out to all teams

### Phase 3 (Month 4+)
- QuickBooks integration
- Advanced fraud detection (unusual patterns)
- Reporting & analytics dashboard
- Target: Optimize and scale

---

## Risks & Assumptions

### Risks
- **OCR accuracy <85%**: Mitigation: Use human review queue for low-confidence receipts; retrain model quarterly with corrected examples
- **Merchants not recognized**: Mitigation: Build merchant lookup service; allow manual override
- **Slack API changes**: Mitigation: Abstract Slack integration; maintain compatibility with multiple versions

### Assumptions
- Expense reports are always submitted with image receipts (not just amounts)
- Managers have time to review within 24 hours
- Company uses Okta for identity management
- Receipt dates are legible on 95%+ of photos

---

## Dependencies & Constraints
- Okta SSO setup must be complete before Phase 1 launch
- Legal approval needed for GDPR compliance checklist
- Finance team training on new approval workflow (2 hours)
- IT: VPN/network setup for image storage (S3 access)

---

## Open Questions
- [ ] What's the max file size for receipt uploads? (Assumed 10MB, needs finance approval)
- [ ] Should rejected reports go back to employee for re-submission, or escalate to finance?
- [ ] Do we need offline mode from day 1, or is Phase 2 acceptable?
- [ ] What's the approval SLA? (1 day, 4 hours, real-time?) — assumed 24 hours
- [ ] Should we auto-reject expenses >30 days old, or just flag them?

---

## Document Info
- **Created**: May 14, 2025
- **Last Updated**: May 14, 2025
- **Owner**: Product Team
- **Status**: Ready for development

---

## How to Use This Example

This is a **filled-in example** showing what a good brief looks like. You can:

1. **Edit it for your project**: Change project name, goals, features, etc.
2. **Delete and start fresh**: Clear it and use the template skeleton
3. **Download it**: Save as `.md` and share with your team
4. **Copy sections**: Borrow the structure for your own brief

---

## Tips for Your Own Brief

✅ **Do:**
- Be as specific as this example (not "user uploads file" but "accept JPG, PNG, PDF up to 10MB")
- Include actual user roles and what success means to them
- List 3+ features in scope so the AI generates enough epics/stories
- Mention key integrations (Slack, QuickBooks, etc.)
- State business metrics and constraints

❌ **Don't:**
- Use vague descriptions like "nice UI" or "good performance"
- Leave sections blank if they're important to your project
- Mix in technical design (database schema, API endpoints) — that's later
- Assume the AI knows your domain jargon — define it

---
