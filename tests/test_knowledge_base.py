"""Tests for the project knowledge base: app/services/database.py's
project_knowledge_entries CRUD, the /projects/{id}/knowledge REST endpoints,
app/services/knowledge_base.py's format_knowledge_context/KNOWLEDGE_CITATION,
main.py's _with_project_instructions injection, and wiki_generator.py's
acceptance of "[KB-n]" as valid citation evidence alongside path:line.

Same isolated-db fixture pattern as tests/test_project_settings.py."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import app.api.projects as projects_api  # noqa: E402
import app.services.database as database  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


def _create_project() -> int:
    return database.create_project("Test Project")["id"]


# ── Database CRUD ───────────────────────────────────────────────────────

def test_add_and_list_knowledge_entry():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "rule", "Refund window", "Refunds are only valid within 14 days.")
    assert entry["project_id"] == project_id
    assert entry["entry_type"] == "rule"
    assert entry["title"] == "Refund window"
    assert entry["body"] == "Refunds are only valid within 14 days."
    assert entry["id"] > 0

    entries = database.list_knowledge_entries(project_id)
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]


def test_add_knowledge_entry_persists_sdlc_area():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "rule", "Refund window", "Refunds are only valid within 14 days.", "Business Rules")
    assert entry["sdlc_area"] == "Business Rules"
    assert database.list_knowledge_entries(project_id)[0]["sdlc_area"] == "Business Rules"


def test_add_knowledge_entry_sdlc_area_defaults_to_none():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "glossary", "SKU", "Stock Keeping Unit.")
    assert entry["sdlc_area"] is None


def test_update_knowledge_entry_can_change_sdlc_area():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "rule", "Refund window", "14 days.", "Business Rules")
    updated = database.update_knowledge_entry(entry["id"], sdlc_area="Functional Requirements")
    assert updated["sdlc_area"] == "Functional Requirements"


def test_create_endpoint_persists_valid_sdlc_area():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "Refund window", "body": "14 days, not 30.", "sdlc_area": "Business Rules",
    })
    assert response.json()["sdlc_area"] == "Business Rules"


def test_create_endpoint_rejects_unrecognized_sdlc_area():
    """A value that isn't one of the 15 canonical SDLC_AREAS is normalized
    to None rather than stored verbatim — same defensive contract as the
    extraction parsers, so the saved list's grouping is never surprised by
    an area name that doesn't exist in SDLC_AREAS."""
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "Refund window", "body": "14 days, not 30.", "sdlc_area": "Not A Real Area",
    })
    assert response.json()["sdlc_area"] is None


def test_list_knowledge_entries_scoped_to_project():
    project_a = _create_project()
    project_b = database.create_project("Other Project")["id"]
    database.add_knowledge_entry(project_a, "glossary", "SKU", "Stock Keeping Unit.")
    database.add_knowledge_entry(project_b, "glossary", "PO", "Purchase Order.")

    assert [e["title"] for e in database.list_knowledge_entries(project_a)] == ["SKU"]
    assert [e["title"] for e in database.list_knowledge_entries(project_b)] == ["PO"]


def test_update_knowledge_entry_partial_update_preserves_other_fields():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "glossary", "SKU", "Stock Keeping Unit.")
    updated = database.update_knowledge_entry(entry["id"], body="Stock Keeping Unit — unique per variant.")
    assert updated["title"] == "SKU"
    assert updated["body"] == "Stock Keeping Unit — unique per variant."
    assert updated["entry_type"] == "glossary"


def test_delete_knowledge_entry():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "decision", "Auth", "We use JWT, not sessions.")
    database.delete_knowledge_entry(entry["id"])
    assert database.list_knowledge_entries(project_id) == []
    assert database.get_knowledge_entry(entry["id"]) is None


def test_deleting_project_cascades_to_knowledge_entries():
    project_id = _create_project()
    database.add_knowledge_entry(project_id, "constraint", "Rate limit", "Max 100 req/min per API key.")
    database.delete_project(project_id)
    conn = database.get_connection()
    count = conn.execute("SELECT COUNT(*) AS n FROM project_knowledge_entries").fetchone()["n"]
    conn.close()
    assert count == 0


# ── API endpoints ────────────────────────────────────────────────────────

def test_knowledge_endpoints_404_for_missing_project():
    assert client.get("/projects/999999/knowledge").status_code == 404
    assert client.post("/projects/999999/knowledge", json={"title": "x", "body": "y"}).status_code == 404


