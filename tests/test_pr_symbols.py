from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository
from app.services.security.pr_diff import PullRequestDiff, PullRequestInfo, parse_unified_diff
from app.services.security.pr_symbols import classify_non_code_file, map_pr_changes_to_symbols

_INFO = PullRequestInfo("1", "t", "d", "feature", "main", "base", "head")


def _diff(diff_text: str) -> PullRequestDiff:
    files, truncated = parse_unified_diff(diff_text)
    return PullRequestDiff(info=_INFO, files=files, truncated=truncated)


def test_new_function_is_added(tmp_path):
    (tmp_path / "a.py").write_text("class A:\n    def existing(self):\n        pass\n\n    def new_one(self):\n        pass\n")
    index = index_repository(tmp_path, "rev")
    diff = _diff(
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,3 +1,6 @@\n class A:\n     def existing(self):\n         pass\n"
        "+\n+    def new_one(self):\n+        pass\n"
    )
    seeds = map_pr_changes_to_symbols(diff, index)
    new_one = next(s for s in seeds if s.symbol_name == "new_one")
    assert new_one.change_status == "ADDED"
    assert not any(s.symbol_name == "existing" for s in seeds)


def test_modified_line_inside_existing_function(tmp_path):
    (tmp_path / "a.py").write_text("def run():\n    x = 1\n    return x\n")
    index = index_repository(tmp_path, "rev")
    diff = _diff(
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,3 +1,3 @@\n def run():\n-    x = 1\n+    x = 2\n     return x\n"
    )
    seeds = map_pr_changes_to_symbols(diff, index)
    run_seed = next(s for s in seeds if s.symbol_name == "run")
    assert run_seed.change_status == "MODIFIED"


def test_module_level_change_with_no_symbol_overlap(tmp_path):
    (tmp_path / "a.py").write_text("VERSION = 1\n\ndef run():\n    pass\n")
    index = index_repository(tmp_path, "rev")
    diff = _diff(
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n-VERSION = 1\n+VERSION = 2\n"
    )
    seeds = map_pr_changes_to_symbols(diff, index)
    assert len(seeds) == 1
    assert seeds[0].symbol_id is None
    assert seeds[0].change_status == "MODIFIED"


def test_deleted_symbol_falls_back_to_file_level_seed(tmp_path):
    (tmp_path / "a.py").write_text("def run():\n    pass\n")
    index = index_repository(tmp_path, "rev")
    diff = _diff(
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex 1..0 100644\n"
        "--- a/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def old():\n-    pass\n"
    )
    seeds = map_pr_changes_to_symbols(diff, index)
    assert len(seeds) == 1
    assert seeds[0].change_status == "DELETED"
    assert seeds[0].symbol_id is None
    assert seeds[0].file == "gone.py"


def test_dependency_file_change_is_seeded_without_symbol_mapping(tmp_path):
    (tmp_path / "a.py").write_text("def run():\n    pass\n")
    index = index_repository(tmp_path, "rev")
    diff = _diff(
        "diff --git a/requirements.txt b/requirements.txt\nindex 1..2 100644\n"
        "--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1 +1 @@\n-flask==2.0\n+flask==2.3\n"
    )
    seeds = map_pr_changes_to_symbols(diff, index)
    assert len(seeds) == 1
    assert seeds[0].seed_type == "DEPENDENCY"
    assert seeds[0].file == "requirements.txt"


def test_classify_non_code_file_categories():
    assert classify_non_code_file("requirements.txt") == "DEPENDENCY"
    assert classify_non_code_file("package-lock.json") == "DEPENDENCY"
    assert classify_non_code_file("Dockerfile") == "INFRASTRUCTURE"
    assert classify_non_code_file("infra/main.tf") == "INFRASTRUCTURE"
    assert classify_non_code_file(".env.example") == "SECURITY_CONFIG"
    assert classify_non_code_file(".github/workflows/ci.yml") == "CONFIGURATION"
    assert classify_non_code_file("app/services/vapt.py") is None
