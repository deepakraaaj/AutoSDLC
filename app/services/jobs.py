"""Persisted background-job execution for long-running AI work."""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Iterator

from app.services.database import get_connection
from app.utils.error_handler import log_error, log_info


JobRunner = Callable[[dict], Iterator[tuple[str, dict]]]
_runners: dict[str, JobRunner] = {}
_executor = ThreadPoolExecutor(max_workers=int(os.getenv("JOB_WORKERS", "2")), thread_name_prefix="autosdlc-job")
_active: set[str] = set()
_lock = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure_runner(kind: str, runner: JobRunner) -> None:
    _runners[kind] = runner


def create_job(kind: str, payload: dict) -> dict:
    if kind not in _runners:
        raise ValueError(f"No job runner configured for {kind}")
    job_id = str(uuid.uuid4())
    now = _now()
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, ?)",
        (job_id, kind, json.dumps(payload), now, now),
    )
    conn.commit()
    conn.close()
    _schedule(job_id)
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, kind, status, result_json, error, cancel_requested, attempt, created_at, updated_at FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"], "kind": row["kind"], "status": row["status"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"], "cancel_requested": bool(row["cancel_requested"]),
        "attempt": row["attempt"], "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_events(job_id: str, after: int = 0) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT seq, event_type, payload_json, created_at FROM job_events WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT 500",
        (job_id, after),
    ).fetchall()
    conn.close()
    return [{"seq": r["seq"], "type": r["event_type"], "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]} for r in rows]


def request_cancel(job_id: str) -> bool:
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ? AND status IN ('queued', 'running')",
        (_now(), job_id),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def recover_jobs() -> int:
    """Requeue work interrupted by a process restart.

    Runners must be idempotent at their own persistence boundary. Generation jobs
    currently use the existing pipeline and are retried at most once after restart.
    """
    conn = get_connection()
    # A process can die during the second attempt. Previously those rows were
    # excluded from recovery but left as `running` forever, which made the PR
    # UI display “Reviewing…” indefinitely after restart.
    conn.execute(
        "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? "
        "WHERE status IN ('queued', 'running') AND attempt >= 2",
        ("Job interrupted and exhausted its restart retry limit.", _now()),
    )
    rows = conn.execute("SELECT id FROM jobs WHERE status IN ('queued', 'running') AND attempt < 2").fetchall()
    recoverable = []
    for row in rows:
        done = conn.execute(
            "SELECT payload_json FROM job_events WHERE job_id = ? AND event_type = 'done' ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        if done:
            conn.execute(
                "UPDATE jobs SET status = 'succeeded', result_json = ?, updated_at = ? WHERE id = ?",
                (done["payload_json"], _now(), row["id"]),
            )
        else:
            conn.execute("UPDATE jobs SET status = 'queued', updated_at = ? WHERE id = ?", (_now(), row["id"]))
            recoverable.append(row["id"])
    conn.commit()
    conn.close()
    for job_id in recoverable:
        _schedule(job_id)
    return len(recoverable)


def _schedule(job_id: str) -> None:
    with _lock:
        if job_id in _active:
            return
        _active.add(job_id)
    _executor.submit(_execute, job_id)


def _append_event(conn, job_id: str, event_type: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO job_events (job_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
        (job_id, event_type, json.dumps(payload), _now()),
    )


def _execute(job_id: str) -> None:
    try:
        conn = get_connection()
        row = conn.execute("SELECT kind, input_json, cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            conn.close()
            return
        if row["cancel_requested"]:
            conn.execute("UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE id = ?", (_now(), job_id))
            conn.commit()
            conn.close()
            return
        runner = _runners.get(row["kind"])
        if not runner:
            raise RuntimeError(f"No runner configured for {row['kind']}")
        conn.execute("UPDATE jobs SET status = 'running', attempt = attempt + 1, updated_at = ? WHERE id = ?", (_now(), job_id))
        conn.commit()
        conn.close()

        result = None
        for event_type, payload in runner(json.loads(row["input_json"])):
            conn = get_connection()
            cancelled = bool(conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()[0])
            if cancelled:
                _append_event(conn, job_id, "cancelled", {"message": "Cancellation requested"})
                conn.execute("UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE id = ?", (_now(), job_id))
                conn.commit()
                conn.close()
                return
            _append_event(conn, job_id, event_type, payload)
            if event_type == "done":
                result = payload
            if event_type == "error":
                message = payload.get("error", {}).get("message") or payload.get("message") or "Job failed"
                conn.execute("UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?", (message[:500], _now(), job_id))
                conn.commit()
                conn.close()
                return
            conn.commit()
            conn.close()

        conn = get_connection()
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', result_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result) if result is not None else None, _now(), job_id),
        )
        conn.commit()
        conn.close()
        log_info("Jobs", f"Job {job_id} succeeded")
    except Exception as exc:
        conn = get_connection()
        conn.execute("UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?", (str(exc)[:500], _now(), job_id))
        conn.commit()
        conn.close()
        log_error("Jobs", f"Job {job_id} failed", exception=exc)
    finally:
        with _lock:
            _active.discard(job_id)
