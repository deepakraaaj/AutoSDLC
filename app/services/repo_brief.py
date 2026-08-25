"""Turns a project's linked repositories into a plain-text brief backlog
generation can consume directly — automating the manual "run a shell
command, paste the output into an AI tool" workflow prompts/EXTRACT_FROM_REPO.md
describes.

Unlike generate_project_wiki/generate_repo_wiki (app/services/wiki_generator.py),
this isn't a standalone artifact: the response is meant to land back in the
brief editor (see app/api/projects.py's generate_project_brief_from_repo_endpoint),
so it's plain Markdown text — the same shape a hand-written brief already
takes — not the {title, summary, sections} JSON wiki pages use.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.langchain_provider import AutoSDLCChatModel
from app.services.prompt import REPO_BRIEF_SYSTEM, build_repo_brief_message


class RepoBriefGenerationError(Exception):
    """The model responded, but with empty/unusable content."""


def generate_repo_derived_brief(
    provider,
    project_name: str,
    description: str,
    repo_materials: list[dict],
    existing_brief: str | None = None,
) -> str:
    """Grounded in each linked repo's build_repo_context_block() output plus
    a best-effort README (repo_materials — gathered the same way project
    wiki generation gathers it, see app/api/projects.py's
    _collect_repo_wiki_material), reconciled with whatever brief/notes the
    user already typed. Never silently returns an empty brief — an
    unusable response raises so the endpoint can report it rather than
    handing back a blank editor."""
    model = AutoSDLCChatModel(provider=provider)
    response = model.invoke([
        SystemMessage(content=REPO_BRIEF_SYSTEM),
        HumanMessage(content=build_repo_brief_message(project_name, description, repo_materials, existing_brief)),
    ])
    text = str(response.content).strip()
    if not text:
        raise RepoBriefGenerationError("Model returned an empty brief.")
    return text
