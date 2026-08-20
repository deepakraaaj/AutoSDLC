"""Tests for POST /generations/{gen_id}/improve-quality — the targeted "fix only the
weak items" pass (app/core/backlog_quality.find_weak_items), as opposed to the old
full-regeneration "quality boost". Isolated from the real dev database, same as
tests/test_content_edit.py."""
import json
import threading
import time
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.services.database as database  # noqa: E402
from app.services.database import save_generation, save_generation_normalized  # noqa: E402
from app.services.metrics import compute_metrics, score_single_story, QUALITY_PASS_THRESHOLD  # noqa: E402
from app.core.backlog_quality import find_weak_items, WEAK_ITEM_THRESHOLD  # noqa: E402
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


class ChangeRequestProvider:
    """Answers only the CHANGE_REQUEST_SYSTEM prompt _generate_content_change sends —
    one targeted field fix per call, keyed off which item the prompt is about."""

    def __init__(self):
        self.calls = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        assert "change request into a precise field-level edit" in system_prompt
        if '"as_a": "user"' in user_message:
            return json.dumps({
                "as_a": "billing administrator",
                "i_want": "reconcile monthly card statements against ledger entries automatically",
                "so_that": "finance can close the books faster with fewer manual errors",
                "acceptance_criteria": [
                    "System should validate each transaction amount and reject mismatches with an error",
                    "When a duplicate transaction is found the system should flag it for review",
                    "System must handle empty statement uploads by showing a validation error",
                ],
            })
        if '"title": "Do stuff"' in user_message:
            return json.dumps({
                "description": "Implement the reconciliation matching algorithm comparing statement rows to ledger entries",
                "definition_of_done": "Unit tests passing, code reviewed and merged, deployed to staging and verified",
                "estimate_hours": "4-6",
            })
        raise AssertionError(f"Unexpected change-request target in: {user_message[:200]!r}")


def _seed_generation(good_story=True):
    """Saves a generation with one deliberately weak story and one deliberately weak
    task (plus a solid story/task when good_story, to prove those are left alone)."""
    stories = [
        Story(id="US-0002", title="Bad", as_a="user", i_want="login", so_that="ok",
              acceptance_criteria=["works"], feature_area="Billing", size="small",
              confidence="low", epic_id="EP-0001"),
    ]
    if good_story:
        stories.insert(0, Story(
            id="US-0001", title="Good", as_a="billing administrator",
            i_want="reconcile monthly card statements against ledger entries automatically",
            so_that="finance can close the books faster with fewer manual errors",
            acceptance_criteria=[
                "System should validate each transaction amount and reject mismatches with an error",
                "When a duplicate transaction is found the system should flag it for review",
                "System must handle empty statement uploads by showing a validation error",
            ],
            feature_area="Billing", size="small", confidence="high", epic_id="EP-0001",
        ))

    output = GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="Billing epic", feature_area="Billing", priority="high")],
        stories=stories,
        tasks=[
            Task(id="T-0002", title="Do stuff", description="do it", definition_of_done="do it",
                 estimate_hours="abc", dependencies=[], confidence="low", story_id="US-0002"),
        ],
        gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Reconcile corporate card statements against the ledger.", output)
    save_generation_normalized(gen_id, output)
    return gen_id


def test_improve_quality_fixes_only_the_weak_items(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=True)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    body = res.json()
    assert body["targeted"] == 2
    assert body["updated"] == 2
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"story", "task"}

    # Each item carries *how* it was fixed (changes, an actual before → after diff).
    # This particular rewrite clears the bar on every story dimension, so
    # weak_dimensions is correctly refreshed to empty rather than the stale pre-fix
    # diagnosis (see test_improve_quality_distinguishes_a_write_from_actually_clearing_the_bar
    # for the case where a rewrite does NOT clear the bar).
    bad_story_result = next(i for i in body["items"] if i["id"] == "US-0002")
    assert bad_story_result["resolved"] is True
    assert bad_story_result["weak_dimensions"] == []
    # The 80% pass bar only decides when we stop touching an item — it's not a ceiling
    # the model is told to aim for. Prove it with real numbers: every dimension here
    # clears 80% by a wide margin (90-95%), not a bare-minimum 80/81.
    assert all(score >= 80 for score in bad_story_result["current_scores"].values())
    assert max(bad_story_result["current_scores"].values()) > 85, "must be real headroom above the bar, not clamped at it"
    changes_by_field = {c["field"]: c for c in bad_story_result["changes"]}
    assert changes_by_field["as_a"]["before"] == "user"
    assert changes_by_field["as_a"]["after"] == "billing administrator"

    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    epic = hierarchy["epics"][0]
    good = next(s for s in epic["stories"] if s["ai_id"] == "US-0001")
    bad = next(s for s in epic["stories"] if s["ai_id"] == "US-0002")
    # The already-strong story was never touched.
    assert good["as_a"] == "billing administrator"
    # The weak story was rewritten in place.
    assert bad["as_a"] == "billing administrator"
    assert len(bad["acceptance_criteria"]) == 3

    task = bad["tasks"][0]
    assert task["estimate_hours"] == "4-6"

    # Scores in the persisted output_json improved and reflect the fix.
    history = client.get(f"/history/{gen_id}").json()
    assert history["output"]["metrics"]["story_metrics"]["overall"] > 60
    assert history["output"]["metrics"]["task_metrics"]["overall"] > 50


