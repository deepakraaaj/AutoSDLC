from __future__ import annotations

import os
import re
from typing import Any

import httpx

from schemas import GenerationOutput


DEFAULT_TRACKER_REFS = ("Epic", "Story", "Task")
DEFAULT_REQUIRED_CUSTOM_FIELDS = (
    "Priority Level",
    "Confidence",
    "Feature Area",
    "Story Size",
    "AutoSDLC ID",
)
DEFAULT_PRIORITY_IDS = {
    "critical": 5,
    "high": 4,
    "medium": 2,
    "low": 1,
}
PRIORITY_NAME_CANDIDATES = {
    "critical": ("immediate", "urgent", "high", "normal", "low"),
    "high": ("urgent", "high", "normal", "low", "immediate"),
    "medium": ("normal", "high", "urgent", "low", "immediate"),
    "low": ("low", "normal", "high", "urgent", "immediate"),
}
DEFAULT_PROJECT_MODULES = ("issue_tracking", "time_tracking", "wiki")
DEFAULT_PROJECT_CATEGORIES = ("Backend", "Frontend", "QA")
DEFAULT_PROJECT_VERSIONS = (
    {
        "name": "MVP",
        "description": "Initial delivery slice for the project.",
        "status": "open",
        "sharing": "none",
    },
)

SUBJECT_SEQUENCE_RE = re.compile(r"^\[(?P<prefix>[EST])(?P<number>\d+)\]\s*")


