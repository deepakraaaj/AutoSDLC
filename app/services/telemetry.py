"""Small in-process operational telemetry registry.

This keeps the deployment dependency-free while exposing useful request/error/latency
signals. Counters reset on process restart; a production metrics backend can consume
the same record_request boundary later.
"""
from collections import defaultdict
from threading import Lock


_lock = Lock()
_requests: dict[tuple[str, str, int], int] = defaultdict(int)
_duration_ms: dict[tuple[str, str], float] = defaultdict(float)


def record_request(method: str, route: str, status: int, elapsed_ms: float) -> None:
    with _lock:
        _requests[(method, route, status)] += 1
        _duration_ms[(method, route)] += elapsed_ms


def snapshot() -> dict:
    with _lock:
        rows = []
        for (method, route, status), count in sorted(_requests.items()):
            total = _duration_ms[(method, route)]
            route_count = sum(v for (m, r, _), v in _requests.items() if m == method and r == route)
            rows.append({
                "method": method,
                "route": route,
                "status": status,
                "count": count,
                "route_average_ms": round(total / max(1, route_count), 1),
            })
        return {"requests": rows}
