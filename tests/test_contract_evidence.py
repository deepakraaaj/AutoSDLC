from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository
import app.services.database as database
from app.services.security.contract_evidence import collect_contract_evidence, render_contract_evidence


def test_changed_frontend_endpoint_is_verified_when_backend_route_exists(tmp_path):
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (backend / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/vts/vts/exception/type/list')\n"
        "def list_exception_types():\n"
        "    return []\n",
    )
    (frontend / "api.js").write_text("export const URL = '/vts/vts/exception/type/list'\n")

    indexes = [index_repository(frontend, "front"), index_repository(backend, "back")]
    evidence = collect_contract_evidence(
        snippets={"src/config/apiConfig.js": "GET_VIOLATION_REPORTS_URL: '/vts/vts/exception/type/list'"},
        indexes=indexes,
    )

    assert evidence[0].classification == "verified_backend_route"
    assert evidence[0].backend_matches == ["GET app.py:4"]


def test_changed_frontend_endpoint_without_backend_route_is_contract_risk(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/trip/vts/exception/type/list')\n"
        "def old_route():\n"
        "    return []\n",
    )

    evidence = collect_contract_evidence(
        snippets={"src/config/apiConfig.js": "GET_VIOLATION_REPORTS_URL: '/vts/vts/exception/type/list'"},
        indexes=[index_repository(backend, "back")],
    )
    rendered = "\n".join(render_contract_evidence(evidence))

    assert evidence[0].classification == "contract_risk_unverified_route"
    assert "report as a contract risk only" in rendered


def test_matching_frontend_pattern_is_not_backend_proof(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "api.js").write_text("getJSON('/vts/report/vts/transaction/mapping/list')\n")

    evidence = collect_contract_evidence(
        snippets={"src/config/apiConfig.js": "URL: '/vts/report/vts/transaction/mapping/list'"},
        indexes=[index_repository(frontend, "front")],
    )

    assert evidence[0].classification == "frontend_pattern_only"
    assert evidence[0].backend_matches == []
    assert evidence[0].frontend_call_matches == ["GET api.js:1"]


def test_repository_index_cache_preserves_branch_name(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    project = database.create_project("P", "")
    repo = database.add_project_repo(project["id"], "front", "acme", "ui")

    source = tmp_path / "repo"
    source.mkdir()
    (source / "api.js").write_text("getJSON('/vts/report/list')\n")
    index = index_repository(source, "abc123")

    database.save_repository_index(project["id"], repo["id"], index.as_dict(), branch_name="feature/sim-list")
    cached = database.get_repository_index(repo["id"], "abc123", branch_name="feature/sim-list")

    assert cached is not None
    assert cached["branch_name"] == "feature/sim-list"
    assert cached["revision"] == "abc123"
