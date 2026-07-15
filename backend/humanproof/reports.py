"""Report exporters for Mr Money AI."""

from __future__ import annotations

import csv
import io
import json
import textwrap
import zipfile
from html import escape
from typing import Any, Dict, Iterable, List, Tuple

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
    severity_chart = _severity_chart_svg(report)
    score_chart = _score_chart_svg(report)
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
    .charts {{ display: flex; gap: 20px; margin: 16px 0; flex-wrap: wrap; }}
    .chart {{ flex: 1; min-width: 300px; }}
  </style>
</head>
<body>
  <h1>Mr Money AI Review Report</h1>
  <p class="meta">Review ID: <code>{escape(report.review_id)}</code><br>Created: {escape(report.created_at)}<br>Document: {escape(report.document.filename)}</p>
  <h2>Executive Summary</h2>
  <p>{escape(report.summary)}</p>
  <div class="charts">
    <div class="chart"><h3>Severity Distribution</h3>{severity_chart}</div>
    <div class="chart"><h3>Score Overview</h3>{score_chart}</div>
  </div>
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


def report_as_csv(report: ReviewReport) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Category", "Severity", "Agent", "Title", "Message", "Recommendation", "Confidence"])
    for finding in report.findings:
        writer.writerow([
            finding.category,
            finding.severity,
            finding.agent,
            finding.title,
            finding.message,
            finding.recommendation,
            finding.confidence,
        ])
    return buffer.getvalue().encode("utf-8")


def get_chart_data(report: ReviewReport) -> Dict[str, Any]:
    severity_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    agent_counts: Dict[str, int] = {}
    for finding in report.findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        category_counts[finding.category] = category_counts.get(finding.category, 0) + 1
        agent_counts[finding.agent] = agent_counts.get(finding.agent, 0) + 1
    return {
        "scores": report.scores,
        "severity_distribution": severity_counts,
        "category_distribution": category_counts,
        "agent_distribution": agent_counts,
        "total_findings": len(report.findings),
    }


def report_as_pdf(report: ReviewReport) -> bytes:
    sections: List[Tuple[str, List[str]]] = []
    sections.append(("Title", [
        "Mr Money AI Review Report",
        f"Review ID: {report.review_id}",
        f"Created: {report.created_at}",
        f"Document: {report.document.filename}",
        "",
    ]))
    sections.append(("Executive Summary", [report.summary, ""]))
    sections.append(("Quality Metrics", list(
        f"{name.replace('_', ' ').title()}: {score}"
        for name, score in sorted(report.scores.items())
    ) + [""]))
    if report.findings:
        finding_lines: List[str] = []
        for i, finding in enumerate(report.findings[:30], 1):
            finding_lines.extend([
                f"{i}. [{finding.severity.upper()}] {finding.title}",
                f"   {finding.message[:200]}",
                f"   Recommendation: {finding.recommendation[:200]}",
                "",
            ])
        sections.append(("Detailed Findings", finding_lines))
    sections.append(("Action Plan", list(report.action_plan) + [""]))
    if report.score_explanations:
        explain_lines: List[str] = []
        for key, exp in report.score_explanations.items():
            label = exp.get("label", key)
            assessment = exp.get("assessment", "")
            explanation = exp.get("explanation", "")
            explain_lines.append(f"{label}: {assessment} ({exp.get('score', 0)}/100)")
            if explanation:
                explain_lines.append(f"  {explanation[:200]}")
            explain_lines.append("")
        sections.append(("Score Explanations", explain_lines[:40]))
    sections.append(("Limitations", list(report.limitations)))
    return _multi_page_pdf(sections)


