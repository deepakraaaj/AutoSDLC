from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import redmine  # noqa: E402
from schemas import GenerationOutput, Story  # noqa: E402


def test_build_priority_id_map_uses_redmine_enumerations(monkeypatch):
    priorities = [
        {"id": 1, "name": "Low", "active": True},
        {"id": 2, "name": "Normal", "active": True, "is_default": True},
        {"id": 3, "name": "High", "active": True},
        {"id": 4, "name": "Urgent", "active": True},
        {"id": 5, "name": "Immediate", "active": True},
    ]

    monkeypatch.setattr(redmine, "list_issue_priorities", lambda *_: priorities)

    priority_map = redmine.build_priority_id_map("http://example.com", "api-key")

    assert priority_map == {
        "critical": 5,
        "high": 4,
        "medium": 2,
        "low": 1,
    }


def test_push_to_redmine_reads_back_actual_priority(monkeypatch):
    monkeypatch.setattr(redmine, "resolve_project_id", lambda *_: "42")
    monkeypatch.setattr(redmine, "build_priority_id_map", lambda *_: {"critical": 5, "high": 4, "medium": 2, "low": 1})
    monkeypatch.setattr(redmine, "get_tracker_id", lambda *_: "7")
    monkeypatch.setattr(redmine, "_get_project_enabled_tracker_ids", lambda *_: {7})
    monkeypatch.setattr(redmine, "get_custom_field_id_map", lambda *_: {})
    monkeypatch.setattr(redmine, "get_project_subject_prefix_counters", lambda *_: {"E": 0, "S": 0, "T": 0})
    monkeypatch.setattr(
        redmine,
        "_create_issue",
        lambda *_: {"id": 123, "priority": {"id": 5, "name": "Immediate"}},
    )
    monkeypatch.setattr(
        redmine,
        "_get_issue",
        lambda *_: {"id": 123, "priority": {"id": 2, "name": "Normal"}},
    )

    output = GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[],
        stories=[
            Story(
                id="S1",
                title="Prioritized story",
                as_a="user",
                i_want="priority handling",
                so_that="the backlog matches Redmine",
                acceptance_criteria=["Priority is visible."],
                feature_area="Planning",
                size="small",
                confidence="high",
                priority="high",
            )
        ],
        tasks=[],
        gaps=[],
    )

    result = redmine.push_to_redmine(
        output,
        redmine.RedmineConfig(url="http://example.com", api_key="api-key", project_id="demo"),
    )

    assert result["created_issues"][0]["redmine_priority_name"] == "Normal"
    assert "warnings" in result
    assert any(
        "Redmine changed one or more issue priorities" in warning
        for warning in result["warnings"]
    )
