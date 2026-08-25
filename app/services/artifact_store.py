"""Storage-neutral persistence for generated wiki artifacts.

Local development writes to ``data/wiki_artifacts``.  Callers address files by
portable object keys, so an S3 implementation can replace the local backend
without changing wiki generation or API code.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Protocol


class ArtifactStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


class UnsafeArtifactKey(ValueError):
    pass


class LocalArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        key_path = PurePosixPath(key)
        if key_path.is_absolute() or not key_path.parts or ".." in key_path.parts:
            raise UnsafeArtifactKey(f"Unsafe artifact key: {key!r}")
        target = self.root.joinpath(*key_path.parts).resolve()
        if target != self.root and self.root not in target.parents:
            raise UnsafeArtifactKey(f"Artifact key escapes storage root: {key!r}")
        return target

    def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type  # Local files preserve type through their extension.
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        start = self._path(prefix)
        if not start.exists():
            return []
        files = [start] if start.is_file() else [path for path in start.rglob("*") if path.is_file()]
        return sorted(path.relative_to(self.root).as_posix() for path in files)


@dataclass(frozen=True)
class StoredWikiArtifact:
    key: str
    content_hash: str
    source_revision: str


def get_artifact_store() -> ArtifactStore:
    default_root = Path(__file__).resolve().parents[2] / "data" / "wiki_artifacts"
    return LocalArtifactStore(os.getenv("AUTOSDLC_ARTIFACT_ROOT", str(default_root)))


def _markdown(page: dict) -> str:
    blocks = [f"# {page['title']}", "", page.get("summary", "").strip()]
    for section in page.get("sections", []):
        blocks.extend(["", f"## {section['heading']}", "", section["body"].strip()])
    return "\n".join(blocks).rstrip() + "\n"


def write_wiki_artifacts(
    store: ArtifactStore,
    *,
    project_id: int,
    repo_id: int | None,
    source_revision: str,
    page: dict,
    sources: list[dict],
    extra_artifacts: dict[str, str] | None = None,
) -> StoredWikiArtifact:
    markdown = _markdown(page).encode("utf-8")
    content_hash = sha256(markdown).hexdigest()
    revision_key = source_revision if source_revision.replace("-", "").isalnum() else sha256(source_revision.encode()).hexdigest()[:16]
    scope = "product" if repo_id is None else f"repo-{repo_id}"
    # Immutable and naturally deduplicated: a regeneration at the same source
    # commit gets its own bundle only when the actual wiki content changed.
    # This object-key layout maps directly to S3 without mutable overwrites.
    prefix = f"project-{project_id}/{scope}/{revision_key}/{content_hash[:16]}"
    overview_key = f"{prefix}/overview.md"
    index = {"title": page["title"], "summary": page.get("summary", ""), "sections": page.get("sections", [])}
    artifact_names = {"overview": "overview.md", "index": "index.json"}
    for name in sorted(extra_artifacts or {}):
        artifact_names[name.rsplit(".", 1)[0]] = name
    manifest = {
        "schema_version": 2,
        "project_id": project_id,
        "repo_id": repo_id,
        "source_revision": source_revision,
        "content_hash": content_hash,
        "artifacts": artifact_names,
        "sources": sources,
    }
    store.put(overview_key, markdown, "text/markdown; charset=utf-8")
    store.put(f"{prefix}/index.json", json.dumps(index, indent=2, ensure_ascii=False).encode(), "application/json")
    for name, content in (extra_artifacts or {}).items():
        content_type = "application/json" if name.endswith(".json") else "text/markdown; charset=utf-8"
        store.put(f"{prefix}/{name}", content.encode("utf-8"), content_type)
    store.put(f"{prefix}/manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode(), "application/json")
    return StoredWikiArtifact(overview_key, content_hash, source_revision)
