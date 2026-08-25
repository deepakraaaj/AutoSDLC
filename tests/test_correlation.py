from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository
from app.services.security.correlation import (
    RELATION_DEPENDENCY,
    RELATION_DIRECT,
    RELATION_EXISTING_NEWLY_EXPOSED,
    RELATION_EXISTING_RELEVANT,
    RELATION_INDIRECT,
    RELATION_UNRELATED,
    correlate_finding,
)
from app.services.security.fingerprint import fingerprint_finding
from app.services.security.impact_graph import build_impact_graph, enrich_with_security_context
from app.services.security.pr_diff import PullRequestDiff, PullRequestInfo, parse_unified_diff
from app.services.security.pr_symbols import map_pr_changes_to_symbols
from app.services.security.related_code import find_security_context

_INFO = PullRequestInfo("1", "Add get_user endpoint", "", "feature", "main", "base123", "head456")


def _write_controller_service_repository(tmp_path):
    (tmp_path / "controller.py").write_text(
        "from service import UserService\n\n"
        "class UserController:\n"
        "    def __init__(self):\n"
        "        self.service = UserService()\n\n"
        "    def get_user(self, user_id):\n"
        "        return self.service.get_user(user_id)\n",
    )
    (tmp_path / "service.py").write_text(
        "from repository import UserRepository\n\n"
        "class UserService:\n"
        "    def __init__(self):\n"
        "        self.repository = UserRepository()\n\n"
        "    def get_user(self, user_id):\n"
        "        return self.repository.find_by_id(user_id)\n",
    )
    (tmp_path / "repository.py").write_text(
        "class UserRepository:\n"
        "    def find_by_id(self, user_id):\n"
        '        conn.execute("SELECT * FROM users WHERE id = " + str(user_id))\n',
    )
    (tmp_path / "unrelated.py").write_text(
        "def helper():\n"
        '    conn.execute("DELETE FROM logs")\n',
    )


_ADD_GET_USER_DIFF = (
    "diff --git a/controller.py b/controller.py\nindex 1..2 100644\n--- a/controller.py\n+++ b/controller.py\n"
    "@@ -3,3 +3,6 @@ class UserController:\n"
    "     def __init__(self):\n"
    "         self.service = UserService()\n \n"
    "+    def get_user(self, user_id):\n"
    "+        return self.service.get_user(user_id)\n+\n"
)


def _build(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "rev")
    files, truncated = parse_unified_diff(_ADD_GET_USER_DIFF)
    diff = PullRequestDiff(info=_INFO, files=files, truncated=truncated)
    seeds = map_pr_changes_to_symbols(diff, index)
    seed_ids = [s.symbol_id for s in seeds if s.symbol_id]
    graph = build_impact_graph(index, seed_ids, max_depth=3, max_nodes=50, max_files=20)
    matches = find_security_context(tmp_path, index=index)
    enrich_with_security_context(graph, matches)
    return index, diff, seeds, graph


def test_direct_finding_on_changed_lines(tmp_path):
    _, diff, seeds, graph = _build(tmp_path)
    finding = {"tool": "semgrep", "rule_id": "r1", "file": "controller.py", "start_line": 6, "severity": "medium"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_DIRECT
    assert result.relation_confidence == "HIGH"


def test_existing_newly_exposed_when_added_route_reaches_it(tmp_path):
    _, diff, seeds, graph = _build(tmp_path)
    finding = {"tool": "semgrep", "rule_id": "sqli", "file": "repository.py", "start_line": 3, "severity": "high"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_EXISTING_NEWLY_EXPOSED
    assert result.affected_path[0] == "get_user"
    assert result.affected_path[-1] == "find_by_id"


def test_indirect_when_reached_via_a_merely_modified_seed(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "rev")
    # PR modifies (not adds) the existing get_user route's body — the path
    # to repository.py already existed before this PR.
    diff_text = (
        "diff --git a/controller.py b/controller.py\nindex 1..2 100644\n--- a/controller.py\n+++ b/controller.py\n"
        "@@ -7,2 +7,3 @@ class UserController:\n"
        "     def get_user(self, user_id):\n"
        "+        # audit log\n"
        "         return self.service.get_user(user_id)\n"
    )
    files, truncated = parse_unified_diff(diff_text)
    diff = PullRequestDiff(info=_INFO, files=files, truncated=truncated)
    seeds = map_pr_changes_to_symbols(diff, index)
    seed_ids = [s.symbol_id for s in seeds if s.symbol_id]
    graph = build_impact_graph(index, seed_ids, max_depth=3, max_nodes=50, max_files=20)

    finding = {"tool": "semgrep", "rule_id": "sqli", "file": "repository.py", "start_line": 3, "severity": "high"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_INDIRECT


def test_dependency_finding_when_manifest_changed(tmp_path):
    _write_controller_service_repository(tmp_path)
    (tmp_path / "requirements.txt").write_text("flask==2.0\n")
    index = index_repository(tmp_path, "rev")
    diff_text = (
        "diff --git a/requirements.txt b/requirements.txt\nindex 1..2 100644\n"
        "--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1 +1 @@\n-flask==2.0\n+flask==2.3\n"
    )
    files, truncated = parse_unified_diff(diff_text)
    diff = PullRequestDiff(info=_INFO, files=files, truncated=truncated)
    seeds = map_pr_changes_to_symbols(diff, index)
    graph = build_impact_graph(index, [], max_depth=3, max_nodes=50, max_files=20)

    finding = {"tool": "osv-scanner", "rule_id": "OSV-1", "file": "requirements.txt", "severity": "high"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_DEPENDENCY
    assert result.relation_confidence == "HIGH"


def test_existing_relevant_when_only_file_context_overlaps(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "rev")
    files, truncated = parse_unified_diff(_ADD_GET_USER_DIFF)
    diff = PullRequestDiff(info=_INFO, files=files, truncated=truncated)
    seeds = map_pr_changes_to_symbols(diff, index)
    seed_ids = [s.symbol_id for s in seeds if s.symbol_id]
    graph = build_impact_graph(index, seed_ids, max_depth=3, max_nodes=50, max_files=20)
    # Force `repository.py` into graph.files without a resolved node overlap
    # by clearing nodes but keeping the file set — simulates a security-
    # context-only (ast-grep) match with no confirmed call-graph edge.
    graph.nodes = {k: v for k, v in graph.nodes.items() if v.path != "repository.py"}

    finding = {"tool": "semgrep", "rule_id": "sqli", "file": "repository.py", "start_line": 3, "severity": "high"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_EXISTING_RELEVANT
    assert result.relation_confidence == "LOW"


def test_unrelated_finding_has_no_connection(tmp_path):
    _, diff, seeds, graph = _build(tmp_path)
    finding = {"tool": "semgrep", "rule_id": "sqli2", "file": "unrelated.py", "start_line": 2, "severity": "high"}
    result = correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)
    assert result.relation_to_pr == RELATION_UNRELATED
