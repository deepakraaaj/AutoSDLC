"""Unit tests for bitbucket/client.py's read-only functions. Follows
tests/test_redmine_client_assistant_helpers.py's convention: monkeypatch the
module's pooled httpx.Client (bb._client).get/.post directly with a minimal
fake response instead of a real network call."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bitbucket.client as bb  # noqa: E402


class FakeResponse:
    def __init__(self, json_data=None, text_data="", is_error=False, status_code=None, headers=None):
        self._json_data = json_data
        self._text_data = text_data
        self.is_error = is_error
        self.status_code = status_code or (422 if is_error else 200)
        self.headers = headers or {}
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
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: FakeResponse({"full_name": "acme/widgets"}))
    assert bb.get_repo_metadata(_config()) == {"full_name": "acme/widgets"}


def test_list_pull_requests_defaults_to_open_merged_declined(monkeypatch):
    """Not just OPEN — the Pull Requests view shows history, so the default
    request covers everything but the rare SUPERSEDED state."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None, follow_redirects=None):
        calls.append(params)
        return FakeResponse({"values": [{"id": 1}]})

    monkeypatch.setattr(bb._client, "get", fake_get)
    result = bb.list_pull_requests(_config())
    assert result == [{"id": 1}]
    assert calls[0]["state"] == ["OPEN", "MERGED", "DECLINED"]
    # Regression: bumping this to 100 (to match list_repo_files/
    # list_pull_request_comments) was tried for real and Bitbucket rejected
    # it live with a 400 "Invalid pagelen" — this endpoint's cap is lower
    # than those two.
    assert calls[0]["pagelen"] == 50


def test_list_pull_requests_accepts_explicit_states(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None, follow_redirects=None):
        calls.append(params)
        return FakeResponse({"values": []})

    monkeypatch.setattr(bb._client, "get", fake_get)
    bb.list_pull_requests(_config(), states=["MERGED"])
    assert calls[0]["state"] == ["MERGED"]


def test_list_pull_requests_retries_rate_limit_using_retry_after(monkeypatch):
    responses = iter([
        FakeResponse({"error": {"message": "rate limited"}}, is_error=True, status_code=429, headers={"Retry-After": "2"}),
        FakeResponse({"values": [{"id": 7}]}),
    ])
    sleeps = []
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: next(responses))
    monkeypatch.setattr(bb.time, "sleep", sleeps.append)

    assert bb.list_pull_requests(_config()) == [{"id": 7}]
    assert sleeps == [2.0]


def test_list_pull_requests_dedupes_items_repeated_across_page_boundary(monkeypatch):
    """Reproduces an observed real case: page 1 ends with PR 59, page 2
    starts by repeating it (a Bitbucket pagination quirk, not a bug in our
    request) — the client must not surface it twice."""
    pages = [
        FakeResponse({
            "values": [{"id": 61}, {"id": 60}, {"id": 59}],
            "next": "https://api.bitbucket.org/2.0/repositories/acme/widgets/pullrequests?page=2",
        }),
        FakeResponse({"values": [{"id": 59}, {"id": 37}]}),  # 59 repeated at the boundary
    ]
    calls = iter(pages)
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: next(calls))

    result = bb.list_pull_requests(_config())
    assert [pr["id"] for pr in result] == [61, 60, 59, 37]


def test_get_repo_metadata_raises_on_http_error(monkeypatch):
    import pytest
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: FakeResponse({"error": {"message": "nope"}}, is_error=True))
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

    monkeypatch.setattr(bb._client, "get", fake_get)
    entries = bb.list_repo_files(_config())
    assert [e["path"] for e in entries] == ["a.py", "b.py"]


def test_list_repo_files_at_root_uses_the_requested_ref(monkeypatch):
    """Regression: Bitbucket's API 404s on `/src/{ref}` (no trailing slash,
    empty subpath) even for ref=HEAD, so listing the repo root used to drop
    `ref` entirely rather than add the slash — silently always listing the
    account's default branch regardless of what was asked for."""
    seen_urls = []

    def fake_get(url, *a, **kw):
        seen_urls.append(url)
        return FakeResponse({"values": [{"path": "src", "type": "commit_directory"}]})

    monkeypatch.setattr(bb._client, "get", fake_get)
    bb.list_repo_files(_config(), path="", ref="dev")
    assert seen_urls == ["https://api.bitbucket.org/2.0/repositories/acme/widgets/src/dev/"]


def test_get_file_content_truncates_large_files(monkeypatch):
    big_text = "x" * (bb.MAX_FILE_BYTES + 1000)
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: FakeResponse(text_data=big_text))
    content = bb.get_file_content(_config(), "big.txt")
    assert content.endswith("[truncated]")
    assert len(content.encode("utf-8")) <= bb.MAX_FILE_BYTES + len("\n\n… [truncated]".encode("utf-8"))


def test_get_pull_request_diff_returns_raw_text(monkeypatch):
    monkeypatch.setattr(bb._client, "get", lambda *a, **kw: FakeResponse(text_data="diff --git a/x b/x"))
    assert bb.get_pull_request_diff(_config(), 42) == "diff --git a/x b/x"


def test_get_pull_request_diff_follows_redirects(monkeypatch):
    """Regression test: Bitbucket's /pullrequests/{id}/diff endpoint 302s to
    the actual diff content rather than serving it directly. httpx doesn't
    follow redirects unless told to, so without follow_redirects=True this
    silently returned an empty body — every review ran against nothing, and
    (correctly, given empty input) reported zero findings. Observed for
    real on a 26KB PR diff that came back as 0 bytes before this fix."""
    calls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        calls.append(follow_redirects)
        return FakeResponse(text_data="diff --git a/x b/x")

    monkeypatch.setattr(bb._client, "get", fake_get)
    bb.get_pull_request_diff(_config(), 42)
    assert calls == [True]


