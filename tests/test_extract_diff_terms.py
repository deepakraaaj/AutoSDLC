"""Tests for main.py's _extract_diff_terms: pulls identifiers touched by a
PR's added/removed lines so a related repo's context can be searched for
what actually changed, instead of a generic file sample.

Running example is the AutoSDLC PR #62 case this was built for: a diff
replacing Date.now() with getDayEnd(moment()).valueOf()."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import _extract_diff_terms  # noqa: E402

SAMPLE_DIFF = """--- a/src/components/DateRangeComponent.tsx
+++ b/src/components/DateRangeComponent.tsx
@@ -15,7 +15,7 @@
-  const maxDateTime = Date.now();
+  const maxDateTime = getDayEnd(moment()).valueOf();
"""


def test_extracts_identifiers_from_added_and_removed_lines():
    terms = _extract_diff_terms(SAMPLE_DIFF)
    assert "getDayEnd" in terms
    assert "maxDateTime" in terms
    assert "moment" in terms


def test_ignores_diff_header_lines():
    # "+++"/"---" file headers must not be treated as content lines (they'd
    # otherwise pollute terms with path fragments on every diff).
    terms = _extract_diff_terms(SAMPLE_DIFF)
    assert "components" not in terms
    assert "DateRangeComponent" not in terms  # only appears in the +++/--- headers here


def test_ignores_unchanged_context_lines():
    diff = "\n".join(
        [
            "--- a/file.py",
            "+++ b/file.py",
            " def unrelated_context_function():",  # unchanged context line (leading space)
            "-    return old_value",
            "+    return new_value",
        ]
    )
    terms = _extract_diff_terms(diff)
    assert "unrelated_context_function" not in terms
    assert "new_value" in terms
    assert "old_value" in terms


def test_filters_common_stopwords():
    diff = "\n".join(
        [
            "--- a/file.py",
            "+++ b/file.py",
            "-import config",
            "+import config",
            "+class Something:",
            "+    async def handler(self, props, state):",
        ]
    )
    terms = _extract_diff_terms(diff)
    for stopword in ("import", "config", "class", "async", "self", "props", "state"):
        assert stopword not in terms


def test_empty_diff_returns_empty_list():
    assert _extract_diff_terms("") == []


def test_respects_limit():
    diff_lines = ["--- a/file.py", "+++ b/file.py"]
    diff_lines += [f"+uniqueTermNumber{i}" for i in range(20)]
    terms = _extract_diff_terms("\n".join(diff_lines), limit=5)
    assert len(terms) == 5