def export_report(report: ReviewReport, file_format: str) -> Tuple[bytes, str, str]:
    normalized = file_format.lower().lstrip(".")
    exporters = {
        "json": (report_as_json, "application/json", "json"),
        "md": (report_as_markdown, "text/markdown", "md"),
        "markdown": (report_as_markdown, "text/markdown", "md"),
        "html": (report_as_html, "text/html", "html"),
        "docx": (report_as_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
        "pdf": (report_as_pdf, "application/pdf", "pdf"),
        "csv": (report_as_csv, "text/csv", "csv"),
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


def _severity_chart_svg(report: ReviewReport) -> str:
    counts: Dict[str, int] = {}
    for f in report.findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    colors = {"critical": "#b42318", "high": "#d92d20", "medium": "#b54708",
              "low": "#2c7da0", "info": "#5c6773"}
    max_count = max(counts.values()) if counts else 1
    y = 10
    bars = []
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = counts.get(sev, 0)
        bar_w = max(0, int(180 * count / max_count)) if max_count > 0 else 0
        color = colors.get(sev, "#5c6773")
        bars.append(f'<rect x="60" y="{y}" width="{bar_w}" height="16" fill="{color}"/>')
        bars.append(f'<text x="55" y="{y + 12}" text-anchor="end" font-size="11">{sev}</text>')
        bars.append(f'<text x="{65 + bar_w}" y="{y + 12}" font-size="11">{count}</text>')
        y += 22
    height = y + 10
    return f'<svg width="300" height="{height}" xmlns="http://www.w3.org/2000/svg">{"".join(bars)}</svg>'


def _score_chart_svg(report: ReviewReport) -> str:
    top_scores = list(report.scores.items())[:8]
    if not top_scores:
        return '<svg width="300" height="40" xmlns="http://www.w3.org/2000/svg"><text x="10" y="20">No scores</text></svg>'
    bar_h = 16
    gap = 4
    width = 300
    height = len(top_scores) * (bar_h + gap) + 10
    bars = []
    y = 5
    for name, score in top_scores:
        label = name.replace("_", " ")[:18]
        bar_w = max(0, int(150 * score / 100))
        color = "#2c7da0" if score >= 70 else ("#b54708" if score >= 50 else "#b42318")
        bars.append(f'<rect x="110" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}"/>')
        bars.append(f'<text x="105" y="{y + 12}" text-anchor="end" font-size="10">{escape(label)}</text>')
        bars.append(f'<text x="{115 + bar_w}" y="{y + 12}" font-size="10">{score}</text>')
        y += bar_h + gap
    return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">{"".join(bars)}</svg>'


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


def _severity_bar_chart(report: ReviewReport) -> str:
    severity_counts: Dict[str, int] = {}
    for f in report.findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
    colors = {"critical": "b42318", "high": "d92d20", "medium": "b54708",
              "low": "2c7da0", "info": "5c6773"}
    bars = []
    y = 700
    max_count = max(severity_counts.values()) if severity_counts else 1
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = severity_counts.get(sev, 0)
        if count == 0:
            continue
        bar_width = max(10, int(200 * count / max_count))
        color = colors.get(sev, "5c6773")
        bars.append(f"0.8 {int(color[0:2],16)/255:.2f} {int(color[2:4],16)/255:.2f} {int(color[4:6],16)/255:.2f} rg")
        bars.append(f"50 {y} {bar_width} 12 re f")
        bars.append(f"0 0 0 rg")
        bars.append("BT")
        bars.append(f"/F1 10 Tf 260 {y + 3} Td ({sev}: {count}) Tj ET")
        y -= 20
    return "\n".join(bars) if bars else ""


def _multi_page_pdf(sections: List[Tuple[str, List[str]]]) -> bytes:
    pages: List[str] = []
    page_num = 1
    header = "Mr Money AI Review Report"
    for section_title, lines in sections:
        all_lines = [f"=== {section_title} ===", ""] + lines
        wrapped: List[str] = []
        for line in all_lines:
            wrapped.extend(textwrap.wrap(line, width=92) or [""])
        chunk_size = 48
        for i in range(0, max(len(wrapped), 1), chunk_size):
            chunk = wrapped[i:i + chunk_size]
            text_cmds = ["BT", "/F1 10 Tf", "50 750 Td", "14 TL"]
            text_cmds.append(f"/F1 8 Tf 50 780 Td ({_pdf_escape(header)}) Tj ET")
            text_cmds.append("BT /F1 10 Tf 50 750 Td 14 TL")
            for line in chunk:
                text_cmds.append(f"({_pdf_escape(line)}) Tj")
                text_cmds.append("T*")
            text_cmds.append(f"/F1 8 Tf 50 30 Td (Page {page_num}) Tj ET")
            text_cmds.append("ET")
            pages.append("\n".join(text_cmds))
            page_num += 1
    objects: List[bytes] = []
    kids: List[str] = []
    for page_content in pages:
        obj_idx = len(objects) + 1
        kids.append(f"{obj_idx + 2} 0 R")
        stream = page_content.encode("latin-1", errors="replace")
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"<< /Type /Pages /Kids [" + " ".join(kids).encode() + b"] /Count " + str(len(pages)).encode() + b" >>")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents " + str(obj_idx + 3).encode() + b" 0 R >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    catalog_idx = 1
    pages_idx = 2
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids_refs = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objects[1] = f"<< /Type /Pages /Kids [{kids_refs}] /Count {len(pages)} >>".encode()
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