def test_all_bitbucket_client_requests_follow_redirects():
    """Broader guard than the one above: every GET/POST in this module
    should follow redirects, not just get_pull_request_diff — Bitbucket's
    redirect-on-diff behavior isn't necessarily unique to that one endpoint,
    and a client that follows redirects inconsistently is a bug waiting to
    resurface somewhere else."""
    import inspect
    source = inspect.getsource(bb)
    get_and_post_calls = source.count("_client.get(") + source.count("_client.post(")
    follow_redirects_uses = source.count("follow_redirects=True")
    assert follow_redirects_uses == get_and_post_calls


def test_build_repo_context_block_returns_empty_when_not_configured():
    unconfigured = bb.BitbucketConfig(base_url="", workspace="", repo_slug="", access_token="")
    assert bb.build_repo_context_block(unconfigured) == ""


def test_build_repo_context_block_degrades_to_empty_on_failure(monkeypatch):
    def raise_error(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(bb._client, "get", raise_error)
    assert bb.build_repo_context_block(_config()) == ""


def test_build_repo_context_block_lists_files(monkeypatch):
    monkeypatch.setattr(
        bb._client, "get",
        lambda *a, **kw: FakeResponse({"values": [
            {"path": "app/main.py", "type": "commit_file"},
            {"path": "app/", "type": "commit_directory"},
        ]}),
    )
    block = bb.build_repo_context_block(_config())
    assert "app/main.py" in block
    assert "Repository Context" in block


def test_build_repo_context_block_includes_high_signal_file_contents(monkeypatch):
    monkeypatch.setattr(bb, "list_repo_files", lambda *a, **kw: [
        {"path": "src/main.ts", "type": "commit_file"},
        {"path": "package.json", "type": "commit_file"},
        {"path": "README.md", "type": "commit_file"},
    ])
    contents = {
        "package.json": '{"dependencies":{"react":"^19"}}',
        "src/main.ts": "createRoot(document.getElementById('root')).render(<App />)",
        "README.md": "This is intentionally gathered separately.",
    }
    monkeypatch.setattr(bb, "get_file_content", lambda config, path, ref="HEAD": contents[path])

    block = bb.build_repo_context_block(_config())

    assert '"react":"^19"' in block
    assert "createRoot" in block
    assert "intentionally gathered separately" not in block


def test_build_repo_context_block_numbers_snippet_lines(monkeypatch):
    """The wiki prompt (app/services/prompt.py) requires a real `path:line`
    citation for every implementation claim, but an unnumbered blob gives
    the model nothing to cite except a line number it has to count out
    itself. Selected file contents must be numbered so the model can quote
    a real line it can see."""
    monkeypatch.setattr(bb, "list_repo_files", lambda *a, **kw: [
        {"path": "src/main.ts", "type": "commit_file"},
    ])
    monkeypatch.setattr(bb, "get_file_content", lambda *a, **kw: "import App\nrender(App)\nexport default App")

    block = bb.build_repo_context_block(_config())

    assert "1: import App" in block
    assert "2: render(App)" in block
    assert "3: export default App" in block


def test_build_repo_context_block_walks_nested_source_and_skips_vendor_dirs(monkeypatch):
    calls = []

    def list_files(config, path="", ref="HEAD"):
        calls.append(path)
        return {
            "": [
                {"path": "src", "type": "commit_directory"},
                {"path": "node_modules", "type": "commit_directory"},
            ],
            "src": [{"path": "src/main.py", "type": "commit_file"}],
        }[path]

    monkeypatch.setattr(bb, "list_repo_files", list_files)
    monkeypatch.setattr(bb, "get_file_content", lambda *a, **kw: "from fastapi import FastAPI")

    block = bb.build_repo_context_block(_config())

    assert calls == ["", "src"]
    assert "src/main.py" in block
    assert "FastAPI" in block


# ── Auth header shape ───────────────────────────────────────────────────
# Three credential types share one access_token field: a Bitbucket-native
# access token (Bearer, no identity), a Bitbucket App Password (Basic,
# username:app-password), and an Atlassian account API token (Basic,
# email:token) — see BitbucketConfig's docstring. `identity` set is what
# selects Basic over Bearer; Basic auth doesn't care whether it's a
# username or an email.

def test_headers_use_bearer_without_identity(monkeypatch):
    # _config() doesn't pass identity=, so it falls through to
    # os.getenv(BITBUCKET_USERNAME/BITBUCKET_EMAIL) — clear both so a real
    # .env with either set can't leak into this assertion.
    monkeypatch.delenv("BITBUCKET_USERNAME", raising=False)
    monkeypatch.delenv("BITBUCKET_EMAIL", raising=False)
    config = _config()
    assert config._headers() == {"Authorization": "Bearer tok"}


def test_headers_use_basic_auth_when_identity_set():
    import base64
    config = bb.BitbucketConfig(
        base_url="https://api.bitbucket.org/2.0", workspace="acme", repo_slug="widgets",
        access_token="app-password", identity="bitbucket-username",
    )
    expected = base64.b64encode(b"bitbucket-username:app-password").decode()
    assert config._headers() == {"Authorization": f"Basic {expected}"}
