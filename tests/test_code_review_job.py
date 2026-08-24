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


class StubReviewProvider:
    """A minimal AIProvider — generate() returns a fixed findings JSON array
    regardless of prompt content, letting the test assert on the SSE events
    run_code_review produces rather than on prompt formatting."""

    def __init__(self, findings=None, raise_error=None):
        self.calls = []
        self._findings = findings if findings is not None else [
            {"file": "app/main.py", "line": 12, "severity": "important", "comment": "Missing null check."},
        ]
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return json.dumps(self._findings)


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


def test_run_code_review_sends_the_diff_to_the_provider():
    provider = StubReviewProvider()
    list(run_code_review("acme/widgets", 42, SAMPLE_DIFF, provider))

    assert len(provider.calls) == 1
    _, user_message = provider.calls[0]
    assert "maybe_none.attr" in user_message


def test_run_code_review_handles_empty_findings():
    provider = StubReviewProvider(findings=[])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    assert [e for e in events if e["type"] == "finding"] == []
    assert [e for e in events if e["type"] == "done"][0]["findings"] == []


def test_run_code_review_reports_error_on_provider_failure():
    provider = StubReviewProvider(raise_error=RuntimeError("provider down"))
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))
    assert any(e["type"] == "error" for e in events)
