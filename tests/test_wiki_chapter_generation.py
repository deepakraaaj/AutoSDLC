"""Tests for Pass 1 chapter generation (app/services/wiki_generator.py's
generate_chapter_wiki/_parse_chapter_response/_chapter_sections/
_filter_grounded_chapter) — reuses the exact same grounding-validation
machinery the flat wiki uses (tests/test_project_wiki.py), so these tests
focus on the leaf-vs-sub_chapters shape branching that's new here."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.wiki_generator import (  # noqa: E402
    WikiGenerationError,
    _chapter_sections,
    _filter_grounded_chapter,
    _parse_chapter_response,
    generate_chapter_wiki,
)


class _StubChapterProvider:
    """Same generate(system_prompt, user_message)->str contract as
    tests/test_project_wiki.py's StubWikiProvider — generate_chapter_wiki
    wraps `provider` in the same AutoSDLCChatModel adapter."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self._responses[len(self.calls) - 1]


# ── _parse_chapter_response ──────────────────────────────────────────────

def test_parse_chapter_response_leaf_shape():
    raw = json.dumps({
        "title": "Facility management", "summary": "Manages facilities.",
        "sections": [{"heading": "Overview", "body": "Facilities are tracked.", "evidence": ["src/Facility.tsx:10"]}],
    })
    parsed = _parse_chapter_response(raw)
    assert "sub_chapters" not in parsed
    assert parsed["sections"][0]["evidence"] == ["src/Facility.tsx:10"]


def test_parse_chapter_response_sub_chapters_shape():
    raw = json.dumps({
        "title": "Operations", "summary": "Covers ops.",
        "sub_chapters": [
            {"title": "Scheduling", "summary": "S.", "sections": [{"heading": "H", "body": "B", "evidence": ["a.py:1"]}]},
            {"title": "Tasks", "summary": "T.", "sections": [{"heading": "H2", "body": "B2", "evidence": ["b.py:2"]}]},
        ],
    })
    parsed = _parse_chapter_response(raw)
    assert len(parsed["sub_chapters"]) == 2
    assert parsed["sub_chapters"][0]["title"] == "Scheduling"


def test_parse_chapter_response_requires_sections_or_sub_chapters():
    raw = json.dumps({"title": "T", "summary": "S"})
    with pytest.raises(WikiGenerationError):
        _parse_chapter_response(raw)


def test_parse_chapter_response_rejects_malformed_json():
    with pytest.raises(WikiGenerationError):
        _parse_chapter_response("not json")


# ── _chapter_sections / _filter_grounded_chapter ─────────────────────────

def test_chapter_sections_flattens_sub_chapters():
    parsed = {
        "sub_chapters": [
            {"sections": [{"heading": "A", "body": "a", "evidence": ["x:1"]}]},
            {"sections": [{"heading": "B", "body": "b", "evidence": ["y:2"]}]},
        ],
    }
    sections = _chapter_sections(parsed)
    assert [s["heading"] for s in sections] == ["A", "B"]


def test_filter_grounded_chapter_drops_ungrounded_sub_chapter_but_keeps_grounded_one():
    source_material = "Evidence: x.py:1."
    parsed = {
        "title": "T", "summary": "S",
        "sub_chapters": [
            {"title": "Good", "summary": "", "sections": [{"heading": "A", "body": "a", "evidence": ["x.py:1"]}]},
            {"title": "Bad", "summary": "", "sections": [{"heading": "B", "body": "b", "evidence": []}]},
        ],
    }
    filtered = _filter_grounded_chapter(parsed, source_material)
    assert len(filtered["sub_chapters"]) == 1
    assert filtered["sub_chapters"][0]["title"] == "Good"


# ── generate_chapter_wiki (full flow through the stub provider) ─────────

def test_generate_chapter_wiki_leaf_succeeds_first_try():
    provider = _StubChapterProvider([json.dumps({
        "title": "Facilities", "summary": "Facility management.",
        "sections": [{"heading": "Overview", "body": "Facilities are tracked here.", "evidence": ["src/Facility.tsx:10"]}],
    })])
    page = generate_chapter_wiki(provider, "REMP", "UI", "Evidence: src/Facility.tsx:10.", 0)
    assert page["title"] == "Facilities"
    assert page["sections"][0]["evidence"] == ["src/Facility.tsx:10"]
    assert len(provider.calls) == 1


def test_generate_chapter_wiki_sub_chapters_succeeds_first_try():
    provider = _StubChapterProvider([json.dumps({
        "title": "Operations", "summary": "Ops.",
        "sub_chapters": [
            {"title": "Scheduling", "summary": "S.", "sections": [{"heading": "H", "body": "B", "evidence": ["a.py:1"]}]},
        ],
    })])
    page = generate_chapter_wiki(provider, "REMP", "backend", "Evidence: a.py:1.", 1)
    assert page["sub_chapters"][0]["title"] == "Scheduling"


def test_generate_chapter_wiki_repairs_ungrounded_response():
    """First response has no evidence (grounding violation); repair call
    fixes it — matches the flat pipeline's one-repair-attempt pattern."""
    bad = json.dumps({
        "title": "Facilities", "summary": "S.",
        "sections": [{"heading": "Overview", "body": "Facilities are tracked.", "evidence": []}],
    })
    good = json.dumps({
        "title": "Facilities", "summary": "S.",
        "sections": [{"heading": "Overview", "body": "Facilities are tracked.", "evidence": ["src/Facility.tsx:10"]}],
    })
    provider = _StubChapterProvider([bad, good])
    page = generate_chapter_wiki(provider, "REMP", "UI", "Evidence: src/Facility.tsx:10.", 0)
    assert page["sections"][0]["evidence"] == ["src/Facility.tsx:10"]
    assert len(provider.calls) == 2


def test_generate_chapter_wiki_raises_when_nothing_grounds_after_repair():
    bad = json.dumps({
        "title": "Facilities", "summary": "S.",
        "sections": [{"heading": "Overview", "body": "Facilities are tracked.", "evidence": []}],
    })
    provider = _StubChapterProvider([bad, bad])
    with pytest.raises(WikiGenerationError):
        generate_chapter_wiki(provider, "REMP", "UI", "Evidence: src/Facility.tsx:10.", 0)