def test_create_list_update_delete_round_trip_via_api():
    project_id = _create_project()

    create = client.post(f"/projects/{project_id}/knowledge", json={
        "entry_type": "rule", "title": "Refund window", "body": "14 days, not 30.",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    listed = client.get(f"/projects/{project_id}/knowledge")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.put(f"/projects/{project_id}/knowledge/{entry_id}", json={"body": "14 days from delivery."})
    assert updated.status_code == 200
    assert updated.json()["body"] == "14 days from delivery."
    assert updated.json()["title"] == "Refund window"  # untouched by partial update

    deleted = client.delete(f"/projects/{project_id}/knowledge/{entry_id}")
    assert deleted.status_code == 200
    assert client.get(f"/projects/{project_id}/knowledge").json() == []


def test_create_strips_whitespace_from_title_and_body():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "  SKU  ", "body": "  Stock Keeping Unit.  ",
    })
    assert response.json()["title"] == "SKU"
    assert response.json()["body"] == "Stock Keeping Unit."


def test_update_404s_for_entry_on_a_different_project():
    project_a = _create_project()
    project_b = database.create_project("Other")["id"]
    entry = database.add_knowledge_entry(project_a, "glossary", "SKU", "Stock Keeping Unit.")
    response = client.put(f"/projects/{project_b}/knowledge/{entry['id']}", json={"body": "hijacked"})
    assert response.status_code == 404


def test_create_rejects_empty_title():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={"title": "", "body": "something"})
    assert response.status_code == 422


# ── format_knowledge_context / KNOWLEDGE_CITATION ───────────────────────

def test_format_knowledge_context_empty_entries_is_empty_string():
    from app.services.knowledge_base import format_knowledge_context
    assert format_knowledge_context([]) == ""


def test_format_knowledge_context_renders_citable_kb_handle():
    from app.services.knowledge_base import format_knowledge_context
    entries = [{"id": 3, "entry_type": "rule", "title": "Refund window", "body": "14 days, not 30."}]
    rendered = format_knowledge_context(entries)
    assert "[KB-3]" in rendered
    assert "Refund window" in rendered
    assert "14 days, not 30." in rendered
    assert "Business rule" in rendered  # ENTRY_TYPE_LABELS


def test_knowledge_citation_matches_kb_handle():
    from app.services.knowledge_base import KNOWLEDGE_CITATION
    assert KNOWLEDGE_CITATION.search("See [KB-12] for details.").group(0) == "[KB-12]"
    assert not KNOWLEDGE_CITATION.search("See [3] for details.")


# ── wiki_generator.py grounding: [KB-n] accepted as citation evidence ───

def test_normalize_citation_accepts_kb_handle():
    from app.services.wiki_generator import _normalize_citation
    assert _normalize_citation("[KB-7]") == "[KB-7]"


def test_grounding_violations_accepts_kb_citation_as_evidence():
    from app.services.wiki_generator import _grounding_violations
    source_material = "[KB-1] (Business rule) Refund window: Refunds are only valid within 14 days."
    page = {"sections": [{
        "heading": "Refunds",
        "body": "Refunds are only accepted within 14 days of delivery.",
        "evidence": ["[KB-1]"],
    }]}
    assert _grounding_violations(page, source_material) == []


def test_grounding_violations_still_requires_evidence_when_kb_citations_present():
    """The presence of KB citations in the source material activates the
    grounding gate exactly like path:line citations do — a section with real
    KB material available but no evidence array is still a violation."""
    from app.services.wiki_generator import _grounding_violations
    source_material = "[KB-1] (Business rule) Refund window: Refunds are only valid within 14 days."
    page = {"sections": [{"heading": "Refunds", "body": "Refunds are handled specially.", "evidence": []}]}
    assert _grounding_violations(page, source_material) == ["section 'Refunds' has no source-file citation"]


def test_grounding_violations_accepts_mix_of_kb_and_path_line_citations():
    from app.services.wiki_generator import _grounding_violations
    source_material = (
        "[KB-1] (Business rule) Refund window: Refunds are only valid within 14 days.\n"
        "Evidence: src/refunds.py:42."
    )
    page = {"sections": [{
        "heading": "Refunds",
        "body": "Refunds are validated against a 14-day window before processing.",
        "evidence": ["[KB-1]", "src/refunds.py:42"],
    }]}
    assert _grounding_violations(page, source_material) == []


# ── Wiki message builders include the KB block ──────────────────────────

def test_build_project_wiki_message_includes_knowledge_context():
    from app.services.prompt import build_project_wiki_message
    message = build_project_wiki_message(
        "Acme", "desc", "brief", None, None,
        knowledge_context="## Project Knowledge Base\n\n[KB-1] (Business rule) Refund window: 14 days.",
    )
    assert "[KB-1]" in message
    assert "Project Knowledge Base" in message


def test_build_repo_wiki_message_includes_knowledge_context():
    from app.services.prompt import build_repo_wiki_message
    message = build_repo_wiki_message(
        "Acme", "acme-api", "context block", None, None,
        knowledge_context="## Project Knowledge Base\n\n[KB-2] (Decision) Auth: JWT, not sessions.",
    )
    assert "[KB-2]" in message


