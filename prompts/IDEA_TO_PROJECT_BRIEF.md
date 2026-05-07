# AutoSDLC New Project Brief Prompt

## Instructions

Use this prompt when you have a rough product idea but do not yet have a written PRD or project brief.
Paste the prompt into ChatGPT, Claude, Gemini, or another AI tool, then append your raw idea underneath.

The goal is to convert an unstructured idea into a standardized Markdown brief that AutoSDLC can consume consistently across projects.

---

## Prompt to paste into AI:

You are a senior product manager and business analyst.
I will give you a rough idea for a software product, feature, or internal tool.
Convert it into a structured Markdown project brief for delivery planning.

Rules:
- Do not invent facts that are not supported by the idea.
- If details are missing or ambiguous, capture them under `Open Questions`.
- Prefer concrete wording over generic wording.
- Write requirements in a way that helps downstream story and task generation.
- Output only the Markdown brief. Do not add commentary before or after.

Output exactly this structure:

---

# Project: [Project Name]

## Summary
[2-4 sentences describing what the product is, who it is for, and what value it provides.]

## Problem Statement
[Describe the current pain point, inefficiency, or unmet need.]

## Goals
- [Primary goal]
- [Secondary goal]
- [Business or operational goal]

## Success Metrics
- [Metric 1]
- [Metric 2]

## Target Users
- **[User Type 1]**: [Who they are, what they need, what success looks like for them]
- **[User Type 2]**: [Who they are, what they need, what success looks like for them]

## MVP Scope
### In Scope
- [Must-have capability]
- [Must-have capability]

### Out of Scope
- [Explicitly excluded from v1]
- [Deferred capability]

## Core User Journeys
### [Journey Name]
1. [Step 1]
2. [Step 2]
3. [Step 3]

## Functional Requirements
### [Feature Area 1]
- [Specific requirement]
- [Specific requirement]

### [Feature Area 2]
- [Specific requirement]
- [Specific requirement]

## Business Rules
- [Rule]
- [Rule]

## Non-Functional Requirements
- Performance: [Targets]
- Security: [Requirements]
- Platform: [Supported devices/platforms]
- Reliability: [Availability, recovery, or resilience expectations]
- Compliance: [If applicable]

## Data and Integrations
### Data Entities
- **[Entity Name]**: [Description]

### External Integrations
- **[Service or API]**: [Purpose]

## Tech Preferences
- Frontend: [If known]
- Backend: [If known]
- Database: [If known]
- Infrastructure: [If known]
- Third-party services: [If known]

## Risks and Assumptions
- [Risk or assumption]

## Open Questions
- [Unknown detail that needs a decision]

---

Idea:
[PASTE YOUR IDEA BELOW THIS LINE]
