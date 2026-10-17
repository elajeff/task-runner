"""Build a safe, readable HTML preview of saved document outputs."""
from __future__ import annotations

import os
import re
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

from runtime.documents import DOCUMENT_OUTPUT_LABELS, load_document_job, output_relative_path

RESULTS_PAGE_FILENAME = "results.html"
_OUTPUT_ORDER = ("verbatim", "summary", "notes", "definitions", "questions", "processing_notes")
_STATUS_LABELS = {
    "pending": "Not started",
    "running": "In progress — showing saved results so far",
    "completed": "Complete",
    "failed": "Stopped — showing saved results",
}
_STYLES = """
:root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #20242b; background: #f4f6f9; }
body { max-width: 1000px; margin: 0 auto; padding: 32px 22px 56px; line-height: 1.6; }
header { margin-bottom: 24px; }
h1 { margin: 0 0 8px; font-size: 1.9rem; }
.meta { color: #5d6673; margin: 0; overflow-wrap: anywhere; }
nav { display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0; }
nav a, .file-link { color: #2458a6; text-decoration: none; }
nav a { padding: 7px 11px; border: 1px solid #d8dee8; border-radius: 8px; background: white; }
section.output { background: white; border: 1px solid #dce2ea; border-radius: 12px; padding: 22px; margin: 18px 0; box-shadow: 0 2px 8px #15243b0a; }
section.output h2 { margin: 0 0 4px; font-size: 1.35rem; }
.file-line { color: #6a7280; font-size: .9rem; margin: 0 0 18px; overflow-wrap: anywhere; }
.markdown-body { overflow-wrap: anywhere; }
.markdown-body table { border-collapse: collapse; display: block; max-width: 100%; overflow-x: auto; margin: 16px 0; }
.markdown-body th, .markdown-body td { border: 1px solid #d9dee7; padding: 8px 11px; text-align: left; vertical-align: top; }
.markdown-body th { background: #f0f3f8; }
.markdown-body blockquote { margin-left: 0; padding: 2px 16px; border-left: 3px solid #a9b9d2; color: #4e596a; }
.markdown-body pre { padding: 14px; overflow-x: auto; background: #f3f5f8; border-radius: 8px; }
.markdown-body code { font-family: ui-monospace, Consolas, monospace; }
footer { color: #687282; font-size: .9rem; margin-top: 28px; }
@media (max-width: 640px) { body { padding: 18px 12px 36px; } section.output { padding: 15px; } }
"""


_TABLE_TAGS = r"table|thead|tbody|tfoot|tr|th|td|caption|colgroup|col"
_TABLE_MARKUP_RE = re.compile(
    r"<table\b.*?(?:</table\s*>|$)", re.IGNORECASE | re.DOTALL
)
_ENCODED_TABLE_RE = re.compile(r"&lt;\s*/?\s*table\b", re.IGNORECASE)
_ESCAPED_TABLE_TAG_RE = re.compile(
    rf"\\(?=\s*</?\s*(?:{_TABLE_TAGS})\b)", re.IGNORECASE
)


