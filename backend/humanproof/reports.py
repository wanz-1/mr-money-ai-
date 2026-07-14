"""Report exporters for Mr Money AI."""

from __future__ import annotations

import io
import json
import textwrap
import zipfile
from html import escape
from typing import Iterable, List, Tuple

from .models import Finding, ReviewReport


def report_as_json(report: ReviewReport) -> bytes:
    return json.dumps(report.to_dict(), ensure_ascii=True, indent=2).encode("utf-8")


def report_as_markdown(report: ReviewReport) -> bytes:
    lines = [
        f"# Mr Money AI Review Report",
        "",
        f"Review ID: `{report.review_id}`",
        f"Created: `{report.created_at}`",
        f"Document: `{report.document.filename}`",
        "",
        "## Executive Summary",
        "",
        report.summary,
        "",
        "## Quality Metrics",
        "",
    ]
    for name, score in sorted(report.scores.items()):
        lines.append(f"- {name.replace('_', ' ').title()}: {score}")
    lines.extend(["", "## Detailed Findings", ""])
    if not report.findings:
        lines.append("No automated findings were generated.")
    for finding in report.findings:
        lines.extend(_finding_markdown(finding))
    lines.extend(["", "## Action Plan", ""])
    for item in report.action_plan:
        lines.append(f"- {item}")
    lines.extend(["", "## Limitations", ""])
    for item in report.limitations:
        lines.append(f"- {item}")
    lines.extend(["", "## Revision History", ""])
    for event in report.revision_history:
        lines.append(f"- {event.get('timestamp')}: {event.get('event')} ({event.get('actor')})")
    return "\n".join(lines).encode("utf-8")