def test_improve_quality_distinguishes_a_write_from_actually_clearing_the_bar(monkeypatch):
    """"updated" only means the rewrite was written to the DB — it says nothing about
    whether the rewrite actually cleared the (now 80%) pass bar. A regression for
    exactly the case reported: a dimension moving 61% -> 75% is real progress but is
    NOT "done", and the UI must be able to tell the two apart instead of a blanket
    "Fixed" badge that quietly hides items still needing another pass."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=True)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    body = res.json()
    assert body["updated"] == 2
    # ChangeRequestProvider's task rewrite is a real, substantive fix (definition of
    # done and estimate both become solid) but its description is only 11 words —
    # short of the 15-word clarity bar — so the task must NOT be reported as resolved.
    assert body["resolved"] < body["updated"], "at least one updated item must still be below the bar"

    task_result = next(i for i in body["items"] if i["id"] == "T-0002")
    assert task_result["updated"] is True
    assert task_result["resolved"] is False
    # weak_dimensions must be refreshed to the item's *current* state, not the stale
    # pre-fix diagnosis — definition_of_done and estimate are fixed now, so only
    # clarity (or whatever's still genuinely weak) should remain.
    remaining = {d["name"] for d in task_result["weak_dimensions"]}
    assert "definition_of_done" not in remaining
    assert "estimate" not in remaining
    assert remaining, "still-weak items must not report an empty diagnosis"


def test_improve_quality_reports_nothing_to_target_when_already_strong(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_provider", lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError("must not call the provider")))
    gen_id = _seed_generation(good_story=True)
    # Remove the weak normalized rows so the canonical backlog is strong. output_json
    # is deliberately an audit snapshot now and must not override editable rows.
    conn = database.get_connection()
    conn.execute("DELETE FROM tasks WHERE generation_id = ?", (gen_id,))
    conn.execute("DELETE FROM stories WHERE generation_id = ? AND ai_id = ?", (gen_id, "US-0002"))
    conn.commit()
    conn.close()

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    body = res.json()
    assert body["targeted"] == 0
    assert body["updated"] == 0
    assert not calls


def test_weak_items_endpoint_explains_why_without_calling_the_model(monkeypatch):
    """GET /weak-items is the diagnosis step: it must explain *why* each score is bad
    (name/score/reason per weak dimension) and must never call the model or write
    anything — it's a free, instant preview, not a fix."""
    monkeypatch.setattr(main, "get_provider", lambda: (_ for _ in ()).throw(AssertionError("weak-items must not call the provider")))
    gen_id = _seed_generation(good_story=True)

    res = client.get(f"/generations/{gen_id}/weak-items")
    assert res.status_code == 200
    items = res.json()["items"]
    assert {i["id"] for i in items} == {"US-0002", "T-0002"}

    story_item = next(i for i in items if i["id"] == "US-0002")
    assert story_item["kind"] == "story"
    names = {d["name"] for d in story_item["weak_dimensions"]}
    assert "specificity" in names and "testability" in names
    for dim in story_item["weak_dimensions"]:
        assert dim["score"] < 60
        assert len(dim["reason"]) > 10

    # Nothing was written — the backlog is untouched by a pure diagnosis call.
    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    story = next(s for e in hierarchy["epics"] for s in e["stories"] if s["ai_id"] == "US-0002")
    assert story["as_a"] == "user"


def test_weak_items_endpoint_filters_by_dimension(monkeypatch):
    """The Scorecard's per-bar "Fix" link (e.g. on the Definition of done bar) needs to
    jump straight to only the items dragging *that* score down, not the whole mixed
    list — GET /weak-items?dimension=definition_of_done must exclude the story (whose
    weak dimensions are specificity/testability, never definition_of_done)."""
    monkeypatch.setattr(main, "get_provider", lambda: (_ for _ in ()).throw(AssertionError("weak-items must not call the provider")))
    gen_id = _seed_generation(good_story=True)

    res = client.get(f"/generations/{gen_id}/weak-items?dimension=definition_of_done")
    assert res.status_code == 200
    items = res.json()["items"]
    assert {i["id"] for i in items} == {"T-0002"}
    # weak_dimensions still lists everything weak about the item (it has more than one
    # problem) — `dimension` only controls which items are *included*, not what's shown.
    assert "definition_of_done" in {d["name"] for d in items[0]["weak_dimensions"]}

    res_none = client.get(f"/generations/{gen_id}/weak-items?dimension=sizing")
    assert res_none.json()["items"] == []


