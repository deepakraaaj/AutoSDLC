import json
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import litellm
import time


class AIProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_message: str) -> str:
        pass

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        """Yield text chunks as they arrive. Falls back to single chunk by default."""
        yield self.generate(system_prompt, user_message)


# ── Groq / Cerebras / Gemini — unified through LiteLLM ─────────────────────
#
# These three are the UI-selectable providers (see /providers in main.py).
# Rather than three near-identical hand-rolled httpx classes each
# reimplementing retry/backoff, they share one LiteLLMProvider backed by
# litellm.completion(): one call site gets automatic retry-with-backoff on
# 429/5xx *and* automatic fallback to the next configured provider if the
# active one's quota runs out mid-generation — exactly the failure mode that
# lost test-case coverage when Cerebras hit its daily token cap.
#
# LiteLLM's own Router has a nicer built-in usage tracker
# (get_remaining_model_group_usage), but it only updates reliably inside a
# persistent async event loop — verified experimentally against this app's
# sync/ThreadPoolExecutor generation pipeline, where each worker thread would
# open and close its own event loop per call and the usage-tracking hook
# (scheduled as a fire-and-forget background task) never got to run before
# the loop closed. So usage/rate tracking for the settings UI is done here
# instead, with UsageTracker below — same sliding-window approach as the
# rate limiter this replaces, just provider-agnostic.

UI_PROVIDERS: dict[str, dict] = {
    "groq": {
        "label": "Groq",
        "litellm_prefix": "groq",
        "api_key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
        # Conservative defaults for the free tier. Live headers observed on
        # this account showed ~1000 requests remaining in a <3min window and
        # tokens replenishing almost instantly — real headroom is larger than
        # this, but there's no single confirmed steady-state RPM/TPM to pin
        # to, so these stay deliberately cautious. Override via env if your
        # key's tier differs.
        "rpm": int(os.getenv("GROQ_RPM", "25")),
        "tpm": int(os.getenv("GROQ_TPM", "10000")),
        "tpd": None,
    },
    "cerebras": {
        "label": "Cerebras",
        "litellm_prefix": "cerebras",
        "api_key_env": "CEREBRAS_API_KEY",
        "model_env": "CEREBRAS_MODEL",
        "default_model": "llama3.1-8b",
        # Confirmed live via this account's actual response headers:
        # x-ratelimit-limit-requests-minute: 5, x-ratelimit-limit-tokens-day: 1000000.
        # The daily token cap — not the per-minute request cap — is what
        # actually ran this account dry during testing.
        "rpm": int(os.getenv("CEREBRAS_RPM", "5")),
        "tpm": None,
        "tpd": int(os.getenv("CEREBRAS_TPD", "1000000")),
    },
    "gemini": {
        "label": "Google Gemini",
        "litellm_prefix": "gemini",
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.0-flash",
        # Typical Gemini free-tier figures; unverifiable live right now since
        # this project's key currently returns a free-tier limit of 0 (billing
        # not enabled on the Google Cloud project) — see the "blocked" note
        # surfaced in status() when that happens.
        "rpm": int(os.getenv("GEMINI_RPM", "15")),
        "tpm": None,
        "tpd": int(os.getenv("GEMINI_TPD", "1000000")),
    },
}

# Fallback priority when the active provider fails or exhausts its quota —
# the other two configured UI providers are tried in this order.
FALLBACK_ORDER = ["groq", "cerebras", "gemini"]


def _is_configured(provider_id: str) -> bool:
    return bool(os.getenv(UI_PROVIDERS[provider_id]["api_key_env"], "").strip())


def _litellm_model_string(provider_id: str) -> str:
    meta = UI_PROVIDERS[provider_id]
    model = os.getenv(meta["model_env"], meta["default_model"])
    return f"{meta['litellm_prefix']}/{model}"


