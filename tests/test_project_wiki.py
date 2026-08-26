"""Tests for the project/repo wiki endpoints (app/api/projects.py) and their
DB layer (project_wiki_pages / upsert_wiki_page / get_wiki_page /
list_wiki_pages in app/services/database.py).

Uses a minimal stub provider — same style as tests/test_code_review_job.py's
StubReviewProvider — since wiki generation is the other call site that goes
through AutoSDLCChatModel/LangChain rather than PhaseGenerator's plain
generate(), and the assertions here are about the endpoint/DB contract, not
prompt formatting."""
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
from app.services.providers import AllProvidersExhaustedError  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AUTOSDLC_ARTIFACT_ROOT", str(tmp_path / "wiki_artifacts"))
    database.init_db()


class StubWikiProvider:
    """generate() returns a fixed wiki JSON object regardless of prompt
    content, so tests assert on the endpoint/DB contract rather than on
    exactly what got sent to the model."""

    def __init__(self, page=None, raise_error=None):
        self.calls = []
        self._page = page if page is not None else {
            "title": "Smart Turf",
            "summary": "A booking platform for turf facilities.",
            "sections": [{"heading": "What it does", "body": "Lets customers book turf slots online.", "evidence": ["src/app.py:1"]}],
        }
        self._raise_error = raise_error

    def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        if self._raise_error:
            raise self._raise_error
        return json.dumps(self._page)


def _stub(monkeypatch, provider):
    monkeypatch.setattr(projects_api, "get_provider", lambda: provider)


def _create_project(name="Smart Turf", description="Turf booking"):
    return client.post("/projects", json={"name": name, "description": description}).json()


# ── Project wiki ─────────────────────────────────────────────────────────

def test_generate_project_wiki_with_no_generations(monkeypatch):
    """No backlog yet — the endpoint must still succeed, grounding the prompt
    in project name/description alone rather than erroring."""
    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    page = response.json()
    assert page["title"] == "Smart Turf"
    assert page["repo_id"] is None
    assert page["sections"][0]["heading"] == "What it does"
    assert page["artifact_key"].endswith("/overview.md")
    artifact_root = Path(__import__("os").environ["AUTOSDLC_ARTIFACT_ROOT"])
    assert (artifact_root / page["artifact_key"]).read_text().startswith("# Smart Turf")
    assert (artifact_root / Path(page["artifact_key"]).parent / "manifest.json").is_file()

    # A manually supplied brief is optional; the prompt explicitly permits
    # generation from the project and linked repositories alone.
    _, user_message = provider.calls[0]
    assert "No project brief was supplied" in user_message


def test_generate_project_wiki_grounds_on_latest_generation_brief(monkeypatch):
    """Inserts a generation row directly via save_generation rather than
    running /generate-stream — no AI provider is involved in producing the
    backlog itself, only in the wiki call under test."""
    from app.schemas.models import GenerationOutput

    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    project = _create_project()

    brief = "Build a turf booking app with slot reservation and payments."
    output = GenerationOutput(needs_clarification=False, clarifying_questions=[], stories=[], tasks=[], gaps=[])
    database.save_generation(brief, output, project_id=project["id"])

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    _, user_message = provider.calls[0]
    assert "turf booking" in user_message.lower()