def report_as_html(report: ReviewReport) -> bytes:
    score_rows = "\n".join(
        f"<tr><th>{escape(name.replace('_', ' ').title())}</th><td>{score}</td></tr>" for name, score in sorted(report.scores.items())
    )
    findings = "\n".join(_finding_html(finding) for finding in report.findings) or "<p>No automated findings were generated.</p>"
    action_plan = "\n".join(f"<li>{escape(item)}</li>" for item in report.action_plan)
    limitations = "\n".join(f"<li>{escape(item)}</li>" for item in report.limitations)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mr Money AI Review Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; line-height: 1.5; margin: 40px; color: #17202a; }}
    h1, h2, h3 {{ color: #0f3d57; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d7dde3; padding: 8px; text-align: left; }}
    th {{ background: #eef3f7; }}
    .finding {{ border: 1px solid #d7dde3; border-left: 5px solid #2c7da0; padding: 12px; margin: 12px 0; }}
    .severity-high, .severity-critical {{ border-left-color: #b42318; }}
    .severity-medium {{ border-left-color: #b54708; }}
    .meta {{ color: #5c6773; }}
    code {{ background: #f1f5f8; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>Mr Money AI Review Report</h1>
  <p class="meta">Review ID: <code>{escape(report.review_id)}</code><br>Created: {escape(report.created_at)}<br>Document: {escape(report.document.filename)}</p>
  <h2>Executive Summary</h2>
  <p>{escape(report.summary)}</p>
  <h2>Quality Metrics</h2>
  <table>{score_rows}</table>
  <h2>Detailed Findings</h2>
  {findings}
  <h2>Action Plan</h2>
  <ul>{action_plan}</ul>
  <h2>Limitations</h2>
  <ul>{limitations}</ul>
</body>
</html>"""
    return html.encode("utf-8")


def report_as_docx(report: ReviewReport) -> bytes:
    paragraphs = [
        ("Mr Money AI Review Report", "Title"),
        (f"Review ID: {report.review_id}", "Normal"),
        (f"Created: {report.created_at}", "Normal"),
        (f"Document: {report.document.filename}", "Normal"),
        ("Executive Summary", "Heading1"),
        (report.summary, "Normal"),
        ("Quality Metrics", "Heading1"),
    ]
    paragraphs.extend((f"{name.replace('_', ' ').title()}: {score}", "Normal") for name, score in sorted(report.scores.items()))
    paragraphs.append(("Detailed Findings", "Heading1"))
    if not report.findings:
        paragraphs.append(("No automated findings were generated.", "Normal"))
    for finding in report.findings:
        paragraphs.extend(
            [
                (f"{finding.title} [{finding.severity.upper()}]", "Heading2"),
                (finding.message, "Normal"),
                (f"Recommendation: {finding.recommendation}", "Normal"),
            ]
        )
    paragraphs.append(("Action Plan", "Heading1"))
    paragraphs.extend((item, "Normal") for item in report.action_plan)
    paragraphs.append(("Limitations", "Heading1"))
    paragraphs.extend((item, "Normal") for item in report.limitations)
    document_xml = _docx_document_xml(paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _docx_content_types())
        docx.writestr("_rels/.rels", _docx_rels())
        docx.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def report_as_pdf(report: ReviewReport) -> bytes:
    lines = [
        "Mr Money AI Review Report",
        f"Review ID: {report.review_id}",
        f"Created: {report.created_at}",
        f"Document: {report.document.filename}",
        "",
        "Executive Summary",
        report.summary,
        "",
        "Quality Metrics",
    ]
    lines.extend(f"{name.replace('_', ' ').title()}: {score}" for name, score in sorted(report.scores.items()))
    lines.extend(["", "Detailed Findings"])
    if not report.findings:
        lines.append("No automated findings were generated.")
    for finding in report.findings[:25]:
        lines.extend([f"{finding.title} [{finding.severity.upper()}]", finding.message, f"Recommendation: {finding.recommendation}", ""])
    return _simple_pdf(lines)


def export_report(report: ReviewReport, file_format: str) -> Tuple[bytes, str, str]:
    normalized = file_format.lower().lstrip(".")
    exporters = {
        "json": (report_as_json, "application/json", "json"),
        "md": (report_as_markdown, "text/markdown", "md"),
        "markdown": (report_as_markdown, "text/markdown", "md"),
        "html": (report_as_html, "text/html", "html"),
        "docx": (report_as_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
        "pdf": (report_as_pdf, "application/pdf", "pdf"),
    }
    if normalized not in exporters:
        raise ValueError(f"Unsupported report format: {file_format}")
    exporter, content_type, extension = exporters[normalized]
    return exporter(report), content_type, extension


def _finding_markdown(finding: Finding) -> List[str]:
    lines = [
        f"### {finding.title}",
        "",
        f"- Severity: `{finding.severity}`",
        f"- Category: `{finding.category}`",
        f"- Agent: `{finding.agent}`",
        f"- Confidence: `{finding.confidence}`",
        f"- Finding: {finding.message}",
        f"- Recommendation: {finding.recommendation}",
    ]
    if finding.span and finding.span.excerpt:
        lines.append(f"- Excerpt: `{finding.span.excerpt}`")
    lines.append("")
    return lines


def _finding_html(finding: Finding) -> str:
    excerpt = ""
    if finding.span and finding.span.excerpt:
        excerpt = f"<p><strong>Excerpt:</strong> <code>{escape(finding.span.excerpt)}</code></p>"
    return f"""<section class="finding severity-{escape(finding.severity)}">
  <h3>{escape(finding.title)}</h3>
  <p class="meta">{escape(finding.category)} | {escape(finding.severity)} | {escape(finding.agent)} | confidence {finding.confidence}</p>
  <p>{escape(finding.message)}</p>
  <p><strong>Recommendation:</strong> {escape(finding.recommendation)}</p>
  {excerpt}
</section>"""


def _docx_document_xml(paragraphs: Iterable[Tuple[str, str]]) -> str:
    body = []
    for text, style in paragraphs:
        style_xml = ""
        if style == "Title":
            style_xml = "<w:pPr><w:pStyle w:val=\"Title\"/></w:pPr>"
        elif style == "Heading1":
            style_xml = "<w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
        elif style == "Heading2":
            style_xml = "<w:pPr><w:pStyle w:val=\"Heading2\"/></w:pPr>"
        body.append(f"<w:p>{style_xml}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}<w:sectPr/></w:body></w:document>"
    )


def _docx_content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def _docx_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _simple_pdf(lines: List[str]) -> bytes:
    wrapped: List[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=92) or [""])
    wrapped = wrapped[:52]
    text_commands = ["BT", "/F1 10 Tf", "50 770 Td", "14 TL"]
    for line in wrapped:
        text_commands.append(f"({_pdf_escape(line)}) Tj")
        text_commands.append("T*")
    text_commands.append("ET")
    stream = "\n".join(text_commands).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")
    xref = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return buffer.getvalue()


def _pdf_escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

