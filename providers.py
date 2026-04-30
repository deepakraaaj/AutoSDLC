import json
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator

import httpx


class AIProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_message: str) -> str:
        pass

    def generate_stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        """Yield text chunks as they arrive. Falls back to single chunk by default."""
        yield self.generate(system_prompt, user_message)


class GroqProvider(AIProvider):
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.base_url = "https://api.groq.com/openai/v1"

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
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta


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
        response = httpx.post(
            f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]

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
