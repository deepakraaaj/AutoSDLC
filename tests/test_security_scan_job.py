"""Tests for app/services/langgraph_pipeline.py's run_security_review — the
VAPT Phase 1 agent. Same stubbing style as tests/test_code_review_job.py's
StubReviewProvider, since this is the other call site that goes through
AutoSDLCChatModel/LangChain rather than PhaseGenerator's plain generate()."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.langgraph_pipeline import run_security_review  # noqa: E402


class StubSecurityProvider:
    def __init__(self, findings=None, raise_error=None):
        self.calls = []
        self._findings = findings if findings is not None else [
            {"file": "app/auth.py", "line": 20, "category": "auth", "severity": "high", "comment": "Missing auth check.", "recommendation": "Require login."},
        ]
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return json.dumps(self._findings)


def _events(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_run_security_review_yields_findings_and_done():
    provider = StubSecurityProvider()
    events = _events(run_security_review(1, "fits-service", "src/auth.py\n  def login(): ...", provider))

    finding_events = [e for e in events if e["type"] == "finding"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(finding_events) == 1
    assert finding_events[0]["finding"]["category"] == "auth"
    assert len(done_events) == 1
    assert done_events[0]["repo_id"] == 1
    assert done_events[0]["repo_label"] == "fits-service"


def test_run_security_review_sends_repo_context_to_the_provider():
    provider = StubSecurityProvider()
    list(run_security_review(1, "fits-service", "src/auth.py has a TODO", provider))

    assert len(provider.calls) == 1
    _, user_message = provider.calls[0]
    assert "fits-service" in user_message
    assert "src/auth.py has a TODO" in user_message


def test_run_security_review_handles_empty_findings():
    provider = StubSecurityProvider(findings=[])
    events = _events(run_security_review(1, "fits-service", "", provider))
    assert [e for e in events if e["type"] == "finding"] == []
    assert [e for e in events if e["type"] == "done"][0]["findings"] == []


def test_run_security_review_reports_error_on_provider_failure():
    provider = StubSecurityProvider(raise_error=RuntimeError("provider down"))
    events = _events(run_security_review(1, "fits-service", "", provider))
    assert any(e["type"] == "error" for e in events)
