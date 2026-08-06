"""Regression test for a real bug found in this repo: GenerateRequest accepted
clarification_answers, but _stream_generate silently dropped it before
calling the 4-phase pipeline — Phase 1 never actually saw the answers. Fixed
in main.py by folding them into the brief text before generation; this test
would fail against the old code."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fake_provider import FakeProvider  # noqa: E402
import main  # noqa: E402


def test_clarification_answers_reach_the_epic_generation_prompt(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)
    # Avoid touching the real database from this test.
    monkeypatch.setattr(main, "save_generation", lambda text, output: 1)
    monkeypatch.setattr(main, "save_generation_normalized", lambda gen_id, output: {})

    answers = {"Who is the target user?": "Freelance graphic designers"}
    list(main._stream_generate("Build a portfolio site.", answers))

    epic_call = next(c for c in provider.calls if "decomposing a project brief into epics" in c[0])
    _, user_message = epic_call
    assert "Freelance graphic designers" in user_message
    assert "Clarifications:" in user_message


def test_no_clarification_answers_means_unmodified_brief(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)
    monkeypatch.setattr(main, "save_generation", lambda text, output: 1)
    monkeypatch.setattr(main, "save_generation_normalized", lambda gen_id, output: {})

    list(main._stream_generate("Build a portfolio site.", {}))

    epic_call = next(c for c in provider.calls if "decomposing a project brief into epics" in c[0])
    _, user_message = epic_call
    assert "Clarifications:" not in user_message
