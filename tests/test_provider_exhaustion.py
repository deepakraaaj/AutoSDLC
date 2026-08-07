"""Regression tests for the "all providers exhausted" handling in
LiteLLMProvider — the failure mode where the active provider AND every
configured fallback are rate-limited (litellm's fallbacks= only raises once
every option it tried has failed; a fallback that succeeds is transparent).
Covers both the error classification/message and the short-lived circuit
breaker that stops every other concurrent call in the same generation from
independently burning through its own retry+fallback chain against APIs
already known to be down."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import litellm  # noqa: E402
from app.services.providers import LiteLLMProvider, AllProvidersExhaustedError  # noqa: E402


def _rate_limit_error() -> litellm.RateLimitError:
    return litellm.RateLimitError(message="boom", llm_provider="groq", model="llama-3.3-70b-versatile")


def _configure_all_providers(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("CEREBRAS_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")


def test_rate_limit_error_is_wrapped_as_all_providers_exhausted(monkeypatch):
    _configure_all_providers(monkeypatch)
    monkeypatch.setattr(litellm, "completion", lambda *a, **k: (_ for _ in ()).throw(_rate_limit_error()))

    provider = LiteLLMProvider("groq")
    with pytest.raises(AllProvidersExhaustedError) as exc_info:
        provider.generate("system", "user")

    # Message should name the providers that were actually tried, not just
    # repeat litellm's raw exception text.
    assert "Groq" in str(exc_info.value)
    assert "Cerebras" in str(exc_info.value)
    assert "Gemini" in str(exc_info.value)


def test_circuit_breaker_fails_fast_without_calling_litellm_again(monkeypatch):
    _configure_all_providers(monkeypatch)
    call_count = {"n": 0}

    def raise_rate_limit(*_args, **_kwargs):
        call_count["n"] += 1
        raise _rate_limit_error()

    monkeypatch.setattr(litellm, "completion", raise_rate_limit)

    provider = LiteLLMProvider("groq")
    with pytest.raises(AllProvidersExhaustedError):
        provider.generate("system", "user")
    assert call_count["n"] == 1

    # A second call while the breaker is tripped must not hit litellm at
    # all — that's the whole point (avoid every other concurrent worker
    # independently retrying against APIs already known to be down).
    with pytest.raises(AllProvidersExhaustedError):
        provider.generate("system", "user")
    assert call_count["n"] == 1


def test_non_rate_limit_errors_are_not_wrapped(monkeypatch):
    _configure_all_providers(monkeypatch)
    monkeypatch.setattr(litellm, "completion", lambda *a, **k: (_ for _ in ()).throw(ValueError("some other failure")))

    provider = LiteLLMProvider("groq")
    with pytest.raises(ValueError):
        provider.generate("system", "user")


def test_successful_call_does_not_trip_breaker(monkeypatch):
    _configure_all_providers(monkeypatch)

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15

    class _Message:
        content = "ok"

    class _Choice:
        message = _Message()

    class _Response:
        model = "groq/llama-3.3-70b-versatile"
        usage = _Usage()
        _hidden_params = {"response_cost": 0.0}
        choices = [_Choice()]

    monkeypatch.setattr(litellm, "completion", lambda *a, **k: _Response())

    provider = LiteLLMProvider("groq")
    result = provider.generate("system", "user")
    assert result == "ok"
    assert provider._exhausted_until is None
