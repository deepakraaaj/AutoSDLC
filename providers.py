import json
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime, timedelta

import httpx
import time


class AIProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_message: str) -> str:
        pass

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        """Yield text chunks as they arrive. Falls back to single chunk by default."""
        yield self.generate(system_prompt, user_message)


class GroqProvider(AIProvider):
    # Class-level request tracking for free tier rate limiting
    _request_times = []  # Track last 30 requests for rate limiting
    _daily_requests = 0  # Track daily request count
    _last_reset = datetime.now()

    # Groq free tier limits
    FREE_TIER_RPM = 30  # 30 requests per minute
    FREE_TIER_RPD = 100  # 100 requests per day
    REQUEST_WINDOW = 60  # seconds (1 minute)

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.base_url = "https://api.groq.com/openai/v1"

    def _apply_rate_limit(self):
        """Apply adaptive rate limiting for Groq free tier."""
        now = datetime.now()

        # Reset daily counter at midnight
        if (now - GroqProvider._last_reset).days >= 1:
            GroqProvider._daily_requests = 0
            GroqProvider._last_reset = now

        # Remove old request timestamps (older than 1 minute)
        GroqProvider._request_times = [
            t for t in GroqProvider._request_times
            if (now - t).total_seconds() < self.REQUEST_WINDOW
        ]

        # Check if we're hitting rate limits
        requests_this_minute = len(GroqProvider._request_times)

        if GroqProvider._daily_requests >= self.FREE_TIER_RPD:
            raise Exception(
                f"[ERROR GroqProvider] Daily rate limit reached ({self.FREE_TIER_RPD} requests/day). "
                f"Please wait until tomorrow or upgrade your API key."
            )

        if requests_this_minute >= self.FREE_TIER_RPM:
            # Calculate wait time for next available slot
            oldest_request = GroqProvider._request_times[0]
            wait_time = self.REQUEST_WINDOW - (now - oldest_request).total_seconds() + 1
            print(f"[WARN GroqProvider] Rate limit approaching ({requests_this_minute}/{self.FREE_TIER_RPM} req/min). "
                  f"Waiting {wait_time:.1f}s to stay within free tier limits...")
            time.sleep(wait_time)

    def generate(self, system_prompt: str, user_message: str) -> str:
        return "".join(self.generate_stream(system_prompt, user_message))

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        # Apply rate limiting before making request
        self._apply_rate_limit()

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

        # Retry with exponential backoff on rate limit (429) or server errors (500)
        for attempt in range(4):  # Increased to 4 attempts (0-3)
            try:
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=120,
                ) as response:
                    response.raise_for_status()

                    # Track successful request
                    GroqProvider._request_times.append(datetime.now())
                    GroqProvider._daily_requests += 1

                    print(f"[INFO GroqProvider] Request {GroqProvider._daily_requests}/{self.FREE_TIER_RPD} for today")

                    for line in response.iter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk["choices"][0]["delta"].get("content", "")
                                if delta:
                                    yield delta
                            except (KeyError, json.JSONDecodeError, IndexError) as e:
                                print(f"[ERROR GroqProvider] Failed to parse chunk: {e}")
                                print(f"[ERROR GroqProvider] Line: {line[:200]}")
                                raise
                    return  # Success, exit retry loop

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                if status_code == 429 and attempt < 3:
                    # Rate limited - exponential backoff
                    wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s, 80s
                    print(f"[WARN GroqProvider] Rate limited (429). Attempt {attempt+1}/4. "
                          f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

                elif status_code >= 500 and attempt < 3:
                    # Server error - retry with longer backoff
                    wait_time = (2 ** attempt) * 5
                    print(f"[WARN GroqProvider] Server error ({status_code}). Attempt {attempt+1}/4. "
                          f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

                else:
                    print(f"[ERROR GroqProvider] generate_stream failed: HTTP {status_code}: {e}")
                    raise

            except Exception as e:
                print(f"[ERROR GroqProvider] generate_stream failed: {type(e).__name__}: {e}")
                raise


class GeminiProvider(AIProvider):
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def generate(self, system_prompt: str, user_message: str) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 8000,
                "responseMimeType": "application/json",
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            resp_json = response.json()
            print(f"[DEBUG GeminiProvider] Response keys: {resp_json.keys() if isinstance(resp_json, dict) else 'not dict'}")
            return resp_json["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"[ERROR GeminiProvider] Failed to extract text from response: {type(e).__name__}: {e}")
            print(f"[ERROR GeminiProvider] Response (full): {response.text[:1000]}")
            raise
        except Exception as e:
            print(f"[ERROR GeminiProvider] generate failed: {type(e).__name__}: {e}")
            raise

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000},
        }
        with httpx.stream(
            "POST",
            f"{self.base_url}/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}",
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                        if text:
                            yield text
                    except (KeyError, json.JSONDecodeError):
                        continue


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


def get_provider() -> AIProvider:
    provider_name = os.getenv("AI_PROVIDER", "groq").lower()
    providers = {
        "groq": GroqProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
        "lmstudio": LMStudioProvider,
    }
    if provider_name not in providers:
        raise ValueError(f"Unknown provider '{provider_name}'. Choose from: {list(providers.keys())}")
    return providers[provider_name]()
