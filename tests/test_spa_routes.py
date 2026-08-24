"""The frontend addresses a generation by id (/app/backlogs/123/stories), so those
deep paths have to serve the SPA shell on a hard reload — a share, a bookmark, or
opening a backlog in a second browser tab all start as a plain GET of a nested path,
not as client-side navigation. If these 404, the whole id-based routing is broken the
moment anyone reloads.

The pre-consolidation paths (/app/brief, /app/history, /app/backlog/...) are covered
too: they were shareable, so links to them exist in the wild, and the redirect that
maps them onto the current routes is client-side (see legacyRedirect in lib/route.ts).
That redirect can only run if the server hands back the shell in the first place."""
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
    # Current routes.
    "/app/projects",
    "/app/projects/7",
    "/app/projects/7/settings",
    "/app/projects/7/stories",
    "/app/create",
    "/app/create/chat",
    "/app/create/upload",
    "/app/assistant",
    "/app/backlogs",
    "/app/backlogs/123",
    "/app/backlogs/123/epics",
    "/app/backlogs/123/stories",
    "/app/backlogs/123/tasks",
    "/app/backlogs/123/tests",
    "/app/backlogs/123/hierarchy",
    "/app/backlogs/hierarchy",
    # Pre-consolidation routes, redirected client-side by legacyRedirect.
    "/app/brief",
    "/app/chat",
    "/app/upload",
    "/app/history",
    "/app/backlog",
    "/app/backlog/123",
    "/app/backlog/123/stories",
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