class UsageTracker:
    """Thread-safe sliding-window request/token tracker for one provider.

    Two roles: (1) proactively blocks calls that would exceed the configured
    per-minute budget — preventing the burst-429 thundering herd that hit
    Cerebras when EPIC_CONCURRENCY-many threads all fired at once — and
    (2) exposes current usage for the settings UI meter.

    Per-minute counters are in-memory only (a process restart mid-minute is a
    non-issue — the window is clean again within 60s regardless). The daily
    token counter is persisted to the settings table via database.py so a
    container restart doesn't silently forget that a key is already
    exhausted for the day, which is exactly what would have kept happening
    after today's incident otherwise.
    """

    def __init__(self, provider_id: str, rpm: int, tpm: int | None, tpd: int | None):
        self.provider_id = provider_id
        self.rpm = rpm
        self.tpm = tpm
        self.tpd = tpd
        self._lock = threading.Lock()
        self._request_times: list[float] = []
        self._token_events_minute: list[tuple[float, int]] = []
        self.last_error: str | None = None

    def _today_key(self) -> str:
        return f"usage:{self.provider_id}:tokens_day:{datetime.now(timezone.utc):%Y-%m-%d}"

    def _get_persisted_day_tokens(self) -> int:
        from app.services.database import get_setting
        return int(get_setting(self._today_key(), "0") or "0")

    def _add_persisted_day_tokens(self, tokens: int) -> None:
        from app.services.database import get_setting, set_setting
        key = self._today_key()
        current = int(get_setting(key, "0") or "0")
        set_setting(key, str(current + tokens))

    def acquire(self):
        """Block until a request slot is free within the per-minute budget."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._request_times = [t for t in self._request_times if now - t < 60]
                if len(self._request_times) < self.rpm:
                    self._request_times.append(now)
                    return
                wait_time = 60 - (now - self._request_times[0]) + 0.1
            time.sleep(max(wait_time, 0.1))

    def record_success(self, tokens: int):
        self.last_error = None
        now = time.monotonic()
        with self._lock:
            if self.tpm:
                self._token_events_minute.append((now, tokens))
        if self.tpd and tokens:
            self._add_persisted_day_tokens(tokens)

    def record_error(self, message: str):
        self.last_error = message[:200]

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            self._request_times = [t for t in self._request_times if now - t < 60]
            result: dict = {
                "requests": {"used": len(self._request_times), "limit": self.rpm, "window": "minute"},
            }
            if self.tpm:
                self._token_events_minute = [(t, n) for t, n in self._token_events_minute if now - t < 60]
                result["tokens"] = {
                    "used": sum(n for _, n in self._token_events_minute),
                    "limit": self.tpm,
                    "window": "minute",
                }
        if self.tpd:
            result["tokens"] = {
                "used": self._get_persisted_day_tokens(),
                "limit": self.tpd,
                "window": "day",
            }
        result["last_error"] = self.last_error
        return result


_TRACKERS: dict[str, UsageTracker] = {
    pid: UsageTracker(pid, meta["rpm"], meta["tpm"], meta["tpd"]) for pid, meta in UI_PROVIDERS.items()
}


class LiteLLMProvider(AIProvider):
    """Backs whichever of Groq/Cerebras/Gemini is active, via LiteLLM."""

    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self.model = _litellm_model_string(provider_id)
        self.fallback_models = [
            _litellm_model_string(pid)
            for pid in FALLBACK_ORDER
            if pid != provider_id and _is_configured(pid)
        ]

    def generate(self, system_prompt: str, user_message: str) -> str:
        tracker = _TRACKERS[self.provider_id]
        tracker.acquire()
        try:
            resp = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=8000,
                num_retries=3,
                fallbacks=self.fallback_models or None,
                timeout=120,
            )
        except Exception as e:
            tracker.record_error(f"{type(e).__name__}: {e}")
            raise

        # If LiteLLM fell back to a different provider, credit that
        # provider's tracker instead of the one we started with — `resp.model`
        # reflects whichever model actually served the request.
        served_provider = self.provider_id
        served_model = getattr(resp, "model", "") or ""
        for pid, meta in UI_PROVIDERS.items():
            if served_model.startswith(f"{meta['litellm_prefix']}/") or served_model == meta["default_model"]:
                served_provider = pid
                break
        usage = getattr(resp, "usage", None)
        _TRACKERS[served_provider].record_success(getattr(usage, "total_tokens", 0) or 0)

        return resp.choices[0].message.content or ""


def list_ui_providers() -> dict:
    """Status for the settings UI: the 3 selectable providers, which one is
    active, whether each has an API key configured, and live usage."""
    from app.services.database import get_setting
    active = (get_setting("ai_provider") or os.getenv("AI_PROVIDER", "groq")).lower()
    if active not in UI_PROVIDERS:
        active = "groq"
    providers = []
    for pid, meta in UI_PROVIDERS.items():
        providers.append({
            "id": pid,
            "label": meta["label"],
            "model": os.getenv(meta["model_env"], meta["default_model"]),
            "configured": _is_configured(pid),
            "active": pid == active,
            "usage": _TRACKERS[pid].status(),
        })
    return {"active": active, "providers": providers}


def select_ui_provider(provider_id: str) -> dict:
    from app.services.database import set_setting
    if provider_id not in UI_PROVIDERS:
        raise ValueError(f"Unknown provider '{provider_id}'. Choose from: {list(UI_PROVIDERS.keys())}")
    if not _is_configured(provider_id):
        raise ValueError(f"{UI_PROVIDERS[provider_id]['label']} has no API key configured.")
    set_setting("ai_provider", provider_id)
    return list_ui_providers()


class OllamaProvider(AIProvider):
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1")

    def generate(self, system_prompt: str, user_message: str) -> str:
        return "".join(self.generate_stream(system_prompt, user_message))

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": True,
            "options": {"temperature": 0.3},
        }
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        text = chunk.get("message", {}).get("content", "")
                        if text:
                            yield text
                    except json.JSONDecodeError:
                        continue


class LMStudioProvider(AIProvider):
    """Local LM Studio server — uses OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self):
        self.base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234")
        self.model = os.getenv("LMSTUDIO_MODEL", "google/gemma-4-e4b")

    def generate(self, system_prompt: str, user_message: str) -> str:
        return "".join(self.generate_stream(system_prompt, user_message))

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 8000,
            "stream": True,
        }
        with httpx.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=300,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError):
                    continue


