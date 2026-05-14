# Project Brief Template (Optimized for AutoSDLC)

**Use this template** when you need a standardized brief for generating backlogs of epics, stories, and tasks.

**How to use:**
1. Fill in each section — be specific, not vague
2. If you don't know something, leave it blank or put "TBD" (don't guess)
3. Save as `.md` and upload to the app, or paste directly in the Brief tab
4. Aim for 200+ words total, include features and user roles for best results

---

# Project: [Project Name]

## Executive Summary
[2-4 sentences: What is the product? Who uses it? What problem does it solve?]

**Example:**
*"An AI-powered expense reporting tool for team leads that automates receipt scanning, categorization, and compliance checks. Reduces approval time from 2 days to 15 minutes. Built for mid-market companies with 50+ employees."*

---

## Problem Statement
[What is broken or inefficient today? What pain point are you solving?]

**Example:**
*"Expense approval is manual: receipts are emailed, managers spend 30 mins/week categorizing, and compliance errors delay reimbursement by 3+ days. This frustrates employees and creates admin overhead."*

---

## Goals
*[List 3-5 outcomes you want. Be specific.]*

- [Primary goal — what must succeed]
- [User experience goal — how should users feel]
- [Business goal — revenue, cost, or operational metric]

**Example:**
- Reduce manual categorization effort by 80%
- Enable employees to self-serve receipts without manager review for <$100
- Achieve 95% compliance accuracy on first submission

---

## Success Metrics
*[How will you know if this succeeded?]*

- [Metric 1]: [Target value] (e.g., "Approval time: 15 minutes or less")
- [Metric 2]: [Target value] (e.g., "Compliance pass rate: 95%+")
- [Metric 3]: [Target value] (e.g., "User adoption: 80% of team leads within 3 months")

---

## Target Users
*[Who will use this? Be specific about roles, not just "users"]*

