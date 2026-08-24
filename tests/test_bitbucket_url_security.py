"""Mirrors tests/test_redmine_url_security.py exactly — bitbucket/client.py's
validate_bitbucket_url is a near-verbatim copy of validate_redmine_url."""
from pathlib import Path
import socket
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from bitbucket.client import validate_bitbucket_url  # noqa: E402


client = TestClient(main.app)


def _dns(address: str):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0) if ":" in address else (address, 443))]


def test_rejects_non_http_and_embedded_credentials():
    with pytest.raises(ValueError, match="http"):
        validate_bitbucket_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="embedded credentials"):
        validate_bitbucket_url("https://user:secret@bitbucket.example.test")


def test_production_rejects_private_and_loopback_destinations(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOW_PRIVATE_BITBUCKET_URLS", raising=False)
    for address in ("127.0.0.1", "10.20.30.40", "169.254.169.254", "::1"):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args, _address=address, **kwargs: _dns(_address))
        with pytest.raises(ValueError, match="private or restricted"):
            validate_bitbucket_url("https://bitbucket.example.test")


def test_production_accepts_public_https_and_normalizes(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOW_PRIVATE_BITBUCKET_URLS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("93.184.216.34"))
    assert validate_bitbucket_url("https://api.bitbucket.org/2.0/") == "https://api.bitbucket.org/2.0"


def test_development_allows_private_destinations(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("ALLOW_PRIVATE_BITBUCKET_URLS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("127.0.0.1"))
    assert validate_bitbucket_url("http://localhost:7990/") == "http://localhost:7990"


def test_bitbucket_repo_endpoint_reports_not_configured_when_env_unset(monkeypatch):
    # Always 200 with a {configured, error} envelope — same graceful-degradation
    # shape used everywhere Bitbucket config is optional — not an HTTP error. The frontend's
    # BitbucketModal reads `configured` to decide whether to enable push/review,
    # and that check needs to be reachable on a normal 200 response.
    for key in ("BITBUCKET_WORKSPACE", "BITBUCKET_REPO_SLUG", "BITBUCKET_ACCESS_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    response = client.get("/bitbucket/repo")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "not configured" in body["error"]


def test_bitbucket_repo_endpoint_reports_configured_on_success(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_WORKSPACE", "acme")
    monkeypatch.setenv("BITBUCKET_REPO_SLUG", "widgets")
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("104.192.141.1"))
    monkeypatch.setattr(
        "app.api.bitbucket.get_repo_metadata",
        lambda config: {"full_name": "acme/widgets"},
    )
    response = client.get("/bitbucket/repo")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["full_name"] == "acme/widgets"
    assert body["workspace"] == "acme"