def test_generate_project_wiki_grounds_on_linked_repo_contents(monkeypatch):
    """A project-level 'Generate overview' with a linked repo must feed that
    repo's file listing/README into the prompt too, not just the brief —
    otherwise clicking Generate overview never actually looks at the repo."""
    import bitbucket.client as bb_client

    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(projects_api, "get_repo_metadata", lambda config: {"mainbranch": {"name": "main", "target": {"hash": "abc123"}}})
    snapshot_branches = []
    def fake_snapshot(config, destination, branch=None, timeout_seconds=None, **kwargs):
        snapshot_branches.append(branch)
        target = destination / "src" / "app.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("from fastapi import FastAPI")
        return "abc123"
    monkeypatch.setattr(projects_api, "create_repository_snapshot", fake_snapshot)
    monkeypatch.setattr(
        bb_client, "list_repo_files",
        lambda config, path="", ref="HEAD": [{"type": "commit_file", "path": "src/app.py"}],
    )
    monkeypatch.setattr(
        bb_client, "get_file_content",
        lambda config, path, ref="HEAD": "from fastapi import FastAPI",
    )
    # build_repo_context_block calls list_repo_files as a same-module name,
    # so patching it on bb_client is enough; _readme_content in projects.py
    # imported get_file_content by name, so that one needs patching there.
    monkeypatch.setattr(projects_api, "get_file_content", lambda config, path: "# fits-service\nA backend service.")
    project = _create_project()
    repo = client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    }).json()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 200
    page = response.json()
    _, user_message = provider.calls[0]
    assert "src/app.py" in user_message
    assert "fits-service" in user_message.lower()
    assert snapshot_branches == ["main"]
    # A project page uses a combined revision; the single linked repository's
    # own index revision is recorded in its manifest source entry.
    artifact_root = Path(__import__("os").environ["AUTOSDLC_ARTIFACT_ROOT"])
    bundle = artifact_root / Path(page["artifact_key"]).parent
    manifest = json.loads((bundle / "manifest.json").read_text())
    repo_revision = manifest["sources"][0]["revision"]
    assert database.get_repository_index(repo["id"], repo_revision) is not None
    assert manifest["sources"][0]["ref"] == "main"
    assert any(path.name == "architecture.md" for path in bundle.rglob("architecture.md"))


def test_generate_project_wiki_combines_all_linked_repositories_without_brief(monkeypatch):
    provider = StubWikiProvider()
    _stub(monkeypatch, provider)
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        projects_api,
        "_collect_repo_wiki_material",
        lambda repo, project_id=None: {
            "label": repo["label"] or repo["repo_slug"],
            "repo_full_name": f"{repo['workspace']}/{repo['repo_slug']}",
            "context_block": f"architecture evidence from {repo['repo_slug']}",
            "readme_text": None,
        },
    )
    project = _create_project()
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-ui", "label": "frontend", "verify": False,
    })
    client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "label": "backend", "verify": False,
    })

    response = client.post(f"/projects/{project['id']}/wiki/generate")

    assert response.status_code == 200
    _, user_message = provider.calls[0]
    assert "No project brief was supplied" in user_message
    assert "architecture evidence from fits-ui" in user_message
    assert "architecture evidence from fits-service" in user_message


