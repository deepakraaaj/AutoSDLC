from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import redmine  # noqa: E402


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
