"""Tests for app/services/code_review_graph.py's internal graph structure —
things tests/test_code_review_job.py's black-box SSE-event tests don't
exercise directly: the review -> verify conditional edge actually skipping
the verify LLM call when there are no findings, verify's result overriding
review's draft, and CodeReviewResult/PydanticOutputParser degrading a
malformed response to ("", []) instead of raising. test_code_review_job.py
already covers output-shape parity (findings, empty findings, errors,
context factors, file dedup) against the same run_code_review entry point;
this file is about the graph mechanics underneath it."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.code_review_graph import (  # noqa: E402
    CodeReviewResult,
    _parse_code_review_response,
    run_code_review,
)

SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
--- a/app/main.py
+++ b/app/main.py
@@ -10,3 +10,4 @@
+    value = maybe_none.attr
"""


class ScriptedProvider:
    """Returns one scripted response per call, in order — lets a test tell
    review and verify apart by what each call returns, and count calls to
    prove verify was (or wasn't) invoked at all."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self.responses[len(self.calls) - 1]


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_verify_node_is_skipped_when_review_finds_nothing():
    """The conditional edge (_route_after_review) must route review -> filter
    directly when there are no findings, not review -> verify -> filter —
    only one LLM call should happen at all."""
    provider = ScriptedProvider([json.dumps({"summary": "No issues.", "findings": []})])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))

    assert len(provider.calls) == 1
    done = [e for e in events if e["type"] == "done"][0]
    assert done["integrity_check"] == "no_findings_to_verify"


def test_verify_node_runs_and_overrides_findings_when_review_finds_something():
    """When review produces findings, verify must actually run (2 calls)
    and its output — not review's draft — is what reaches the caller."""
    review_response = json.dumps({
        "summary": "Draft summary.",
        "findings": [
            {"file": "app/main.py", "line": 12, "severity": "important", "comment": "no null check", "verification": "risk"},
            {"file": "app/main.py", "line": 20, "severity": "minor", "comment": "unrelated nit", "verification": "risk"},
        ],
    })
    # Verify drops the second finding and confirms the first — proves the
    # caller sees verify's output, not review's.
    verify_response = json.dumps({
        "summary": "Verified summary.",
        "findings": [
            {"file": "app/main.py", "line": 12, "severity": "important", "comment": "no null check", "verification": "confirmed"},
        ],
    })
    provider = ScriptedProvider([review_response, verify_response])
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))

    assert len(provider.calls) == 2
    assert "integrity-check pass" in provider.calls[1][0]
    done = [e for e in events if e["type"] == "done"][0]
    assert done["summary"] == "Verified summary."
    assert done["integrity_check"] == "second_pass"
    assert len(done["findings"]) == 1
    assert done["findings"][0]["verification"] == "confirmed"


def test_verify_node_failure_keeps_review_draft_instead_of_erroring():
    """A verify call that raises must not discard an otherwise-good draft
    review — the request should still complete with review's findings,
    just flagged as unverified rather than failed outright."""
    review_response = json.dumps({
        "summary": "Draft summary.",
        "findings": [{"file": "app/main.py", "line": 12, "severity": "important", "comment": "no null check"}],
    })

    class FlakyVerifyProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt, user_message):
            self.calls += 1
            if "integrity-check pass" in system_prompt:
                raise RuntimeError("verify provider timed out")
            return review_response

    provider = FlakyVerifyProvider()
    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, provider))

    done = [e for e in events if e["type"] == "done"][0]
    assert not any(e["type"] == "error" for e in events)
    assert done["integrity_check"] == "no_findings_to_verify"  # integrity_checked=False on verify failure
    assert done["summary"] == "Draft summary."
    assert len(done["findings"]) == 1


def test_all_providers_exhausted_still_reports_error_event():
    """Same AllProvidersExhaustedError handling as the plain-function
    version had — the graph's review node must still surface this as an
    'error' SSE event, not let it propagate out of run_code_review."""
    from app.services.providers import AllProvidersExhaustedError

    class ExhaustedProvider:
        def generate(self, system_prompt, user_message):
            raise AllProvidersExhaustedError("all providers exhausted")

    events = _events(run_code_review("acme/widgets", 1, SAMPLE_DIFF, ExhaustedProvider()))
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert "exhausted" in error_events[0]["error"]["message"].lower()


def test_parse_code_review_response_validates_against_schema():
    summary, findings = _parse_code_review_response(json.dumps({
        "summary": "Adds logging.",
        "findings": [{"file": "a.py", "line": 3, "severity": "blocking", "comment": "leaks a secret", "verification": "confirmed", "evidence": "line 3"}],
    }))
    assert summary == "Adds logging."
    assert findings == [{"file": "a.py", "line": 3, "severity": "blocking", "comment": "leaks a secret", "verification": "confirmed", "evidence": "line 3"}]


def test_parse_code_review_response_degrades_on_malformed_json():
    """Not valid JSON at all — must degrade to ("", []), never raise."""
    summary, findings = _parse_code_review_response("this is not json output from a confused model")
    assert (summary, findings) == ("", [])


def test_parse_code_review_response_accepts_bare_array_legacy_shape():
    """A model that ignores the object shape and returns a bare findings
    array (the pre-summary contract) still yields usable findings."""
    summary, findings = _parse_code_review_response(json.dumps([
        {"file": "a.py", "line": 1, "severity": "minor", "comment": "nit"},
    ]))
    assert summary == ""
    assert findings == [{"file": "a.py", "line": 1, "severity": "minor", "comment": "nit"}]


def test_code_review_result_schema_defaults_are_safe():
    """A finding missing optional fields (line, severity, ...) should still
    validate — the schema shouldn't be stricter than the prompt's contract,
    which only requires 'file' in practice."""
    result = CodeReviewResult.model_validate({"summary": "", "findings": [{"file": "a.py"}]})
    assert result.findings[0].file == "a.py"
    assert result.findings[0].line is None
    assert result.findings[0].severity == "minor"
