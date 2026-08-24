"""Thin LangChain BaseChatModel adapter around the existing AIProvider
abstraction (app/services/providers.py:13-20). This wraps AIProvider.generate()
rather than replacing LiteLLMProvider with a LangChain-native model class —
the retry/fallback/circuit-breaker/usage-tracking logic already in
LiteLLMProvider (app/services/providers.py:308-428) stays exactly as-is.
This class only translates between LangChain's chat-model call interface and
generate(system_prompt, user_message) -> str, so LangGraph nodes
(app/services/langgraph_pipeline.py) and any future LangChain-based agent
(Phase 3's code-review agent) can call an AutoSDLC provider like any other
LangChain chat model."""
from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

def _split_system_and_user(messages: List[BaseMessage]) -> tuple[str, str]:
    """AIProvider.generate() takes exactly one system prompt + one user
    message (app/services/providers.py:15) — collapse a LangChain message
    list down to that shape, the same way every PhaseGenerator call site
    already does (one SYSTEM_PROMPT + one built user message per call)."""
    system_parts = [str(m.content) for m in messages if isinstance(m, SystemMessage)]
    user_parts = [str(m.content) for m in messages if not isinstance(m, SystemMessage)]
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


class AutoSDLCChatModel(BaseChatModel):
    """Adapts an AIProvider instance (typically from get_provider()) to
    LangChain's chat model interface. Every call still routes through the
    wrapped provider's own fallback/rate-limit/usage-tracking machinery —
    this class adds no retry or provider-selection logic of its own.

    `provider` is typed Any rather than AIProvider: pydantic's is_instance_of
    validation would otherwise reject anything that merely duck-types
    generate(system_prompt, user_message) -> str without subclassing
    AIProvider — which is exactly how tests/fake_provider.py's FakeProvider
    (used across this codebase's test suite) and any future test double are
    built. Structural typing, not nominal, is the actual contract here."""

    provider: Any
    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "autosdlc-provider"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        system_prompt, user_message = _split_system_and_user(messages)
        text = self.provider.generate(system_prompt, user_message)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