def test_build_chapter_wiki_message_includes_knowledge_context():
    from app.services.prompt import build_chapter_wiki_message
    message = build_chapter_wiki_message(
        "Acme", "acme-api", "chapter context", 0,
        knowledge_context="## Project Knowledge Base\n\n[KB-2] (Decision) Auth: JWT, not sessions.",
    )
    assert "[KB-2]" in message


# ── main.py: _with_project_instructions injects the knowledge base ──────

def _create_generation(project_id: int | None = None) -> int:
    from datetime import datetime, timezone
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO generations (created_at, project_name, input_text, output_json, project_id) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), "Test Project", "brief text", "{}", project_id),
    )
    conn.commit()
    gen_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()
    return gen_id


def test_with_project_instructions_prepends_knowledge_base():
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    database.add_knowledge_entry(project_id, "rule", "Refund window", "14 days, not 30.")
    result = main._with_project_instructions("Build a refund feature.", gen_id)
    assert "[KB-" in result
    assert "Refund window" in result
    assert result.endswith("Build a refund feature.")


def test_with_project_instructions_includes_both_instructions_and_knowledge():
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    database.upsert_project_settings(project_id, custom_instructions="Use snake_case.")
    database.add_knowledge_entry(project_id, "glossary", "SKU", "Stock Keeping Unit.")
    result = main._with_project_instructions("Build a catalog.", gen_id)
    assert "Use snake_case." in result
    assert "SKU" in result
    assert result.index("Project Instructions") < result.index("Project Knowledge Base")


def test_with_project_instructions_noop_when_no_instructions_or_knowledge():
    project_id = _create_project()
    gen_id = _create_generation(project_id)
    assert main._with_project_instructions("Build a thing.", gen_id) == "Build a thing."


def test_with_project_instructions_noop_when_generation_has_no_project():
    gen_id = _create_generation(project_id=None)
    assert main._with_project_instructions("Build a thing.", gen_id) == "Build a thing."


# ── parse_knowledge_markdown ─────────────────────────────────────────────

def test_parse_knowledge_markdown_splits_on_headings_and_classifies_type():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Glossary: SKU\n"
        "Stock Keeping Unit — a unique identifier per product variant, used across "
        "inventory and order systems.\n\n"
        "## Business Rule: Refund window\n"
        "Refunds are only valid within 14 days of delivery, not 30, per the 2025 policy update.\n\n"
        "## Decision: Auth approach\n"
        "We use JWT access tokens, not server-side sessions, for all new services.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert [c["title"] for c in candidates] == ["SKU", "Refund window", "Auth approach"]
    assert [c["entry_type"] for c in candidates] == ["glossary", "rule", "decision"]
    assert all(not c["needs_info"] for c in candidates)


def test_parse_knowledge_markdown_flags_empty_section():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Constraint: Rate limit\n\n## Next heading\nSome real content here about limits.")
    empty = candidates[0]
    assert empty["needs_info"] is True
    assert "no content" in empty["reason"]


def test_parse_knowledge_markdown_flags_too_short_section():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Rule: Refunds\nShort.")
    assert candidates[0]["needs_info"] is True
    assert "short" in candidates[0]["reason"].lower()


def test_parse_knowledge_markdown_flags_placeholder_marker():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Decision: Payments provider\nTBD - need to confirm with finance team before shipping this.")
    assert candidates[0]["needs_info"] is True
    assert "placeholder" in candidates[0]["reason"]


def test_parse_knowledge_markdown_no_headings_becomes_one_candidate():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("Just some plain notes with no heading structure at all here.")
    assert len(candidates) == 1
    assert candidates[0]["title"] == "Untitled"
    assert candidates[0]["needs_info"] is False


def test_parse_knowledge_markdown_empty_text_returns_no_candidates():
    from app.services.knowledge_base import parse_knowledge_markdown
    assert parse_knowledge_markdown("   ") == []


def test_parse_knowledge_markdown_defaults_unrecognized_heading_to_glossary():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Onboarding flow\nNew users go through email verification before accessing the dashboard.")
    assert candidates[0]["entry_type"] == "glossary"


def test_parse_knowledge_markdown_strips_category_prefix_from_title():
    """prompts/EXTRACT_KNOWLEDGE_BASE.md's output shape prefixes every
    heading with its category label ("## Rule: Refund window") so the type
    can be classified — that label shouldn't also survive into the display
    title once the type badge already shows it."""
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Glossary: SKU\nStock Keeping Unit, unique per product variant across systems.\n\n"
        "## Business Rule: Refund window\nRefunds are valid within 14 days of delivery, not 30.\n\n"
        "## Constraint: Rate limit\nMax 100 requests per minute per API key, enforced at the gateway.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert [c["title"] for c in candidates] == ["SKU", "Refund window", "Rate limit"]
    assert [c["entry_type"] for c in candidates] == ["glossary", "rule", "constraint"]


