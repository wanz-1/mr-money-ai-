import json
import unittest
import zipfile
from io import BytesIO

from backend.humanproof.orchestrator import review_text
from backend.humanproof.reports import export_report, report_as_docx, report_as_json, report_as_pdf


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.report = review_text("This is a concise report. References\nSmith (2024).", "report.md")

    def test_json_report_is_valid(self):
        payload = json.loads(report_as_json(self.report).decode("utf-8"))
        self.assertEqual(payload["reviewId"], self.report.review_id)

    def test_docx_report_is_zip_package(self):
        data = report_as_docx(self.report)
        self.assertTrue(data.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertIn("word/document.xml", archive.namelist())

    def test_pdf_report_has_pdf_header(self):
        data = report_as_pdf(self.report)
        self.assertTrue(data.startswith(b"%PDF-1.4"))

    def test_export_report_content_types(self):
        _, content_type, extension = export_report(self.report, "html")
        self.assertEqual(content_type, "text/html")
        self.assertEqual(extension, "html")


if __name__ == "__main__":
    unittest.main()

