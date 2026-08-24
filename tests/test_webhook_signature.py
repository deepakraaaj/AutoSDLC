"""Tests for app/utils/webhook_auth.py and POST /webhooks/bitbucket. The
signature check is the security-critical piece of Phase 3 — verify it fails
closed on every bad input, not just rejects a wrong signature."""
import hashlib
import hmac
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.api.webhooks as webhooks_module  # noqa: E402
import app.services.database as database  # noqa: E402
from app.utils.webhook_auth import verify_bitbucket_signature  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """The webhook endpoint writes to webhook_deliveries for dedup — without
    this, repeated test runs against the real dev DB file would find
    delivery ids from a prior run already recorded and every 'schedules a
    job' assertion would spuriously look like a duplicate delivery."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_rejects_missing_secret():
    assert verify_bitbucket_signature(b"payload", "sha256=abc", None) is False
    assert verify_bitbucket_signature(b"payload", "sha256=abc", "") is False


def test_verify_rejects_missing_or_malformed_header():
    assert verify_bitbucket_signature(b"payload", None, "secret") is False
    assert verify_bitbucket_signature(b"payload", "not-a-signature", "secret") is False
    assert verify_bitbucket_signature(b"payload", "md5=deadbeef", "secret") is False


def test_verify_rejects_wrong_signature():
    body = b'{"a": 1}'
    assert verify_bitbucket_signature(body, "sha256=" + "0" * 64, "secret") is False


def test_verify_accepts_correct_signature():
    body = b'{"a": 1}'
    signature = _sign(body, "secret")
    assert verify_bitbucket_signature(body, signature, "secret") is True


def test_endpoint_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("BITBUCKET_WEBHOOK_SECRET", "topsecret")
    response = client.post(
        "/webhooks/bitbucket",
        content=json.dumps({"pullrequest": {"id": 1}, "repository": {"full_name": "acme/widgets"}}),
        headers={"X-Event-Key": "pullrequest:created"},
    )
    assert response.status_code == 401


def test_endpoint_rejects_when_secret_unset(monkeypatch):
    monkeypatch.delenv("BITBUCKET_WEBHOOK_SECRET", raising=False)
    body = json.dumps({"pullrequest": {"id": 1}, "repository": {"full_name": "acme/widgets"}}).encode()
    response = client.post(
        "/webhooks/bitbucket",
        content=body,
        headers={"X-Event-Key": "pullrequest:created", "X-Hub-Signature": _sign(body, "irrelevant")},
    )
    assert response.status_code == 401


def test_endpoint_ignores_unsupported_event(monkeypatch):
    monkeypatch.setenv("BITBUCKET_WEBHOOK_SECRET", "topsecret")
    body = json.dumps({"repository": {"full_name": "acme/widgets"}}).encode()
    response = client.post(
        "/webhooks/bitbucket",
        content=body,
        headers={"X-Event-Key": "repo:push", "X-Hub-Signature": _sign(body, "topsecret")},
    )
    assert response.status_code == 202
    assert "Ignored" in response.json()["message"]


def test_endpoint_schedules_job_on_valid_signature(monkeypatch):
    monkeypatch.setenv("BITBUCKET_WEBHOOK_SECRET", "topsecret")
    scheduled = {}

    def fake_create_job(kind, payload):
        scheduled["call"] = (kind, payload)
        return {"id": "job-123"}

    monkeypatch.setattr(webhooks_module, "create_job", fake_create_job)
    body = json.dumps({"pullrequest": {"id": 7}, "repository": {"full_name": "acme/widgets"}}).encode()
    response = client.post(
        "/webhooks/bitbucket",
        content=body,
        headers={
            "X-Event-Key": "pullrequest:created",
            "X-Hub-Signature": _sign(body, "topsecret"),
            "X-Request-UUID": "delivery-1",
        },
    )
    assert response.status_code == 202
    assert response.json()["job_id"] == "job-123"
    assert scheduled["call"] == ("bitbucket_review", {
        "repo_full_name": "acme/widgets", "pr_id": 7, "related_repos": [],
    })


def test_endpoint_dedups_repeated_delivery(monkeypatch):
    monkeypatch.setenv("BITBUCKET_WEBHOOK_SECRET", "topsecret")
    calls = []
    monkeypatch.setattr(webhooks_module, "create_job", lambda kind, payload: calls.append(1) or {"id": "job-456"})
    body = json.dumps({"pullrequest": {"id": 9}, "repository": {"full_name": "acme/widgets"}}).encode()
    headers = {
        "X-Event-Key": "pullrequest:updated",
        "X-Hub-Signature": _sign(body, "topsecret"),
        "X-Request-UUID": "delivery-dup",
    }
    first = client.post("/webhooks/bitbucket", content=body, headers=headers)
    second = client.post("/webhooks/bitbucket", content=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert "Already processed" in second.json()["message"]
    assert len(calls) == 1