def test_parse_knowledge_markdown_leaves_heading_without_category_label_untouched():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Onboarding flow\nNew users go through email verification before accessing the dashboard.")
    assert candidates[0]["title"] == "Onboarding flow"


# ── sdlc_area extraction (prompts/GENERATE_KNOWLEDGE_BASE_FROM_REPO.md's
#    "## Rule: Name (SDLC Area)" heading shape) ─────────────────────────

def test_parse_knowledge_markdown_extracts_recognized_sdlc_area():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Rule: Maker-Checker approval (Business Rules)\n"
        "All financial transactions above ₹10,000 require a second approver who is not the request creator.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["title"] == "Maker-Checker approval"
    assert candidates[0]["sdlc_area"] == "Business Rules"


def test_parse_knowledge_markdown_area_tag_is_case_insensitive():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = "## Constraint: Rate limit (non-functional requirements)\nMax 100 requests per minute per API key, enforced at the gateway.\n"
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["sdlc_area"] == "Non-Functional Requirements"


def test_parse_knowledge_markdown_unrecognized_parenthetical_is_not_treated_as_area():
    """A parenthetical that isn't one of the 15 known areas is left in the
    title untouched rather than silently swallowed as a bogus area tag —
    e.g. a human note, a ticket reference, a symbol name."""
    from app.services.knowledge_base import parse_knowledge_markdown
    text = "## Glossary: SKU (see JIRA-1234)\nStock Keeping Unit, unique per product variant across systems.\n"
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["title"] == "SKU (see JIRA-1234)"
    assert candidates[0]["sdlc_area"] is None


def test_parse_knowledge_markdown_no_area_tag_is_none():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Rule: Refund window\nRefunds are valid within 14 days of delivery, not 30.\n")
    assert candidates[0]["sdlc_area"] is None


def test_sdlc_areas_list_has_all_15_canonical_names():
    from app.services.knowledge_base import SDLC_AREAS
    assert len(SDLC_AREAS) == 15
    assert SDLC_AREAS[0] == "Business Context"
    assert SDLC_AREAS[-1] == "Operations & Production"


# ── "Source: path" line stripped out of body; code-leakage detection ────
# Regression coverage for a real bad run: prompts/GENERATE_KNOWLEDGE_BASE_
# FROM_REPO.md originally allowed "the real file/module ... if useful
# context" inline, and a real extraction produced bodies like "`Facility
# Application` defines three `JavaMailSender` beans bound to `spring.mail`"
# — unreadable to anyone who hasn't opened the codebase. Both the prompt and
# the parser were tightened; these tests cover the parser side.

def test_parse_knowledge_markdown_strips_source_line_out_of_body():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Rule: Exam session scheduling (Business Rules)\n"
        "The system supports scheduling proctored exam sessions tied to a location and a device, with a "
        "time-limited access password.\n"
        "Source: db/migrations/V6__create_exam_session_table.sql\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["source"] == "db/migrations/V6__create_exam_session_table.sql"
    assert "Source:" not in candidates[0]["body"]
    assert "migrations" not in candidates[0]["body"]
    assert candidates[0]["needs_info"] is False


def test_parse_knowledge_markdown_no_source_line_is_none():
    from app.services.knowledge_base import parse_knowledge_markdown
    candidates = parse_knowledge_markdown("## Rule: Refund window\nRefunds are valid within 14 days of delivery, not 30.\n")
    assert candidates[0]["source"] is None


def test_parse_knowledge_markdown_flags_backtick_code_leaked_into_body():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Decision: Mail sender design (Architecture Decisions)\n"
        "`FacilityApplication` defines three distinct `JavaMailSender` beans bound to `spring.mail` prefixes.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["needs_info"] is True
    assert "plain business language" in candidates[0]["reason"]


def test_parse_knowledge_markdown_flags_file_extension_leaked_into_body():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = "## Glossary: Exam session (Domain & Glossary)\nDefined in V6_Create_exam_session_table.sql with several tracked fields.\n"
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["needs_info"] is True


def test_parse_knowledge_markdown_flags_enum_value_dump_exact_regression():
    """The exact real bad entry that motivated broadening CODE_LEAKAGE_RE
    beyond backticks/file-extensions — flag it whether or not the model
    wrapped the tokens in backticks."""
    from app.services.knowledge_base import parse_knowledge_markdown
    with_backticks = (
        "## Glossary: NotificationType enum (Domain & Glossary)\n"
        "`NotificationType` (`constants/NotificationType.java`) has 4 values: `NONE(0)`, `SMS(1)`, `EMAIL(2)`, "
        "`VAIOT(3)`. VAIOT-sourced notifications are tagged with type id 3.\n"
    )
    without_backticks = (
        "## Glossary: NotificationType enum (Domain & Glossary)\n"
        "NotificationType has 4 values: NONE(0), SMS(1), EMAIL(2), VAIOT(3). VAIOT-sourced notifications are "
        "tagged with type id 3.\n"
    )
    for text in (with_backticks, without_backticks):
        candidates = parse_knowledge_markdown(text)
        assert candidates[0]["needs_info"] is True, text


