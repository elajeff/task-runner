from pathlib import Path

from runtime.documents import create_document_job, process_document_job
from runtime.results_view import build_results_page


def test_results_preview_renders_tables_and_escapes_embedded_html(tmp_path: Path):
    source = tmp_path / "report.txt"
    source.write_text(
        "# Revenue report\n\n<script>alert('no')</script>\n\n"
        "| Product | Revenue |\n|---|---:|\n| Alpha | 1,200 |",
        encoding="utf-8",
    )
    job_dir = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")
    process_document_job(job_dir, None)

    preview = build_results_page(job_dir)
    assert preview == job_dir / "results.html"
    html = preview.read_text(encoding="utf-8")
    assert "Revenue report" in html
    assert "<table>" in html
    assert "Alpha" in html and "1,200" in html
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html
    assert 'href="01_Extracted_Text/extracted_text.md"' in html


def test_results_preview_returns_none_until_output_exists(tmp_path: Path):
    source = tmp_path / "report.txt"
    source.write_text("Some text", encoding="utf-8")
    job_dir = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")

    assert build_results_page(job_dir) is None
    assert not (job_dir / "results.html").exists()


def test_results_preview_converts_backslash_escaped_html_tables(tmp_path: Path):
    source = tmp_path / "financial-report.md"
    source.write_text(
        "## Net Asset Value\n\n"
        r"\<table> \<tr>\<th>Item\</th>\<th>Value\</th>\</tr> "
        r"\<tr>\<td>Cash\</td>\<td>0.00\</td>\</tr>\</table>",
        encoding="utf-8",
    )
    job_dir = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")
    process_document_job(job_dir, None)

    preview = build_results_page(job_dir)
    assert preview is not None
    html = preview.read_text(encoding="utf-8")
    assert "Net Asset Value" in html
    assert "<table>" in html
    assert "<th>Item</th>" in html
    assert "<td>Cash</td>" in html
    assert r"\<table>" not in html


def test_results_preview_converts_entity_encoded_table_and_keeps_it_safe(tmp_path: Path):
    from runtime.results_view import _render_markdown

    rendered = _render_markdown(
        "&lt;table&gt;&lt;tr&gt;&lt;th&gt;Name&lt;/th&gt;&lt;th&gt;Value&lt;/th&gt;&lt;/tr&gt;"
        "&lt;tr&gt;&lt;td&gt;Alpha&lt;/td&gt;&lt;td&gt;1 &amp; 2&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;"
        "\n\n&lt;script&gt;alert('no')&lt;/script&gt;"
    )
    assert "<table>" in rendered
    assert "<td>Alpha</td>" in rendered
    assert "1 &amp; 2" in rendered
    assert "&lt;script&gt;alert('no')&lt;/script&gt;" in rendered
    assert "<script>" not in rendered
