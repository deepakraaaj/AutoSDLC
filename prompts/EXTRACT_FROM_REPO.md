# AutoSDLC Repo Code Extraction Prompt

## Instructions

Run the command below in your repository to collect project info, then paste this prompt + the output into any AI tool.
The AI will analyze your codebase and generate a project description AutoSDLC can process.

## Step 1: Collect repo info (run this in your terminal)

```bash
(echo "=== Directory Structure ===" && find . -type f -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/.next/*' -not -path '*/build/*' -not -path '*/dist/*' | head -100) && (echo "=== Package files ===" && (cat package.json 2>/dev/null || cat requirements.txt 2>/dev/null || cat Gemfile 2>/dev/null || cat go.mod 2>/dev/null || cat pom.xml 2>/dev/null)) && (echo "=== README ===" && cat README.md 2>/dev/null)
```

Copy all the output.

## Step 2: Paste this prompt + the output into any AI tool

You are a senior software architect. I will give you the structure and documentation of a software project.
Analyze the codebase and produce a project description in the following format for AutoSDLC.
Focus on: what already exists, what is being built next, and what gaps exist.

Do not add commentary before or after. Output exactly this format:

---

# Project: [Project Name — infer from package name, directory name, or README]

## Summary
[What this project is, who it's for, current maturity stage (MVP/alpha/beta/production)]

## Current State (what's already built)
- [Feature or module that currently exists]
- [Another existing feature]
- [...]

## Goals (what's being built next / planned features)
- [Planned feature or capability]
- [Another planned feature]
- [...]

## User Types
- **[User Type 1]**: [What they do in this system, their pain point]
- **[User Type 2]**: [What they do, their pain point]

## Features Needed
### [Feature Area 1]
- [Specific feature with enough detail a developer could start building]
- [Another related feature]

### [Feature Area 2]
- [...]

## Tech Stack
- Frontend: [language/framework inferred from files]
- Backend: [language/framework inferred]
- Database: [inferred from files or dependencies]
- Infrastructure: [inferred]

## Pain Points / Technical Debt
- [Issues visible in the code structure or dependencies]
- [Complexity or maintainability concerns]

## Open Questions
- [Anything that's unclear from the repo structure]

---

[PASTE THE OUTPUT FROM STEP 1 HERE]
