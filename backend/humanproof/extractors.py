"""Best-effort document text extraction using the Python standard library."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from typing import Iterable, List, Tuple
from xml.etree import ElementTree

try:
    from bs4 import BeautifulSoup as _BeautifulSoup
except ImportError:
    _BeautifulSoup = None  # type: ignore[assignment]

from .models import Document, DocumentMetadata


TEXT_FORMATS = {"txt", "md", "markdown", "html", "htm", "json", "xml", "csv", "tex", "latex", "rtf"}
ZIP_XML_FORMATS = {"docx", "odt", "epub", "xlsx", "pptx"}
SUPPORTED_FORMATS = sorted(TEXT_FORMATS | ZIP_XML_FORMATS | {"pdf"})


def detect_format(filename: str, content_type: str = "") -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix == "markdown":
        return "md"
    if suffix:
        return suffix
    if "html" in content_type:
        return "html"
    if "json" in content_type:
        return "json"
    if "xml" in content_type:
        return "xml"
    if "csv" in content_type:
        return "csv"
    if "pdf" in content_type:
        return "pdf"
    return "txt"


def extract_document(data: bytes, filename: str = "upload.txt", content_type: str = "") -> Document:
    file_format = detect_format(filename, content_type)
    metadata = DocumentMetadata(
        filename=filename or "upload.txt",
        file_format=file_format,
        content_type=content_type or _content_type_for(file_format),
        size_bytes=len(data),
    )
    limitations: List[str] = []

    try:
        if file_format in {"txt", "md", "markdown", "tex", "latex"}:
            text = _decode(data)
        elif file_format in {"html", "htm"}:
            text = _html_to_text(_decode(data))
        elif file_format == "json":
            text = _json_to_text(_decode(data))
        elif file_format == "xml":
            text = _xml_to_text(_decode(data))
        elif file_format == "csv":
            text = _csv_to_text(_decode(data))
        elif file_format == "rtf":
            text = _rtf_to_text(_decode(data))
        elif file_format == "docx":
            text = _extract_zip_xml(data, ["word/document.xml", "word/footnotes.xml", "word/endnotes.xml"])
        elif file_format == "odt":
            text = _extract_zip_xml(data, ["content.xml"])
        elif file_format == "epub":
            text = _extract_epub(data)
        elif file_format == "xlsx":
            text = _extract_xlsx(data)
        elif file_format == "pptx":
            text = _extract_pptx(data)
        elif file_format == "pdf":
            text, pdf_limitations = _extract_pdf_text(data)
            limitations.extend(pdf_limitations)
        else:
            text = _decode(data)
            limitations.append(f"Format '{file_format}' is not explicitly supported; decoded as plain text.")
    except Exception as exc:  # pragma: no cover - defensive boundary for arbitrary uploads
        text = _decode(data)
        limitations.append(f"Text extraction fell back to plain decoding: {exc}")

    if not text.strip():
        limitations.append("No readable text was extracted. Scanned PDFs and image-only files require OCR.")

    return Document(text=_normalize_text(text), metadata=metadata, limitations=limitations)


def _content_type_for(file_format: str) -> str:
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "html": "text/html",
        "md": "text/markdown",
        "json": "application/json",
        "xml": "application/xml",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "odt": "application/vnd.oasis.opendocument.text",
        "epub": "application/epub+zip",
    }.get(file_format, "text/plain")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _html_to_text(html: str) -> str:
    if _BeautifulSoup is not None:
        soup = _BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li|tr)>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return unescape(re.sub(r"[ \t]+", " ", html))


def _json_to_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, ensure_ascii=True, indent=2)
    except json.JSONDecodeError:
        return raw


def _xml_to_text(raw: str) -> str:
    try:
        root = ElementTree.fromstring(raw)
        return " ".join(text.strip() for text in root.itertext() if text and text.strip())
    except ElementTree.ParseError:
        return _html_to_text(raw)


def _csv_to_text(raw: str) -> str:
    output: List[str] = []
    reader = csv.reader(io.StringIO(raw))
    for row in reader:
        output.append(" | ".join(cell.strip() for cell in row))
    return "\n".join(output)


def _rtf_to_text(raw: str) -> str:
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    raw = re.sub(r"\\[a-zA-Z]+\d* ?", " ", raw)
    raw = raw.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", raw)


def _iter_zip_text(data: bytes, members: Iterable[str]) -> Iterable[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in members:
            if member not in archive.namelist():
                continue
            xml = archive.read(member)
            try:
                root = ElementTree.fromstring(xml)
            except ElementTree.ParseError:
                continue
            buffer: List[str] = []
            for node in root.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag in {"t", "text", "span"} and node.text:
                    buffer.append(node.text)
                elif tag in {"p", "br", "tab", "tr"}:
                    buffer.append("\n")
            yield " ".join(buffer)


def _extract_zip_xml(data: bytes, members: Iterable[str]) -> str:
    return "\n".join(_iter_zip_text(data, members))


def _extract_epub(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm", ".xml"))
            and not name.lower().endswith(("container.xml", ".opf", ".ncx"))
        ]
        chunks = []
        for member in members:
            chunks.append(_html_to_text(_decode(archive.read(member))))
        return "\n".join(chunks)


def _extract_xlsx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [name for name in archive.namelist() if name.startswith("xl/worksheets/") or name == "xl/sharedStrings.xml"]
        return "\n".join(_iter_zip_text_from_archive(archive, members))


def _extract_pptx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/") and name.endswith(".xml"))
        return "\n".join(_iter_zip_text_from_archive(archive, members))


def _iter_zip_text_from_archive(archive: zipfile.ZipFile, members: Iterable[str]) -> Iterable[str]:
    for member in members:
        try:
            root = ElementTree.fromstring(archive.read(member))
        except ElementTree.ParseError:
            continue
        pieces: List[str] = []
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"t", "v"} and node.text:
                pieces.append(node.text)
            elif tag in {"row", "p"}:
                pieces.append("\n")
        yield " ".join(pieces)


def _extract_pdf_text(data: bytes) -> Tuple[str, List[str]]:
    raw = data.decode("latin-1", errors="ignore")
    limitations = [
        "PDF extraction uses a lightweight text-object parser; complex layouts may need a dedicated PDF/OCR service."
    ]
    strings = re.findall(r"\((?:\\.|[^\\()])*\)\s*Tj", raw)
    arrays = re.findall(r"\[(.*?)\]\s*TJ", raw, flags=re.S)
    pieces: List[str] = []
    for item in strings:
        pieces.append(_unescape_pdf_string(item.rsplit(")", 1)[0].lstrip("(")))
    for array in arrays:
        for item in re.findall(r"\((?:\\.|[^\\()])*\)", array):
            pieces.append(_unescape_pdf_string(item[1:-1]))
    if not pieces:
        visible_ascii = re.findall(r"[A-Za-z0-9][A-Za-z0-9 ,.;:'\"!?%$#@/\-]{5,}", raw)
        pieces.extend(visible_ascii[:500])
    return " ".join(pieces), limitations


def _unescape_pdf_string(value: str) -> str:
    value = value.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    value = value.replace(r"\n", "\n").replace(r"\r", "\n").replace(r"\t", "\t")
    return value

