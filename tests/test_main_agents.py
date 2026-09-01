"""Tests for app/services/main_agents.py — the LangChain-routed replacements
for main.py's 4 direct provider.generate() call sites (clarify-check,
content-change field-diff, manual epic generation, assistant router). These
test the schema validation and degrade-on-malformed-output behavior
directly; tests/test_clarify_chat.py, tests/test_improve_quality.py, and
tests/test_redmine_assistant.py already cover each function's behavior
end-to-end through its real main.py endpoint."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.main_agents import (  # noqa: E402
    run_assistant_router,
    run_clarify_check,
    run_content_change,
    run_generate_new_epics,
)


class StubProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self.response


# ---------------------------------------------------------------------------
# run_clarify_check
# ---------------------------------------------------------------------------

def test_run_clarify_check_parses_questions():
    provider = StubProvider(json.dumps({
        "needs_clarification": True,
        "questions": [{"question": "Who is this for?", "why_it_matters": "Shapes scope."}],
    }))
    result = run_clarify_check("sys", "brief", provider)
    assert result.needs_clarification is True
    assert result.questions[0].question == "Who is this for?"


def test_run_clarify_check_degrades_on_malformed_json():
    provider = StubProvider("not json at all")
    result = run_clarify_check("sys", "brief", provider)
    assert result.needs_clarification is False
    assert result.questions == []


def test_run_clarify_check_degrades_on_wrong_shape():
    """A bare array (wrong top-level shape for this schema) must still
    degrade gracefully, not raise."""
    provider = StubProvider(json.dumps(["not", "an", "object"]))
    result = run_clarify_check("sys", "brief", provider)
    assert result.needs_clarification is False
    assert result.questions == []


# ---------------------------------------------------------------------------
# run_content_change
# ---------------------------------------------------------------------------

def test_run_content_change_returns_arbitrary_allowed_fields():
    """The schema must not restrict which keys pass through — main.py's
    EDITABLE_FIELDS allow-list is what actually filters these, not this
    function."""
    provider = StubProvider(json.dumps({
        "title": "New title", "acceptance_criteria": ["a", "b"], "some_unexpected_field": 123,
    }))
    fields = run_content_change("sys", "msg", provider)
    assert fields == {"title": "New title", "acceptance_criteria": ["a", "b"], "some_unexpected_field": 123}


def test_run_content_change_returns_empty_dict_on_malformed_json():
    provider = StubProvider("garbage {{{")
    assert run_content_change("sys", "msg", provider) == {}


def test_run_content_change_returns_empty_dict_on_non_object_response():
    provider = StubProvider(json.dumps(["not", "an", "object"]))
    assert run_content_change("sys", "msg", provider) == {}


def test_run_content_change_returns_empty_dict_for_empty_object():
    """CHANGE_REQUEST_SYSTEM's documented behavior for 'no applicable
    change': an empty object, not an error."""
    provider = StubProvider(json.dumps({}))
    assert run_content_change("sys", "msg", provider) == {}


# ---------------------------------------------------------------------------
# run_generate_new_epics
# ---------------------------------------------------------------------------

def test_run_generate_new_epics_parses_array():
    provider = StubProvider(json.dumps([
        {"title": "Billing", "description": "Invoicing.", "feature_area": "Billing", "priority": "high"},
    ]))
    epics = run_generate_new_epics("sys", "prompt", provider)
    assert len(epics) == 1
    assert epics[0].title == "Billing"
    assert epics[0].priority == "high"


def test_run_generate_new_epics_returns_empty_list_on_malformed_json():
    provider = StubProvider("not json")
    assert run_generate_new_epics("sys", "prompt", provider) == []


def test_run_generate_new_epics_returns_empty_list_on_non_array_response():
    """A model that returns a bare object instead of an array (unlike
    _parse_json_array, which wraps a bare object as a single-item list —
    NEW_EPICS_SYSTEM's contract is unambiguously an array, so this
    doesn't need that leniency) must degrade to []."""
    provider = StubProvider(json.dumps({"title": "Billing"}))
    assert run_generate_new_epics("sys", "prompt", provider) == []


def test_run_generate_new_epics_fills_schema_defaults_for_missing_fields():
    provider = StubProvider(json.dumps([{"title": "Only a title"}]))
    epics = run_generate_new_epics("sys", "prompt", provider)
    assert epics[0].title == "Only a title"
    assert epics[0].description == ""
    assert epics[0].feature_area == ""
    assert epics[0].priority == "medium"


# ---------------------------------------------------------------------------
# run_assistant_router
# ---------------------------------------------------------------------------

def test_run_assistant_router_parses_full_envelope():
    provider = StubProvider(json.dumps({
        "intent": "list_issues",
        "params": {"project": "website-redesign", "status": "open"},
        "reply": "Here's what's open.",
    }))
    result = run_assistant_router("sys", "msg", provider)
    assert result.intent == "list_issues"
    assert result.params == {"project": "website-redesign", "status": "open"}
    assert result.reply == "Here's what's open."


def test_run_assistant_router_degrades_to_chitchat_on_malformed_json():
    provider = StubProvider("not json at all")
    result = run_assistant_router("sys", "msg", provider)
    assert result.intent == "chitchat"
    assert result.params == {}
    assert result.reply == ""


def test_run_assistant_router_accepts_unrecognized_intent_without_raising():
    """intent is validated as a free string, not a Literal enum —
    _dispatch_assistant_intent (main.py) is what falls back to chitchat for
    an intent it doesn't recognize, not this schema."""
    provider = StubProvider(json.dumps({"intent": "some_future_intent", "params": {}, "reply": "ok"}))
    result = run_assistant_router("sys", "msg", provider)
    assert result.intent == "some_future_intent"