def test_parse_knowledge_markdown_does_not_flag_plain_business_prose():
    """Regression against over-eager flagging — a body with a capitalized
    business term or a number-with-comma should never trip the leakage
    check just because it superficially resembles code."""
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Rule: Large invoice approval (Business Rules)\n"
        "Invoices above 5,00,000 rupees require sign-off from both the Finance Manager and the CFO before "
        "payment is released.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["needs_info"] is False


def test_parse_knowledge_markdown_accepts_clean_plain_language_body():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Rule: Exam session scheduling (Business Rules)\n"
        "The system supports scheduling proctored exam sessions tied to a location and a device, with an "
        "access password that is only valid for a limited time window.\n"
        "Source: db/migrations/V6__create_exam_session_table.sql\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["needs_info"] is False


# ── /knowledge/extract endpoint ──────────────────────────────────────────

def test_extract_endpoint_404s_for_missing_project():
    response = client.post(
        "/projects/999999/knowledge/extract",
        files={"file": ("kb.md", b"## Term\nSome real definition text here.", "text/markdown")},
    )
    assert response.status_code == 404


def test_extract_endpoint_rejects_unsupported_extension():
    project_id = _create_project()
    response = client.post(
        f"/projects/{project_id}/knowledge/extract",
        files={"file": ("kb.txt", b"content", "text/plain")},
    )
    assert response.status_code == 400