def test_improve_quality_fixes_only_the_selected_items(monkeypatch):
    """The grouped-checklist UI sends an explicit selection instead of a top-N cutoff —
    only the ticked item(s) should be touched, even though a second weak item exists."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=True)

    res = client.post(f"/generations/{gen_id}/improve-quality", json={"items": [{"kind": "story", "id": "US-0002"}]})
    assert res.status_code == 200
    body = res.json()
    assert body["targeted"] == 1
    assert body["updated"] == 1
    assert body["items"][0]["id"] == "US-0002"

    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    epic = hierarchy["epics"][0]
    bad_story = next(s for s in epic["stories"] if s["ai_id"] == "US-0002")
    assert bad_story["as_a"] == "billing administrator"
    # The weak task was NOT selected, so it must be left exactly as seeded.
    task = bad_story["tasks"][0]
    assert task["estimate_hours"] == "abc"


class RoundAwareTaskProvider:
    """Returns a genuinely weak rewrite on the first call, then a solid one on the
    second — proves the retry loop actually re-diagnoses and re-attempts an item that
    improved without clearing the bar, instead of reporting the same weak result
    forever and making the caller click "Fix" again themselves."""

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.call_count += 1
        if self.call_count == 1:
            return json.dumps({
                "description": "Fix the thing",  # 3 words — stays well short of the 15-word clarity bar
                "definition_of_done": "Unit tests passing, code reviewed and merged, deployed to staging and verified",
                "estimate_hours": "4-6",
            })
        return json.dumps({
            "description": "Implement the reconciliation matching algorithm comparing statement rows to ledger entries using tolerant date windows",
            "definition_of_done": "Unit tests passing, code reviewed and merged, deployed to staging and verified",
            "estimate_hours": "4-6",
        })


def test_improve_quality_retries_an_item_automatically_until_resolved(monkeypatch):
    """The reported complaint: an item that improved but stayed below the bar just
    kept showing up, requiring a manual re-click of "Fix" every time. It should now
    resolve within a single request instead."""
    provider = RoundAwareTaskProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    task = Task(id="T-0001", title="Do stuff", description="do it", definition_of_done="do it",
                estimate_hours="abc", dependencies=[], confidence="low", story_id=None)
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[], tasks=[task], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    body = res.json()
    item = body["items"][0]

    assert provider.call_count == 2, "must have retried automatically after the first, still-weak rewrite"
    assert item["attempts"] == 2
    assert item["resolved"] is True
    assert body["resolved"] == 1

    # The diff must span the WHOLE journey (true original -> final good value), not
    # just round 2's own small delta against round 1's intermediate "Fix the thing".
    desc_change = next(c for c in item["changes"] if c["field"] == "description")
    assert desc_change["before"] == "do it"
    assert "reconciliation matching algorithm" in desc_change["after"]

    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    saved_task = hierarchy["epics"][0]["stories"][0]["tasks"][0] if hierarchy["epics"][0]["stories"] else None
    # Task has no story (story_id=None) so it won't be in the hierarchy join at all —
    # confirm the final content landed via the direct id-map path instead.
    assert saved_task is None
    from app.services.database import get_task_id_map
    db_id = get_task_id_map(gen_id)["T-0001"]
    conn = database.get_connection()
    row = conn.execute("SELECT description FROM tasks WHERE id = ?", (db_id,)).fetchone()
    conn.close()
    assert "reconciliation matching algorithm" in row["description"]


def test_improve_quality_stops_retrying_at_max_attempts(monkeypatch):
    """A provider that never produces a passing rewrite must not retry forever — it
    stops at max_attempts and reports the item honestly as still unresolved."""
    class NeverGoodEnoughProvider:
        def __init__(self):
            self.call_count = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.call_count += 1
            return json.dumps({"description": f"Still too short attempt {self.call_count}", "definition_of_done": "todo", "estimate_hours": "x"})

    provider = NeverGoodEnoughProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    task = Task(id="T-0001", title="Do stuff", description="do it", definition_of_done="do it",
                estimate_hours="abc", dependencies=[], confidence="low", story_id=None)
    output = GenerationOutput(needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[], tasks=[task], gaps=[])
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality", json={"max_attempts": 2})
    body = res.json()
    item = body["items"][0]

    assert provider.call_count == 2, "must stop at max_attempts, not retry indefinitely"
    assert item["attempts"] == 2
    assert item["updated"] is True
    assert item["resolved"] is False
    assert body["resolved"] == 0


def test_improve_quality_fixes_a_task_whose_story_link_is_broken(monkeypatch):
    """Regression for the reported bug: items kept showing up as weak forever, never
    actually fixable, no matter how many times "Fix" was clicked. Root cause — the fix
    endpoint resolved db_id by walking the epic->story->task hierarchy join
    (get_generation_hierarchy), which silently drops any row whose parent link is
    missing or dangling. save_tasks_only happily inserts a task with story_id=NULL
    when its story_id doesn't resolve (a real, reachable case — e.g. a hallucinated
    cross-story reference), so that task is scored as weak by find_weak_items (which
    only looks at output.tasks, no join) but was invisible to the old hierarchy-walk
    lookup — "No longer in the backlog" on every attempt, forever. This seeds through
    the real save_generation_normalized path (not a hand-built DB row) to prove the
    scenario is genuinely reachable, not contrived."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())

    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[],  # no story exists to satisfy the task's story_id reference below
        tasks=[
            Task(id="T-0002", title="Do stuff", description="do it", definition_of_done="do it",
                 estimate_hours="abc", dependencies=[], confidence="low", story_id="US-9999"),
        ],
        gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    # Confirm the setup actually reproduces the dangling-link scenario before testing
    # the fix — the task must be absent from the hierarchy join (old lookup, since it
    # has no story to be nested under) yet present via the direct id map (new lookup).
    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    tasks_in_hierarchy = [t["ai_id"] for e in hierarchy["epics"] for s in e["stories"] for t in s["tasks"]]
    assert "T-0002" not in tasks_in_hierarchy, "test fixture must actually reproduce the dangling link"
    from app.services.database import get_task_id_map
    assert "T-0002" in get_task_id_map(gen_id), "task must still exist in the DB despite the broken link"

    res = client.post(f"/generations/{gen_id}/improve-quality", json={"items": [{"kind": "task", "id": "T-0002"}]})
    assert res.status_code == 200
    body = res.json()
    item = body["items"][0]
    assert item["updated"] is True, f"expected the fix to succeed, got: {item.get('error')}"
    changes_by_field = {c["field"]: c for c in item["changes"]}
    assert changes_by_field["estimate_hours"]["after"] == "4-6"


