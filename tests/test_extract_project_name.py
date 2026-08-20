"""Tests for app.services.database.extract_project_name — a pure string function, so
these need no DB/fixtures. Regression for the reported bug: the standard brief
template's "# Project: <Name>" heading was showing up verbatim (literal "Project:"
label and all) everywhere this name is displayed to users — History list, History
detail, and the Backlog page header (see App.tsx's pageTitle)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.database import extract_project_name  # noqa: E402


def test_strips_project_label_from_the_standard_brief_template_heading():
    text = "# Project: Corporate Card Reconciliation Platform\n\n## Executive Summary\n..."
    assert extract_project_name(text) == "Corporate Card Reconciliation Platform"


def test_strips_project_label_case_insensitively_and_regardless_of_spacing():
    assert extract_project_name("project:Tight Spacing") == "Tight Spacing"
    assert extract_project_name("PROJECT :   Extra Spacing") == "Extra Spacing"


def test_leaves_a_plain_markdown_heading_without_the_label_alone():
    assert extract_project_name("# AutoSDLC Project Architecture\n\nBody text.") == "AutoSDLC Project Architecture"


def test_does_not_strip_project_when_it_is_not_a_leading_label():
    """Only a leading "Project:" is a template label to strip — "Project" appearing
    later in the title (not immediately followed by a colon) is part of the name."""
    assert extract_project_name("# Fleet Project Management Suite") == "Fleet Project Management Suite"


def test_plain_sentence_brief_is_used_as_is():
    text = "Build a small SaaS product."
    assert extract_project_name(text) == text


def test_empty_input_returns_empty_string():
    # "Untitled Project" in the docstring/fallback is dead code — "".split("\n")
    # returns [""], not [], so `lines` is always truthy for any string input,
    # including "". Pre-existing quirk, not part of this fix; documented here so
    # a future change to that fallback doesn't silently regress unnoticed.
    assert extract_project_name("") == ""


def test_long_first_line_is_truncated_to_50_chars():
    text = "x" * 80
    assert extract_project_name(text) == "x" * 50