def test_extract_endpoint_returns_candidates_and_gap_count():
    project_id = _create_project()
    content = (
        "## Glossary: SKU\n"
        "Stock Keeping Unit — a unique identifier per product variant.\n\n"
        "## Rule: Refund window\nTBD\n"
    ).encode("utf-8")
    response = client.post(
        f"/projects/{project_id}/knowledge/extract",
        files={"file": ("kb.md", content, "text/markdown")},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 2
    assert body["gap_count"] == 1
    assert body["candidates"][1]["needs_info"] is True


def test_extract_endpoint_does_not_persist_anything():
    """Extraction is review-before-save — this call must never write to the
    database, only parse and return candidates."""
    project_id = _create_project()
    content = b"## Glossary: SKU\nStock Keeping Unit, unique per product variant."
    client.post(f"/projects/{project_id}/knowledge/extract", files={"file": ("kb.md", content, "text/markdown")})
    assert database.list_knowledge_entries(project_id) == []


# ── extract_knowledge_from_repo (LLM-backed, code-grounded) ─────────────

class _FakeRepoProvider:
    """Minimal AIProvider stand-in (generate(system_prompt, user_message) ->
    str duck-type — see AutoSDLCChatModel's own docstring) for
    extract_knowledge_from_repo, which builds its own AutoSDLCChatModel
    internally rather than taking one as an argument."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self._responses[len(self.calls) - 1]


def test_extract_knowledge_from_repo_returns_grounded_candidates():
    from app.services.knowledge_base import extract_knowledge_from_repo

    context_block = "- `MAX_LOGIN_ATTEMPTS = 5` (constant) — `app/auth/config.py:12`"
    response = json.dumps({"candidates": [
        {"entry_type": "constraint", "title": "Max login attempts", "sdlc_area": "Non-Functional Requirements",
         "body": "An account is locked after 5 failed login attempts within 15 minutes.",
         "evidence": ["app/auth/config.py:12"], "needs_info": False, "reason": None},
    ]})
    provider = _FakeRepoProvider([response])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", context_block, None)
    assert candidates == [{
        "entry_type": "constraint", "title": "Max login attempts", "sdlc_area": "Non-Functional Requirements",
        "business_context_kind": None,
        "body": "An account is locked after 5 failed login attempts within 15 minutes.",
        "source": "app/auth/config.py:12", "needs_info": False, "reason": None,
    }]


def test_extract_knowledge_from_repo_flags_candidate_with_no_citation():
    """Real repository intelligence was supplied (context_block has real
    path:line facts), so a candidate that claims something with an empty
    evidence array is a gap, not a trusted fact — same grounding gate
    wiki_generator._grounding_violations applies to wiki sections."""
    from app.services.knowledge_base import extract_knowledge_from_repo

    context_block = "- `MAX_LOGIN_ATTEMPTS = 5` (constant) — `app/auth/config.py:12`"
    response = json.dumps({"candidates": [
        {"entry_type": "rule", "title": "Unclear approval rule", "body": "Orders above some threshold need manager approval.",
         "evidence": [], "needs_info": False, "reason": None},
    ]})
    provider = _FakeRepoProvider([response])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", context_block, None)
    assert candidates[0]["needs_info"] is True
    assert "no source citation" in candidates[0]["reason"]


def test_extract_knowledge_from_repo_rejects_vendor_only_citation():
    from app.services.knowledge_base import extract_knowledge_from_repo

    context_block = "- `MAX_LOGIN_ATTEMPTS = 5` (constant) — `app/auth/config.py:12`"
    response = json.dumps({"candidates": [
        {"entry_type": "glossary", "title": "Bogus", "body": "Something invented from a vendor file.",
         "evidence": ["node_modules/lodash/lodash.js:100"], "needs_info": False, "reason": None},
    ]})
    provider = _FakeRepoProvider([response])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", context_block, None)
    assert candidates[0]["needs_info"] is True
    assert "third-party" in candidates[0]["reason"]


def test_extract_knowledge_from_repo_preserves_model_flagged_gap():
    from app.services.knowledge_base import extract_knowledge_from_repo

    context_block = "- `MAX_LOGIN_ATTEMPTS = 5` (constant) — `app/auth/config.py:12`"
    response = json.dumps({"candidates": [
        {"entry_type": "decision", "title": "Auth approach", "body": "Unclear whether this is JWT or session-based from the code alone.",
         "evidence": [], "needs_info": True, "reason": "Auth middleware isn't in the indexed files."},
    ]})
    provider = _FakeRepoProvider([response])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", context_block, None)
    assert candidates[0]["needs_info"] is True
    assert candidates[0]["reason"] == "Auth middleware isn't in the indexed files."


def test_extract_knowledge_from_repo_repairs_invalid_json_once():
    from app.services.knowledge_base import extract_knowledge_from_repo

    context_block = "- `MAX_LOGIN_ATTEMPTS = 5` (constant) — `app/auth/config.py:12`"
    good = json.dumps({"candidates": [
        {"entry_type": "constraint", "title": "Max login attempts", "body": "Locked after 5 failed attempts, per config.",
         "evidence": ["app/auth/config.py:12"], "needs_info": False, "reason": None},
    ]})
    provider = _FakeRepoProvider(["not valid json at all", good])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", context_block, None)
    assert len(candidates) == 1
    assert len(provider.calls) == 2


def test_extract_knowledge_from_repo_ungrounded_material_does_not_force_citations():
    """No repository intelligence was actually available (e.g. Bitbucket
    unreachable) — nothing here should demand citations the model was never
    given, same as wiki_generator's grounding gate."""
    from app.services.knowledge_base import extract_knowledge_from_repo

    response = json.dumps({"candidates": [
        {"entry_type": "glossary", "title": "Facility", "body": "A physical site tracked by the platform.",
         "evidence": [], "needs_info": False, "reason": None},
    ]})
    provider = _FakeRepoProvider([response])
    candidates = extract_knowledge_from_repo(provider, "REMP", "backend", "", None)
    assert candidates[0]["needs_info"] is False


# ── POST /projects/{id}/knowledge/extract-from-repo endpoint ────────────
# Same monkeypatch shape as tests/test_project_wiki.py's wiki-generation
# tests — _collect_repo_wiki_material is the shared repo-intelligence
# pipeline, so faking Bitbucket at the same seams proves this endpoint is
# wired the same way, not a separate code path with its own bugs.

def test_extract_from_repo_endpoint_404s_for_missing_project():
    response = client.post("/projects/999999/knowledge/extract-from-repo")
    assert response.status_code == 404


def test_extract_from_repo_endpoint_400s_with_no_linked_repos():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge/extract-from-repo")
    assert response.status_code == 400


def test_extract_from_repo_endpoint_returns_grounded_candidates(monkeypatch):
    provider = _FakeRepoProvider([json.dumps({"candidates": [
        {"entry_type": "constraint", "title": "Max login attempts",
         "body": "An account is locked after 5 failed login attempts, per the auth config.",
         "evidence": ["src/app.py:1"], "needs_info": False, "reason": None},
    ]})])
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"mainbranch": {"name": "main", "target": {"hash": "abc123"}}})

    def fake_snapshot(config, destination, branch=None, timeout_seconds=None, **kwargs):
        target = destination / "src" / "app.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("from fastapi import FastAPI")
        return "abc123"
    monkeypatch.setattr(projects_api, "create_repository_snapshot", fake_snapshot)
    import bitbucket.client as bb_client
    monkeypatch.setattr(bb_client, "list_repo_files", lambda config, path="", ref="HEAD": [{"type": "commit_file", "path": "src/app.py"}])
    monkeypatch.setattr(bb_client, "get_file_content", lambda config, path, ref="HEAD": "from fastapi import FastAPI")
    monkeypatch.setattr(projects_api, "get_file_content", lambda config, path: None)

    project_id = _create_project()
    client.post(f"/projects/{project_id}/repos", json={"workspace": "kritilabs", "repo_slug": "fits-service", "verify": False})

    response = client.post(f"/projects/{project_id}/knowledge/extract-from-repo")
    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["title"] == "Max login attempts"
    assert body["gap_count"] == 0
    assert body["repo_errors"] == []