### [User Role 1]: [Title]
- **Who:** [One sentence: job title, company size, or department]
- **Need:** [What problem do they have?]
- **Success:** [How do they win? What's easier/faster?]

### [User Role 2]: [Title]
- **Who:** [One sentence]
- **Need:** [What problem do they have?]
- **Success:** [How do they win?]

**Example:**

### Manager
- **Who:** Team lead or department head responsible for approving expenses
- **Need:** Quick approval process with automated compliance checks; low risk of fraud
- **Success:** Can review 20 reports in 10 minutes instead of 90 minutes; confident all expenses are compliant

### Employee
- **Who:** Individual contributor who submits expense reports
- **Need:** Fast reimbursement; don't want to manually fill out expense forms
- **Success:** Submit receipt, get auto-categorized result in real time; reimbursed within 3 days

---

## MVP Scope

### Must-Have Features (In Scope)
*[The absolute minimum to solve the problem]*

- [Feature 1: Specific, not vague. Example: "Upload receipt image, auto-extract amount and date"]
- [Feature 2: Example: "Categorize expense as travel, meals, or equipment"]
- [Feature 3: Example: "Manager dashboard shows pending reports with auto-flagged items"]

### Nice-to-Have (Out of Scope / v2)
*[Important but not blocking v1]*

- [Feature that can wait]
- [Enhancement for later]

### Explicitly Out of Scope
*[What you will NOT do in v1]*

- [Feature that users might expect but won't build]

---

## Core User Journeys
*[Step-by-step flows for the most common use cases]*

### Journey 1: [Name]
**Actor:** [Who is doing this?]

1. [Action 1 — what they do]
2. [Action 2]
3. [System response or outcome]

**Example: Employee Submits Expense**
1. Employee opens app and taps "New Expense"
2. Employee takes photo of receipt or uploads image
3. System extracts amount, date, merchant
4. Employee reviews and confirms category (Travel, Meals, Equipment)
5. Employee adds notes (if needed) and submits
6. System sends to manager for approval

### Journey 2: [Name]
**Actor:** [Who is doing this?]

1. [Action]
2. [Action]
3. [Outcome]

---

## Functional Requirements
*[What the system must do. Be specific.]*

### [Feature Area 1]
- [Specific requirement — not vague]
- [Specific requirement]

### [Feature Area 2]
- [Specific requirement]
- [Specific requirement]

**Example:**

### Receipt Processing
- Accept JPG, PNG, PDF file formats up to 10MB
- Extract: date, merchant name, amount, receipt number (if present)
- Confidence score for extracted data: show ≥90% as green, 70-89% as yellow, <70% as red
- Allow manual override on any field after extraction

### Categorization
- Provide 6 categories: Travel, Meals, Equipment, Software, Training, Other
- Auto-suggest category based on merchant name and amount
- Remember user's past categorizations (e.g., "Uber" → Travel)

### Manager Dashboard
- Show all reports submitted in the last 7 days
- Flag reports with low extraction confidence or unusual amounts
- Allow bulk-approve up to 5 reports at once

---

## Business Rules & Constraints
*[Rules, limits, workflows that govern the system]*

- [Rule 1: Example: "Expenses >$500 require VP approval before processing"]
- [Rule 2: Example: "Only expenses within 30 days of receipt date are eligible"]
- [Rule 3: Example: "Duplicate submissions (same merchant, same day) are flagged"]

---

## Non-Functional Requirements

### Performance
- Receipt upload and extraction: <3 seconds
- Dashboard load: <1 second
- Support 1000+ concurrent users

### Security & Compliance
- All data encrypted in transit and at rest
- Support SSO (Okta, Google Workspace)
- Audit log: who approved what, when
- GDPR compliant: allow users to delete personal data

### Platform & Availability
- Web app: Chrome, Firefox, Safari (latest 2 versions)
- Mobile: iOS and Android apps (native or React Native)
- 99.5% uptime SLA
- Offline mode: queue submissions to sync when online

### Data & Integrations
- Integrate with Slack: post approval notifications
- Integrate with QuickBooks: sync approved expenses as journal entries
- Connect to company's identity system (LDAP, Okta)

---

## Data Entities
*[The main "things" the system tracks]*

### Receipt
- **ID**: Unique identifier
- **Fields**: Date, merchant, amount, category, confidence score, image URL, user who submitted
- **States**: Uploaded, Extracted, Review-Pending, Approved, Rejected, Reimbursed
- **Owner**: Employee who submitted

### Expense Report
- **ID**: Unique identifier
- **Fields**: Created date, submitted date, approval date, approver name, total amount
- **Contains**: 1 or more receipts
- **States**: Draft, Submitted, Approved, Rejected, Paid

### User Profile
- **Fields**: Name, email, role (employee/manager/admin), department, cost center
- **Preferences**: Default category, notification settings

---

## External Integrations
*[Systems this needs to talk to]*

- **[Service Name]**: [Why needed] — [Data exchanged]

**Example:**

- **Slack**: Send approval notifications to team channels; notify employee when report is approved
- **QuickBooks**: Sync approved expenses to GL accounts based on category
- **Okta**: SSO login; pull user roles and departments
- **AWS S3**: Store receipt images (encrypted, with retention policy)

---

## Technology & Preferences
*[Any constraints or strong preferences]*

### Frontend
- [Example: "React + TypeScript", or "No specific preference"]

### Backend
- [Example: "FastAPI (Python)", or "TBD"]

### Database
- [Example: "PostgreSQL", or "Open to suggestions"]

### Infrastructure
- [Example: "AWS (EC2 + RDS)", or "Cloud-agnostic"]

### Key Libraries/Tools
- [Example: "Tesseract for OCR"]

---

## Phased Rollout (Optional)
*[If you're releasing this in phases, describe each]*

### Phase 1 (MVP, Month 1-2)
- Receipt upload and auto-extraction
- Basic categorization
- Manager approval dashboard
- Slack notifications

### Phase 2 (Month 3)
- Mobile app
- QuickBooks integration
- Bulk approval

### Phase 3 (Month 4+)
- Advanced fraud detection (unusual amounts, patterns)
- Mobile OCR (camera capture in app)
- Reports and analytics dashboard

---

## Risks & Assumptions

### Risks
- [Risk]: [Mitigation]
- **Example**: *"OCR accuracy <85%"* → Use human review for low-confidence receipts; retrain model quarterly

### Assumptions
- [Assumption]: [If this changes, we need to revisit]
- **Example**: *"Expense reports are always submitted with image receipts (not just amounts)"*

---

## Dependencies & Constraints
*[What else needs to happen for this to work?]*

- [External dependency or constraint]
- **Example**: "Okta SSO setup must be complete before launch"
- **Example**: "Legal approval needed for GDPR compliance checklist"

---

## Open Questions
*[Things you don't know yet — flag these for discussion]*

- [ ] What's the max file size for receipt uploads? (Assumed 10MB, needs clarification)
- [ ] Should rejected reports go back to employee for re-submission, or escalate to finance?
- [ ] Do we need offline mode from day 1, or is v2 acceptable?
- [ ] What's the approval SLA? (1 day, 4 hours, real-time?)

---

## Appendix: Glossary (Optional)
*[Define domain-specific terms]*

- **OCR**: Optical character recognition — extracting text from images
- **Confidence Score**: A percentage (0-100%) indicating how certain the AI is about extracted data
- **GL Account**: General ledger account in accounting system
- **Cost Center**: Department or team code for expense attribution

---

## Document Info
- **Created**: [Date]
- **Last Updated**: [Date]
- **Owner**: [Name/team]
- **Status**: Ready for development / In review / Approved

---

## How to Use This Brief in the App

**Option 1: Copy & Paste**
1. Copy the filled-in brief (this file)
2. Go to the app → **Brief** tab
3. Paste the content
4. Click **Generate backlog**

**Option 2: Upload File**
1. Save this file as `project-brief.md`
2. Go to the app → **Upload** tab
3. Upload the file
4. Click **Generate backlog**

**Option 3: Quick Idea (Chat Tab)**
1. Go to the app → **Chat** tab
2. Describe the project in 1-2 sentences
3. The app will ask clarifying questions
4. Refine in the **Brief** tab for more control

---

## Tips for Best Results

✅ **Do:**
- Be specific: "User can upload a JPG, PNG, or PDF receipt" not "user uploads file"
- Include actual user roles and goals
- Mention key integrations
- State business metrics
- List 3+ features in scope

❌ **Don't:**
- Leave sections blank if they're important
- Use vague descriptions like "nice UI" or "good performance"
- Mix in technical design (database schema, API endpoints) — that comes later
- Assume the AI knows your domain jargon

---
