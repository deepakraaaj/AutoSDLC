"""Helpers for ingesting uploaded brief files."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Final

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

SUPPORTED_UPLOAD_EXTENSIONS: Final = {".md", ".docx"}


def extract_uploaded_brief_text(filename: str, content: bytes) -> str:
    """Extract plain text from a supported uploaded brief file."""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx":
        return extract_docx_text(content)
    if suffix == ".md":
        return content.decode("utf-8-sig", errors="ignore").strip()
    raise ValueError("Only .md and .docx files are accepted.")


def extract_docx_text(content: bytes) -> str:
    """Extract readable text from a Word document."""
    try:
        document = Document(BytesIO(content))
    except Exception as exc:  # pragma: no cover - dependency-specific parse errors
        raise ValueError("Unable to read the uploaded .docx file.") from exc

    lines: list[str] = []
    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            line = _format_paragraph(block)
            if line:
                lines.append(line)
        elif isinstance(block, Table):
            lines.extend(_format_table(block))

    return "\n".join(lines).strip()


def _iter_docx_blocks(document: DocxDocument):
    """Yield paragraphs and tables in document order."""
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _format_paragraph(paragraph: Paragraph) -> str:
    text = paragraph.text.strip()
    if not text:
        return ""

    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    match = re.search(r"heading\s*(\d+)", style_name, flags=re.IGNORECASE)
    if match:
        level = max(1, min(int(match.group(1)), 6))
        return f"{'#' * level} {text}"
    return text


def _format_table(table: Table) -> list[str]:
    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
        if cells:
            rows.append(" | ".join(cells))
    return rows
