"""Normalized pull-request metadata + diff model, independent of Bitbucket's
raw response shape.

Reuses the existing Bitbucket client wholesale (bitbucket/client.py's
get_pull_request / get_pull_request_diff — no new HTTP/auth code here) and
adds a unified-diff parser plus the PullRequestInfo/PullRequestFileChange/
PullRequestDiff models the rest of the PR-impact pipeline is built on, so
nothing downstream has to know Bitbucket's diff format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re

from bitbucket.client import BitbucketConfig, get_pull_request, get_pull_request_diff

STATUS_ADDED = "ADDED"
STATUS_MODIFIED = "MODIFIED"
STATUS_DELETED = "DELETED"
STATUS_RENAMED = "RENAMED"
STATUS_BINARY = "BINARY"

# Bitbucket truncates a very large PR diff server-side rather than erroring;
# this is our own client-side backstop so an unusually large diff can't
# blow the parser's/LLM's budget either way — same intent as vapt.py's
# MAX_SNAPSHOT_BYTES. Parsing what's within the cap and marking `truncated`
# beats either hanging on a multi-megabyte diff or refusing to analyze it.
MAX_DIFF_BYTES = max(200_000, int(os.getenv("PR_DIFF_MAX_BYTES", "3000000")))
MAX_DIFF_FILES = max(20, int(os.getenv("PR_DIFF_MAX_FILES", "500")))

_DIFF_GIT_LINE = re.compile(r"^diff --git a/(.*) b/(.*)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    added_lines: list[int] = field(default_factory=list)   # new-file line numbers
    removed_lines: list[int] = field(default_factory=list)  # old-file line numbers
    header: str = ""


@dataclass
class PullRequestFileChange:
    path: str
    old_path: str | None
    status: str
    hunks: list[DiffHunk] = field(default_factory=list)
    added_lines: list[int] = field(default_factory=list)
    removed_lines: list[int] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class PullRequestInfo:
    pull_request_id: str
    title: str
    description: str
    source_branch: str
    destination_branch: str
    base_sha: str
    head_sha: str
    author: str | None = None


@dataclass
class PullRequestDiff:
    info: PullRequestInfo
    files: list[PullRequestFileChange]
    truncated: bool = False


def build_pull_request_info(pr: dict, pull_request_id: str | int) -> PullRequestInfo:
    """PullRequestInfo from Bitbucket's raw pullrequest object (the same
    shape get_pull_request/list_pull_requests already return). Bitbucket
    doesn't expose a real merge-base; `destination.commit.hash` (the
    destination branch's tip when the PR was opened/last synced) is the
    closest available approximation of "base" and is documented as such —
    good enough for baseline selection (security/baseline.py), not a claim
    of git merge-base precision."""
    source = pr.get("source") or {}
    destination = pr.get("destination") or {}
    author = ((pr.get("author") or {}).get("display_name")) or None
    return PullRequestInfo(
        pull_request_id=str(pull_request_id),
        title=str(pr.get("title") or "").strip(),
        description=str(pr.get("description") or "").strip(),
        source_branch=((source.get("branch") or {}).get("name")) or "",
        destination_branch=((destination.get("branch") or {}).get("name")) or "",
        base_sha=((destination.get("commit") or {}).get("hash")) or "",
        head_sha=((source.get("commit") or {}).get("hash")) or "",
        author=author,
    )


def _parse_hunk_lines(lines: list[str], start: int, hunk: DiffHunk) -> int:
    """Consume this hunk's body lines starting at `start`, recording added/
    removed new-file/old-file line numbers on `hunk`. Returns the index of
    the first line not belonging to this hunk."""
    old_line = hunk.old_start
    new_line = hunk.new_start
    index = start
    while index < len(lines):
        line = lines[index]
        if line.startswith("@@") or line.startswith("diff --git "):
            break
        if line.startswith("+") and not line.startswith("+++"):
            hunk.added_lines.append(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            hunk.removed_lines.append(old_line)
            old_line += 1
        elif line.startswith("\\"):
            pass  # "\ No newline at end of file" — not a content line
        else:
            old_line += 1
            new_line += 1
        index += 1
    return index


def _parse_one_file(block_lines: list[str]) -> PullRequestFileChange | None:
    header = block_lines[0]
    match = _DIFF_GIT_LINE.match(header)
    if not match:
        return None
    old_path, new_path = match.group(1), match.group(2)
    status = STATUS_MODIFIED
    rename_from: str | None = None
    index = 1
    while index < len(block_lines):
        line = block_lines[index]
        if line.startswith("@@") or line.startswith("--- ") or line.startswith("+++ "):
            break
        if line.startswith("new file mode"):
            status = STATUS_ADDED
        elif line.startswith("deleted file mode"):
            status = STATUS_DELETED
        elif line.startswith("rename from "):
            rename_from = line[len("rename from "):].strip()
            status = STATUS_RENAMED
        elif line.startswith("rename to "):
            status = STATUS_RENAMED
        elif line.startswith("Binary files ") or line.endswith("differ"):
            return PullRequestFileChange(path=new_path, old_path=old_path if old_path != new_path else None, status=STATUS_BINARY)
        index += 1

    hunks: list[DiffHunk] = []
    added_lines: list[int] = []
    removed_lines: list[int] = []
    while index < len(block_lines):
        line = block_lines[index]
        hunk_match = _HUNK_HEADER.match(line)
        if not hunk_match:
            index += 1
            continue
        old_start, old_count, new_start, new_count = hunk_match.groups()
        hunk = DiffHunk(
            old_start=int(old_start), old_lines=int(old_count or 1),
            new_start=int(new_start), new_lines=int(new_count or 1),
            header=line.strip(),
        )
        index = _parse_hunk_lines(block_lines, index + 1, hunk)
        hunks.append(hunk)
        added_lines.extend(hunk.added_lines)
        removed_lines.extend(hunk.removed_lines)

    if status == STATUS_MODIFIED and old_path != new_path:
        status = STATUS_RENAMED
        rename_from = old_path

    return PullRequestFileChange(
        path=new_path,
        old_path=rename_from if status == STATUS_RENAMED else (old_path if status == STATUS_DELETED else None),
        status=status, hunks=hunks, added_lines=added_lines, removed_lines=removed_lines,
    )


def parse_unified_diff(diff_text: str, *, max_files: int = MAX_DIFF_FILES) -> tuple[list[PullRequestFileChange], bool]:
    """Parse a git-style unified diff (Bitbucket's get_pull_request_diff
    output) into PullRequestFileChange records. Never raises: a file block
    that doesn't parse cleanly is still returned, tagged with
    `parse_error`, rather than aborting the whole diff — "one problematic
    file must not crash the entire analysis" is the whole point of this
    function's error handling. Returns (files, truncated)."""
    truncated = False
    if len(diff_text.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        diff_text = diff_text.encode("utf-8", errors="ignore")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        truncated = True

    lines = diff_text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    if len(blocks) > max_files:
        blocks = blocks[:max_files]
        truncated = True

    files: list[PullRequestFileChange] = []
    for block in blocks:
        try:
            parsed = _parse_one_file(block)
        except Exception as exc:  # malformed block — keep going
            match = _DIFF_GIT_LINE.match(block[0]) if block else None
            path = match.group(2) if match else "<unparsable file>"
            files.append(PullRequestFileChange(path=path, old_path=None, status=STATUS_MODIFIED, parse_error=str(exc)[:300]))
            continue
        if parsed:
            files.append(parsed)
    return files, truncated


def fetch_pull_request_diff(config: BitbucketConfig, pull_request_id: str | int) -> PullRequestDiff:
    """The one entry point PR analysis needs: PR metadata + normalized
    diff, built entirely from the existing Bitbucket client
    (get_pull_request/get_pull_request_diff — no new HTTP calls added)."""
    pr = get_pull_request(config, pull_request_id)
    diff_text = get_pull_request_diff(config, pull_request_id)
    info = build_pull_request_info(pr, pull_request_id)
    files, truncated = parse_unified_diff(diff_text)
    return PullRequestDiff(info=info, files=files, truncated=truncated)
