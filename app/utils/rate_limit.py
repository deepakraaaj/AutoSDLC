"""
Minimal in-memory rate limiting.

This is a per-process, sliding-window limiter keyed by client IP. It is
enough to stop a single caller from looping the expensive LLM-backed
generation endpoints and running up provider cost, which is the actual risk
today (single uvicorn worker, no load balancer).

It does NOT survive process restarts and is NOT shared across multiple
workers/instances — if this app is ever scaled horizontally, swap the
in-memory `_hits` store for something shared (e.g. Redis) so limits are
enforced consistently across processes.
"""
import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from app.utils.error_handler import RateLimitError

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def _client_key(request: Request, bucket: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{bucket}:{client_ip}"


def enforce_rate_limit(request: Request, *, bucket: str, limit: int, window_seconds: int = 60) -> None:
    """Raise RateLimitError if this client has exceeded `limit` calls to
    `bucket` within `window_seconds`. Call at the top of a route handler."""
    key = _client_key(request, bucket)
    now = time.monotonic()

    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
            raise RateLimitError(
                message=f"Too many requests to {bucket} — limit is {limit} per {window_seconds}s.",
                retry_after=retry_after,
            )

        hits.append(now)


# Defaults are deliberately generous for a single-user/small-team dev tool —
# tune down via env vars for a shared production deployment.
GENERATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_GENERATE_PER_MINUTE", "5"))

# Each clarify-chat round is a single cheap LLM call (not a full 4-phase
# generation), so it gets a more generous allowance and its own bucket.
CLARIFY_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_CLARIFY_PER_MINUTE", "15"))

# Each assistant-chat turn is one routing LLM call (plus, on confirm, one Redmine
# API call) — similarly cheap, so it gets its own generous bucket rather than
# sharing GENERATE_LIMIT_PER_MINUTE.
ASSISTANT_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_ASSISTANT_PER_MINUTE", "20"))
