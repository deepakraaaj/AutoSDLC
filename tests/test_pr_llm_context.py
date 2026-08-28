from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository
from app.services.security.baseline import BaselineSelection
from app.services.security.context_budget import ContextBudget, TruncationRecord
from app.services.security.correlation import correlate_finding
from app.services.security.fingerprint import fingerprint_finding
from app.services.security.impact_graph import build_impact_graph, enrich_with_security_context
from app.services.security.pr_diff import PullRequestDiff, PullRequestInfo, parse_unified_diff
from app.services.security.pr_llm_context import build_pr_review_context
from app.services.security.pr_symbols import map_pr_changes_to_symbols
from app.services.security.related_code import find_security_context

_DIFF_TEXT = (
    "diff --git a/controller.py b/controller.py\nindex 1..2 100644\n--- a/controller.py\n+++ b/controller.py\n"
    "@@ -3,3 +3,6 @@ class UserController:\n"
    "     def __init__(self):\n"
    "         self.service = UserService()\n \n"
    "+    def get_user(self, user_id):\n"
    "+        return self.service.get_user(user_id)\n+\n"
)


def _setup(tmp_path):
    (tmp_path / "controller.py").write_text(
        "from service import UserService\n\nclass UserController:\n"
        "    def __init__(self):\n        self.service = UserService()\n\n"
        "    def get_user(self, user_id):\n        return self.service.get_user(user_id)\n",
    )
    (tmp_path / "service.py").write_text(
        "from repository import UserRepository\n\nclass UserService:\n"
        "    def __init__(self):\n        self.repository = UserRepository()\n\n"
        "    def get_user(self, user_id):\n        return self.repository.find_by_id(user_id)\n",
    )
    (tmp_path / "repository.py").write_text(
        "class UserRepository:\n    def find_by_id(self, user_id):\n"
        '        conn.execute("SELECT * FROM users WHERE id = " + str(user_id))\n',
    )
    index = index_repository(tmp_path, "rev")
    files, truncated = parse_unified_diff(_DIFF_TEXT)
    info = PullRequestInfo("1", "Add get_user endpoint", "adds a retrieval endpoint", "feature", "main", "base123", "head456")
    diff = PullRequestDiff(info=info, files=files, truncated=truncated)
    seeds = map_pr_changes_to_symbols(diff, index)
    seed_ids = [s.symbol_id for s in seeds if s.symbol_id]
    graph = build_impact_graph(index, seed_ids, max_depth=3, max_nodes=50, max_files=20)
    matches = find_security_context(tmp_path, index=index)
    enrich_with_security_context(graph, matches)

    finding = {"tool": "semgrep", "rule_id": "sqli", "file": "repository.py", "start_line": 3, "severity": "high", "comment": "SQL injection"}
    correlated = [correlate_finding(finding, fingerprint_finding(finding), diff=diff, seeds=seeds, graph=graph)]
    return diff, seeds, graph, correlated


def test_context_includes_pr_metadata_changed_symbols_and_paths(tmp_path):
    diff, seeds, graph, correlated = _setup(tmp_path)
    baseline = BaselineSelection(None, None, "NONE", "NONE")
    truncation = TruncationRecord()
    text = build_pr_review_context(diff=diff, seeds=seeds, graph=graph, correlated_findings=correlated, baseline=baseline, budget=ContextBudget(), truncation=truncation)

    assert "Add get_user endpoint" in text
    assert "get_user" in text
    assert "EXISTING_NEWLY_EXPOSED" in text or "INDIRECT" in text
    assert "No reliable baseline" in text
    assert truncation.any_truncated is False


def test_unrelated_findings_are_excluded_from_llm_context(tmp_path):
    diff, seeds, graph, _ = _setup(tmp_path)
    unrelated_finding = {"tool": "semgrep", "rule_id": "x", "file": "totally/unrelated.py", "start_line": 1, "severity": "low", "comment": "not connected"}
    correlated = [correlate_finding(unrelated_finding, fingerprint_finding(unrelated_finding), diff=diff, seeds=seeds, graph=graph)]
    baseline = BaselineSelection(None, None, "NONE", "NONE")
    truncation = TruncationRecord()
    text = build_pr_review_context(diff=diff, seeds=seeds, graph=graph, correlated_findings=correlated, baseline=baseline, budget=ContextBudget(), truncation=truncation)
    assert "totally/unrelated.py" not in text


def test_llm_input_is_truncated_and_recorded_when_over_budget(tmp_path):
    diff, seeds, graph, correlated = _setup(tmp_path)
    baseline = BaselineSelection(None, None, "NONE", "NONE")
    truncation = TruncationRecord()
    tiny_budget = ContextBudget(max_llm_input_chars=200)
    text = build_pr_review_context(diff=diff, seeds=seeds, graph=graph, correlated_findings=correlated, baseline=baseline, budget=tiny_budget, truncation=truncation)

    assert len(text) <= 200 + len("\n\n[... truncated to fit context budget ...]")
    assert truncation.llm_input_truncated is True
    assert truncation.any_truncated is True


def test_snippets_are_included_and_capped_by_max_snippets(tmp_path):
    diff, seeds, graph, correlated = _setup(tmp_path)
    baseline = BaselineSelection(None, None, "NONE", "NONE")
    truncation = TruncationRecord()
    budget = ContextBudget(max_snippets=1)
    snippets = {"controller.py": "def get_user(): pass", "service.py": "def get_user(): pass"}
    text = build_pr_review_context(diff=diff, seeds=seeds, graph=graph, correlated_findings=correlated, baseline=baseline, budget=budget, truncation=truncation, snippets=snippets)

    assert text.count("--- controller.py ---") + text.count("--- service.py ---") == 1
    assert truncation.llm_input_truncated is True


def test_contract_evidence_is_included_when_branch_indexes_are_supplied(tmp_path):
    diff, seeds, graph, correlated = _setup(tmp_path)
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/vts/vts/exception/type/list')\n"
        "def route():\n"
        "    return []\n",
    )
    index = index_repository(tmp_path, "branch-rev")
    baseline = BaselineSelection(None, None, "NONE", "NONE")
    truncation = TruncationRecord()

    text = build_pr_review_context(
        diff=diff, seeds=seeds, graph=graph, correlated_findings=correlated,
        baseline=baseline, budget=ContextBudget(), truncation=truncation,
        snippets={"src/config/apiConfig.js": "GET_URL = '/vts/vts/exception/type/list'"},
        branch_indexes=[index],
    )

    assert "Branch/contract evidence" in text
    assert "verified_backend_route" in text
    assert "GET api.py:4" in text
