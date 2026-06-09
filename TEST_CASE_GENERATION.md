# Test Case Generation Feature

## Overview
Integrated a 4th phase into the story/task generation pipeline that automatically generates unit test cases for each developer task.

## Architecture Changes

### 1. Data Models (app/schemas/models.py)
- **New TestCase model**: Captures unit test details
  - `id`: Unique identifier (format: T1-T1, T2-T1, etc.)
  - `title`: Short test name
  - `test_type`: Literal["unit", "integration", "e2e"]
  - `description`: What the test verifies and why
  - `test_code`: Pseudocode or language-agnostic test snippet
  - `expected_result`: What should happen if code is correct
  - `assertion`: Specific assertion statement

- **Updated Task model**: Now includes
  - `test_cases: list[TestCase] = []`

- **New TestMetrics**: Measures test quality
  - `coverage_score`: 0-100
  - `assertion_quality_score`: 0-100
  - `edge_case_coverage_score`: 0-100
  - `overall`: 0-100

### 2. Generation Prompts (app/services/prompt.py)
- **TEST_GENERATION_SYSTEM**: AI system prompt for test generation
  - Instructs AI to generate 2-3 tests per task
  - Covers: happy path, edge cases, error conditions, boundary values
  - Ensures tests are concrete and actionable
  
- **build_test_generation_message()**: Formats task context for test generation
  - Includes project brief excerpt
  - Lists all tasks with definitions of done
  - Critical: Ensures task IDs are used exactly as provided

### 3. Generation Pipeline (main.py)
- **Phase 4: Test Case Generation** (new)
  - Triggered after all tasks are generated
  - Runs after phases 1-3 (epics, stories, tasks)
  - Batches all tasks and sends to AI provider
  - Parses returned JSON and assigns tests to tasks
  - Includes retry logic (up to 2 attempts)
  - Graceful failure: continues if test generation fails

#### Generation Phases:
1. **Phase 1**: Epic generation (10+ epics)
2. **Phase 2**: Story generation (5+ stories per epic)
3. **Phase 3**: Task generation (4+ tasks per story)
4. **Phase 4**: Test case generation (2-3 tests per task)

## Usage

When users generate stories/tasks, they now automatically get:
- Developer tasks with full context
- **Unit test cases** for each task (new)
- Test code snippets they can immediately use
- Edge case coverage recommendations

No UI changes needed — tests are included in the response structure automatically.

## Example Output

A task will now include:
```json
{
  "id": "T1",
  "title": "Implement user authentication endpoint",
  "description": "Create POST /auth/login endpoint",
  "definition_of_done": "Endpoint returns 200 with JWT token for valid credentials",
  "test_cases": [
    {
      "id": "T1-T1",
      "title": "Valid credentials return 200 with JWT token",
      "test_type": "unit",
      "description": "Verify successful login returns token",
      "test_code": "response = post('/auth/login', {'email': 'user@test.com', 'password': 'pass123'}) assert response.status_code == 200 assert 'token' in response.json()",
      "expected_result": "HTTP 200 with JWT token in response",
      "assertion": "response.status_code == 200 and response.json()['token'] is not None"
    },
    {
      "id": "T1-T2",
      "title": "Invalid credentials return 401",
      "test_type": "unit",
      "description": "Verify failed login with wrong password",
      "test_code": "response = post('/auth/login', {'email': 'user@test.com', 'password': 'wrongpass'}) assert response.status_code == 401",
      "expected_result": "HTTP 401 Unauthorized",
      "assertion": "response.status_code == 401"
    },
    {
      "id": "T1-T3",
      "title": "Missing email field returns 400",
      "test_type": "unit",
      "description": "Verify validation for required fields",
      "test_code": "response = post('/auth/login', {'password': 'pass123'}) assert response.status_code == 400",
      "expected_result": "HTTP 400 Bad Request with validation error",
      "assertion": "response.status_code == 400"
    }
  ]
}
```

## Implementation Details

### Test Generation Prompt Characteristics
- **Concrete**: Each test has actual code snippets
- **Comprehensive**: Covers happy path, edge cases, error states
- **Actionable**: Tests are immediately usable by developers
- **Testable**: Assertions are specific and measurable

### Error Handling
- If test generation fails, generation continues (graceful degradation)
- Failed tests are logged but don't block the overall process
- Users receive status updates about test generation progress

### Performance
- Test generation batches all tasks in a single API call
- Retry logic handles transient failures
- Tests are stored in-memory with the task data structure

## Future Enhancements

1. **Language-specific test code generation**
   - Generate actual test code in Python, JavaScript, Go, etc.
   - Parse language preference from task or project context

2. **Test coverage metrics**
   - Calculate code coverage expectations
   - Suggest additional tests for uncovered scenarios

3. **Integration with CI/CD**
   - Export tests to test file format (.test.js, _test.py, etc.)
   - Generate test fixtures and mocks

4. **Test execution**
   - Run generated tests against actual code
   - Provide feedback on test pass rates

5. **Per-language best practices**
   - AAA pattern (Arrange-Act-Assert)
   - Given-When-Then (BDD style)
   - Property-based testing recommendations
