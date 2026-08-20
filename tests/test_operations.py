from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def test_health_preserves_sidebar_contract():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "provider" in response.json()
    assert response.headers["x-request-id"]


def test_readiness_checks_database_and_frontend():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] is True
    assert response.json()["checks"]["frontend"] is True


def test_metrics_uses_route_templates_not_concrete_ids():
    client.get("/history/987654321")
    response = client.get("/metrics")
    assert response.status_code == 200
    routes = {row["route"] for row in response.json()["requests"]}
    assert "/history/{gen_id}" in routes
    assert "/history/987654321" not in routes


def test_api_has_no_duplicate_method_path_registrations():
    seen = set()
    duplicates = []
    for route in main.app.routes:
        for method in getattr(route, "methods", set()):
            key = (method, route.path)
            if key in seen:
                duplicates.append(key)
            seen.add(key)
    assert duplicates == []
