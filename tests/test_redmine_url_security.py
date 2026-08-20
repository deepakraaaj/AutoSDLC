from pathlib import Path
import socket
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from redmine.client import validate_redmine_url  # noqa: E402


client = TestClient(main.app)


def _dns(address: str):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0) if ":" in address else (address, 443))]


def test_rejects_non_http_and_embedded_credentials():
    with pytest.raises(ValueError, match="http"):
        validate_redmine_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="embedded credentials"):
        validate_redmine_url("https://user:secret@redmine.example.test")


def test_production_rejects_private_and_loopback_destinations(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOW_PRIVATE_REDMINE_URLS", raising=False)
    for address in ("127.0.0.1", "10.20.30.40", "169.254.169.254", "::1"):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args, _address=address, **kwargs: _dns(_address))
        with pytest.raises(ValueError, match="private or restricted"):
            validate_redmine_url("https://redmine.example.test")


def test_production_accepts_public_https_and_normalizes(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOW_PRIVATE_REDMINE_URLS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("93.184.216.34"))
    assert validate_redmine_url("https://redmine.example.test/base/") == "https://redmine.example.test/base"


def test_development_explicitly_supports_bundled_local_redmine(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("ALLOW_PRIVATE_REDMINE_URLS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("127.0.0.1"))
    assert validate_redmine_url("http://localhost:3001/") == "http://localhost:3001"


def test_redmine_endpoint_rejects_invalid_url_before_network_call():
    response = client.post("/redmine/projects/list", json={
        "redmine_url": "file:///etc/passwd",
        "redmine_api_key": "secret",
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
