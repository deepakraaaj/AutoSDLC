"""Every phase of the generation pipeline depends on _parse_json_array /
_clean_raw to survive whatever an LLM hands back (markdown fences, a bare
object instead of an array, outright garbage). These were previously
completely untested despite sitting on the critical path of every phase."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from app.utils.text_parsing import clean_raw  # noqa: E402


def test_clean_raw_strips_markdown_json_fence():
    raw = '```json\n[{"a": 1}]\n```'
    assert clean_raw(raw) == '[{"a": 1}]'


def test_clean_raw_strips_bare_markdown_fence():
    raw = '```\n[{"a": 1}]\n```'
    assert clean_raw(raw) == '[{"a": 1}]'


def test_clean_raw_passes_through_unfenced_json():
    raw = '  [{"a": 1}]  '
    assert clean_raw(raw) == '[{"a": 1}]'


def test_parse_json_array_valid_array():
    result = main._parse_json_array('[{"title": "a"}, {"title": "b"}]')
    assert result == [{"title": "a"}, {"title": "b"}]


def test_parse_json_array_strips_markdown_fence():
    result = main._parse_json_array('```json\n[{"title": "a"}]\n```')
    assert result == [{"title": "a"}]


def test_parse_json_array_wraps_bare_object_as_single_item_list():
    # Some models return a single JSON object instead of a one-item array.
    result = main._parse_json_array('{"title": "a"}')
    assert result == [{"title": "a"}]


def test_parse_json_array_returns_empty_list_on_garbage():
    result = main._parse_json_array("not json at all {{{")
    assert result == []


def test_parse_json_array_returns_empty_list_on_empty_string():
    assert main._parse_json_array("") == []