def test_weak_item_threshold_matches_the_validation_pass_bar():
    """Regression for the exact bug reported: WEAK_ITEM_THRESHOLD used to be a separate,
    lower constant (60) than the 70% bar run_validation actually gates on. A dimension
    sitting at 61-69% would drag the aggregate below 70% forever without ever being
    flagged as "weak" — a dead zone with no way to fix it. The two must be one number."""
    assert WEAK_ITEM_THRESHOLD == QUALITY_PASS_THRESHOLD


def test_find_weak_items_flags_the_former_dead_zone_between_60_and_70():
    """A story scoring 68 on specificity — below the 70% pass bar, but was previously
    above the old 60 "weak" cutoff — must now be flagged, and must stop being flagged
    if a caller explicitly asks for the old, looser 60 threshold instead."""
    story = Story(
        id="US-0003", title="Dead zone", as_a="billing administrator",
        i_want="reconcile", so_that="finance can close the books faster with fewer errors",
        acceptance_criteria=[
            "System should validate each transaction amount and reject mismatches with an error",
            "When a duplicate transaction is found the system should flag it for review",
            "System must handle empty statement uploads by showing a validation error",
        ],
        feature_area="Billing", size="small", confidence="high", epic_id="EP-0001",
    )
    scores = score_single_story(story)
    assert 60 <= scores["specificity"] < 70, "test fixture must actually land in the dead zone"

    output = GenerationOutput(needs_clarification=False, clarifying_questions=[], epics=[],
                               stories=[story], tasks=[], gaps=[])

    flagged_default = find_weak_items(output, max_items=None)
    assert any(w["id"] == "US-0003" for w in flagged_default), "68% must be flagged against the real (70%) pass bar"

    flagged_old_cutoff = find_weak_items(output, max_items=None, threshold=60)
    assert not any(w["id"] == "US-0003" for w in flagged_old_cutoff), "threshold must be a real, overridable parameter"


