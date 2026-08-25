from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.security.pr_diff import (
    STATUS_ADDED,
    STATUS_BINARY,
    STATUS_DELETED,
    STATUS_MODIFIED,
    STATUS_RENAMED,
    build_pull_request_info,
    parse_unified_diff,
)


def test_parses_modified_file_with_multiple_hunks():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "index 111..222 100644\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,3 +1,4 @@\n"
        " one\n"
        "+two\n"
        " three\n"
        " four\n"
        "@@ -10,2 +11,3 @@\n"
        " ten\n"
        "+eleven\n"
        " twelve\n"
    )
    files, truncated = parse_unified_diff(diff)
    assert len(files) == 1
    change = files[0]
    assert change.status == STATUS_MODIFIED
    assert change.path == "a.py"
    assert len(change.hunks) == 2
    assert change.added_lines == [2, 12]
    assert truncated is False


def test_parses_added_file():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "index 0000000..abc123\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def hello():\n"
        "+    pass\n"
    )
    files, _ = parse_unified_diff(diff)
    assert files[0].status == STATUS_ADDED
    assert files[0].added_lines == [1, 2]


def test_parses_deleted_file():
    diff = (
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "index abc123..0000000\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-def bye():\n"
        "-    pass\n"
    )
    files, _ = parse_unified_diff(diff)
    assert files[0].status == STATUS_DELETED
    assert files[0].old_path == "old.py"
    assert files[0].removed_lines == [1, 2]


def test_parses_renamed_file():
    diff = (
        "diff --git a/old_name.py b/new_name.py\n"
        "similarity index 100%\n"
        "rename from old_name.py\n"
        "rename to new_name.py\n"
    )
    files, _ = parse_unified_diff(diff)
    assert files[0].status == STATUS_RENAMED
    assert files[0].path == "new_name.py"
    assert files[0].old_path == "old_name.py"


def test_parses_binary_file():
    diff = (
        "diff --git a/img.png b/img.png\n"
        "index abc..def 100644\n"
        "Binary files a/img.png and b/img.png differ\n"
    )
    files, _ = parse_unified_diff(diff)
    assert files[0].status == STATUS_BINARY
    assert files[0].hunks == []


def test_multiple_files_in_one_diff():
    diff = (
        "diff --git a/one.py b/one.py\n"
        "index 111..222 100644\n"
        "--- a/one.py\n"
        "+++ b/one.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
        "diff --git a/two.py b/two.py\n"
        "index 333..444 100644\n"
        "--- a/two.py\n"
        "+++ b/two.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    files, _ = parse_unified_diff(diff)
    assert {item.path for item in files} == {"one.py", "two.py"}


def test_malformed_block_does_not_crash_the_whole_diff():
    diff = (
        "diff --git a/broken.py b/broken.py\n"
        "@@ this is not a valid hunk header @@\n"
        "diff --git a/fine.py b/fine.py\n"
        "index 111..222 100644\n"
        "--- a/fine.py\n"
        "+++ b/fine.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    files, _ = parse_unified_diff(diff)
    paths = {item.path for item in files}
    assert "fine.py" in paths
    # The broken block is still present (never silently dropped), just
    # with no parsed hunks.
    assert "broken.py" in paths


def test_large_diff_is_truncated_deterministically():
    hunk = "diff --git a/f.py b/f.py\nindex 1..2 100644\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y\n"
    diff = hunk * 20
    files, truncated = parse_unified_diff(diff, max_files=5)
    assert len(files) == 5
    assert truncated is True


def test_build_pull_request_info_from_raw_bitbucket_shape():
    pr = {
        "title": "Add endpoint",
        "description": "adds a thing",
        "source": {"branch": {"name": "feature/x"}, "commit": {"hash": "head123"}},
        "destination": {"branch": {"name": "main"}, "commit": {"hash": "base456"}},
        "author": {"display_name": "Alex"},
    }
    info = build_pull_request_info(pr, 42)
    assert info.pull_request_id == "42"
    assert info.source_branch == "feature/x"
    assert info.destination_branch == "main"
    assert info.head_sha == "head123"
    assert info.base_sha == "base456"
    assert info.author == "Alex"
