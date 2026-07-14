import base64
import unittest

from backend.humanproof.extractors import detect_format, extract_document


class ExtractorTests(unittest.TestCase):
    def test_detect_format_from_filename(self):
        self.assertEqual(detect_format("paper.docx"), "docx")
        self.assertEqual(detect_format("notes.markdown"), "md")
        self.assertEqual(detect_format("", "application/json"), "json")

    def test_extract_markdown_text(self):
        document = extract_document(b"# Title\n\nThis is a test.", "sample.md", "text/markdown")
        self.assertEqual(document.metadata.file_format, "md")
        self.assertIn("This is a test.", document.text)

    def test_extract_json_pretty_text(self):
        document = extract_document(b'{"title":"Policy","enabled":true}', "policy.json", "application/json")
        self.assertIn('"title": "Policy"', document.text)

    def test_invalid_binary_has_limitation(self):
        document = extract_document(base64.b64decode("AAECAwQ="), "scan.pdf", "application/pdf")
        self.assertIn("PDF extraction uses", " ".join(document.limitations))


if __name__ == "__main__":
    unittest.main()

