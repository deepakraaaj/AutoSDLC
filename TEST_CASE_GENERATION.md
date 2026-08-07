# Test Case Generation Feature

## Overview
A 4th phase in the generation pipeline that automatically generates **manual QA test cases**
for each developer task — plain-language steps a QA tester can execute by hand, not source code.
This is a backlog tool producing product-management artifacts (epics/stories/tasks); test cases
follow the same spirit — something a tester or PM can read and act on without touching code.

## Architecture

### 1. Data Model (app/schemas/models.py)
- **TestCase**: a manual test case, deliberately not code
  - `id`: Unique identifier (format: T1-T1, T2-T1, etc.)
  - `title`: Short test name
  - `test_type`: `"functional"` (default happy path) | `"edge_case"` (boundary values) |
    `"negative"` (invalid input / error handling) | `"regression"`
  - `description`: What this test verifies and why
  - `preconditions`: State required before the test starts, or `"None"`
  - `steps`: Ordered list of concrete actions a human tester performs
  - `expected_result`: The observable outcome a tester would see — plain language, not an
    assertion or status code

- **Task model**: includes `test_cases: list[TestCase] = []`

- **TestMetrics**: reserved for future test-quality scoring (`coverage_score`,
  `expected_result_quality_score`, `edge_case_coverage_score`, `overall`) — not currently
  computed by `compute_metrics()`.

### 2. Generation Prompts (app/services/prompt.py)
- **TEST_GENERATION_SYSTEM**: instructs the AI to write manual test cases a QA tester can
  execute by hand — no source code, no assertion syntax, no framework references.
- **build_test_generation_message()**: formats task context (brief excerpt + task IDs/DoD) for
  one batch of tasks.

### 3. Generation Pipeline (main.py)
- **Phase 4: Test Case Generation** — runs after Phases 1-3 (epics, stories, tasks)
  - Every epic's tasks are split into batches of `TASKS_PER_TEST_BATCH` (5) tasks per AI call —
    not one call per epic — because a full epic's worth of tasks in one call comfortably exceeds
    providers' ~8000-token completion cap, truncating the response mid-JSON and failing to parse.
  - All batches across all epics are flattened into one queue and run concurrently
    (`EPIC_CONCURRENCY` workers at a time), not epic-by-epic — see the concurrency comment at
    that phase in main.py for why.
  - 1 retry per batch on an empty/invalid response; failures are logged and skipped (graceful
    degradation — a bad batch doesn't block the rest of the generation).

#### Generation Phases
1. **Phase 1**: Epic generation (10-20 epics)
2. **Phase 2**: Story generation (5+ stories per epic)
3. **Phase 3**: Task generation (4+ tasks per story)
4. **Phase 4**: Test case generation (2-3 test cases per task)

## Example Output

```json
{
  "id": "T1",
  "title": "Implement user authentication endpoint",
  "description": "Create POST /auth/login endpoint",
  "definition_of_done": "Endpoint returns 200 with JWT token for valid credentials",
  "test_cases": [
    {
      "id": "T1-T1",
      "title": "Valid credentials log the user in",
      "test_type": "functional",
      "description": "Verifies a user with correct credentials can successfully log in.",
      "preconditions": "A user account exists with a known email and password.",
      "steps": [
        "Open the login page.",
        "Enter the registered email and correct password.",
        "Submit the form."
      ],
      "expected_result": "The user is logged in and redirected to their dashboard."
    },
    {
      "id": "T1-T2",
      "title": "Incorrect password is rejected",
      "test_type": "negative",
      "description": "Verifies login fails cleanly with the wrong password.",
      "preconditions": "A user account exists with a known email.",
      "steps": [
        "Open the login page.",
        "Enter the registered email and an incorrect password.",
        "Submit the form."
      ],
      "expected_result": "An 'Invalid email or password' error is shown and the user stays on the login page."
    },
    {
      "id": "T1-T3",
      "title": "Missing email field is rejected",
      "test_type": "edge_case",
      "description": "Verifies the form validates required fields before submitting.",
      "preconditions": "None",
      "steps": [
        "Open the login page.",
        "Leave the email field empty, enter any password.",
        "Submit the form."
      ],
      "expected_result": "A 'Email is required' validation message appears and the form does not submit."
    }
  ]
}
```

## Error Handling
- If test generation fails for a batch, generation continues — failed batches are logged and
  skipped rather than blocking the rest of the backlog.
- Status updates stream to the client every 5 completed batches (not per-batch — dozens of
  batches per generation would otherwise flood the UI).

## Future Enhancements
1. Compute `TestMetrics` (currently defined but unused) to score test coverage and quality.
2. Export test cases directly into a Redmine test-management plugin or a dedicated QA tracker.
3. Let a user request test cases in a different style (e.g. Gherkin/BDD Given-When-Then) per
   project.
