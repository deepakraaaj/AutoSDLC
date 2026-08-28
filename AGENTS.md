# Repository Instructions for Coding Agents

## Engineering Knowledge Logging

This repository maintains a lightweight engineering knowledge base at:

```text
docs/knowledge/INDEX.md
```

Before creating new troubleshooting, architecture decision, or runbook documentation, check the existing knowledge base:

```text
docs/knowledge/INDEX.md
docs/knowledge/troubleshooting/
docs/knowledge/decisions/
docs/knowledge/runbooks/
```

Create or update knowledge entries only for meaningful engineering work such as:

- bugs or unexpected behavior that required investigation
- API, database, deployment, CI/CD, Docker, Kubernetes, or integration failures
- performance, security, configuration, dependency, or data consistency issues
- frontend behavior that was difficult to trace
- architecture decisions that are significant or hard to reverse
- reusable operational procedures

Do not create knowledge entries for trivial edits, obvious typo fixes, simple formatting changes, minor CSS adjustments, or changes that required no real investigation.

## Troubleshooting Entries

Use sequential IDs and filenames:

```text
docs/knowledge/troubleshooting/TS-001-short-description.md
```

Before assigning a new ID, check `docs/knowledge/INDEX.md` and existing troubleshooting files. Never reuse an ID.

Each troubleshooting entry should include:

- front matter with `id`, `title`, `date`, `status`, `area`, and `tags`
- `TL;DR`
- `Issue`
- `Investigation`
- `Approaches Considered`
- `Chosen Approach`
- `Root Cause`
- `Fix & Verification`
- `Takeaway`

Use statuses: `investigating`, `resolved`, `workaround`, or `blocked`. Prefer `resolved` only after verification.

## Architecture Decisions

Create ADRs only for decisions that are architecturally significant or difficult to reverse.

Use:

```text
docs/knowledge/decisions/ADR-001-short-decision-name.md
```

Recommended sections: `Context`, `Options Considered`, `Decision`, `Why`, `Trade-offs`, and `Consequences`.

## Runbooks

Create or update a runbook when an investigation produces a reusable procedure.

Use:

```text
docs/knowledge/runbooks/example-procedure.md
```

Runbooks should describe how to handle a class of issue next time, not duplicate the full troubleshooting entry.

## Index Maintenance

Whenever a troubleshooting document, ADR, or runbook is created or materially updated, update:

```text
docs/knowledge/INDEX.md
```

Keep the index for discovery and navigation only. Do not place full troubleshooting content in the index.

## Evidence Standard

Do not document assumptions as facts. Clearly distinguish observed, suspected, and confirmed findings.

Include useful commands, logs, file paths, stack traces, API responses, or configuration snippets when they help another developer understand or reproduce the investigation. Redact secrets, credentials, tokens, keys, and sensitive data.

The knowledge base should answer:

- what happened
- how it was investigated
- what options existed
- what was chosen and why
- what the root cause was
- how it was fixed and verified
- what should be remembered next time
