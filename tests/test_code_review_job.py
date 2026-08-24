"""Tests for app/services/langgraph_pipeline.py's run_code_review — the
Phase 3 code-review agent. Uses a minimal stub provider (not
tests/fake_provider.py's FakeProvider, which doesn't recognize the code
review system prompt) since this is the one call site that goes through
AutoSDLCChatModel/LangChain rather than PhaseGenerator's plain generate()."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.langgraph_pipeline import run_code_review  # noqa: E402
from app.services.prompt import build_code_review_message  # noqa: E402


class StubReviewProvider:
    """A minimal AIProvider — generate() returns a fixed {"summary", "findings"}
    JSON object (CODE_REVIEW_SYSTEM's contract) regardless of prompt content,
    letting the test assert on the SSE events run_code_review produces
    rather than on prompt formatting."""

    def __init__(self, findings=None, summary="Added a null check.", raise_error=None):
        self.calls = []
        self._findings = findings if findings is not None else [
            {"file": "app/main.py", "line": 12, "severity": "important", "comment": "Missing null check."},
        ]
        self._summary = summary
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return json.dumps({"summary": self._summary, "findings": self._findings})


SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index 111..222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -10,3 +10,4 @@
+    value = maybe_none.attr
"""


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_run_code_review_yields_findings_and_done():
    provider = StubReviewProvider()
    events = _events(run_code_review("acme/widgets", 42, SAMPLE_DIFF, provider))

    finding_events = [e for e in events if e["type"] == "finding"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(finding_events) == 1
    assert finding_events[0]["finding"]["file"] == "app/main.py"
    assert len(done_events) == 1
    assert done_events[0]["pr_id"] == 42
    assert done_events[0]["repo_full_name"] == "acme/widgets"
    assert done_events[0]["summary"] == "Added a null check."


def test_run_code_review_sends_the_diff_to_the_provider():
    provider = StubReviewProvider()
    list(run_code_review("acme/widgets", 42, SAMPLE_DIFF, provider))

    assert len(provider.calls) == 2
    _, initial_message = provider.calls[0]
    _, verification_message = provider.calls[1]
    assert "maybe_none.attr" in initial_message
    assert "maybe_none.attr" in verification_message
    assert "Draft review to integrity-check" in verification_message


def test_run_code_review_handles_empty_findings():
    provider = StubReviewProvider(findings=[])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    assert [e for e in events if e["type"] == "finding"] == []
    assert [e for e in events if e["type"] == "done"][0]["findings"] == []


def test_run_code_review_reports_error_on_provider_failure():
    provider = StubReviewProvider(raise_error=RuntimeError("provider down"))
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    assert any(e["type"] == "error" for e in events)


class BareArrayReviewProvider:
    """A provider that ignores the {"summary", "findings"} object shape and
    returns the pre-summary bare findings array — what every provider
    returned before CODE_REVIEW_SYSTEM asked for a summary too. The parser
    must still extract findings from this, just with an empty summary,
    rather than losing the whole response."""

    def __init__(self, findings):
        self._findings = findings

    def generate(self, system_prompt: str, user_message: str) -> str:
        return json.dumps(self._findings)


def test_run_code_review_falls_back_to_findings_only_for_bare_array_responses():
    provider = BareArrayReviewProvider([
        {"file": "app/main.py", "line": 1, "severity": "minor", "comment": "nit"},
    ])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    done = [e for e in events if e["type"] == "done"][0]
    assert done["summary"] == ""
    assert done["findings"] == [{"file": "app/main.py", "line": 1, "severity": "minor", "comment": "nit"}]


def test_run_code_review_summary_is_required_even_when_findings_are_empty():
    provider = StubReviewProvider(findings=[], summary="Removed unused imports.")
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    done = [e for e in events if e["type"] == "done"][0]
    assert done["summary"] == "Removed unused imports."
    assert done["findings"] == []


def test_run_code_review_reports_which_files_it_looked_at():
    """The 'done' event's files_reviewed is what a clean review shows in
    place of findings — "checked these N files, nothing flagged" instead of
    a bare 'Reviewed' badge with no substance behind it."""
    provider = StubReviewProvider(findings=[])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    done = [e for e in events if e["type"] == "done"][0]
    assert done["files_reviewed"] == ["app/main.py"]


MULTI_FILE_DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old
+new
diff --git a/removed.py b/removed.py
deleted file mode 100644
--- a/removed.py
+++ /dev/null
@@ -1,1 +0,0 @@
-gone
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -5,1 +5,1 @@
-old2
+new2
"""


def test_build_code_review_message_keeps_a_real_pr_diff_intact():
    """Regression test: the old 16000-char cap truncated a real, observed
    26KB PR diff by ~40% — reviewing an incomplete diff and never saying
    so. 60000 chars covers it whole."""
    diff = "x" * 26148
    message = build_code_review_message(diff)
    assert "x" * 26148 in message
    assert "truncated" not in message


def test_build_code_review_message_truncates_and_says_so_past_the_cap():
    diff = "x" * 70000
    message = build_code_review_message(diff)
    assert len(message) < len(diff)  # actually truncated, not just decorated
    assert "truncated" in message


def test_run_code_review_dedupes_files_touched_more_than_once():
    """a.py appears in two separate hunks (non-contiguous changes to the
    same file are split into multiple diff sections) — files_reviewed lists
    it once. A deleted file (+++ /dev/null) reports its old path."""
    provider = StubReviewProvider(findings=[])
    events = _events(run_code_review("acme/widgets", 1, MULTI_FILE_DIFF, provider))
    done = [e for e in events if e["type"] == "done"][0]
    assert done["files_reviewed"] == ["a.py", "removed.py"]
