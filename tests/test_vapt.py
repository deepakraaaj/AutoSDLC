from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.vapt import _parse_gitleaks, _parse_npm_audit, _parse_osv, _parse_semgrep, _parse_trivy


def test_semgrep_parser_preserves_evidence_and_normalizes_severity():
    findings = _parse_semgrep({"results": [{"check_id": "python.sql", "path": "app/db.py", "start": {"line": 8}, "extra": {"severity": "ERROR", "message": "SQL injection", "lines": "query(user)"}}]})
    assert findings[0]["severity"] == "high"
    assert findings[0]["file"] == "app/db.py"
    assert findings[0]["evidence"] == "query(user)"


def test_gitleaks_parser_marks_secrets_high():
    finding = _parse_gitleaks([{"RuleID": "aws-access-token", "File": "config.js", "StartLine": 4, "Description": "AWS key", "Match": "AKIA..."}])[0]
    assert finding["category"] == "secrets"
    assert finding["severity"] == "high"
    assert finding["evidence"] == "AKIA..."


def test_trivy_and_osv_parsers_include_identifiers():
    trivy = _parse_trivy({"Results": [{"Target": "package-lock.json", "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "demo", "InstalledVersion": "1", "FixedVersion": "2", "Severity": "HIGH"}]}]})
    osv = _parse_osv({"results": [{"source": {"path": "requirements.txt"}, "packages": [{"package": {"name": "demo", "version": "1"}, "vulnerabilities": [{"id": "GHSA-1", "aliases": ["CVE-1"], "summary": "bad"}]}]}]})
    assert trivy[0]["identifiers"] == ["CVE-1"]
    assert osv[0]["identifiers"] == ["GHSA-1", "CVE-1"]


def test_npm_audit_parser_reads_advisory_metadata():
    finding = _parse_npm_audit({"vulnerabilities": {"demo": {"via": [{"source": 123, "title": "Prototype pollution", "severity": "high"}], "fixAvailable": {"version": "2.0.0"}}}})[0]
    assert finding["tool"] == "npm-audit"
    assert finding["severity"] == "high"
    assert "Prototype pollution" in finding["comment"]