def test_extract_from_repo_endpoint_does_not_persist_anything(monkeypatch):
    provider = _FakeRepoProvider([json.dumps({"candidates": [
        {"entry_type": "glossary", "title": "SKU", "body": "Stock Keeping Unit, unique per product variant.",
         "evidence": ["src/app.py:1"], "needs_info": False, "reason": None},
    ]})])
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"mainbranch": {"name": "main", "target": {"hash": "abc123"}}})

    def fake_snapshot(config, destination, branch=None, timeout_seconds=None, **kwargs):
        target = destination / "src" / "app.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("from fastapi import FastAPI")
        return "abc123"
    monkeypatch.setattr(projects_api, "create_repository_snapshot", fake_snapshot)
    import bitbucket.client as bb_client
    monkeypatch.setattr(bb_client, "list_repo_files", lambda config, path="", ref="HEAD": [{"type": "commit_file", "path": "src/app.py"}])
    monkeypatch.setattr(bb_client, "get_file_content", lambda config, path, ref="HEAD": "from fastapi import FastAPI")
    monkeypatch.setattr(projects_api, "get_file_content", lambda config, path: None)

    project_id = _create_project()
    client.post(f"/projects/{project_id}/repos", json={"workspace": "kritilabs", "repo_slug": "fits-service", "verify": False})
    client.post(f"/projects/{project_id}/knowledge/extract-from-repo")
    assert database.list_knowledge_entries(project_id) == []


# ── GET /projects/{id}/knowledge/quality-check ───────────────────────────
# Retroactive re-check for entries saved before check_body_quality existed
# (or before CODE_LEAKAGE_RE was broadened) — real motivating case: an entry
# reading "`NotificationType` has 4 values: `NONE(0)`, `SMS(1)` ..." that had
# already been saved with no gap flag at all.

def test_quality_check_endpoint_404s_for_missing_project():
    response = client.get("/projects/999999/knowledge/quality-check")
    assert response.status_code == 404


def test_quality_check_endpoint_flags_pre_existing_bad_entry():
    project_id = _create_project()
    bad = database.add_knowledge_entry(
        project_id, "glossary", "NotificationType enum",
        "`NotificationType` (`constants/NotificationType.java`) has 4 values: `NONE(0)`, `SMS(1)`, `EMAIL(2)`, `VAIOT(3)`.",
    )
    good = database.add_knowledge_entry(project_id, "rule", "Refund window", "Refunds are valid within 14 days of delivery, not 30.")

    response = client.get(f"/projects/{project_id}/knowledge/quality-check")
    assert response.status_code == 200
    body = response.json()
    assert body["checked_count"] == 2
    flagged_ids = [f["id"] for f in body["flagged"]]
    assert bad["id"] in flagged_ids
    assert good["id"] not in flagged_ids
    assert "plain business language" in next(f for f in body["flagged"] if f["id"] == bad["id"])["reason"]


def test_quality_check_endpoint_empty_when_nothing_flagged():
    project_id = _create_project()
    database.add_knowledge_entry(project_id, "rule", "Refund window", "Refunds are valid within 14 days of delivery, not 30.")
    response = client.get(f"/projects/{project_id}/knowledge/quality-check")
    assert response.json()["flagged"] == []


def test_quality_check_endpoint_does_not_modify_entries():
    """Read-only — re-checking must never mutate the saved entry itself,
    only report what's wrong so the user can fix it themselves."""
    project_id = _create_project()
    bad = database.add_knowledge_entry(project_id, "glossary", "X", "NONE(0), SMS(1), EMAIL(2), VAIOT(3) are the four values.")
    client.get(f"/projects/{project_id}/knowledge/quality-check")
    unchanged = database.get_knowledge_entry(bad["id"])
    assert unchanged["body"] == bad["body"]


# ── business_context_kind — Business Context's structured breakdown
# (objective/stakeholder/scope_boundary/success_metric) in place of the
# generic entry_type, matching the reference table's row #01. ────────────

def test_add_knowledge_entry_persists_business_context_kind():
    project_id = _create_project()
    entry = database.add_knowledge_entry(
        project_id, "glossary", "Reduce approval time", "Cut manual approval time by 40% within two quarters.",
        "Business Context", "objective",
    )
    assert entry["business_context_kind"] == "objective"
    assert database.list_knowledge_entries(project_id)[0]["business_context_kind"] == "objective"


def test_add_knowledge_entry_business_context_kind_defaults_to_none():
    project_id = _create_project()
    entry = database.add_knowledge_entry(project_id, "glossary", "SKU", "Stock Keeping Unit.")
    assert entry["business_context_kind"] is None