def test_improve_quality_not_found_returns_404(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    res = client.post("/generations/999999/improve-quality")
    assert res.status_code == 404


def test_weak_items_endpoint_surfaces_the_real_error_not_a_generic_message(monkeypatch):
    """Regression: a genuine backend failure (a malformed output_json that fails
    GenerationOutput validation on load, here standing in for whatever produced the
    real "Database error: Failed to analyze backlog quality" report) used to return a
    bare, undiagnosable placeholder. safe_exc(e) is the same pattern every other
    endpoint in this file already uses for its error responses — this one just hadn't
    been given it, so a real cause was silently thrown away instead of shown."""
    monkeypatch.setattr(main, "get_provider", lambda: (_ for _ in ()).throw(AssertionError("must not call the provider")))
    gen_id = _seed_generation(good_story=True)

    conn = database.get_connection()
    conn.execute("UPDATE generations SET output_json = ? WHERE id = ?", ('{"not": "a valid GenerationOutput"}', gen_id))
    conn.commit()
    conn.close()

    res = client.get(f"/generations/{gen_id}/weak-items")
    assert res.status_code == 500
    message = res.json()["error"]["message"]
    assert message != "Failed to analyze backlog quality", "must include the actual cause, not just the generic prefix"
    assert "Failed to analyze backlog quality" in message
    assert "validation error" in message.lower()


def _weak_sizing_story(size: str = "large") -> Story:
    """A story flagged weak on exactly one dimension — sizing — so a fix attempt
    isolates whatever happens to the "size" field without other dimensions muddying
    the result. "large" scores 50 (< 80 threshold) per score_single_story's rubric —
    large stories are always penalized, on the theory they should be split."""
    return Story(
        id="US-0002", title="Weak sizing", as_a="billing administrator",
        i_want="reconcile monthly card statements against ledger entries automatically",
        so_that="finance can close the books faster with fewer manual errors",
        acceptance_criteria=[
            "System should validate each transaction amount and reject mismatches with an error",
            "When a duplicate transaction is found the system should flag it for review",
            "System must handle empty statement uploads by showing a validation error",
        ],
        feature_area="Billing", size=size, confidence="high", epic_id="EP-0001",
    )


def test_improve_quality_rejects_an_invalid_size_value_instead_of_writing_it(monkeypatch):
    """Regression for real reported data corruption: Story.size is a closed Literal
    ("small"/"medium"/"large"), but _generate_content_change's model call returns
    plain, schema-less JSON — a value like "extra-large" used to get applied via
    setattr() with zero validation, corrupting both the DB row and output_json. The
    corruption was invisible until the *next* reload re-validated it through Pydantic
    and 500'd every endpoint touching that generation ("Input should be 'small',
    'medium' or 'large'"). An invalid value must now be dropped, not written."""
    class BadSizeProvider:
        def generate(self, system_prompt: str, user_message: str) -> str:
            return json.dumps({"size": "extra-large"})

    monkeypatch.setattr(main, "get_provider", lambda: BadSizeProvider())
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[_weak_sizing_story()], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["updated"] is False
    assert item["error"] == "The model returned no usable change for this item"
    assert item["error_kind"] == "blocked"

    # Confirm nothing was corrupted, in both the normalized row and output_json.
    hierarchy = client.get(f"/hierarchy/{gen_id}").json()
    assert hierarchy["epics"][0]["stories"][0]["size"] == "large"
    history = client.get(f"/history/{gen_id}").json()
    assert history["output"]["stories"][0]["size"] == "large"
    # And the generation must still be loadable at all — the whole point of this bug.
    assert client.get(f"/generations/{gen_id}/weak-items").status_code == 200


def test_improve_quality_normalizes_a_validly_cased_size_value(monkeypatch):
    """A value that's actually valid modulo case (the model writing "Small" instead
    of "small") should be accepted and normalized, not rejected outright — dropping
    every case variant would make this fix needlessly stricter than the schema itself."""
    class CapitalizedSizeProvider:
        def generate(self, system_prompt: str, user_message: str) -> str:
            return json.dumps({"size": "Small"})

    monkeypatch.setattr(main, "get_provider", lambda: CapitalizedSizeProvider())
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[_weak_sizing_story()], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    item = res.json()["items"][0]
    assert item["updated"] is True
    assert item["changes"][0] == {"field": "size", "before": "large", "after": "small"}
    assert client.get(f"/hierarchy/{gen_id}").json()["epics"][0]["stories"][0]["size"] == "small"


def test_a_generation_already_corrupted_with_an_invalid_size_self_heals_on_load(monkeypatch):
    """Recovery for a generation corrupted before this fix existed (an invalid "size"
    already sitting in output_json) — it must not stay permanently 500ing on every
    reload; the next load coerces the bad value back to a valid one instead."""
    monkeypatch.setattr(main, "get_provider", lambda: (_ for _ in ()).throw(AssertionError("must not call the provider")))
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[_weak_sizing_story(size="large")], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    # Simulate pre-existing corruption directly, the way the old unvalidated setattr()
    # path would have produced it — bypassing the app entirely, straight into the DB.
    conn = database.get_connection()
    row = conn.execute("SELECT output_json FROM generations WHERE id = ?", (gen_id,)).fetchone()
    corrupted = json.loads(row["output_json"])
    corrupted["stories"][0]["size"] = "extra-large"
    conn.execute("UPDATE generations SET output_json = ? WHERE id = ?", (json.dumps(corrupted), gen_id))
    conn.commit()
    conn.close()

    res = client.get(f"/generations/{gen_id}/weak-items")
    assert res.status_code == 200, "a pre-existing corrupted value must self-heal, not 500 forever"


class SleepyProvider:
    """Simulates real AI call latency (a fixed delay per call, no actual network) so a
    test can prove the fix loop dispatches its _generate_content_change calls
    concurrently instead of one at a time. Records each call's start time under a
    lock — self.calls started sequentially would be spaced ~delay apart; started
    concurrently they cluster within a fraction of it."""

    def __init__(self, delay: float = 0.3):
        self.delay = delay
        self.start_times: list[float] = []
        self._lock = threading.Lock()

    def generate(self, system_prompt: str, user_message: str) -> str:
        with self._lock:
            self.start_times.append(time.monotonic())
        time.sleep(self.delay)
        return "{}"  # No concrete change — irrelevant to this test, only timing matters.


def test_improve_quality_runs_fix_calls_concurrently_not_one_at_a_time(monkeypatch):
    """Regression for the actual complaint: fixing a large selection was slow because
    each item's AI call ran sequentially. 5 items behind a 0.3s-per-call fake provider
    must all start within a fraction of that delay of each other — proof the calls
    were dispatched in parallel, not queued one after another (which would take 1.5s+
    and spread the start times ~0.3s apart)."""
    provider = SleepyProvider(delay=0.3)
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    stories = [
        Story(
            id=f"US-000{i}", title=f"Bad story {i}", as_a="user", i_want="login", so_that="ok",
            acceptance_criteria=["works"], feature_area="Billing", size="small",
            confidence="low", epic_id="EP-0001",
        )
        for i in range(1, 6)
    ]
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=stories, tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    started = time.monotonic()
    res = client.post(f"/generations/{gen_id}/improve-quality", json={
        "items": [{"kind": "story", "id": s.id} for s in stories],
        # This test is about round-1 concurrency specifically — SleepyProvider always
        # returns "{}" (no fields), so every item "fails" and would otherwise trigger
        # the retry loop's later rounds too, no longer isolating a single round's fan-out.
        "max_attempts": 1,
    })
    elapsed = time.monotonic() - started

    assert res.status_code == 200
    assert res.json()["targeted"] == 5
    assert len(provider.start_times) == 5
    # All 5 calls fired within a fraction of the per-call delay of each other — if
    # they'd run sequentially, the spread would be ~4 * delay (1.2s) instead.
    spread = max(provider.start_times) - min(provider.start_times)
    assert spread < provider.delay, f"calls did not overlap — ran sequentially (spread={spread:.2f}s)"
    assert elapsed < 4 * provider.delay, f"5 sequential 0.3s calls would take ~1.5s; took {elapsed:.2f}s"


def test_improve_quality_never_leaves_an_item_worse_than_it_started(monkeypatch):
    """Regression for the reported "you're making it worse": every rewrite the model
    returned used to be written to the DB and output_json unconditionally, with no
    check that it was actually an improvement. Across MAX_FIX_ATTEMPTS rounds per
    click — and repeat clicks on items that never clear the bar — that let a story
    walk steadily downhill, each round overwriting the last with whatever came back
    and no way to recover the original. A rewrite that scores no better than what it
    replaces must be discarded, leaving the item untouched."""
    class DegradingProvider:
        """Returns a *plausible-looking* but strictly worse rewrite: a vaguer actor,
        a shorter intent/rationale, and one thin acceptance criterion in place of
        three substantive ones."""

        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls += 1
            return json.dumps({
                "as_a": "user",
                "i_want": "reconcile statements",
                "so_that": "it works",
                "acceptance_criteria": ["works"],
            })

    provider = DegradingProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    # Weak on sizing only — every other dimension is strong, which is exactly what
    # the degrading rewrite would destroy in exchange for nothing.
    story = _weak_sizing_story()
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[story], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    before = score_single_story(story)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    body = res.json()
    item = body["items"][0]

    # The rewrite was attempted and rejected — not silently counted as a success.
    assert provider.calls >= 1, "the model should still have been asked"
    assert item["updated"] is False
    assert body["updated"] == 0
    assert "no better" in item["error"]

    # Nothing was written anywhere: the original content survives in the normalized
    # rows AND in output_json.
    stored = client.get(f"/history/{gen_id}").json()["output"]["stories"][0]
    assert stored["as_a"] == "billing administrator"
    assert len(stored["acceptance_criteria"]) == 3
    hierarchy_story = client.get(f"/hierarchy/{gen_id}").json()["epics"][0]["stories"][0]
    assert hierarchy_story["as_a"] == "billing administrator"

    # And the scores genuinely did not regress — the actual promise being made.
    after = score_single_story(Story(**stored))
    for dimension, score in before.items():
        assert after[dimension] >= score, f"{dimension} regressed: {score} -> {after[dimension]}"


def test_improve_quality_keeps_a_rewrite_that_actually_improves_the_item(monkeypatch):
    """The guard above must not be so strict it rejects real fixes — a rewrite that
    lifts the weak dimension is still written, same as before."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=False)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    body = res.json()
    assert body["updated"] == 2, "genuine improvements must still be applied"
    story_item = next(i for i in body["items"] if i["kind"] == "story")
    assert story_item["updated"] is True
    assert client.get(f"/history/{gen_id}").json()["output"]["stories"][0]["as_a"] == "billing administrator"


def test_improve_quality_keeps_the_best_rewrite_when_a_later_round_degrades(monkeypatch):
    """The retry loop's specific failure mode: round 1 genuinely improves an item but
    leaves it short of the bar, so round 2 runs — and round 2's rewrite is worse.
    Round 1's gain must survive; it must not be overwritten by round 2."""
    class ImproveThenDegradeProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls += 1
            if self.calls == 1:
                # Better rationale/intent, but still only two ACs — real progress,
                # not enough to clear the bar, so the loop will retry.
                return json.dumps({
                    "i_want": "reconcile monthly card statements against ledger entries automatically",
                    "so_that": "finance can close the books faster with fewer manual errors",
                    "acceptance_criteria": [
                        "System should validate each transaction amount and reject mismatches with an error",
                        "When a duplicate transaction is found the system should flag it for review",
                    ],
                })
            return json.dumps({
                "i_want": "login",
                "so_that": "ok",
                "acceptance_criteria": ["works"],
            })

    provider = ImproveThenDegradeProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    story = Story(
        id="US-0002", title="Weak", as_a="user", i_want="login", so_that="ok",
        acceptance_criteria=["works"], feature_area="Billing", size="small",
        confidence="low", epic_id="EP-0001",
    )
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[story], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    item = res.json()["items"][0]

    assert provider.calls >= 2, "the loop should have retried an item still short of the bar"
    assert item["updated"] is True
    stored = client.get(f"/history/{gen_id}").json()["output"]["stories"][0]
    # Round 1's content, not round 2's regression.
    assert stored["so_that"] == "finance can close the books faster with fewer manual errors"
    assert len(stored["acceptance_criteria"]) == 2
    # A later bad round must not resurrect an error on an item that did improve.
    assert "error" not in item or not item["error"]


def test_improve_quality_stops_retrying_an_item_whose_score_does_not_move(monkeypatch):
    """Regression for the reported "(3 attempts)" churn on an item that can never
    win. A "large" story scores a flat 50 on sizing no matter what its prose says —
    only splitting it (which this endpoint can't do) or a genuinely wrong size label
    would move it. The retry loop used to re-ask the model MAX_FIX_ATTEMPTS times on
    every click regardless, always to the same result. A round that leaves the score
    exactly where it started must stop the retries there."""
    class NoProgressProvider:
        """Returns a change that moves no dimension at all — a title rewrite, which
        no dimension in the rubric scores. Whether it's then written or declined by
        the improvement guard, the item's score is identical either way, which is
        exactly the situation retrying cannot get out of."""

        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls += 1
            return json.dumps({"title": f"Weak sizing (rephrased {self.calls})"})

    provider = NoProgressProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)

    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=[_weak_sizing_story()], tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    assert res.status_code == 200
    item = res.json()["items"][0]

    # One attempt, not MAX_FIX_ATTEMPTS — the whole point.
    assert provider.calls == 1, f"stalled item was retried {provider.calls} times"
    assert item["attempts"] == 1
    assert item["stalled"] is True
    assert item["resolved"] is False

    # And it reports where it actually stands, before and after, so the UI can say
    # "50% -> 50%" instead of a bare "improved to 50%" that hides that nothing moved.
    assert item["before_scores"]["sizing"] == 50
    assert item["current_scores"]["sizing"] == 50


