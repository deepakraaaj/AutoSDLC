# AutoSDLC Document Extraction Prompt

## Instructions

Use this when you already have source material such as a PRD, spec, emails, meeting notes, or a README.
If this is a brand-new project with only a rough idea, start with `docs/PROJECT_BRIEF_TEMPLATE.md` or `prompts/IDEA_TO_PROJECT_BRIEF.md` instead.

Paste this prompt followed by your documents into any AI tool (Claude, ChatGPT, Gemini, etc.).
The AI will extract your project information into a standardized format that AutoSDLC can process.

---

## Prompt to paste into AI:

You are a senior business analyst. I will give you one or more documents describing a software project.
Extract ALL relevant information and output it in the following structured Markdown format.
Be exhaustive — include everything that would help a developer understand what needs to be built.
Do not summarize or omit details. If something is unclear, flag it in the "Open Questions" section.

Output exactly this format (do not add commentary before or after):

---

# Project: [Project Name]

## Summary
[2-3 sentences: what this project is and who it's for]

## Goals
- [Primary goal]
- [Secondary goal]
- [...]

## User Types
- **[User Type 1]**: [What they do, what they need]
- **[User Type 2]**: [What they do, what they need]
- [...]

## Features
### [Feature Area 1]
- [Specific feature or capability]
- [Specific feature or capability]

### [Feature Area 2]
- [Specific feature or capability]
- [...]

## Constraints & Non-Functional Requirements
- [Performance targets, e.g. "page must load under 2 seconds"]
- [Security requirements]
- [Platform constraints, e.g. "must work on mobile"]
- [Integration requirements]
- [Compliance or regulatory requirements]

## Tech Stack (if known)
- Frontend: [...]
- Backend: [...]
- Database: [...]
- Infrastructure: [...]
- Third-party services: [...]

## Open Questions
- [Anything unclear or missing from the documents]

---

[PASTE YOUR DOCUMENTS BELOW THIS LINE]