def test_generate_project_wiki_404_for_missing_project(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    assert client.post("/projects/999999/wiki/generate").status_code == 404


def test_generate_project_wiki_maps_provider_exhaustion_to_503(monkeypatch):
    provider = StubWikiProvider(raise_error=AllProvidersExhaustedError("no provider available"))
    _stub(monkeypatch, provider)
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 503


def test_generate_project_wiki_502_on_malformed_model_response(monkeypatch):
    class RawProvider:
        def generate(self, system_prompt, user_message):
            return "not json"

    _stub(monkeypatch, RawProvider())
    project = _create_project()

    response = client.post(f"/projects/{project['id']}/wiki/generate")
    assert response.status_code == 502


def test_get_project_wiki_round_trips_generated_page(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    generated = client.post(f"/projects/{project['id']}/wiki/generate").json()

    fetched = client.get(f"/projects/{project['id']}/wiki")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["project_id"] == project["id"]
    assert len(body["pages"]) == 1
    assert body["pages"][0]["id"] == generated["id"]
    assert body["pages"][0]["title"] == generated["title"]


def test_wiki_background_runner_emits_real_status_and_done(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()

    events = list(projects_api._wiki_generation_job_runner({"project_id": project["id"]}))

    assert events[0] == ("status", {"message": "Reading and indexing all linked repositories…"})
    assert events[-1][0] == "done"
    assert events[-1][1]["page"]["title"] == "Smart Turf"
    assert database.get_wiki_page(project["id"])["title"] == "Smart Turf"


def test_wiki_background_runner_requests_clarification_without_persisting(monkeypatch):
    _stub(monkeypatch, StubWikiProvider(page={
        "needs_clarification": True,
        "clarifying_questions": [{
            "id": "als_meaning",
            "question": "What does ALS mean in this product?",
            "why": "It changes how the telemetry workflow should be described.",
        }],
    }))
    project = _create_project("I Kendrit")

    events = list(projects_api._wiki_generation_job_runner({"project_id": project["id"]}))

    assert events[-1] == ("clarification", {"questions": [{
        "id": "als_meaning",
        "question": "What does ALS mean in this product?",
        "why": "It changes how the telemetry workflow should be described.",
    }]})
    assert database.list_wiki_pages(project["id"]) == []


def test_regenerating_project_wiki_overwrites_not_duplicates(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    first = client.post(f"/projects/{project['id']}/wiki/generate").json()

    _stub(monkeypatch, StubWikiProvider(page={
        "title": "Smart Turf v2", "summary": "Updated.", "sections": [],
    }))
    second = client.post(f"/projects/{project['id']}/wiki/generate").json()

    assert second["id"] == first["id"]
    assert second["title"] == "Smart Turf"
    pages = client.get(f"/projects/{project['id']}/wiki").json()["pages"]
    assert len(pages) == 1


def test_get_project_wiki_404_for_missing_project():
    assert client.get("/projects/999999/wiki").status_code == 404


# ── Repo wiki ────────────────────────────────────────────────────────────

def test_generate_repo_wiki_without_bitbucket_configured(monkeypatch):
    """Never fabricate a repository wiki when no source can be retrieved."""
    provider = StubWikiProvider(page={
        "title": "fits-service", "summary": "Backend service repo.", "sections": [],
    })
    _stub(monkeypatch, provider)
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    project = _create_project()
    repo = client.post(f"/projects/{project['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-service", "verify": False,
    }).json()

    response = client.post(f"/projects/{project['id']}/repos/{repo['id']}/wiki/generate")
    assert response.status_code == 502
    assert "No wiki was generated from empty data" in response.json()["error"]["message"]
    assert provider.calls == []


def test_generate_repo_wiki_404_for_repo_not_on_project(monkeypatch):
    _stub(monkeypatch, StubWikiProvider())
    project_a = _create_project("A")
    project_b = _create_project("B")
    repo = client.post(f"/projects/{project_b['id']}/repos", json={
        "workspace": "acme", "repo_slug": "fits-ui", "verify": False,
    }).json()

    response = client.post(f"/projects/{project_a['id']}/repos/{repo['id']}/wiki/generate")
    assert response.status_code == 404


def test_wiki_page_deleted_when_project_deleted(monkeypatch):
    """Cascade via ON DELETE CASCADE on project_wiki_pages.project_id."""
    _stub(monkeypatch, StubWikiProvider())
    project = _create_project()
    client.post(f"/projects/{project['id']}/wiki/generate")

    client.delete(f"/projects/{project['id']}")
    assert database.get_wiki_page(project["id"]) is None


def test_source_citation_recognizes_any_source_extension():
    """build_repo_context_block() (bitbucket/client.py) pulls files of any
    extension into the wiki prompt, and the prompt asks for `path:line`
    citations regardless of file type — the citation regex must not
    silently reject a correctly-formatted citation just because it points
    at a .cs/.go/.php/.sql/.vue file instead of one of a hardcoded few."""
    from app.services.wiki_generator import SOURCE_CITATION

    for citation in (
        "controllers/CameraAlertController.cs:42",
        "internal/alerts/dispatch.go:118",
        "app/Http/Controllers/FacilityController.php:7",
        "db/migrations/0007_add_camera_alerts.sql:3",
        "src/components/ScheduleBoard.vue:56",
    ):
        assert SOURCE_CITATION.search(f"See {citation} for the implementation."), citation


def test_grounding_violations_accepts_non_whitelisted_extension_citation():
    from app.services.wiki_generator import _grounding_violations

    source_material = "Evidence: controllers/CameraAlertController.cs:42."
    page = {"sections": [{"heading": "VAIOT IoT camera alerts", "body": "Alerts are dispatched to on-site staff.", "evidence": ["controllers/CameraAlertController.cs:42"]}]}
    assert _grounding_violations(page, source_material) == []


def test_grounding_violations_rejects_citation_embedded_in_body_instead_of_evidence():
    """Citations belong in the section's "evidence" array, never inline in
    "body" — this is the exact failure mode observed live against
    mistral-small-latest: the model wrote a route mention in prose instead
    of a path:line citation in the evidence field, and the old body-scanning
    check let that slide because *something* matched the citation shape."""
    from app.services.wiki_generator import _grounding_violations

    source_material = "Evidence: controllers/CameraAlertController.cs:42."
    page = {"sections": [{"heading": "IoT alerts", "body": "Alerts are dispatched from controllers/CameraAlertController.cs:42.", "evidence": []}]}
    assert _grounding_violations(page, source_material) == ["section 'IoT alerts' has no source-file citation"]


def test_grounding_violations_rejects_route_mention_as_evidence():
    """A route/endpoint string is not a path:line citation, even though it
    looks 'sourced' — this is what mistral-small-latest substituted in
    practice when asked for evidence it didn't want to write. It has no
    path:line shape at all, so it normalizes away to nothing, same as an
    empty evidence array — "no source-file citation", not a separate
    "malformed" category."""
    from app.services.wiki_generator import _grounding_violations

    source_material = "Evidence: src/routes/alerts.py:12."
    page = {"sections": [{"heading": "IoT alerts", "body": "Alerts are dispatched to on-site staff.", "evidence": ["/analytics/v1/alerts"]}]}
    violations = _grounding_violations(page, source_material)
    assert violations == ["section 'IoT alerts' has no source-file citation"]


def test_grounding_violations_tolerates_trailing_annotation_on_citation():
    """Observed live against mistral-small-latest: it copies a symbol name
    along with the citation straight from the source artifact's own
    `name (kind) — path:line` bullet format, producing entries like
    "Facility.tsx:36:FacilityProps" instead of "Facility.tsx:36". That's an
    over-eager citation, not a fabricated or wrong one — it must be accepted
    (normalized), not rejected as malformed."""
    from app.services.wiki_generator import _grounding_violations

    source_material = "- `FacilityProps` (symbol) — `src/components/Facility.tsx:36`"
    page = {"sections": [{"heading": "Facilities", "body": "Facilities are managed here.", "evidence": ["src/components/Facility.tsx:36:FacilityProps"]}]}
    assert _grounding_violations(page, source_material) == []


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeModel:
    """Stands in for AutoSDLCChatModel in unit tests that exercise
    _invoke_and_parse/_invoke_grounded directly — returns each entry in
    `responses` in order, one per .invoke() call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, messages):
        response = self._responses[self.calls]
        self.calls += 1
        return _FakeResponse(response)


def test_invoke_and_parse_repairs_malformed_json_once():
    """A model that returns invalid JSON syntax (e.g. an unescaped quote in
    a string value) gets one repair attempt with the parse error fed back,
    instead of failing the whole wiki generation outright."""
    from app.services.wiki_generator import _invoke_and_parse

    good_page = {"title": "T", "summary": "S", "sections": [{"heading": "H", "body": "B"}]}
    model = _FakeModel([
        '{"title": "T", "summary": "S", "sections": [{"heading": "H", "body": "broken}]}',  # malformed
        json.dumps(good_page),
    ])
    page = _invoke_and_parse(model, "system", "user")
    # _parse_wiki_response always fills in "evidence" (defaulting to []
    # when the model didn't send one), so the parsed shape carries one more
    # key than what was sent over the wire.
    assert page == {**good_page, "sections": [{"heading": "H", "body": "B", "evidence": []}]}
    assert model.calls == 2


def test_invoke_and_parse_raises_when_repair_also_fails():
    from app.services.wiki_generator import WikiGenerationError, _invoke_and_parse

    model = _FakeModel(["not json at all", "still not json"])
    with pytest.raises(WikiGenerationError):
        _invoke_and_parse(model, "system", "user")
    assert model.calls == 2


def test_vendor_citation_does_not_false_positive_on_first_party_folder_names():
    """Live-observed root cause of most "wiki page is too thin" reports: the
    old regex matched vendor library names (bootstrap/jquery/datatables/...)
    as a bare case-insensitive substring anywhere in the citation, which also
    matched this app's own src/components/dataTables/ folder (a first-party
    component directory, plural noun "data tables") purely because it
    case-folds to the same letters as the jQuery DataTables plugin. That
    silently discarded every section whose evidence lived there — most of a
    real repo's business capabilities in practice (asset tables, user
    tables, compliance report tables all lived under dataTables/)."""
    from app.services.wiki_generator import VENDOR_CITATION

    for path in (
        "src/components/dataTables/AssetTable.tsx:14",
        "src/components/dataTables/SchedulerTable.tsx:68",
        "src/components/DatePickerField.tsx:5",
        "src/components/BootstrapModal.tsx:8",
    ):
        assert not VENDOR_CITATION.search(path), path


def test_vendor_citation_still_catches_real_vendored_files():
    from app.services.wiki_generator import VENDOR_CITATION

    for path in (
        "static/vendor/jquery.min.js:1",
        "node_modules/react/index.js:1",
        "public/lib/bootstrap.min.css:1",
        "assets/js/jquery-3.6.0.js:1",
        "public/css/font-awesome.css:1",
    ):
        assert VENDOR_CITATION.search(path), path


def test_invoke_and_parse_forces_a_page_when_followup_asks_again():
    """Live-observed: a follow-up call (clarification_answers already given)
    can still return another needs_clarification round — the "don't ask
    again" instruction is only a note in the user message, competing with
    the system prompt's own "you may ask" branch, and a small model doesn't
    reliably honor it. is_followup=True must force one more call with a
    blunt instruction rather than silently handing back yet another
    question round, which is what let this loop indefinitely through the UI."""
    from app.services.wiki_generator import _invoke_and_parse

    good_page = {"title": "T", "summary": "S", "sections": [{"heading": "H", "body": "B"}]}
    model = _FakeModel([
        json.dumps({"needs_clarification": True, "clarifying_questions": [{"id": "x", "question": "Q?", "why": "W"}]}),
        json.dumps(good_page),
    ])
    page = _invoke_and_parse(model, "system", "user", is_followup=True)
    assert page.get("needs_clarification") is not True
    assert page["title"] == "T"
    assert model.calls == 2


def test_invoke_and_parse_does_not_force_on_first_call():
    """A first call (no prior clarification round) is allowed to ask —
    is_followup defaults to False, so a needs_clarification response is
    returned as-is, not forced through."""
    from app.services.wiki_generator import _invoke_and_parse

    clarification = {"needs_clarification": True, "clarifying_questions": [{"id": "x", "question": "Q?", "why": "W"}]}
    model = _FakeModel([json.dumps(clarification)])
    page = _invoke_and_parse(model, "system", "user")
    assert page.get("needs_clarification") is True
    assert model.calls == 1


def test_invoke_and_parse_gives_up_gracefully_if_forced_call_still_asks():
    """If even the forced call insists on asking again, return that
    clarification response rather than raising or looping further — the
    endpoint already handles needs_clarification as a normal 409, so this
    degrades to the pre-existing UX rather than a hard failure."""
    from app.services.wiki_generator import _invoke_and_parse

    clarification = {"needs_clarification": True, "clarifying_questions": [{"id": "x", "question": "Q?", "why": "W"}]}
    model = _FakeModel([json.dumps(clarification), json.dumps(clarification)])
    page = _invoke_and_parse(model, "system", "user", is_followup=True)
    assert page.get("needs_clarification") is True
    assert model.calls == 2
