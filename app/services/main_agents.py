"""LangChain-routed replacements for the 4 LLM call sites that used to call
provider.generate() directly from main.py: clarify-check, content-change
field-diff, manual epic generation, and the assistant intent router. Every
other LLM call in this codebase already goes through AutoSDLCChatModel
(app/services/langchain_provider.py) — PhaseGenerator's _llm_call
(app/services/generators.py), the LangGraph pipelines
(app/services/langgraph_pipeline.py, app/services/code_review_graph.py),
wiki generation, knowledge-base extraction. These 4 were the last holdouts,
calling `provider.generate(system_prompt, user_message)` inline in main.py
with hand-rolled json.loads + manual key-checking.

Schema fidelity is deliberately mixed, not uniform, matching how fixed each
prompt's actual output shape is:
- ClarifyCheckResult and NewEpic are full Pydantic schemas — both prompts
  return a genuinely fixed shape, so real validation is worth having.
- ContentChangeResult and AssistantRouterResult validate only their fixed
  envelope. CHANGE_REQUEST_SYSTEM's output is arbitrary allowed-field keys
  that depend on `kind` (epic/story/task) at call time — main.py's existing
  EDITABLE_FIELDS/CONSTRAINED_FIELD_VALUES filtering already validates that
  part, so a rigid schema here would either duplicate that logic or reject
  valid output. ASSISTANT_ROUTER_SYSTEM's `params` shape depends on which
  `intent` the model picked — _dispatch_assistant_intent already narrows
  and validates params per intent downstream. Forcing dict[str, Any] into a
  fixed schema in both cases would be exactly the "more manual definitions"
  this migration is supposed to avoid, not genuine validation.

Every function below keeps the exact fallback contract its main.py call
site relied on: malformed/unparsable output degrades to an empty result
(never raises) so a bad LLM response costs missing questions/fields/intent,
not a 500.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field, ValidationError

from app.services.langchain_provider import AutoSDLCChatModel
from app.utils.text_parsing import clean_raw


# ---------------------------------------------------------------------------
# Clarify-check (main.py's clarify_chat_endpoint)
# ---------------------------------------------------------------------------

class ClarifyQuestion(BaseModel):
    question: str = ""
    why_it_matters: str = ""


class ClarifyCheckResult(BaseModel):
    needs_clarification: bool = False
    questions: list[ClarifyQuestion] = Field(default_factory=list)


_clarify_parser = PydanticOutputParser(pydantic_object=ClarifyCheckResult)


def run_clarify_check(system_prompt: str, user_message: str, provider) -> ClarifyCheckResult:
    """Runs the clarify-check call through AutoSDLCChatModel and validates
    the response against ClarifyCheckResult. Degrades to
    ClarifyCheckResult() (needs_clarification=False, no questions) on any
    parse/validation failure — same as clarify_chat_endpoint's previous
    `except json.JSONDecodeError: data = {}` fallback, which downstream
    code already treated as "not clarification-worthy"."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
    cleaned = clean_raw(str(response.content))
    try:
        return _clarify_parser.parse(cleaned)
    except (ValidationError, Exception):
        return ClarifyCheckResult()


# ---------------------------------------------------------------------------
# Content-change field-diff (main.py's _generate_content_change)
# ---------------------------------------------------------------------------

class ContentChangeResult(BaseModel):
    """CHANGE_REQUEST_SYSTEM returns an object of arbitrary allowed-field
    keys (only the fields that should change), which depends on `kind`
    (epic/story/task) at call time — not a fixed set this schema can
    enumerate. `fields` validates only that the top-level shape is an
    object; main.py's existing EDITABLE_FIELDS/CONSTRAINED_FIELD_VALUES
    filtering (unchanged) is still what decides which of those keys are
    actually applied."""
    fields: dict[str, Any] = Field(default_factory=dict)


def run_content_change(system_prompt: str, user_message: str, provider) -> dict[str, Any]:
    """Runs the content-change call through AutoSDLCChatModel. Returns {}
    on any parse failure or non-object response — same fallback
    _generate_content_change's `except json.JSONDecodeError: return {}`
    and `if not isinstance(parsed, dict): return {}` had."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
    cleaned = clean_raw(str(response.content))
    try:
        result = ContentChangeResult(fields=_load_json_object(cleaned))
    except (ValidationError, ValueError):
        return {}
    return result.fields


# ---------------------------------------------------------------------------
# Manual epic generation (main.py's _generate_new_epics)
# ---------------------------------------------------------------------------

class NewEpic(BaseModel):
    title: str = ""
    description: str = ""
    feature_area: str = ""
    priority: str = "medium"


class NewEpicsResult(BaseModel):
    epics: list[NewEpic] = Field(default_factory=list)


def run_generate_new_epics(system_prompt: str, user_message: str, provider) -> list[NewEpic]:
    """Runs the manual-epic-generation call through AutoSDLCChatModel.
    NEW_EPICS_SYSTEM/build_new_epics_message ask for a bare JSON array (not
    an object), so this wraps the parsed array into NewEpicsResult.epics
    for validation rather than using PydanticOutputParser directly (which
    expects the top-level shape to match the model, i.e. an object).
    Returns [] on any parse/validation failure, matching
    _generate_new_epics's previous `except json.JSONDecodeError: return []`
    and `if not isinstance(parsed, list): return []`."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
    cleaned = clean_raw(str(response.content))
    try:
        data = _load_json(cleaned)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    try:
        return NewEpicsResult(epics=data).epics
    except ValidationError:
        return []


# ---------------------------------------------------------------------------
# Assistant intent router (main.py's assistant_chat_endpoint)
# ---------------------------------------------------------------------------

class AssistantRouterResult(BaseModel):
    """ASSISTANT_ROUTER_SYSTEM's {"intent", "params", "reply"} envelope.
    `intent` is validated as a free string rather than a Literal enum of
    the 9 known intents — _dispatch_assistant_intent (main.py) already
    falls back to "chitchat" for any intent it doesn't recognize, so a
    Literal here would just move that same fallback into a stricter,
    harder-to-extend place. `params`' shape depends on which intent was
    picked, validated downstream per-intent the same way it always was."""
    intent: str = "chitchat"
    params: dict[str, Any] = Field(default_factory=dict)
    reply: str = ""


_router_parser = PydanticOutputParser(pydantic_object=AssistantRouterResult)


def run_assistant_router(system_prompt: str, user_message: str, provider) -> AssistantRouterResult:
    """Runs the assistant router call through AutoSDLCChatModel. Degrades
    to AssistantRouterResult() (intent="chitchat", empty params/reply) on
    any parse/validation failure — same as assistant_chat_endpoint's
    previous `except json.JSONDecodeError: routed = {}` fallback, which
    downstream code already defaulted to chitchat for."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
    cleaned = clean_raw(str(response.content))
    try:
        return _router_parser.parse(cleaned)
    except (ValidationError, Exception):
        return AssistantRouterResult()


# ---------------------------------------------------------------------------
# Shared JSON loading helpers
# ---------------------------------------------------------------------------

def _load_json(raw: str) -> Any:
    import json
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e


def _load_json_object(raw: str) -> dict[str, Any]:
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data
