from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.security.fingerprint import compute_fingerprint, fingerprint_finding


def test_same_logical_finding_survives_line_shift():
    fp1 = compute_fingerprint(tool="semgrep", rule_id="sql-injection", path="repository.py", symbol="find_by_id", context="conn.execute(query)")
    fp2 = compute_fingerprint(tool="semgrep", rule_id="sql-injection", path="repository.py", symbol="find_by_id", context="conn.execute(query)")
    assert fp1 == fp2


def test_different_rule_or_file_changes_the_fingerprint():
    base = compute_fingerprint(tool="semgrep", rule_id="sql-injection", path="repository.py", symbol="find_by_id", context="x")
    different_rule = compute_fingerprint(tool="semgrep", rule_id="other-rule", path="repository.py", symbol="find_by_id", context="x")
    different_file = compute_fingerprint(tool="semgrep", rule_id="sql-injection", path="other.py", symbol="find_by_id", context="x")
    assert base != different_rule
    assert base != different_file


def test_context_normalization_tolerates_whitespace_reformatting():
    fp1 = compute_fingerprint(tool="semgrep", rule_id="r", path="a.py", context="  conn.execute(query)\n")
    fp2 = compute_fingerprint(tool="semgrep", rule_id="r", path="a.py", context="conn.execute(query)")
    assert fp1 == fp2


def test_fingerprint_finding_ignores_line_number():
    finding_at_line_10 = {"tool": "semgrep", "rule_id": "sql-injection", "file": "repository.py", "line": 10, "evidence": "conn.execute(query)"}
    finding_at_line_25 = {"tool": "semgrep", "rule_id": "sql-injection", "file": "repository.py", "line": 25, "evidence": "conn.execute(query)"}
    assert fingerprint_finding(finding_at_line_10) == fingerprint_finding(finding_at_line_25)


def test_fingerprint_finding_is_stable_for_identical_finding():
    finding = {"tool": "gitleaks", "rule_id": "aws-key", "file": "config.py", "evidence": "AKIA..."}
    assert fingerprint_finding(finding) == fingerprint_finding(dict(finding))