class _TableTextParser(HTMLParser):
    """Extract cell text from an HTML table without rendering source HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table" and not self._in_table:
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in {"th", "td"} and self._row is not None:
            self._cell_parts = []
        elif self._in_table and tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_table and tag in {"th", "td"} and self._cell_parts is not None:
            value = re.sub(r"\s+", " ", "".join(self._cell_parts)).strip()
            # A backslash protects literal pipes inside Markdown table cells.
            value = value.replace("|", r"\|")
            if self._row is not None:
                self._row.append(value)
            self._cell_parts = None
        elif self._in_table and tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._in_table:
            if self._row is not None:
                self.rows.append(self._row)
                self._row = None
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


def _html_table_to_markdown(table_markup: str) -> str | None:
    parser = _TableTextParser()
    try:
        parser.feed(table_markup)
        parser.close()
    except Exception:
        return None
    rows = [row for row in parser.rows if row]
    if not rows:
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    # Markdown requires a header row. Use the first source row even when the
    # original HTML used only <td> cells; this preserves the table's columns.
    header = rows[0]
    body = rows[1:]
    rendered = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    rendered.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(rendered)


def _normalize_editor_tables(content: str) -> str:
    """Convert common escaped/encoded HTML tables from editors into Markdown."""
    # Some editors escape angle brackets or prefix every tag with a Markdown
    # backslash. Only decode when a table marker is present; other HTML remains
    # escaped by the Markdown renderer below.
    if _ENCODED_TABLE_RE.search(content):
        content = unescape(content)
    content = _ESCAPED_TABLE_TAG_RE.sub("", content)
    matches = list(_TABLE_MARKUP_RE.finditer(content))
    if not matches:
        return content

    chunks: list[str] = []
    cursor = 0
    for match in matches:
        chunks.append(content[cursor:match.start()])
        markdown_table = _html_table_to_markdown(match.group(0))
        chunks.append(markdown_table if markdown_table else escape(match.group(0)))
        cursor = match.end()
    chunks.append(content[cursor:])
    return "\n".join(part for part in chunks if part is not None)


def _render_markdown(content: str) -> str:
    """Render Markdown and safely make pasted HTML tables readable."""
    content = _normalize_editor_tables(content)
    try:
        import mistune
        from mistune.plugins.formatting import strikethrough
        from mistune.plugins.table import table
    except ImportError:
        # Keep viewing available in incomplete source installs; packaged builds include Mistune.
        return f"<pre>{escape(content)}</pre>"

    renderer = mistune.HTMLRenderer(escape=True)
    parser = mistune.Markdown(renderer=renderer, plugins=[table, strikethrough])
    return parser(content)


def build_results_page(job_dir: Path) -> Path | None:
    """Create an HTML overview for a document job, or None if it has no saved outputs yet."""
    job_dir = Path(job_dir).expanduser().resolve()
    state = load_document_job(job_dir)
    selected = set(state.get("selected", []))
    sections: list[tuple[str, str, Path, str]] = []

    for key in _OUTPUT_ORDER:
        if key != "processing_notes" and key not in selected:
            continue
        relative = output_relative_path(key, state)
        source_path = job_dir / relative
        if not source_path.is_file():
            continue
        label = "Processing notes" if key == "processing_notes" else DOCUMENT_OUTPUT_LABELS[key]
        sections.append((key, label, source_path, source_path.read_text(encoding="utf-8")))

    if not sections:
        return None

    source_name = Path(state.get("source", "Document")).name or "Document"
    status = _STATUS_LABELS.get(str(state.get("status", "pending")), "Saved results")
    nav = "\n".join(
        f'<a href="#{escape(key, quote=True)}">{escape(label)}</a>'
        for key, label, _, _ in sections
    )
    rendered_sections: list[str] = []
    for key, label, source_path, content in sections:
        relative = source_path.relative_to(job_dir).as_posix()
        href = escape(relative, quote=True)
        rendered_sections.append(
            f'<section class="output" id="{escape(key, quote=True)}">'
            f'<h2>{escape(label)}</h2>'
            f'<p class="file-line">Saved file: <a class="file-link" href="{href}">{escape(relative)}</a></p>'
            f'<div class="markdown-body">{_render_markdown(content)}</div>'
            '</section>'
        )
    section_html = "\n".join(rendered_sections)

    page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{escape(source_name)} — task runner results</title>\n'
        f'<style>{_STYLES}</style>\n</head>\n<body>\n'
        f'<header><h1>{escape(source_name)}</h1><p class="meta">{escape(status)} · task runner results</p></header>\n'
        f'<nav aria-label="Results">{nav}</nav>\n'
        f'{section_html}\n'
        '<footer>Review important values against the original document, especially where OCR or complex layouts were used.</footer>\n'
        '</body>\n</html>\n'
    )
    target = job_dir / RESULTS_PAGE_FILENAME
    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(page, encoding="utf-8", newline="\n")
    os.replace(temporary, target)
    return target
