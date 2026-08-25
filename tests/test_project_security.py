"""Tests for the project-scoped Security/VAPT endpoints (app/api/projects.py):
reading each repo's latest security_scan job, and triggering a new one.

Same stubbing style as tests/test_project_pull_requests.py."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.api.projects as projects_api  # noqa: E402
import app.services.database as database  # noqa: E402
import app.services.jobs as jobs  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _create_project(name="Smart Turf"):
    return client.post("/projects", json={"name": name}).json()


def _add_repo(project_id, workspace="acme", repo_slug="fits-service"):
    return client.post(f"/projects/{project_id}/repos", json={
        "workspace": workspace, "repo_slug": repo_slug, "verify": False,
    }).json()


def test_get_security_with_no_repos():
    project = _create_project()
    response = client.get(f"/projects/{project['id']}/security")
    assert response.status_code == 200
    assert response.json()["repos"] == []


def test_get_security_defaults_to_not_scanned():
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.get(f"/projects/{project['id']}/security")
    assert response.status_code == 200
    entry = response.json()["repos"][0]
    assert entry["repo_id"] == repo["id"]
    assert entry["scan"]["status"] == "not_scanned"
    assert entry["scan"]["findings"] == []


def test_get_security_reflects_completed_scan():
    project = _create_project()
    repo = _add_repo(project["id"])

    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('job-1', 'security_scan', 'succeeded', ?, ?, '2026-08-01', '2026-08-02')",
        (
            json.dumps({"repo_id": repo["id"], "label": "fits-service", "workspace": "acme", "repo_slug": "fits-service"}),
            json.dumps({"repo_id": repo["id"], "repo_label": "fits-service", "findings": [
                {"file": "a.py", "line": 3, "category": "secrets", "severity": "critical", "comment": "Hardcoded API key"},
                {"file": "b.py", "line": 9, "category": "input-validation", "severity": "low", "comment": "Unvalidated query param"},
            ]}),
        ),
    )
    conn.commit()
    conn.close()

    entry = client.get(f"/projects/{project['id']}/security").json()["repos"][0]
    assert entry["scan"]["status"] == "succeeded"
    assert entry["scan"]["job_id"] == "job-1"
    assert entry["scan"]["scanned_at"] == "2026-08-02"
    assert len(entry["scan"]["findings"]) == 2
    assert entry["scan"]["severity_counts"] == {"critical": 1, "high": 0, "medium": 0, "low": 1}


def test_get_security_bundles_same_package_same_fix_across_cves():
    """Four distinct CVEs against react-router, all fixed by the same
    7.18.0 upgrade, should collapse into one remediation entry — the
    action is identical, so four cards for it is noise, not signal."""
    project = _create_project()
    repo = _add_repo(project["id"])

    def _rr_finding(cve, ghsa, comment, tool="osv-scanner"):
        return {
            "tool": tool, "file": "package-lock.json", "line": None, "category": "dependency",
            "severity": "high", "comment": comment,
            "recommendation": "Upgrade react-router to 7.18.0.", "evidence": "",
            "identifiers": [cve, ghsa], "package": "react-router", "fixed_version": "7.18.0",
            "fingerprint": f"fp-{ghsa}",
        }

    # Identifiers are already normalized upper-case here, matching what
    # vapt.py's _finding() actually stores (real scan results always pass
    # through it) — this test exercises _security_summary's grouping on
    # top of that, not the normalization itself (covered separately in
    # tests/test_vapt.py).
    findings = [
        _rr_finding("CVE-2026-55685", "GHSA-CHX6-HX7R-MCP5", "Denial of Service via unauthenticated manifest endpoint requests"),
        _rr_finding("CVE-2026-53666", "GHSA-337J-9HXR-RHXG", "Information disclosure via client-side constructor execution", tool="trivy"),
        _rr_finding("CVE-2026-53667", "GHSA-H8FP-F39C-Q6MH", "Untrusted redirects due to missing protocol validation"),
        _rr_finding("CVE-2026-53669", "GHSA-WRJC-X8RR-H8H6", "Open Redirect vulnerability via backslashes in navigation components"),
    ]
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('job-1', 'security_scan', 'succeeded', ?, ?, '2026-08-01', '2026-08-02')",
        (
            json.dumps({"repo_id": repo["id"], "label": "fits-service", "workspace": "acme", "repo_slug": "fits-service"}),
            json.dumps({"repo_id": repo["id"], "repo_label": "fits-service", "findings": findings}),
        ),
    )
    conn.commit()
    conn.close()

    entry = client.get(f"/projects/{project['id']}/security").json()["repos"][0]
    dependency_findings = [f for f in entry["scan"]["findings"] if f.get("package") == "react-router"]
    assert len(dependency_findings) == 1
    bundled = dependency_findings[0]
    assert bundled["fixed_version"] == "7.18.0"
    assert set(bundled["identifiers"]) == {"CVE-2026-55685", "GHSA-CHX6-HX7R-MCP5", "CVE-2026-53666", "GHSA-337J-9HXR-RHXG", "CVE-2026-53667", "GHSA-H8FP-F39C-Q6MH", "CVE-2026-53669", "GHSA-WRJC-X8RR-H8H6"}
    assert bundled["tool"] == "osv-scanner, trivy"
    assert "4 known issues" in bundled["comment"]
    assert "Denial of Service" in bundled["comment"]
    assert "Open Redirect" in bundled["comment"]
    # Bundling is presentation only — the box shows how many raw advisories
    # it represents, and severity_counts must still count all 4 "high"
    # findings, not 1, so the summary badge doesn't understate exposure.
    assert bundled["advisory_count"] == 4
    assert entry["scan"]["severity_counts"]["high"] == 4


def test_get_security_bundles_same_package_differing_fix_versions():
    """Regression: three brace-expansion advisories with three DIFFERENT
    minimum fix versions (5.0.7, 5.0.8, 1.1.18 — different branches, not a
    typo) were previously grouped by (package, fixed_version), so they
    never collapsed and the UI showed three boxes for the same package
    each quoting a different 'Required fix' number — reading as
    contradictory. Grouping by package alone should still bundle them into
    one entry, listing every fix version rather than forcing one wrong
    answer."""
    project = _create_project()
    repo = _add_repo(project["id"])

    def _be_finding(ghsa, comment, fixed_version, tool="npm-audit"):
        return {
            "tool": tool, "file": "/src/package-lock.json", "line": None, "category": "dependency",
            "severity": "medium", "comment": comment,
            "recommendation": f"Upgrade brace-expansion to {fixed_version}.", "evidence": "",
            "identifiers": [ghsa], "package": "brace-expansion", "fixed_version": fixed_version,
            "fingerprint": f"fp-{ghsa}",
        }

    findings = [
        _be_finding("GHSA-3JXR-9VMJ-R5CP", "brace-expansion 1.1.15 is affected by GHSA-3jxr-9vmj-r5cp.", "5.0.7"),
        _be_finding("GHSA-MH99-V99M-4GVG", "brace-expansion 1.1.15 is affected by GHSA-mh99-v99m-4gvg.", "5.0.8", tool="osv-scanner"),
        _be_finding("GHSA-RGW5-RVV9-X895", "brace-expansion 1.1.15 is affected by GHSA-rgw5-rvv9-x895.", "1.1.18"),
    ]
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO jobs (id, kind, status, input_json, result_json, created_at, updated_at) "
        "VALUES ('job-1', 'security_scan', 'succeeded', ?, ?, '2026-08-01', '2026-08-02')",
        (
            json.dumps({"repo_id": repo["id"], "label": "fits-service", "workspace": "acme", "repo_slug": "fits-service"}),
            json.dumps({"repo_id": repo["id"], "repo_label": "fits-service", "findings": findings}),
        ),
    )
    conn.commit()
    conn.close()

    entry = client.get(f"/projects/{project['id']}/security").json()["repos"][0]
    dependency_findings = [f for f in entry["scan"]["findings"] if f.get("package") == "brace-expansion"]
    assert len(dependency_findings) == 1
    bundled = dependency_findings[0]
    assert set(bundled["identifiers"]) == {"GHSA-3JXR-9VMJ-R5CP", "GHSA-MH99-V99M-4GVG", "GHSA-RGW5-RVV9-X895"}
    assert bundled["tool"] == "npm-audit, osv-scanner"
    # All three fix versions surface — none silently dropped or overwritten.
    assert "5.0.7" in bundled["recommendation"]
    assert "5.0.8" in bundled["recommendation"]
    assert "1.1.18" in bundled["recommendation"]
    assert "3 known issues" in bundled["comment"]
    assert bundled["advisory_count"] == 3
    assert entry["scan"]["severity_counts"]["medium"] == 3


def test_get_security_404_for_missing_project():
    assert client.get("/projects/999999/security").status_code == 404


def test_trigger_scan_schedules_security_scan_job(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setitem(jobs._runners, "security_scan", lambda payload: iter(()))
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 202
    assert response.json()["kind"] == "security_scan"


def test_trigger_scan_404_for_repo_not_on_project(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    project_a = _create_project("A")
    project_b = _create_project("B")
    repo = _add_repo(project_b["id"])

    response = client.post(f"/projects/{project_a['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 404


def test_trigger_scan_400_without_bitbucket_configured(monkeypatch):
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    repo = _add_repo(project["id"])

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/security-scan")
    assert response.status_code == 400