def test_create_endpoint_persists_business_context_kind_for_business_context_area():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "Reduce approval time", "body": "Cut manual approval time by 40% within two quarters.",
        "sdlc_area": "Business Context", "business_context_kind": "objective",
    })
    assert response.json()["business_context_kind"] == "objective"


def test_create_endpoint_drops_business_context_kind_for_other_areas():
    """A business_context_kind only means something on a Business Context
    entry — a client sending it for any other area gets it silently dropped
    rather than stored, same defensive normalization as sdlc_area itself."""
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "Refund window", "body": "14 days, not 30.",
        "sdlc_area": "Business Rules", "business_context_kind": "objective",
    })
    assert response.json()["business_context_kind"] is None


def test_create_endpoint_rejects_unrecognized_business_context_kind():
    project_id = _create_project()
    response = client.post(f"/projects/{project_id}/knowledge", json={
        "title": "X", "body": "Some real content about the project's goals here.",
        "sdlc_area": "Business Context", "business_context_kind": "not_a_real_kind",
    })
    assert response.status_code == 422


def test_update_endpoint_clears_business_context_kind_when_area_changes_away():
    project_id = _create_project()
    entry = database.add_knowledge_entry(
        project_id, "glossary", "Reduce approval time", "Cut manual approval time by 40%.",
        "Business Context", "objective",
    )
    response = client.put(f"/projects/{project_id}/knowledge/{entry['id']}", json={"sdlc_area": "Business Rules"})
    assert response.json()["business_context_kind"] is None


def test_parse_knowledge_markdown_classifies_business_context_kind_from_heading():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Objective: Reduce approval time (Business Context)\n"
        "Cut manual approval time by 40% within the first two quarters of the rollout.\n\n"
        "## Stakeholder: Head of Operations (Business Context)\n"
        "Owns the go-live decision and reports project status to the board every month.\n\n"
        "## Scope Boundary: Mobile app excluded (Business Context)\n"
        "Mobile app support is explicitly out of scope for the phase-1 release.\n\n"
        "## Success Metric: Onboarding target (Business Context)\n"
        "95% of users must be onboarded within 30 days of the launch date.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert [c["business_context_kind"] for c in candidates] == ["objective", "stakeholder", "scope_boundary", "success_metric"]
    # The kind label is stripped from the title the same way Rule:/Decision:/etc are.
    assert candidates[0]["title"] == "Reduce approval time"
    assert candidates[1]["title"] == "Head of Operations"


def test_parse_knowledge_markdown_classifies_the_three_brd_opening_kinds():
    """The 3 kinds added alongside the original 4 — the real Business Case/
    Charter sections a BRD opens with, ahead of objectives/stakeholders/
    scope/metrics."""
    from app.services.knowledge_base import parse_knowledge_markdown
    text = (
        "## Problem Statement: Manual approvals are slow (Business Context)\n"
        "Facility managers wait an average of 5 business days for approval on routine maintenance requests.\n\n"
        "## Competitive Landscape: No integrated tool (Business Context)\n"
        "Competing products handle facility management and asset tracking separately, requiring manual reconciliation.\n\n"
        "## Proposed Solution: Unified platform (Business Context)\n"
        "A single platform combining facility hierarchy, asset tracking, and IoT alerting into one system.\n"
    )
    candidates = parse_knowledge_markdown(text)
    assert [c["business_context_kind"] for c in candidates] == ["problem_statement", "competitive_landscape", "proposed_solution"]
    assert candidates[0]["title"] == "Manual approvals are slow"
    assert candidates[1]["title"] == "No integrated tool"
    assert candidates[2]["title"] == "Unified platform"


def test_business_context_kinds_has_all_7_canonical_kinds():
    from app.services.knowledge_base import BUSINESS_CONTEXT_KINDS
    assert BUSINESS_CONTEXT_KINDS == [
        "problem_statement", "competitive_landscape", "proposed_solution",
        "objective", "stakeholder", "scope_boundary", "success_metric",
    ]


def test_parse_knowledge_markdown_business_context_kind_none_outside_business_context():
    from app.services.knowledge_base import parse_knowledge_markdown
    text = "## Rule: Refund window (Business Rules)\nRefunds are valid within 14 days of delivery, not 30.\n"
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["business_context_kind"] is None


def test_parse_knowledge_markdown_business_context_without_recognized_kind_keyword_is_none():
    """A Business Context heading that doesn't use one of the four kind
    labels still parses (still grouped under Business Context), just with
    no kind classified — never guessed at."""
    from app.services.knowledge_base import parse_knowledge_markdown
    text = "## Something else entirely (Business Context)\nA fact that doesn't map cleanly to any of the four kinds.\n"
    candidates = parse_knowledge_markdown(text)
    assert candidates[0]["sdlc_area"] == "Business Context"
    assert candidates[0]["business_context_kind"] is None
