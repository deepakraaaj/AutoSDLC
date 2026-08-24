"""Tests for GET /integrations/status — read-only aggregation of Bitbucket
and Redmine connection status, no new credential storage."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402

client = TestClient(main.app)


def _clear_bitbucket_env(monkeypatch):
    for key in ("BITBUCKET_WORKSPACE", "BITBUCKET_REPO_SLUG", "BITBUCKET_ACCESS_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def _clear_redmine_env(monkeypatch):
    for key in ("REDMINE_URL", "REDMINE_API_KEY", "REDMINE_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)


def test_both_unconfigured(monkeypatch):
    _clear_bitbucket_env(monkeypatch)
    _clear_redmine_env(monkeypatch)
    response = client.get("/integrations/status")
    assert response.status_code == 200
    body = response.json()
    assert body["bitbucket"]["connected"] is False
    assert body["redmine"]["connected"] is False


def test_both_configured(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "acme")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "widgets")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
    monkeypatch.setenv("REDMINE_API_KEY", "key")
    monkeypatch.setenv("REDMINE_PROJECT_ID", "1")

    response = client.get("/integrations/status")
    body = response.json()
    assert body["bitbucket"]["connected"] is True
    assert body["bitbucket"]["workspace"] == "acme"
    assert body["redmine"]["connected"] is True
    assert body["redmine"]["project_id"] == "1"


def test_one_configured_one_not(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "acme")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "widgets")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    _clear_redmine_env(monkeypatch)

    body = client.get("/integrations/status").json()
    assert body["bitbucket"]["connected"] is True
    assert body["redmine"]["connected"] is False