def test_improve_quality_separates_a_deliberate_no_op_from_a_real_failure(monkeypatch):
    """A rewrite that's declined because it wasn't an improvement is not a failure —
    nothing broke and the backlog is intact. It must be reported as such (a red
    "Failed" badge on an untouched backlog is what made the panel alarming), and
    distinctly from a model call that actually raised."""
    class DegradingProvider:
        def generate(self, system_prompt: str, user_message: str) -> str:
            return json.dumps({"as_a": "user", "so_that": "ok", "acceptance_criteria": ["works"]})

    class ExplodingProvider:
        """A genuinely broken call, not a transient one — no rate-limit/timeout wording,
        so _classify_provider_error must land on ERROR_FAILED rather than scheduling a
        retry (see test_improve_quality_retries_a_transient_provider_error)."""

        def generate(self, system_prompt: str, user_message: str) -> str:
            raise RuntimeError("model returned a malformed payload")

    def _seed():
        out = GenerationOutput(
            needs_clarification=False, clarifying_questions=[],
            epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
            stories=[_weak_sizing_story()], tasks=[], gaps=[],
        )
        out.metrics = compute_metrics(out)
        gid = save_generation("Some brief.", out)
        save_generation_normalized(gid, out)
        return gid

    monkeypatch.setattr(main, "get_provider", lambda: DegradingProvider())
    blocked = client.post(f"/generations/{_seed()}/improve-quality").json()["items"][0]
    assert blocked["updated"] is False
    assert blocked["error_kind"] == "blocked"

    monkeypatch.setattr(main, "get_provider", lambda: ExplodingProvider())
    failed = client.post(f"/generations/{_seed()}/improve-quality").json()["items"][0]
    assert failed["updated"] is False
    assert failed["error_kind"] == "failed"
    assert "malformed" in failed["error"]


