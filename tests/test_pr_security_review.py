"""Tests for run_pr_security_review (app/services/langgraph_pipeline.py) —
same stubbing style as tests/test_security_scan_job.py's StubSecurityProvider,
no external LLM API keys required."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.langgraph_pipeline import run_pr_security_review  # noqa: E402


class StubPRSecurityProvider:
    def __init__(self, raw_response=None, raise_error=None):
        self.calls = []
        self._raw_response = raw_response
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return self._raw_response


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


_GOOD_FINDING = {
    "title": "Existing vulnerable retrieval newly exposed",
    "severity": "high",
    "confidence": "high",
    "changed_file": "controller.py",
    "changed_symbol": "UserController.get_user",
    "related_files": ["service.py", "repository.py"],
    "related_symbols": ["UserService.get_user", "UserRepository.find_by_id"],
    "execution_or_security_path": "UserController.get_user -> UserService.get_user -> UserRepository.find_by_id",
    "reason_for_pr_relevance": "The PR adds a new route that reaches an existing unvalidated retrieval path.",
    "security_impact": "Any authenticated user can retrieve another user's record by id.",
    "recommendation": "Enforce ownership validation before retrieval.",
}


def test_yields_structured_finding_and_done():
    provider = StubPRSecurityProvider(raw_response=json.dumps([_GOOD_FINDING]))
    events = _events(run_pr_security_review("PR context text", provider))

    finding_events = [e for e in events if e["type"] == "finding"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(finding_events) == 1
    finding = finding_events[0]["finding"]
    assert finding["source"] == "llm_pr_review"
    assert finding["severity"] == "high"
    assert finding["confidence"] == "high"
    assert finding["file"] == "controller.py"
    assert finding["symbol"] == "UserController.get_user"
    assert finding["related_files"] == ["service.py", "repository.py"]
    assert "ownership validation" in finding["recommendation"]
    assert len(done_events) == 1
    assert done_events[0]["findings"] == [finding]


def test_context_is_sent_to_the_provider_unmodified():
    provider = StubPRSecurityProvider(raw_response="[]")
    list(run_pr_security_review("## Pull Request #7\nsome curated context", provider))

    assert len(provider.calls) == 1
    system_prompt, user_message = provider.calls[0]
    assert "PR" in system_prompt or "pull request" in system_prompt.lower()
    assert "Pull Request #7" in user_message


def test_finding_with_no_evidence_is_downgraded_to_low_confidence():
    weak_finding = {**_GOOD_FINDING, "confidence": "high", "reason_for_pr_relevance": ""}
    provider = StubPRSecurityProvider(raw_response=json.dumps([weak_finding]))
    events = _events(run_pr_security_review("ctx", provider))

    finding = next(e for e in events if e["type"] == "finding")["finding"]
    assert finding["confidence"] == "low"


def test_malformed_model_response_yields_no_findings_not_a_crash():
    provider = StubPRSecurityProvider(raw_response="not valid json at all")
    events = _events(run_pr_security_review("ctx", provider))

    assert not any(e["type"] == "error" for e in events)
    done_events = [e for e in events if e["type"] == "done"]
    assert done_events[0]["findings"] == []


def test_provider_failure_yields_error_event_not_a_crash():
    provider = StubPRSecurityProvider(raise_error=RuntimeError("provider timed out"))
    events = _events(run_pr_security_review("ctx", provider))

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert "provider timed out" in error_events[0]["error"]["message"] or "PR security review failed" in error_events[0]["error"]["message"]
    assert not any(e["type"] == "done" for e in events)


def test_summary_object_shape_is_parsed_and_yielded_in_done():
    payload = {"summary": "This PR adds the Kritilabs logo to the landing page. No security-relevant behavior changed.", "findings": []}
    provider = StubPRSecurityProvider(raw_response=json.dumps(payload))
    events = _events(run_pr_security_review("ctx", provider))

    done = next(e for e in events if e["type"] == "done")
    assert done["summary"] == payload["summary"]
    assert done["findings"] == []
    assert not any(e["type"] == "finding" for e in events)


def test_bare_array_response_still_works_with_empty_summary():
    """Backward-compat fallback: a model that ignores the object shape and
    returns a bare findings array still yields usable findings, just with
    no summary — same tolerance _parse_code_review_response has."""
    provider = StubPRSecurityProvider(raw_response=json.dumps([_GOOD_FINDING]))
    events = _events(run_pr_security_review("ctx", provider))

    done = next(e for e in events if e["type"] == "done")
    assert done["summary"] == ""
    assert len(done["findings"]) == 1


def test_invalid_severity_and_confidence_values_are_normalized():
    bad_finding = {**_GOOD_FINDING, "severity": "catastrophic", "confidence": "very sure"}
    provider = StubPRSecurityProvider(raw_response=json.dumps([bad_finding]))
    events = _events(run_pr_security_review("ctx", provider))

    finding = next(e for e in events if e["type"] == "finding")["finding"]
    assert finding["severity"] == "medium"
    assert finding["confidence"] == "low"
