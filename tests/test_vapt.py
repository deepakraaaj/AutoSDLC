import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.services.vapt as vapt
from app.services.vapt import _parse_gitleaks, _parse_npm_audit, _parse_osv, _parse_semgrep, _parse_trivy, _semgrep_config_args, best_fix_version, scanner_capabilities
from bitbucket.client import BitbucketConfig


def test_best_fix_version_prefers_installed_major_line():
    """uuid deprecated its 9.x/10.x lines outright, so 8.x installs are
    offered 11.1.1/12.0.1/13.0.1 as equally-valid 'the fix' — none share
    the installed major, so the smallest jump should win rather than
    forcing a guess between three options."""
    chosen, candidates = best_fix_version("8.3.2", ["11.1.1", "12.0.1", "13.0.1"])
    assert chosen == "11.1.1"
    assert candidates == ["11.1.1", "12.0.1", "13.0.1"]


def test_best_fix_version_matches_same_major_when_available():
    """When one candidate IS on the installed package's current major line,
    that's the smallest possible bump and should win over a larger jump to
    a newer major, even if the newer major is numerically listed first."""
    chosen, _ = best_fix_version("5.0.2", ["8.0.0", "5.0.8"])
    assert chosen == "5.0.8"


def test_best_fix_version_handles_no_installed_version():
    chosen, candidates = best_fix_version(None, ["2.1.0", "1.1.18"])
    assert chosen == "1.1.18"
    assert set(candidates) == {"2.1.0", "1.1.18"}


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
    # _finding() sorts+dedupes identifiers (feeds cross-tool merge in
    # app/api/projects.py's _security_summary), so order is alphabetical
    # rather than insertion order.
    assert osv[0]["identifiers"] == ["CVE-1", "GHSA-1"]


def test_trivy_parser_picks_one_fix_version_from_a_comma_list():
    """Regression for the uuid case: Trivy's FixedVersion can be a
    comma-separated list when multiple major lines are patched
    ("11.1.1, 12.0.1, 13.0.1"). The recommendation should name one concrete
    version to upgrade to, not just echo the raw list and leave the reader
    to guess."""
    finding = _parse_trivy({"Results": [{"Target": "package-lock.json", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-X", "PkgName": "uuid", "InstalledVersion": "8.3.2", "FixedVersion": "11.1.1, 12.0.1, 13.0.1", "Severity": "MEDIUM"},
    ]}]})[0]
    assert finding["fixed_version"] == "11.1.1"
    assert finding["recommendation"].startswith("Upgrade uuid to 11.1.1.")
    assert "12.0.1" in finding["recommendation"] and "13.0.1" in finding["recommendation"]


def test_npm_audit_parser_reads_advisory_metadata():
    finding = _parse_npm_audit({"vulnerabilities": {"demo": {"via": [{"source": 123, "title": "Prototype pollution", "severity": "high"}], "fixAvailable": {"version": "2.0.0"}}}})[0]
    assert finding["tool"] == "npm-audit"
    assert finding["severity"] == "high"
    assert "Prototype pollution" in finding["comment"]


def test_npm_audit_and_osv_identifiers_normalize_to_the_same_form():
    """npm-audit reports advisories as a full GitHub URL; osv-scanner/trivy
    report the bare GHSA/CVE ID. Without normalizing both to the same
    shape, the same vulnerability from two tools never shares an exact
    identifier string, so app/api/projects.py's cross-tool dedup silently
    fails to merge them and the remediation queue shows duplicate rows for
    one real issue — regression for exactly that bug."""
    npm = _parse_npm_audit({"vulnerabilities": {"react-router": {"via": [
        {"url": "https://github.com/advisories/GHSA-chx6-hx7r-mcp5", "title": "DoS via unauthenticated manifest endpoint", "severity": "high"},
    ]}}})[0]
    osv = _parse_osv({"results": [{"source": {"path": "package-lock.json"}, "packages": [
        {"package": {"name": "react-router", "version": "7.17.0"},
         "vulnerabilities": [{"id": "GHSA-chx6-hx7r-mcp5", "aliases": ["CVE-2026-55685"], "summary": "DoS"}]},
    ]}]})[0]
    assert npm["identifiers"] == ["GHSA-CHX6-HX7R-MCP5"]
    assert set(npm["identifiers"]) & set(osv["identifiers"])


