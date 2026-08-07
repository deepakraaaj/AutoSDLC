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
        # Confirmed live via a real 429 body from this account: "Rate limit
        # reached ... on tokens per day (TPD): Limit 100000" — the daily
        # token cap, not requests/minute, is the binding constraint here.
        "rpm": int(os.getenv("GROQ_RPM", "25")),
        "tpm": None,
        "tpd": int(os.getenv("GROQ_TPD", "100000")),
        "rpd": None,
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
        "rpd": None,
    },
    "gemini": {
        "label": "Google Gemini",
        "litellm_prefix": "gemini",
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        # Confirmed live via this account's own quota dashboard: the full
        # "Flash" models (gemini-2.5-flash, gemini-3.5-flash, ...) are capped
        # at a stingy 20 requests/day on this key's free tier — already
        # exceeded from today's testing. The "Flash Lite" variants get a much
        # more usable 500 requests/day, barely touched. Not a fluke of one
        # model either — several Lite variants show the same 500 RPD, so this
        # is a tier-wide free-tier policy, not a quirk of this one model.
        "default_model": "gemini-3.5-flash-lite",
        # RPM/TPM from the same dashboard (Flash Lite row). RPD (requests/day)
        # is the actually-binding constraint for Gemini's free tier — tracked
        # separately from tokens/day, which this tier doesn't meaningfully
        # limit (250K/min dwarfs what one generation needs).
        "rpm": int(os.getenv("GEMINI_RPM", "15")),
        "tpm": int(os.getenv("GEMINI_TPM", "250000")),
        "tpd": None,
        "rpd": int(os.getenv("GEMINI_RPD", "500")),
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

    def __init__(self, provider_id: str, rpm: int, tpm: int | None, tpd: int | None, rpd: int | None = None):
        self.provider_id = provider_id
        self.rpm = rpm
        self.tpm = tpm
        self.tpd = tpd
        self.rpd = rpd
        self._lock = threading.Lock()
        self._request_times: list[float] = []
        self._token_events_minute: list[tuple[float, int]] = []
        self.last_error: str | None = None
        self._live: dict | None = None
        self._live_checked_at: datetime | None = None

    def _day_key(self, kind: str) -> str:
        return f"usage:{self.provider_id}:{kind}_day:{datetime.now(timezone.utc):%Y-%m-%d}"

    def _get_persisted_day(self, kind: str) -> int:
        from app.services.database import get_setting
        return int(get_setting(self._day_key(kind), "0") or "0")

    def _add_persisted_day(self, kind: str, amount: int) -> None:
        from app.services.database import get_setting, set_setting
        key = self._day_key(kind)
        current = int(get_setting(key, "0") or "0")
        set_setting(key, str(current + amount))

    def acquire(self):
        """Block until a request slot is free within the per-minute budget.

        Deliberately doesn't also block on rpd (requests/day) — unlike a
        minute window, waiting out a daily cap could mean sleeping for
        hours. Daily limits are tracked (see record_success) for accurate
        display and left to LiteLLM's real 429 handling + automatic
        fallback to actually enforce, same as the tpd token cap already did.
        """
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
            self._add_persisted_day("tokens", tokens)
        if self.rpd:
            self._add_persisted_day("requests", 1)

    def record_error(self, message: str):
        self.last_error = message[:200]

    def set_live(self, live: dict):
        """Record a real snapshot fetched straight from the provider's own
        response headers (see probe_provider) — supersedes the self-tracked
        estimate below in status() until it goes stale."""
        with self._lock:
            self._live = live
            self._live_checked_at = datetime.now(timezone.utc)

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            self._request_times = [t for t in self._request_times if now - t < 60]
            result: dict = {
                "requests": {"used": len(self._request_times), "limit": self.rpm, "window": "minute"},
                "live": False,
                "checked_at": None,
            }
            if self.tpm:
                self._token_events_minute = [(t, n) for t, n in self._token_events_minute if now - t < 60]
                result["tokens"] = {
                    "used": sum(n for _, n in self._token_events_minute),
                    "limit": self.tpm,
                    "window": "minute",
                }
            live = self._live
            live_checked_at = self._live_checked_at
        if self.tpd:
            result["tokens"] = {
                "used": self._get_persisted_day("tokens"),
                "limit": self.tpd,
                "window": "day",
            }
        if self.rpd:
            # Daily request cap is the binding constraint for some providers
            # (Gemini's free tier), overriding the per-minute requests meter
            # the same way tpd overrides the per-minute tokens meter above.
            result["requests"] = {
                "used": self._get_persisted_day("requests"),
                "limit": self.rpd,
                "window": "day",
            }
        # A real probe (see probe_provider) overrides the self-tracked
        # estimate above — it reflects the account's actual state, including
        # usage from outside this app, rather than just what this app has
        # sent since it last restarted. `live` distinguishes "never probed"
        # (None) from "probed successfully but the provider exposes no
        # numeric quota headers" (an empty dict, e.g. Gemini on success) —
        # the latter must still count as a completed, live check, not look
        # identical to never having checked at all.
        if live is not None:
            result["live"] = True
            result["checked_at"] = live_checked_at.isoformat() if live_checked_at else None
            if "requests" in live:
                result["requests"] = live["requests"]
            if "tokens" in live:
                result["tokens"] = live["tokens"]
            elif not live.get("error"):
                # Probed successfully, but this provider (Gemini) exposes no
                # numeric quota headers on success — say so explicitly rather
                # than silently passing off the stale self-tracked estimate
                # as if it were equally live/accurate.
                result["no_live_numbers"] = True
            if live.get("error"):
                result["last_error"] = live["error"]
        result.setdefault("last_error", self.last_error)
        return result


_TRACKERS: dict[str, UsageTracker] = {
    pid: UsageTracker(pid, meta["rpm"], meta["tpm"], meta["tpd"], meta.get("rpd")) for pid, meta in UI_PROVIDERS.items()
}


class AllProvidersExhaustedError(Exception):
    """Raised when a call fails after LiteLLM has already tried the active
    provider and every configured fallback — i.e. every provider this app
    knows about is currently rate-limited or unavailable, not just one."""


class LiteLLMProvider(AIProvider):
    """Backs whichever of Groq/Cerebras/Gemini is active, via LiteLLM.

    A fresh instance is created per generation (see get_provider(), called
    once at the top of _stream_generate and reused for every phase), so
    usage_log naturally scopes to "everything this one generation spent" —
    exactly what the UI's token/cost breakdown reports via usage_summary().
    Multiple phases call generate() concurrently from a thread pool, so
    usage_log is lock-guarded rather than a plain list append.

    _exhausted_until is a short-lived, per-generation circuit breaker: once
    one call discovers every provider (primary + all fallbacks) is
    rate-limited, there's no reason for the other dozens of concurrent
    calls in this same generation to each independently burn through their
    own retry+fallback chain against APIs already known to be down — they'd
    just add minutes of wasted waiting before the generation fails anyway.
    Short (not permanent) because a burst 429 can clear within seconds.
    """

    _EXHAUSTION_COOLDOWN_SECONDS = 20

    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self.model = _litellm_model_string(provider_id)
        self.fallback_models = [
            _litellm_model_string(pid)
            for pid in FALLBACK_ORDER
            if pid != provider_id and _is_configured(pid)
        ]
        self._usage_lock = threading.Lock()
        self.usage_log: list[dict] = []
        self._exhausted_lock = threading.Lock()
        self._exhausted_until: float | None = None
        self._exhaustion_message: str | None = None

    def _tried_providers_label(self) -> str:
        tried = [self.provider_id] + [
            pid for pid in FALLBACK_ORDER if pid != self.provider_id and _is_configured(pid)
        ]
        return ", ".join(UI_PROVIDERS[pid]["label"] for pid in tried)

    def generate(self, system_prompt: str, user_message: str) -> str:
        with self._exhausted_lock:
            if self._exhausted_until and time.monotonic() < self._exhausted_until:
                raise AllProvidersExhaustedError(self._exhaustion_message)

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
            # A RateLimitError surfacing here means LiteLLM already tried the
            # primary AND every fallback (that's the whole point of passing
            # fallbacks= — a fallback that itself succeeds never raises).
            if isinstance(e, litellm.RateLimitError):
                message = (
                    f"All configured AI providers ({self._tried_providers_label()}) are currently "
                    f"rate-limited. This usually clears within a few minutes — check AI Provider "
                    f"settings for live quota, or try again shortly."
                )
                with self._exhausted_lock:
                    self._exhausted_until = time.monotonic() + self._EXHAUSTION_COOLDOWN_SECONDS
                    self._exhaustion_message = message
                raise AllProvidersExhaustedError(message) from e
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
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
        try:
            cost_usd = float(getattr(resp, "_hidden_params", {}).get("response_cost") or 0.0)
        except (TypeError, ValueError):
            cost_usd = 0.0

        _TRACKERS[served_provider].record_success(total_tokens)
        with self._usage_lock:
            self.usage_log.append({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
            })

        return resp.choices[0].message.content or ""

    def usage_summary(self) -> dict:
        """Total tokens/cost across every call made through this instance —
        i.e. this one generation. See the class docstring for why that scope
        is correct without any extra bookkeeping in main.py."""
        with self._usage_lock:
            calls = list(self.usage_log)
        return {
            "ai_calls": len(calls),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            "total_tokens": sum(c["total_tokens"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"] for c in calls), 5),
        }


def estimate_call_cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    """Real per-token pricing for the currently active provider's model, via
    LiteLLM's own cost map — used by /estimate-tokens in main.py for an
    accurate pre-generation cost guess instead of a flat blended rate that
    ignored which provider was actually selected. None if the active
    model isn't in LiteLLM's cost map (e.g. a self-hosted Ollama/LM Studio
    model has no list price) — the caller falls back to a rough guess then."""
    from app.services.database import get_setting
    active = (get_setting("ai_provider") or os.getenv("AI_PROVIDER", "groq")).lower()
    if active not in UI_PROVIDERS:
        return None
    try:
        info = litellm.get_model_info(_litellm_model_string(active))
    except Exception:
        return None
    input_cost = info.get("input_cost_per_token") or 0.0
    output_cost = info.get("output_cost_per_token") or 0.0
    if not input_cost and not output_cost:
        return None
    return input_tokens * input_cost + output_tokens * output_cost


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


# ── Live quota probes ───────────────────────────────────────────────────
#
# UsageTracker's self-tracked counters only see usage sent through this app
# — they miss anything spent outside it (curl testing, other tools sharing
# the same key) and reset when the process restarts, so they can read "0
# used" on a key that's actually near-exhausted. These probes go straight to
# the provider's own API with a 1-token request and read its real
# x-ratelimit-* response headers — bypassing LiteLLM, which doesn't surface
# them (verified: `additional_headers` comes back empty on its completion()
# responses). Deliberately not called on every status poll — only when the
# settings UI opens or the user hits Refresh, since each is a real (tiny)
# request against the account's quota.

def _probe_cerebras() -> dict:
    meta = UI_PROVIDERS["cerebras"]
    api_key = os.getenv(meta["api_key_env"], "")
    model = os.getenv(meta["model_env"], meta["default_model"])
    resp = httpx.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_completion_tokens": 1},
        timeout=15,
    )
    h = resp.headers
    result: dict = {}
    if "x-ratelimit-limit-requests-minute" in h:
        limit = int(h["x-ratelimit-limit-requests-minute"])
        remaining = int(h.get("x-ratelimit-remaining-requests-minute", limit))
        result["requests"] = {"used": max(0, limit - remaining), "limit": limit, "window": "minute"}
    if "x-ratelimit-limit-tokens-day" in h:
        limit = int(h["x-ratelimit-limit-tokens-day"])
        remaining = int(h.get("x-ratelimit-remaining-tokens-day", limit))
        result["tokens"] = {"used": max(0, limit - remaining), "limit": limit, "window": "day"}
    if resp.status_code >= 400 and not result:
        result["error"] = f"HTTP {resp.status_code}: {resp.text[:150]}"
    return result


def _probe_groq() -> dict:
    meta = UI_PROVIDERS["groq"]
    api_key = os.getenv(meta["api_key_env"], "")
    model = os.getenv(meta["model_env"], meta["default_model"])
    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
        timeout=15,
    )
    h = resp.headers
    result: dict = {}
    # Groq's headers have no minute/day suffix — just "current window",
    # whatever that window turns out to be for this account/tier.
    if "x-ratelimit-limit-requests" in h:
        limit = int(h["x-ratelimit-limit-requests"])
        remaining = int(h.get("x-ratelimit-remaining-requests", limit))
        result["requests"] = {"used": max(0, limit - remaining), "limit": limit, "window": "current"}
    if "x-ratelimit-limit-tokens" in h:
        limit = int(h["x-ratelimit-limit-tokens"])
        remaining = int(h.get("x-ratelimit-remaining-tokens", limit))
        result["tokens"] = {"used": max(0, limit - remaining), "limit": limit, "window": "current"}
    if resp.status_code >= 400 and not result:
        result["error"] = f"HTTP {resp.status_code}: {resp.text[:150]}"
    return result


def _probe_gemini() -> dict:
    # Gemini doesn't return numeric x-ratelimit-* headers on success — the
    # only signal available is reachable-vs-blocked. A 429 body does include
    # a human-readable quota message (e.g. "limit: 0" when billing isn't
    # enabled on the project), which is at least honest about being blocked.
    meta = UI_PROVIDERS["gemini"]
    api_key = os.getenv(meta["api_key_env"], "")
    model = os.getenv(meta["model_env"], meta["default_model"])
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 1}},
        timeout=15,
    )
    if resp.status_code >= 400:
        try:
            message = resp.json().get("error", {}).get("message", "")
        except Exception:
            message = ""
        return {"error": (message or f"HTTP {resp.status_code}")[:200]}
    return {}


_PROBES = {"cerebras": _probe_cerebras, "groq": _probe_groq, "gemini": _probe_gemini}


def refresh_provider_status() -> dict:
    """Probe every configured UI provider live and return the same shape as
    list_ui_providers(). Each probe is a best-effort, ~1-token request —
    failures are recorded as that provider's last_error rather than raised."""
    for provider_id in UI_PROVIDERS:
        if not _is_configured(provider_id):
            continue
        try:
            live = _PROBES[provider_id]()
            _TRACKERS[provider_id].set_live(live)
        except Exception as e:
            _TRACKERS[provider_id].record_error(f"Live check failed: {type(e).__name__}: {e}")
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
