"""Command-line entry point for local HumanProof AI reviews."""

from __future__ import annotations

import argparse
from pathlib import Path

from .extractors import extract_document
from .reports import export_report
from .orchestrator import review_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a document with HumanProof AI.")
    parser.add_argument("document", help="Path to the document to review.")
    parser.add_argument("--format", default="md", choices=["json", "md", "html", "docx", "pdf"], help="Report format.")
    parser.add_argument("--output", help="Output report path.")
    args = parser.parse_args()

    source = Path(args.document)
    document = extract_document(source.read_bytes(), source.name)
    report = review_document(document)
    body, _, extension = export_report(report, args.format)
    output = Path(args.output) if args.output else source.with_suffix(f".humanproof-report.{extension}")
    output.write_bytes(body)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()

