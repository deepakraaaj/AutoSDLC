"""Unit tests for bitbucket/client.py's read-only functions. Follows
tests/test_redmine_client_assistant_helpers.py's convention: monkeypatch
httpx.get directly with a minimal fake response instead of a real network call."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bitbucket.client as bb  # noqa: E402


class FakeResponse:
    def __init__(self, json_data=None, text_data="", is_error=False, status_code=None):
        self._json_data = json_data
        self._text_data = text_data
        self.is_error = is_error
        self.status_code = status_code or (422 if is_error else 200)
        self.text = text_data or (json.dumps(json_data) if json_data is not None else "")

    def json(self):
        return self._json_data


def _config():
    return bb.BitbucketConfig(
        base_url="https://api.bitbucket.org/2.0",
        workspace="acme",
        repo_slug="widgets",
        access_token="tok",
    )


def test_get_repo_metadata_returns_json(monkeypatch):
    monkeypatch.setattr(bb.httpx, "get", lambda *a, **kw: FakeResponse({"full_name": "acme/widgets"}))
    assert bb.get_repo_metadata(_config()) == {"full_name": "acme/widgets"}


def test_get_repo_metadata_raises_on_http_error(monkeypatch):
    import pytest
    monkeypatch.setattr(bb.httpx, "get", lambda *a, **kw: FakeResponse({"error": {"message": "nope"}}, is_error=True))
    with pytest.raises(RuntimeError, match="nope"):
        bb.get_repo_metadata(_config())


def test_list_repo_files_follows_pagination(monkeypatch):
    pages = [
        FakeResponse({"values": [{"path": "a.py", "type": "commit_file"}], "next": "https://api.bitbucket.org/2.0/next"}),
        FakeResponse({"values": [{"path": "b.py", "type": "commit_file"}]}),
    ]
    calls = {"n": 0}

    def fake_get(*a, **kw):
        response = pages[calls["n"]]
        calls["n"] += 1
        return response

    monkeypatch.setattr(bb.httpx, "get", fake_get)
    entries = bb.list_repo_files(_config())
    assert [e["path"] for e in entries] == ["a.py", "b.py"]


def test_get_file_content_truncates_large_files(monkeypatch):
    big_text = "x" * (bb.MAX_FILE_BYTES + 1000)
    monkeypatch.setattr(bb.httpx, "get", lambda *a, **kw: FakeResponse(text_data=big_text))
    content = bb.get_file_content(_config(), "big.txt")
    assert content.endswith("[truncated]")
    assert len(content.encode("utf-8")) <= bb.MAX_FILE_BYTES + len("\n\n… [truncated]".encode("utf-8"))


def test_get_pull_request_diff_returns_raw_text(monkeypatch):
    monkeypatch.setattr(bb.httpx, "get", lambda *a, **kw: FakeResponse(text_data="diff --git a/x b/x"))
    assert bb.get_pull_request_diff(_config(), 42) == "diff --git a/x b/x"


def test_build_repo_context_block_returns_empty_when_not_configured():
    unconfigured = bb.BitbucketConfig(base_url="", workspace="", repo_slug="", access_token="")
    assert bb.build_repo_context_block(unconfigured) == ""


def test_build_repo_context_block_degrades_to_empty_on_failure(monkeypatch):
    def raise_error(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(bb.httpx, "get", raise_error)
    assert bb.build_repo_context_block(_config()) == ""


def test_build_repo_context_block_lists_files(monkeypatch):
    monkeypatch.setattr(
        bb.httpx, "get",
        lambda *a, **kw: FakeResponse({"values": [
            {"path": "app/main.py", "type": "commit_file"},
            {"path": "app/", "type": "commit_directory"},
        ]}),
    )
    block = bb.build_repo_context_block(_config())
    assert "app/main.py" in block
    assert "Repository Context" in block