def test_dependency_findings_are_categorized_not_lumped_as_other():
    """category defaulted to 'other' for every non-gitleaks finding, making
    dependency vulnerabilities indistinguishable from code findings in the
    UI's category filter/labels."""
    trivy = _parse_trivy({"Results": [{"Target": "package-lock.json", "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "demo", "Severity": "HIGH"}]}]})
    osv = _parse_osv({"results": [{"source": {"path": "requirements.txt"}, "packages": [{"package": {"name": "demo"}, "vulnerabilities": [{"id": "GHSA-1"}]}]}]})
    npm = _parse_npm_audit({"vulnerabilities": {"demo": {"via": [{"source": 1, "title": "x", "severity": "high"}]}}})
    assert trivy[0]["category"] == "dependency"
    assert osv[0]["category"] == "dependency"
    assert npm[0]["category"] == "dependency"


def test_eslint_stays_gated_even_when_the_binary_is_on_path(monkeypatch, tmp_path):
    """Regression: `A or B and C and D and E` parses as `A or (B and C and D
    and E)` in Python, so when eslint's own binary is found locally (A),
    the eslint_config opt-in gate (C) — and npm/pip-audit's manifest checks
    (D/E) — were silently skipped entirely."""
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(vapt, "_which", lambda name: f"/usr/bin/{name}")  # every tool "installed"
    monkeypatch.delenv("VAPT_ALLOW_ESLINT_CONFIG", raising=False)

    caps = {c["tool"]: c["available"] for c in scanner_capabilities(source)}
    assert caps["eslint"] is False  # no opt-in env var, no config file in the snapshot
    assert caps["npm-audit"] is False  # no package-lock.json in the snapshot
    assert caps["pip-audit"] is False  # no requirements.txt in the snapshot


def test_rest_fallback_snapshot_skips_files_bitbucket_wont_serve(monkeypatch, tmp_path):
    """One file 404ing/rate-limiting past bitbucket.client's own retries
    shouldn't sink the whole REST-fallback snapshot (used when git-over-HTTPS
    auth fails) — it should be skipped, with every other file still landing
    on disk."""
    destination = tmp_path / "source"

    # Force the git-clone path to fail so create_repository_snapshot falls
    # through to the REST API materialization under test.
    monkeypatch.setattr(vapt, "_run", lambda *a, **kw: subprocess.CompletedProcess([], 128, stdout="", stderr="auth failed"))
    monkeypatch.setattr(vapt, "list_repo_files", lambda config, path="", ref="HEAD", max_attempts=4: (
        [{"path": "good.txt", "type": "commit_file"}, {"path": "bad.txt", "type": "commit_file"}] if path == "" else []
    ))

    def fake_get_file_content(config, path, ref="HEAD", max_attempts=4):
        if path == "bad.txt":
            raise RuntimeError("Bitbucket file fetch failed (429): rate limited")
        return "hello"

    monkeypatch.setattr(vapt, "get_file_content", fake_get_file_content)

    config = BitbucketConfig(base_url="https://api.bitbucket.org/2.0", workspace="acme", repo_slug="widgets", access_token="tok")
    commit = vapt.create_repository_snapshot(config, destination, branch="dev")

    assert (destination / "good.txt").read_text() == "hello"
    assert not (destination / "bad.txt").exists()
    assert "dev" in commit


def test_rest_fallback_snapshot_stops_at_deadline_instead_of_hanging(monkeypatch, tmp_path):
    """Regression: the REST-fallback snapshot (git-over-HTTPS auth
    unavailable) had no wall-clock bound of its own — observed in practice
    running past 15+ minutes fetching a large repo tree file-by-file under
    Bitbucket's rate limiting. It should give up at SNAPSHOT_TIMEOUT_SECONDS
    and keep whatever landed on disk rather than block indefinitely."""
    import time as time_module
    destination = tmp_path / "source"

    monkeypatch.setattr(vapt, "_run", lambda *a, **kw: subprocess.CompletedProcess([], 128, stdout="", stderr="auth failed"))
    # Budget covers roughly one round of the (4-worker) pool, so the first
    # batch lands (proving partial progress isn't discarded) while the rest
    # of the 20 files are still cut off well short of 20 * 1s serial.
    monkeypatch.setattr(vapt, "SNAPSHOT_TIMEOUT_SECONDS", 1.5)
    monkeypatch.setattr(vapt, "list_repo_files", lambda config, path="", ref="HEAD", max_attempts=4: (
        [{"path": f"f{i}.txt", "type": "commit_file"} for i in range(20)] if path == "" else []
    ))

    def slow_get_file_content(config, path, ref="HEAD", max_attempts=4):
        time_module.sleep(1)
        return "hello"

    monkeypatch.setattr(vapt, "get_file_content", slow_get_file_content)

    config = BitbucketConfig(base_url="https://api.bitbucket.org/2.0", workspace="acme", repo_slug="widgets", access_token="tok")
    started = time_module.monotonic()
    vapt.create_repository_snapshot(config, destination, branch="dev")
    elapsed = time_module.monotonic() - started

    fetched = list(destination.glob("f*.txt"))
    assert 0 < len(fetched) < 20  # some landed, not all 20 — proof it stopped early
    assert elapsed < 5  # well under 20 * 1s if every file were awaited serially


def test_run_deterministic_scan_reuses_a_supplied_snapshot_without_refetching(monkeypatch, tmp_path):
    """PR impact analysis passes source=/commit= to reuse the snapshot it
    already fetched for the repository index, instead of Bitbucket being
    hit a second time for the same commit (which doubled request volume
    against the same rate-limit budget — the actual root cause of a
    snapshot failure observed under repeated PR-scan testing)."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("create_repository_snapshot must not be called when a snapshot is supplied")
    monkeypatch.setattr(vapt, "create_repository_snapshot", fail_if_called)
    monkeypatch.setattr(vapt, "scanner_capabilities", lambda src: [])

    events = list(vapt.run_deterministic_scan(config=object(), source=source, commit="abc123"))
    snapshot_events = [payload for event_type, payload in events if event_type == "scanner_status" and payload.get("stage") == "snapshot"]
    assert len(snapshot_events) == 1
    assert snapshot_events[0]["status"] == "completed"
    assert snapshot_events[0]["commit"] == "abc123"
    assert snapshot_events[0]["reused"] is True
    assert snapshot_events[0]["files"] == 1


def test_osv_scanner_no_manifests_is_completed_not_failed(monkeypatch, tmp_path):
    """osv-scanner exits 128 with a plain-text banner (no JSON) when a
    snapshot has no manifest it recognizes. That's a clean "nothing to
    check" outcome, not a scanner failure — regression for a bug where the
    UI showed a spurious 'error while running' on every scan of a repo
    without a lockfile it understands."""
    source = tmp_path / "source"
    source.mkdir()

    monkeypatch.setattr(vapt, "scanner_capabilities", lambda src: [{"tool": "osv-scanner", "available": True}])
    monkeypatch.setattr(vapt, "_scanner_command", lambda tool, src, work: (["osv-scanner", "scan", "source", "-r", "--format", "json", str(src)], None))
    monkeypatch.setattr(vapt, "create_repository_snapshot", lambda config, destination, branch=None, commit_sha=None: "deadbeef")
    monkeypatch.setattr(
        vapt, "_run",
        # osv-scanner writes this banner to stderr, not stdout.
        lambda command, **kwargs: subprocess.CompletedProcess(command, 128, stdout="", stderr="Scanning dir /src\nNo package sources found, --help for usage information.\n"),
    )

    events = dict(vapt.run_deterministic_scan(config=object()))
    complete = events["deterministic_complete"]
    osv_result = next(t for t in complete["tools"] if t["tool"] == "osv-scanner")
    assert osv_result["status"] == "completed"
    assert osv_result["findings_count"] == 0
    assert complete["partial"] is False


def test_eslint_unresolved_plugin_import_is_not_applicable_not_failed(monkeypatch, tmp_path):
    """A flat eslint.config.js can `import` plugin packages resolved
    relative to itself, which needs node_modules alongside it — excluded
    from every snapshot (size, and to avoid executing install scripts).
    Node's ESM loader then throws ERR_MODULE_NOT_FOUND before eslint scans
    anything, on basically any real-world plugin-based config. That should
    surface as a clean not_applicable result, not a raw JS stack trace
    reported as a scanner failure."""
    source = tmp_path / "source"
    source.mkdir()

    monkeypatch.setattr(vapt, "scanner_capabilities", lambda src: [{"tool": "eslint", "available": True}])
    monkeypatch.setattr(vapt, "_scanner_command", lambda tool, src, work: (["eslint", str(src), "--format", "json"], None))
    monkeypatch.setattr(vapt, "create_repository_snapshot", lambda config, destination, branch=None, commit_sha=None: "deadbeef")
    stack_trace = (
        "file:///src/eslint.config.js:1\n"
        "import reactPlugin from 'eslint-plugin-react'\n"
        "         ^\n\n"
        "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'eslint-plugin-react' imported from /src/eslint.config.js\n"
        "    at packageResolve (node:internal/modules/esm/resolve:767:81)\n"
        "    at moduleResolve (node:internal/modules/esm/resolve:853:18)\n"
        "    at defaultResolve (node:internal/modules/esm/resolve:983:11)\n"
        "    at ModuleJob._link (node:internal/modules/esm/module_job:182:49)\n"
    )
    monkeypatch.setattr(
        vapt, "_run",
        # ESLint's own exit-code convention: 0 = clean, 1 = lint findings,
        # 2 = fatal error (e.g. config failed to load) — this is the 2 case.
        lambda command, **kwargs: subprocess.CompletedProcess(command, 2, stdout="", stderr=stack_trace),
    )

    events = dict(vapt.run_deterministic_scan(config=object()))
    complete = events["deterministic_complete"]
    eslint_result = next(t for t in complete["tools"] if t["tool"] == "eslint")
    assert eslint_result["status"] == "not_applicable"
    assert eslint_result["findings_count"] == 0
    assert "node_modules" in eslint_result["error"]


def test_semgrep_config_args_always_includes_base_rulesets(tmp_path):
    configs = _semgrep_config_args(tmp_path)
    assert configs == ["p/security-audit", "p/secure-defaults"]


def test_semgrep_config_args_adds_js_node_for_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "^4.0.0"}}')
    configs = _semgrep_config_args(tmp_path)
    assert configs == ["p/security-audit", "p/secure-defaults", "p/javascript", "p/nodejs"]


def test_semgrep_config_args_adds_expressjs_when_express_dependency_present(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"express": "^4.18.0"}}')
    configs = _semgrep_config_args(tmp_path)
    assert configs == ["p/security-audit", "p/secure-defaults", "p/javascript", "p/nodejs", "p/expressjs"]


def test_semgrep_config_args_adds_ai_best_practices_for_python_ai_sdk(tmp_path):
    (tmp_path / "requirements.txt").write_text("anthropic==0.30.0\nfastapi==0.110.0\n")
    configs = _semgrep_config_args(tmp_path)
    assert configs == ["p/security-audit", "p/secure-defaults", "p/ai-best-practices"]


def test_semgrep_config_args_skips_p_secrets():
    """p/secrets is deliberately excluded — gitleaks/trivy already cover
    secret detection, and secret findings carry no `identifiers` for the
    cross-tool dedup to merge on, so it would just double-report."""
    assert "p/secrets" not in vapt._SEMGREP_BASE_CONFIGS