def test_improve_quality_reports_before_and_after_scores_for_a_real_improvement(monkeypatch):
    """The delta must be readable for items that did move, not just stalled ones —
    a lone current number is impossible to tell apart from where the item started."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=False)

    res = client.post(f"/generations/{gen_id}/improve-quality")
    story_item = next(i for i in res.json()["items"] if i["kind"] == "story")
    assert story_item["updated"] is True
    worst_before = min(story_item["before_scores"].values())
    worst_after = min(story_item["current_scores"].values())
    assert worst_after > worst_before, "a real fix must show a real upward delta"


def test_improve_quality_retries_a_transient_provider_error_and_reports_success(monkeypatch):
    """Regression for a wall of red "Failed" rows. Two separate faults combined to make
    a burst rate-limit permanent:

    1. _generate_content_change built its own provider per call, so a run fanning items
       out concurrently got one LiteLLMProvider each — and the "all providers exhausted"
       circuit breaker is per-instance, so it never short-circuited anything.
    2. The stall check treated "the score didn't move" as proof the item was stuck. An
       errored call doesn't move the score either, so a transient failure retired the
       item immediately and no retry was ever allowed to happen.

    A rate limit must be waited out and retried, and the recovered item must report as
    genuinely fixed."""
    monkeypatch.setattr(main, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)

    class RateLimitedThenFineProvider:
        """Fails the first call the way an exhausted provider does, then works."""

        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt: str, user_message: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise main.AllProvidersExhaustedError("All configured AI providers are rate-limited.")
            return json.dumps({
                "as_a": "billing administrator",
                "i_want": "reconcile monthly card statements against ledger entries automatically",
                "so_that": "finance can close the books faster with fewer manual errors",
                "acceptance_criteria": [
                    "System should validate each transaction amount and reject mismatches with an error",
                    "When a duplicate transaction is found the system should flag it for review",
                    "System must handle empty statement uploads by showing a validation error",
                ],
            })

    provider = RateLimitedThenFineProvider()
    monkeypatch.setattr(main, "get_provider", lambda: provider)
    gen_id = _seed_generation(good_story=False)

    res = client.post(f"/generations/{gen_id}/improve-quality", json={
        "items": [{"kind": "story", "id": "US-0002"}],
    })
    assert res.status_code == 200
    item = res.json()["items"][0]

    assert provider.calls >= 2, "a transient error must be retried, not retired on the spot"
    assert item["updated"] is True
    assert item["resolved"] is True
    # The transient error must not linger on a run that went on to succeed.
    assert not item.get("error")
    assert item.get("error_kind") is None


def test_improve_quality_shares_one_provider_across_every_item(monkeypatch):
    """The circuit breaker that stops a rate-limited run from stampeding is per-provider
    -instance state, so the whole request has to run on one instance. Building a fresh
    one per item silently disabled it."""
    built = []

    class CountingProvider:
        def generate(self, system_prompt: str, user_message: str) -> str:
            return json.dumps({})

    def _build():
        provider = CountingProvider()
        built.append(provider)
        return provider

    monkeypatch.setattr(main, "get_provider", _build)

    stories = [
        Story(id=f"US-{i:04d}", title=f"Weak {i}", as_a="user", i_want="login", so_that="ok",
              acceptance_criteria=["works"], feature_area="Billing", size="small",
              confidence="low", epic_id="EP-0001")
        for i in range(1, 6)
    ]
    output = GenerationOutput(
        needs_clarification=False, clarifying_questions=[],
        epics=[Epic(id="EP-0001", title="Billing", description="", feature_area="Billing", priority="high")],
        stories=stories, tasks=[], gaps=[],
    )
    output.metrics = compute_metrics(output)
    gen_id = save_generation("Some brief.", output)
    save_generation_normalized(gen_id, output)

    res = client.post(f"/generations/{gen_id}/improve-quality", json={
        "items": [{"kind": "story", "id": s.id} for s in stories],
        "max_attempts": 1,
    })
    assert res.status_code == 200
    assert len(built) == 1, f"expected one shared provider for the whole request, built {len(built)}"


def test_improve_quality_stream_reports_progress_then_the_same_result(monkeypatch):
    """The streaming endpoint must emit progress as it works and finish with exactly the
    payload the blocking endpoint returns — a run over dozens of items does several
    rounds of AI calls and can pause 20s+ on a rate limit, which is far too long to show
    the user nothing."""
    monkeypatch.setattr(main, "get_provider", lambda: ChangeRequestProvider())
    gen_id = _seed_generation(good_story=False)

    with client.stream("POST", f"/generations/{gen_id}/improve-quality-stream") as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        events = [
            json.loads(line[6:])
            for line in res.iter_lines()
            if line.startswith("data: ")
        ]

    progress = [e for e in events if e["type"] == "progress"]
    results = [e for e in events if e["type"] == "result"]

    assert progress, "must report progress while working"
    assert [e["phase"] for e in progress][0] == "start"
    assert any(e["phase"] == "item" for e in progress), "must report each item as it lands"
    assert any(e["phase"] == "scoring" for e in progress)
    # Progress must actually advance, and never claim more done than were targeted.
    completed = [e["completed"] for e in progress]
    assert completed == sorted(completed)
    assert max(completed) <= progress[0]["total"]

    assert len(results) == 1, "exactly one terminal result"
    assert results[0]["targeted"] == 2
    assert results[0]["updated"] == 2
    assert "output" in results[0]


def test_improve_quality_stream_reports_a_missing_generation_as_an_error_event():
    with client.stream("POST", "/generations/999999/improve-quality-stream") as res:
        events = [json.loads(line[6:]) for line in res.iter_lines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["status"] == 404


def test_repair_dependencies_returns_json_not_a_generator(monkeypatch):
    """Guard for a real breakage: repair-dependencies is a plain endpoint that happens to
    sit next to several SSE generators, and an edit that put a `yield` in it turned the
    whole function into a generator — FastAPI then returns something meaningless instead
    of the repair result. Nothing covered this endpoint at all, so it went unnoticed."""
    monkeypatch.setattr(main, "get_provider", lambda: (_ for _ in ()).throw(
        AssertionError("dependency repair is deterministic — it must not call the model")))
    gen_id = _seed_generation(good_story=True)

    res = client.post(f"/generations/{gen_id}/repair-dependencies")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, dict)
    assert "output" in body

    missing = client.post("/generations/999999/repair-dependencies")
    assert missing.status_code == 404
