"""The frontend addresses a generation by id (/app/backlog/123/stories), so those
deep paths have to serve the SPA shell on a hard reload — a share, a bookmark, or
opening a backlog in a second browser tab all start as a plain GET of a nested path,
not as client-side navigation. If these 404, the whole id-based routing is broken the
moment anyone reloads."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402

client = TestClient(main.app)


@pytest.mark.parametrize("path", [
    "/app/backlog",
    "/app/backlog/123",
    "/app/backlog/123/epics",
    "/app/backlog/123/stories",
    "/app/backlog/123/tasks",
    "/app/backlog/123/tests",
    "/app/backlog/123/hierarchy",
    "/app/backlog/hierarchy",
    "/app/history",
])
def test_nested_app_paths_serve_the_spa_shell(path):
    res = client.get(path)
    assert res.status_code == 200, f"{path} must serve the SPA, not 404"
    assert "text/html" in res.headers["content-type"]


def test_api_routes_are_not_shadowed_by_the_spa_catch_all():
    """The catch-all is scoped under /app so it can't swallow the API — a generation
    id in a URL path must still reach the JSON endpoint, not the HTML shell."""
    res = client.get("/history/999999")
    assert "application/json" in res.headers["content-type"]
