import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.artifact_store import LocalArtifactStore, UnsafeArtifactKey, write_wiki_artifacts


def test_local_store_rejects_paths_outside_root(tmp_path):
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(UnsafeArtifactKey):
        store.put("../outside.txt", b"no", "text/plain")
    with pytest.raises(UnsafeArtifactKey):
        store.get("/absolute.txt")


def test_write_wiki_artifact_bundle(tmp_path):
    store = LocalArtifactStore(tmp_path)
    result = write_wiki_artifacts(
        store,
        project_id=4,
        repo_id=9,
        source_revision="abc123",
        page={
            "title": "Payments API",
            "summary": "Processes payments.",
            "sections": [{"heading": "Runtime", "body": "Runs as a service."}],
        },
        sources=[{"repository": "acme/payments", "ref": "main", "revision": "abc123"}],
        extra_artifacts={"architecture.md": "# Architecture\n\nCited at `src/app.py:4`.\n"},
    )

    version_prefix = f"project-4/repo-9/abc123/{result.content_hash[:16]}"
    assert result.key == f"{version_prefix}/overview.md"
    assert store.get(result.key).decode().startswith("# Payments API")
    manifest = json.loads(store.get(f"{version_prefix}/manifest.json"))
    assert manifest["schema_version"] == 2
    assert manifest["content_hash"] == result.content_hash
    assert manifest["sources"][0]["repository"] == "acme/payments"
    assert store.get(f"{version_prefix}/architecture.md").startswith(b"# Architecture")
    assert store.list(version_prefix) == [
        f"{version_prefix}/architecture.md",
        f"{version_prefix}/index.json",
        f"{version_prefix}/manifest.json",
        f"{version_prefix}/overview.md",
    ]


def test_changed_wiki_content_creates_immutable_version(tmp_path):
    store = LocalArtifactStore(tmp_path)
    common = dict(project_id=1, repo_id=None, source_revision="same-commit", sources=[])
    first = write_wiki_artifacts(store, page={"title": "Product", "summary": "First", "sections": []}, **common)
    second = write_wiki_artifacts(store, page={"title": "Product", "summary": "Second", "sections": []}, **common)

    assert first.key != second.key
    assert store.exists(first.key)
    assert store.exists(second.key)