class RedmineConfig:
    def __init__(self, url: str = "", api_key: str = "", project_id: str = ""):
        self.url = (url or os.getenv("REDMINE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("REDMINE_API_KEY", "")
        self.project_id = project_id or os.getenv("REDMINE_PROJECT_ID", "")
        self.epic_tracker_id = os.getenv("REDMINE_EPIC_TRACKER_ID", "Epic")
        self.story_tracker_id = os.getenv("REDMINE_STORY_TRACKER_ID", "Story")
        self.task_tracker_id = os.getenv("REDMINE_TASK_TRACKER_ID", "Task")

    @classmethod
    def from_env(cls) -> "RedmineConfig":
        return cls(
            url=os.getenv("REDMINE_URL", ""),
            api_key=os.getenv("REDMINE_API_KEY", ""),
            project_id=os.getenv("REDMINE_PROJECT_ID", "")
        )

    def is_configured(self) -> bool:
        return bool(self.url and self.api_key and self.project_id)


def resolve_project_id(redmine_url: str, api_key: str, project_ref: str) -> str:
    """Resolve a Redmine project identifier or numeric id to the canonical numeric id."""
    project_ref = str(project_ref).strip()
    if not project_ref:
        raise ValueError("Project identifier is empty")

    try:
        response = httpx.get(
            f"{redmine_url}/projects/{project_ref}.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        project = response.json().get("project", {})
        project_id = project.get("id")
        if project_id is not None:
            return str(project_id)
    except Exception:
        pass

    return project_ref


def get_tracker_id(redmine_url: str, api_key: str, tracker_name: str) -> str | None:
    """Get tracker ID by name or numeric id from Redmine."""
    tracker_ref = str(tracker_name).strip()
    if not tracker_ref:
        return None

    try:
        response = httpx.get(
            f"{redmine_url}/trackers.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10
        )
        response.raise_for_status()
        trackers = response.json().get("trackers", [])
        for tracker in trackers:
            tracker_id = str(tracker.get("id", "")).strip()
            name = str(tracker.get("name", "")).strip()
            if tracker_ref == tracker_id or tracker_ref == name:
                return str(tracker.get("id"))
        return None
    except Exception:
        return None


def get_custom_field_id_map(redmine_url: str, api_key: str) -> dict[str, int]:
    """Return issue custom field ids keyed by field name."""
    try:
        response = httpx.get(
            f"{redmine_url}/custom_fields.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        fields = response.json().get("custom_fields", [])
        field_map: dict[str, int] = {}
        for field in fields:
            if field.get("customized_type") not in (None, "issue"):
                continue
            field_id = field.get("id")
            name = field.get("name")
            if field_id is not None and name:
                field_map[str(name)] = int(field_id)
        return field_map
    except Exception:
        return {}


def list_redmine_projects(redmine_url: str, api_key: str) -> list[dict]:
    """List Redmine projects with hierarchical parent/child metadata."""
    projects: list[dict[str, Any]] = []
    offset = 0
    limit = 100

    while True:
        response = httpx.get(
            f"{redmine_url}/projects.json",
            headers={"X-Redmine-API-Key": api_key},
            params={"limit": limit, "offset": offset},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        batch = data.get("projects", [])
        projects.extend(batch)

        total_count = data.get("total_count")
        if total_count is not None and len(projects) >= int(total_count):
            break
        if len(batch) < limit:
            break
        offset += len(batch)

    detail_map: dict[int, dict[str, Any]] = {}
    for project in projects:
        project_ref = project.get("identifier") or project.get("id")
        detail = project
        try:
            response = httpx.get(
                f"{redmine_url}/projects/{project_ref}.json",
                headers={"X-Redmine-API-Key": api_key},
                params={"include": "trackers"},
                timeout=10,
            )
            response.raise_for_status()
            detail = response.json().get("project", project)
        except Exception:
            pass

        parent = detail.get("parent") or {}
        parent_id = None
        parent_identifier = None
        parent_name = None
        if isinstance(parent, dict):
            parent_id = parent.get("id")
            parent_identifier = parent.get("identifier")
            parent_name = parent.get("name")
        elif detail.get("parent_id") is not None:
            parent_id = detail.get("parent_id")

        node = {
            "id": detail.get("id"),
            "name": detail.get("name"),
            "identifier": detail.get("identifier"),
            "description": detail.get("description", ""),
            "status": detail.get("status"),
            "is_public": detail.get("is_public"),
            "inherit_members": detail.get("inherit_members"),
            "parent_id": parent_id,
            "parent_identifier": parent_identifier,
            "parent_name": parent_name,
            "trackers": detail.get("trackers", []),
            "children": [],
        }
        if node["id"] is not None:
            detail_map[int(node["id"])] = node

    roots: list[dict[str, Any]] = []
    for node in detail_map.values():
        parent_id = node.get("parent_id")
        if parent_id and parent_id in detail_map:
            detail_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    def sort_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(items, key=lambda item: str(item.get("name", "")).lower())
        for item in ordered:
            item["children"] = sort_tree(item.get("children", []))
        return ordered

    return sort_tree(roots)


def flatten_redmine_projects(projects: list[dict], depth: int = 0, prefix: str = "") -> list[dict]:
    """Flatten a project tree into dropdown-friendly option rows."""
    options: list[dict[str, Any]] = []
    ordered = sorted(projects, key=lambda item: str(item.get("name", "")).lower())
    for project in ordered:
        name = str(project.get("name", ""))
        identifier = str(project.get("identifier") or project.get("id") or "").strip()
        path = f"{prefix} / {name}" if prefix else name
        label_prefix = "  " * depth
        if depth > 0:
            label_prefix += "└─ "
        options.append({
            "value": identifier,
            "label": f"{label_prefix}{name}",
            "path": path,
            "depth": depth,
            "id": project.get("id"),
            "name": name,
            "identifier": project.get("identifier"),
            "parent_id": project.get("parent_id"),
            "parent_identifier": project.get("parent_identifier"),
            "parent_name": project.get("parent_name"),
        })
        options.extend(flatten_redmine_projects(project.get("children", []), depth + 1, path))
    return options


def describe_redmine_workspace(redmine_url: str, api_key: str) -> dict:
    """Return projects, trackers, and default metadata readiness for a Redmine instance."""
    projects = list_redmine_projects(redmine_url, api_key)
    project_options = flatten_redmine_projects(projects)
    trackers = list_trackers(redmine_url, api_key)
    custom_fields = list_issue_custom_fields(redmine_url, api_key)
    tracker_map = {str(tracker.get("name")): str(tracker.get("id")) for tracker in trackers if tracker.get("name") and tracker.get("id") is not None}
    custom_field_map = {
        str(field.get("name")): str(field.get("id"))
        for field in custom_fields
        if field.get("name") and field.get("id") is not None
    }
    missing_tracker_defaults = [
        str(tracker.get("name"))
        for tracker in trackers
        if tracker.get("name") and not tracker.get("default_status")
    ]
    return {
        "projects": projects,
        "project_options": project_options,
        "trackers": trackers,
        "custom_fields": custom_fields,
        "defaults": {
            "required_trackers": list(DEFAULT_TRACKER_REFS),
            "missing_trackers": [name for name in DEFAULT_TRACKER_REFS if name not in tracker_map],
            "required_custom_fields": list(DEFAULT_REQUIRED_CUSTOM_FIELDS),
            "missing_custom_fields": [name for name in DEFAULT_REQUIRED_CUSTOM_FIELDS if name not in custom_field_map],
            "missing_tracker_defaults": missing_tracker_defaults,
        },
    }


def list_trackers(redmine_url: str, api_key: str) -> list[dict]:
    """List Redmine trackers."""
    try:
        response = httpx.get(
            f"{redmine_url}/trackers.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("trackers", [])
    except Exception:
        return []


def list_issue_custom_fields(redmine_url: str, api_key: str) -> list[dict]:
    """List Redmine issue custom fields."""
    try:
        response = httpx.get(
            f"{redmine_url}/custom_fields.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        fields = response.json().get("custom_fields", [])
        return [field for field in fields if field.get("customized_type") in (None, "issue")]
    except Exception:
        return []


def compute_subject_prefix_counters(subjects: list[str]) -> dict[str, int]:
    """Return max numeric counters found in issue subjects, keyed by E/S/T prefix."""
    counters = {"E": 0, "S": 0, "T": 0}
    for subject in subjects:
        match = SUBJECT_SEQUENCE_RE.match(str(subject or "").strip())
        if not match:
            continue
        prefix = match.group("prefix")
        try:
            number = int(match.group("number"))
        except ValueError:
            continue
        if number > counters[prefix]:
            counters[prefix] = number
    return counters


def get_project_subject_prefix_counters(redmine_url: str, api_key: str, project_id: str) -> dict[str, int]:
    """Scan Redmine issues in a project and return max subject counters for E/S/T."""
    subjects: list[str] = []
    offset = 0
    limit = 100

    while True:
        response = httpx.get(
            f"{redmine_url}/issues.json",
            headers={"X-Redmine-API-Key": api_key},
            params={
                "project_id": project_id,
                "status_id": "*",
                "limit": limit,
                "offset": offset,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json() or {}
        issues = data.get("issues", []) or []
        subjects.extend(issue.get("subject", "") for issue in issues if isinstance(issue, dict))

        total_count = data.get("total_count")
        if total_count is not None:
            offset += len(issues)
            if offset >= int(total_count):
                break
        else:
            if len(issues) < limit:
                break
            offset += len(issues)

        if not issues:
            break

    return compute_subject_prefix_counters(subjects)


def list_issue_priorities(redmine_url: str, api_key: str) -> list[dict]:
    """List Redmine issue priorities."""
    try:
        response = httpx.get(
            f"{redmine_url}/enumerations/issue_priorities.json",
            headers={"X-Redmine-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("issue_priorities", [])
    except Exception:
        return []


def _resolve_priority_id_from_options(priority_options: list[dict], priority_label: str) -> int | None:
    label = str(priority_label or "").strip().lower()
    active_options = [
        option
        for option in priority_options
        if option.get("id") is not None and option.get("active", True)
    ]
    if not active_options:
        return None

    name_to_id = {
        str(option.get("name", "")).strip().lower(): int(option["id"])
        for option in active_options
        if option.get("name")
    }

    for candidate in PRIORITY_NAME_CANDIDATES.get(label, PRIORITY_NAME_CANDIDATES["medium"]):
        if candidate in name_to_id:
            return name_to_id[candidate]

    default_id = next((int(option["id"]) for option in active_options if option.get("is_default")), None)
    if default_id is not None:
        return default_id

    ordered = sorted(active_options, key=lambda option: int(option["id"]))
    if label == "critical":
        return int(ordered[-1]["id"])
    if label == "high":
        return int(ordered[max(len(ordered) - 2, 0)]["id"])
    if label == "low":
        return int(ordered[0]["id"])
    return int(ordered[min(len(ordered) // 2, len(ordered) - 1)]["id"])


def build_priority_id_map(redmine_url: str, api_key: str) -> dict[str, int]:
    """Resolve the app's priority labels to Redmine issue priority IDs."""
    priority_options = list_issue_priorities(redmine_url, api_key)
    priority_map: dict[str, int] = {}
    for label, fallback_id in DEFAULT_PRIORITY_IDS.items():
        resolved = _resolve_priority_id_from_options(priority_options, label)
        priority_map[label] = resolved if resolved is not None else fallback_id
    return priority_map


def create_redmine_project(
    redmine_url: str,
    api_key: str,
    name: str,
    identifier: str | None = None,
    description: str = "",
    parent_project_ref: str | None = None,
    is_public: bool = True,
    inherit_members: bool = False,
    tracker_refs: list[str] | None = None,
    issue_categories: list[str] | None = None,
    versions: list[dict[str, Any]] | None = None,
) -> dict:
    """Create a Redmine project with a standard IT-project template."""
    tracker_refs = tracker_refs or list(DEFAULT_TRACKER_REFS)
    tracker_ids: list[int] = []
    missing_trackers: list[str] = []
    for tracker_ref in tracker_refs:
        tracker_id = get_tracker_id(redmine_url, api_key, tracker_ref)
        if tracker_id is None:
            missing_trackers.append(tracker_ref)
            continue
        tracker_ids.append(int(tracker_id))

    if missing_trackers:
        raise ValueError(f"Missing Redmine trackers: {', '.join(missing_trackers)}")

    custom_field_map = get_custom_field_id_map(redmine_url, api_key)

    project_identifier = identifier.strip() if identifier else ""
    if not project_identifier:
        project_identifier = slugify_identifier(name)

    payload = {
        "project": {
            "name": name,
            "identifier": project_identifier,
            "description": description,
            "is_public": is_public,
            "inherit_members": inherit_members,
            "tracker_ids": tracker_ids,
            "enabled_module_names": list(DEFAULT_PROJECT_MODULES),
        }
    }

    if parent_project_ref:
        parent_id = resolve_project_id(redmine_url, api_key, parent_project_ref)
        if not parent_id or not str(parent_id).isdigit():
            raise ValueError(f"Parent project '{parent_project_ref}' not found")
        payload["project"]["parent_id"] = int(parent_id)

    response = httpx.post(
        f"{redmine_url}/projects.json",
        json=payload,
        headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    created_project = response.json().get("project", {})
    created_identifier = created_project.get("identifier") or project_identifier

    categories = issue_categories or list(DEFAULT_PROJECT_CATEGORIES)
    for category in categories:
        curl_payload = {"issue_category": {"name": category}}
        httpx.post(
            f"{redmine_url}/projects/{created_identifier}/issue_categories.json",
            json=curl_payload,
            headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
            timeout=10,
        ).raise_for_status()

    project_versions = versions or [dict(DEFAULT_PROJECT_VERSIONS[0])]
    for version in project_versions:
        version_payload = {"version": dict(version)}
        httpx.post(
            f"{redmine_url}/projects/{created_identifier}/versions.json",
            json=version_payload,
            headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
            timeout=10,
        ).raise_for_status()

    project_detail = created_project
    try:
        response = httpx.get(
            f"{redmine_url}/projects/{created_identifier}.json",
            headers={"X-Redmine-API-Key": api_key},
            params={"include": "trackers"},
            timeout=10,
        )
        response.raise_for_status()
        project_detail = response.json().get("project", created_project)
    except Exception:
        pass

    return {
        "project": project_detail,
        "missing_trackers": [],
        "missing_custom_fields": [
            name for name in DEFAULT_REQUIRED_CUSTOM_FIELDS if name not in custom_field_map
        ],
    }


def build_issue_custom_fields(custom_field_map: dict[str, int], values: dict[str, Any]) -> list[dict]:
    """Format issue custom field payloads for Redmine."""
    payload: list[dict[str, Any]] = []
    for field_name, value in values.items():
        field_id = custom_field_map.get(field_name)
        if field_id is None or value in (None, "", []):
            continue
        payload.append({"id": field_id, "value": str(value)})
    return payload


def _create_issue(redmine_url: str, api_key: str, payload: dict) -> dict:
    response = httpx.post(
        f"{redmine_url}/issues.json",
        json=payload,
        headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    if response.is_error:
        detail = _extract_redmine_error(response)
        raise RuntimeError(f"Redmine issue create failed ({response.status_code}): {detail}")
    return response.json().get("issue", {})


def _get_issue(redmine_url: str, api_key: str, issue_id: int | str) -> dict:
    response = httpx.get(
        f"{redmine_url}/issues/{issue_id}.json",
        headers={"X-Redmine-API-Key": api_key},
        timeout=10,
    )
    if response.is_error:
        detail = _extract_redmine_error(response)
        raise RuntimeError(f"Redmine issue lookup failed ({response.status_code}): {detail}")
    return response.json().get("issue", {})


def _extract_priority_metadata(issue: dict[str, Any]) -> dict[str, Any]:
    priority = issue.get("priority")
    if not isinstance(priority, dict):
        return {"redmine_priority_id": None, "redmine_priority_name": None}

    priority_id = priority.get("id")
    try:
        priority_id = int(priority_id) if priority_id is not None else None
    except (TypeError, ValueError):
        priority_id = None

    priority_name = str(priority.get("name", "")).strip() or None
    return {
        "redmine_priority_id": priority_id,
        "redmine_priority_name": priority_name,
    }


def _get_created_issue_metadata(redmine_url: str, api_key: str, issue_data: dict[str, Any]) -> dict[str, Any]:
    issue_id = issue_data.get("id")
    metadata = {
        "redmine_id": issue_id,
        "redmine_priority_id": None,
        "redmine_priority_name": None,
    }
    if issue_id is None:
        return metadata

    try:
        created_issue = _get_issue(redmine_url, api_key, issue_id)
    except Exception:
        metadata.update(_extract_priority_metadata(issue_data))
        return metadata

    metadata.update(_extract_priority_metadata(created_issue))
    return metadata


def _extract_redmine_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"

    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            messages = [str(item).strip() for item in errors if str(item).strip()]
            if messages:
                return "; ".join(messages)
        elif errors:
            return str(errors)

        for key in ("error", "message", "detail"):
            value = body.get(key)
            if value:
                return str(value)

    text = response.text.strip()
    if text:
        return text
    return f"HTTP {response.status_code}"


def _get_project_enabled_tracker_ids(redmine_url: str, api_key: str, project_ref: str) -> set[int]:
    """Return the tracker ids currently enabled for a Redmine project."""
    response = httpx.get(
        f"{redmine_url}/projects/{project_ref}.json",
        headers={"X-Redmine-API-Key": api_key},
        params={"include": "trackers"},
        timeout=10,
    )
    if response.is_error:
        detail = _extract_redmine_error(response)
        raise RuntimeError(
            f"Redmine project lookup failed ({response.status_code}) for '{project_ref}': {detail}"
        )

    project = (response.json() or {}).get("project", {}) or {}
    tracker_ids: set[int] = set()
    for tracker in project.get("trackers", []) or []:
        if not isinstance(tracker, dict):
            continue
        tracker_id = tracker.get("id")
        if tracker_id is None:
            continue
        try:
            tracker_ids.add(int(tracker_id))
        except (TypeError, ValueError):
            continue
    return tracker_ids


def _set_project_tracker_ids(
    redmine_url: str,
    api_key: str,
    project_ref: str,
    tracker_ids: set[int],
) -> None:
    """Update a Redmine project's enabled trackers."""
    payload = {"project": {"tracker_ids": sorted(tracker_ids)}}
    response = httpx.put(
        f"{redmine_url}/projects/{project_ref}.json",
        json=payload,
        headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    if response.is_error:
        detail = _extract_redmine_error(response)
        raise RuntimeError(
            f"Redmine project tracker update failed ({response.status_code}) for '{project_ref}': {detail}"
        )


def push_to_redmine(output: GenerationOutput, config: RedmineConfig) -> dict:
    """Push stories and tasks to Redmine. Returns created issue info."""
    if not config.is_configured():
        raise ValueError("Redmine not configured. Set REDMINE_URL, REDMINE_API_KEY, REDMINE_PROJECT_ID in .env")

    project_id = resolve_project_id(config.url, config.api_key, config.project_id)
    created_issues = []
    warnings: list[str] = []
    epic_to_redmine_id = {}
    story_to_redmine_id = {}
    priority_map = build_priority_id_map(config.url, config.api_key)
    priority_override_detected = False

    epic_tracker_id = get_tracker_id(config.url, config.api_key, config.epic_tracker_id)
    story_tracker_id = get_tracker_id(config.url, config.api_key, config.story_tracker_id)
    task_tracker_id = get_tracker_id(config.url, config.api_key, config.task_tracker_id)

    if not epic_tracker_id:
        raise ValueError(f"Tracker '{config.epic_tracker_id}' not found in Redmine")
    if not story_tracker_id:
        raise ValueError(f"Tracker '{config.story_tracker_id}' not found in Redmine")
    if not task_tracker_id:
        raise ValueError(f"Tracker '{config.task_tracker_id}' not found in Redmine")

    # Redmine projects must explicitly enable trackers. If Story isn't enabled, Redmine may silently
    # coerce issues into a different tracker, which breaks reporting and counts.
    required_trackers = [
        (int(epic_tracker_id), str(config.epic_tracker_id)),
        (int(story_tracker_id), str(config.story_tracker_id)),
        (int(task_tracker_id), str(config.task_tracker_id)),
    ]
    enabled_tracker_ids = _get_project_enabled_tracker_ids(config.url, config.api_key, project_id)
    missing_tracker_names = [
        name for tracker_id, name in required_trackers if tracker_id not in enabled_tracker_ids
    ]
    if missing_tracker_names:
        try:
            new_tracker_ids = enabled_tracker_ids.union({tracker_id for tracker_id, _ in required_trackers})
            _set_project_tracker_ids(config.url, config.api_key, project_id, new_tracker_ids)
            warnings.append(
                f"Enabled missing trackers for project '{config.project_id}': {', '.join(missing_tracker_names)}"
            )
        except Exception as e:
            missing = ", ".join(missing_tracker_names)
            raise ValueError(
                f"Redmine project '{config.project_id}' is missing enabled trackers ({missing}). "
                f"Enable them in Project settings → Trackers. ({e})"
            )

    custom_field_map = get_custom_field_id_map(config.url, config.api_key)
    missing_custom_fields = [name for name in DEFAULT_REQUIRED_CUSTOM_FIELDS if name not in custom_field_map]
    if missing_custom_fields:
        warnings.append(
            "Missing Redmine custom fields: " + ", ".join(missing_custom_fields)
        )

    counters = get_project_subject_prefix_counters(config.url, config.api_key, project_id)
    next_epic_number = counters["E"] + 1
    next_story_number = counters["S"] + 1
    next_task_number = counters["T"] + 1

    # Create Epic issues
    for epic in output.epics:
        display_id = f"E{next_epic_number}"
        next_epic_number += 1
        description = f"{epic.description}\n\n*Feature Area:* {epic.feature_area}"
        custom_fields = build_issue_custom_fields(custom_field_map, {
            "Priority Level": epic.priority,
            "Feature Area": epic.feature_area,
            "AutoSDLC ID": epic.id,
        })
        payload = {
            "issue": {
                "project_id": project_id,
                "tracker_id": epic_tracker_id,
                "subject": f"[{display_id}] {epic.title}",
                "description": description,
                "priority_id": priority_map.get(epic.priority, 4),
            }
        }
        if custom_fields:
            payload["issue"]["custom_fields"] = custom_fields

        try:
            issue_data = _create_issue(config.url, config.api_key, payload)
            issue_meta = _get_created_issue_metadata(config.url, config.api_key, issue_data)
            issue_id = issue_meta.get("redmine_id")
            epic_to_redmine_id[epic.id] = issue_id
            if issue_meta.get("redmine_priority_id") not in (None, payload["issue"]["priority_id"]):
                priority_override_detected = True
            created_issues.append({
                "ai_id": epic.id,
                "display_id": display_id,
                "type": "epic",
                "redmine_id": issue_id,
                "redmine_priority_name": issue_meta.get("redmine_priority_name"),
                "url": f"{config.url}/issues/{issue_id}",
                "status": "created"
            })
        except Exception as e:
            created_issues.append({
                "ai_id": epic.id,
                "display_id": display_id,
                "type": "epic",
                "error": str(e)
            })

    # Create Story issues as children of Epics
    for story in output.stories:
        parent_id = epic_to_redmine_id.get(story.epic_id) if story.epic_id else None
        display_id = f"S{next_story_number}"
        next_story_number += 1
        ac_text = "\n".join(f"• {ac}" for ac in story.acceptance_criteria)
        custom_fields = build_issue_custom_fields(custom_field_map, {
            "Priority Level": story.priority,
            "Confidence": story.confidence,
            "Feature Area": story.feature_area,
            "Story Size": story.size,
            "AutoSDLC ID": story.id,
        })
        description = (
            f"*As a* {story.as_a}\n"
            f"*I want to* {story.i_want}\n"
            f"*So that* {story.so_that}\n\n"
            f"*Acceptance Criteria:*\n{ac_text}\n\n"
            f"*Size:* {story.size} | *Confidence:* {story.confidence} | *Area:* {story.feature_area}"
        )

        payload = {
            "issue": {
                "project_id": project_id,
                "tracker_id": story_tracker_id,
                "subject": f"[{display_id}] {story.title}",
                "description": description,
                "priority_id": priority_map.get(story.priority, 4),
            }
        }
        if custom_fields:
            payload["issue"]["custom_fields"] = custom_fields

        if parent_id:
            payload["issue"]["parent_issue_id"] = parent_id

        try:
            issue_data = _create_issue(config.url, config.api_key, payload)
            issue_meta = _get_created_issue_metadata(config.url, config.api_key, issue_data)
            issue_id = issue_meta.get("redmine_id")
            story_to_redmine_id[story.id] = issue_id
            if issue_meta.get("redmine_priority_id") not in (None, payload["issue"]["priority_id"]):
                priority_override_detected = True
            created_issues.append({
                "ai_id": story.id,
                "display_id": display_id,
                "type": "story",
                "redmine_id": issue_id,
                "redmine_priority_name": issue_meta.get("redmine_priority_name"),
                "url": f"{config.url}/issues/{issue_id}",
                "status": "created"
            })
        except Exception as e:
            created_issues.append({
                "ai_id": story.id,
                "display_id": display_id,
                "type": "story",
                "error": str(e)
            })

    # Create Task issues as children of Stories
    for task in output.tasks:
        parent_id = story_to_redmine_id.get(task.story_id) if task.story_id else None
        display_id = f"T{next_task_number}"
        next_task_number += 1
        deps_text = "\n".join(f"• {d}" for d in task.dependencies) if task.dependencies else "None"
        parent_story = next((story for story in output.stories if story.id == task.story_id), None)
        task_feature_area = parent_story.feature_area if parent_story else ""
        custom_fields = build_issue_custom_fields(custom_field_map, {
            "Priority Level": task.priority,
            "Confidence": task.confidence,
            "Feature Area": task_feature_area,
            "AutoSDLC ID": task.id,
        })
        description = (
            f"{task.description}\n\n"
            f"*Definition of Done:*\n{task.definition_of_done}\n\n"
            f"*Dependencies:*\n{deps_text}\n\n"
            f"*Confidence:* {task.confidence}"
        )

        try:
            est_hours = float(task.estimate_hours.split('-')[0].strip()) if task.estimate_hours else None
        except (ValueError, IndexError, AttributeError):
            est_hours = None

        payload = {
            "issue": {
                "project_id": project_id,
                "tracker_id": task_tracker_id,
                "subject": f"[{display_id}] {task.title}",
                "description": description,
                "priority_id": priority_map.get(task.priority, 4),
                "estimated_hours": est_hours,
            }
        }
        if custom_fields:
            payload["issue"]["custom_fields"] = custom_fields

        if parent_id:
            payload["issue"]["parent_issue_id"] = parent_id

        try:
            issue_data = _create_issue(config.url, config.api_key, payload)
            issue_meta = _get_created_issue_metadata(config.url, config.api_key, issue_data)
            issue_id = issue_meta.get("redmine_id")
            if issue_meta.get("redmine_priority_id") not in (None, payload["issue"]["priority_id"]):
                priority_override_detected = True
            created_issues.append({
                "ai_id": task.id,
                "display_id": display_id,
                "type": "task",
                "redmine_id": issue_id,
                "redmine_priority_name": issue_meta.get("redmine_priority_name"),
                "url": f"{config.url}/issues/{issue_id}",
                "status": "created"
            })
        except Exception as e:
            created_issues.append({
                "ai_id": task.id,
                "display_id": display_id,
                "type": "task",
                "error": str(e)
            })

    if priority_override_detected:
        warnings.append(
            "Redmine changed one or more issue priorities from the generated values. "
            "Check the API user's permission to set issue priorities and the target project's priority configuration."
        )

    result = {"created_issues": created_issues}
    if warnings:
        result["warnings"] = warnings
    return result
