# Documentation Rules

This repository keeps documentation in the `main` branch inside the `docs/` folder.

## Rules

1. `main` is the source of truth for documentation.
2. Long-lived documentation branches are not allowed.
3. Project documentation must live under `docs/`, except for the repo-level `README.md`.
4. Feature or behavior changes must update the relevant documentation in the same branch before merge.
5. Temporary drafts can be written on short-lived `docs/*` branches, but they must be merged back into `main` quickly or discarded.
6. If two documents describe the same topic, one must be marked as canonical and the other must link back to it.
7. Old or replaced documents should be moved to `docs/archive/` instead of staying mixed with active docs.

## Structure

- `README.md`: entry point, setup, and links
- `docs/`: active project documentation
- `docs/AUTOSDLC_PROJECT_BRIEF.md`: canonical project brief
- `docs/archive/`: retired or replaced documentation

## Working Agreement

- Do not keep a separate documentation-only source of truth outside `main`.
- Do not leave important product or engineering notes only in PRs, chats, or draft branches.
- When in doubt, update the canonical doc in `docs/` and link to it from `README.md`.
