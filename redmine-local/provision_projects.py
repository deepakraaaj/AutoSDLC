#!/usr/bin/env python3
"""Provision repeatable Redmine projects from a JSON template.

This uses curl for the Redmine REST calls so the provisioning flow stays
portable and easy to inspect from the terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = ROOT / "compose.yaml"
DEFAULT_TEMPLATE = ROOT / "projects.template.json"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision Redmine projects from a JSON template.")
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="Path to the JSON template file.",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("REDMINE_URL", "http://localhost:3001"),
        help="Redmine base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("REDMINE_API_KEY", ""),
        help="Redmine API key.",
    )
    parser.add_argument(
        "--skip-tracker-seed",
        action="store_true",
        help="Skip the one-time Epic/Story/Task tracker and issue custom field seed step.",
    )
    return parser.parse_args()


def run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def curl_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, str]:
    cmd = [
        "curl",
        "-sS",
        "-X",
        method,
        "-H",
        "Accept: application/json",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"X-Redmine-API-Key: {api_key}",
    ]
    if payload is not None:
        cmd.extend(["--data-binary", "@-"])
    cmd.extend([url, "-w", "\n__STATUS__%{http_code}"])
    result = run(cmd, input_text=json.dumps(payload) if payload is not None else None)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "curl failed"
        raise RuntimeError(stderr)

    body, _, status_text = result.stdout.rpartition("\n__STATUS__")
    if not status_text.isdigit():
        raise RuntimeError(f"Could not parse HTTP status from response for {url}")

    status = int(status_text)
    if status >= 400:
        detail = body.strip() or result.stderr.strip() or "Unknown Redmine API error"
        raise RuntimeError(f"HTTP {status} calling {url}: {detail}")

    return status, body.strip()


def seed_trackers() -> None:
    ruby = (
        'new_status = IssueStatus.find_by!(name: "New"); '
        '[{"name"=>"Epic","description"=>"Parent issues / epics","is_in_roadmap"=>true},'
        '{"name"=>"Story","description"=>"User stories / feature work","is_in_roadmap"=>true},'
        '{"name"=>"Task","description"=>"Implementation tasks","is_in_roadmap"=>false}].each do |attrs|; '
        'tracker = Tracker.find_or_initialize_by(name: attrs["name"]); '
        'tracker.description = attrs["description"]; '
        'tracker.default_status = new_status; '
        'tracker.is_in_roadmap = attrs["is_in_roadmap"]; '
        'tracker.position = Tracker.maximum(:position).to_i + 1 if tracker.new_record?; '
        'tracker.save!; end; '
        'field_specs = ['
        '{"name"=>"Priority Level","field_format"=>"list","possible_values"=>"critical\\nhigh\\nmedium\\nlow"},'
        '{"name"=>"Confidence","field_format"=>"list","possible_values"=>"high\\nmedium\\nlow"},'
        '{"name"=>"Feature Area","field_format"=>"string"},'
        '{"name"=>"Story Size","field_format"=>"list","possible_values"=>"small\\nmedium\\nlarge"},'
        '{"name"=>"AutoSDLC ID","field_format"=>"string"}'
        ']; '
        'field_specs.each do |attrs|; '
        'field = IssueCustomField.find_or_initialize_by(name: attrs["name"]); '
        'field.type = "IssueCustomField"; '
        'field.field_format = attrs["field_format"]; '
        'field.is_required = false; '
        'field.is_for_all = true; '
        'field.is_filter = true; '
        'field.searchable = true; '
        'field.visible = true; '
        'field.editable = true; '
        'field.possible_values = attrs["possible_values"] if attrs["possible_values"]; '
        'field.save!; end; '
        'puts Tracker.where(name: ["Epic", "Story", "Task"]).pluck(:id, :name).map { |id, name| "#{name}=#{id}" }.join(", "); '
        'puts IssueCustomField.where(name: ["Priority Level", "Confidence", "Feature Area", "Story Size", "AutoSDLC ID"]).pluck(:id, :name).map { |id, name| "#{name}=#{id}" }.join(", ")'
    )
    cmd = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "exec",
        "-T",
        "redmine",
        "bundle",
        "exec",
        "rails",
        "runner",
        ruby,
    ]
    result = run(cmd)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "tracker seed failed"
        raise RuntimeError(stderr)


def get_tracker_id_map(url: str, api_key: str) -> dict[str, int]:
    status, body = curl_json("GET", f"{url.rstrip('/')}/trackers.json", api_key)
    data = json.loads(body) if body else {}
    trackers = data.get("trackers", [])
    tracker_map: dict[str, int] = {}
    for tracker in trackers:
        name = tracker.get("name")
        tracker_id = tracker.get("id")
        if name and tracker_id is not None:
            tracker_map[str(name)] = int(tracker_id)
    return tracker_map


def slugify_identifier(value: str) -> str:
    slug = []
    last_was_dash = False
    for ch in value.lower().strip():
        if ch.isalnum():
            slug.append(ch)
            last_was_dash = False
        elif ch in {" ", "-", "_"} and not last_was_dash:
            slug.append("-")
            last_was_dash = True
    result = "".join(slug).strip("-")
    return result or "project"


def merge_project(defaults: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    merged.update(project)
    return merged


def create_project(url: str, api_key: str, project: dict[str, Any], tracker_map: dict[str, int]) -> dict[str, Any]:
    tracker_names = project.get("tracker_names", [])
    tracker_ids = []
    for tracker_name in tracker_names:
        tracker_id = tracker_map.get(str(tracker_name))
        if tracker_id is None:
            raise RuntimeError(f"Tracker '{tracker_name}' is missing. Run the tracker seed step first.")
        tracker_ids.append(tracker_id)

    identifier = project.get("identifier") or slugify_identifier(str(project["name"]))
    payload = {
        "project": {
            "name": project["name"],
            "identifier": identifier,
            "description": project.get("description", ""),
            "is_public": bool(project.get("is_public", True)),
            "inherit_members": bool(project.get("inherit_members", False)),
            "tracker_ids": tracker_ids,
            "enabled_module_names": project.get("enabled_module_names", []),
        }
    }
    if project.get("homepage"):
        payload["project"]["homepage"] = project["homepage"]

    status, body = curl_json("POST", f"{url.rstrip('/')}/projects.json", api_key, payload)
    response = json.loads(body) if body else {}
    created = response.get("project", {})
    created_identifier = created.get("identifier") or identifier

    for category in project.get("issue_categories", []):
        category_payload = {"issue_category": {"name": category}}
        curl_json(
            "POST",
            f"{url.rstrip('/')}/projects/{created_identifier}/issue_categories.json",
            api_key,
            category_payload,
        )

    for version in project.get("versions", []):
        if isinstance(version, str):
            version_payload = {"version": {"name": version}}
        else:
            version_payload = {"version": dict(version)}
        curl_json(
            "POST",
            f"{url.rstrip('/')}/projects/{created_identifier}/versions.json",
            api_key,
            version_payload,
        )

    return {
        "name": project["name"],
        "identifier": created_identifier,
        "status": status,
    }


def main() -> int:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT.parent / ".env")

    args = parse_args()
    if not args.api_key:
        print("Missing REDMINE_API_KEY. Export it or add it to story-generator/redmine-local/.env.", file=sys.stderr)
        return 1

    if not args.template.exists():
        print(f"Template file not found: {args.template}", file=sys.stderr)
        return 1

    if not args.skip_tracker_seed:
        seed_trackers()

    tracker_map = get_tracker_id_map(args.url, args.api_key)
    template = json.loads(args.template.read_text(encoding="utf-8"))
    defaults = template.get("defaults", {})
    projects = template.get("projects", [])
    if not projects:
        print("Template does not define any projects.", file=sys.stderr)
        return 1

    created_projects = []
    for project_spec in projects:
        project = merge_project(defaults, project_spec)
        if "name" not in project:
            print("Every project entry needs a name.", file=sys.stderr)
            return 1
        if "identifier" not in project:
            project["identifier"] = slugify_identifier(str(project["name"]))
        created_projects.append(create_project(args.url, args.api_key, project, tracker_map))

    print(json.dumps({"created_projects": created_projects}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
