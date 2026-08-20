"""Regression for a backlog page that contradicted itself: the Checks panel read a
`validation` blob frozen into output_json at generation time, while the Scorecard
beside it scored against the *current* QUALITY_PASS_THRESHOLD. Raising the bar from
70 to 80 left old generations reporting "TRUSTED OUTPUT - 5/5 checks passed - Story
Quality 76% (>= 70%)" next to a Quality panel offering a "Fix" link on every
dimension under 80."""
import json
import sqlite3
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.services.database import save_generation  # noqa: E402
from app.services.metrics import compute_metrics, QUALITY_PASS_THRESHOLD  # noqa: E402
from app.schemas.models import GenerationOutput, Epic, Story, Task  # noqa: E402
from app.utils import rate_limit  # noqa: E402


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


def _seed_with_stale_validation() -> int:
    """A backlog that scores in the 70s — passing under the old 70 bar, failing under
    the current 80 one — saved with a validation blob claiming it fully passed."""
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="Billing epic",
                    feature_area="Billing", priority="high")],
        stories=[Story(
            id="US-0001", title="Weak-ish", as_a="billing administrator",
            i_want="reconcile monthly card statements against ledger entries automatically",
            so_that="finance can close the books faster with fewer manual errors",
            acceptance_criteria=[
                "System should validate each transaction amount and reject mismatches with an error",
                "When a duplicate transaction is found the system should flag it for review",
            ],
            feature_area="Billing", size="large", confidence="high", epic_id="EP-0001",
        )],
        tasks=[Task(id="T-0001", title="Build matcher", description="do it",
                    definition_of_done="done", estimate_hours="abc", dependencies=[],
                    confidence="low", story_id="US-0001")],
        gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Reconcile corporate card statements.", output)

    # Overwrite the stored blob with the verdict the old 70 bar would have produced.
    stored = json.loads(json.dumps(output.model_dump()))
    stored["validation"] = {
        "trust_level": "trusted",
        "recommendation": "✓ Output is ready to use. Review any gaps and push to Redmine.",
        "checks": [
            {"label": "Coverage Score", "passed": True, "value": "100%", "threshold": "≥ 70%"},
            {"label": "Story Quality", "passed": True, "value": "76%", "threshold": "≥ 70%"},
            {"label": "Task Quality", "passed": True, "value": "76%", "threshold": "≥ 70%"},
            {"label": "Gap Count", "passed": True, "value": "0", "threshold": "≤ 3"},
            {"label": "Input Quality", "passed": True, "value": "High", "threshold": "= High"},
        ],
    }
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("UPDATE generations SET output_json = ? WHERE id = ?", (json.dumps(stored), gen_id))
    conn.commit()
    conn.close()
    return gen_id


def test_history_rescores_a_generation_against_the_current_pass_bar():
    gen_id = _seed_with_stale_validation()

    validation = client.get(f"/history/{gen_id}").json()["output"]["validation"]
    checks = {c["label"]: c for c in validation["checks"]}

    # The thresholds shown must be today's bar, not the one baked in at save time.
    assert checks["Story Quality"]["threshold"] == f"≥ {QUALITY_PASS_THRESHOLD}%"
    assert checks["Task Quality"]["threshold"] == f"≥ {QUALITY_PASS_THRESHOLD}%"
    assert checks["Coverage Score"]["threshold"] == f"≥ {QUALITY_PASS_THRESHOLD}%"

    # And a sub-bar score must not still be reported as a pass.
    story_score = int(checks["Story Quality"]["value"].rstrip("%"))
    assert story_score < QUALITY_PASS_THRESHOLD, "fixture must score below the bar to be meaningful"
    assert checks["Story Quality"]["passed"] is False
    assert validation["trust_level"] != "trusted"


def test_history_agrees_with_the_weak_items_diagnosis():
    """The actual contradiction the user saw: "5/5 checks passed" beside a panel
    listing items to fix. If anything is weak enough to target, the checks must not
    claim the backlog fully passed."""
    gen_id = _seed_with_stale_validation()

    validation = client.get(f"/history/{gen_id}").json()["output"]["validation"]
    weak_items = client.get(f"/generations/{gen_id}/weak-items").json()["items"]

    assert weak_items, "fixture must have something to fix for this test to mean anything"
    assert validation["trust_level"] != "trusted"
    assert not all(c["passed"] for c in validation["checks"])


def test_history_still_serves_a_generation_whose_scores_cannot_be_refreshed():
    """Rescoring runs on a read path that previously did no validation at all — a
    generation that renders today must not start erroring because it couldn't be
    re-scored."""
    gen_id = _seed_with_stale_validation()
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute(
        "UPDATE generations SET output_json = ? WHERE id = ?",
        (json.dumps({"stories": "not-a-list", "validation": {"trust_level": "trusted", "checks": []}}), gen_id),
    )
    conn.commit()
    conn.close()

    res = client.get(f"/history/{gen_id}")
    assert res.status_code == 200
    assert res.json()["output"]["validation"]["trust_level"] == "trusted", "must fall back to stored, not 500"