class HuggingFaceProvider(AIProvider):
    def __init__(self):
        self.api_key = os.getenv("HUGGINGFACE_API_KEY", "")
        self.model = os.getenv("HUGGINGFACE_MODEL", "openai/gpt-oss-120b:fastest")
        self.base_url = "https://router.huggingface.co/v1"

    def generate(self, system_prompt: str, user_message: str) -> str:
        return "".join(self.generate_stream(system_prompt, user_message))

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 8000,
            "stream": True,
        }

        for attempt in range(4):
            try:
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                ) as response:
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except json.JSONDecodeError:
                                continue
                    return

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                if status_code == 429 and attempt < 3:
                    wait_time = (2 ** attempt) * 5
                    print(f"[WARN HuggingFace] Rate limited (429). Waiting {wait_time}s before retry {attempt+1}/4...")
                    time.sleep(wait_time)
                    continue

                elif status_code >= 500 and attempt < 3:
                    wait_time = (2 ** attempt) * 3
                    print(f"[WARN HuggingFace] Server error ({status_code}). Waiting {wait_time}s before retry {attempt+1}/4...")
                    time.sleep(wait_time)
                    continue

                else:
                    print(f"[ERROR HuggingFace] generate_stream failed: HTTP {status_code}: {e}")
                    raise

            except Exception as e:
                print(f"[ERROR HuggingFace] generate_stream failed: {type(e).__name__}: {e}")
                raise


_LEGACY_PROVIDERS = {
    # Not part of the UI provider picker (self-hosted / no rate-limit
    # concerns to track) — still selectable via the AI_PROVIDER env var.
    "ollama": OllamaProvider,
    "lmstudio": LMStudioProvider,
    "huggingface": HuggingFaceProvider,
}


def get_provider() -> AIProvider:
    from app.services.database import get_setting
    provider_name = (get_setting("ai_provider") or os.getenv("AI_PROVIDER", "groq")).lower()
    if provider_name in UI_PROVIDERS:
        return LiteLLMProvider(provider_name)
    if provider_name in _LEGACY_PROVIDERS:
        return _LEGACY_PROVIDERS[provider_name]()
    raise ValueError(
        f"Unknown provider '{provider_name}'. Choose from: {list(UI_PROVIDERS.keys()) + list(_LEGACY_PROVIDERS.keys())}"
    )
