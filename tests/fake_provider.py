"""A deterministic stand-in for a real AIProvider, used across the pipeline
tests. It doesn't hardcode responses by call order — it reads the actual
prompt text the pipeline sends (story/task IDs included) and returns
structurally valid, ID-consistent JSON, the same way a well-behaved LLM
would. This lets one instance drive a full epics -> stories -> tasks -> tests
run without the test needing to know call ordering in advance.
"""
import json
import re


class FakeProvider:
    def __init__(self, epics=None, stories=None, story_queue=None):
        self.calls = []  # [(system_prompt, user_message), ...] for assertions
        self._epics_response = epics
        self._stories_response = stories
        # story_queue: optional list of responses consumed in order, one per
        # call, for testing retry behavior (e.g. [empty, valid]).
        self._story_queue = list(story_queue) if story_queue is not None else None

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if "decomposing a project brief into epics" in system_prompt:
            return self._epics()
        if "writing user stories for one specific Epic" in system_prompt:
            return self._stories()
        if "breaking user stories into implementation tasks" in system_prompt:
            return self._tasks(user_message)
        if "writing manual test cases for a product backlog" in system_prompt:
            return self._tests(user_message)
        if "deciding whether a project brief has enough" in system_prompt:
            return self._clarify_check()
        raise AssertionError(f"FakeProvider got an unexpected system prompt: {system_prompt[:80]!r}")

    def _epics(self):
        if self._epics_response is not None:
            return self._epics_response
        return json.dumps([
            {"title": "User Accounts", "description": "Signup, login, profile management.", "feature_area": "Accounts", "priority": "high"},
            {"title": "Billing", "description": "Subscription and invoicing.", "feature_area": "Billing", "priority": "medium"},
        ])

    def _stories(self):
        if self._story_queue is not None:
            # Consume one response per call; repeat the last once exhausted.
            idx = min(len([c for c in self.calls if "writing user stories" in c[0]]) - 1, len(self._story_queue) - 1)
            return self._story_queue[idx]
        if self._stories_response is not None:
            return self._stories_response
        return json.dumps([
            {
                "title": "Sign up",
                "as_a": "new visitor",
                "i_want": "to create an account with just email and password",
                "so_that": "I can start using the product right away",
                "acceptance_criteria": [
                    "Given a valid email and password, when submitted, then the account should be created",
                    "Given a duplicate email, when submitted, then an error should be displayed",
                ],
                "size": "small",
                "priority": "high",
            },
            {
                "title": "Log in",
                "as_a": "returning customer",
                "i_want": "to log in using my existing credentials",
                "so_that": "I can access my saved data again",
                "acceptance_criteria": [
                    "Given valid credentials, when submitted, then the user should be logged in",
                    "Given invalid credentials, when submitted, then an error should be shown",
                ],
                "size": "small",
                "priority": "high",
            },
        ])

    def _tasks(self, user_message):
        story_ids = re.findall(r"\[(S\d+)\]", user_message)
        tasks = []
        for sid in story_ids:
            tasks.append({
                "story_id": sid,
                "title": f"Build backend endpoint for {sid}",
                "description": "Implement the API endpoint, validation, and persistence layer.",
                "definition_of_done": "Endpoint returns 200 with the expected schema and is covered by tests.",
                "estimate_hours": "4-6",
                "dependencies": [],
                "priority": "high",
            })
            tasks.append({
                "story_id": sid,
                "title": f"Build UI form for {sid}",
                "description": "Implement the form, client-side validation, and API wiring.",
                "definition_of_done": "Form submits successfully and shows validation errors, covered by tests.",
                "estimate_hours": "3-5",
                "dependencies": [],
                "priority": "medium",
            })
        return json.dumps(tasks)

    def _tests(self, user_message):
        task_ids = re.findall(r"\[(T\d+)\]", user_message)
        return json.dumps({
            "tasks": [
                {
                    "task_id": tid,
                    "test_cases": [
                        {
                            "title": "Happy path succeeds",
                            "test_type": "functional",
                            "description": "Verifies the success case behaves as expected.",
                            "preconditions": "None",
                            "steps": ["Perform the action with valid input."],
                            "expected_result": "The action completes and shows the expected outcome.",
                        },
                    ],
                }
                for tid in task_ids
            ]
        })

    def _clarify_check(self):
        return json.dumps({"needs_clarification": False, "questions": []})
