"""
Tests for PDF export.
"""

import unittest

from backend.pdf_exporter import synapse_to_pdf


class TestPdfExport(unittest.TestCase):
    def test_plain_text_produces_pdf(self):
        result = synapse_to_pdf("Hello world", [])
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_bold_italic_underline(self):
        text = "Hello world"
        intervals = [[0, 5, {"bold": True}], [6, 11, {"italic": True}]]
        result = synapse_to_pdf(text, intervals)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))
        self.assertGreater(len(result), 0)

    def test_header_levels(self):
        text = "Title\nSubtitle\nSection"
        intervals = [
            [0, 5, {"header": 1}],
            [6, 14, {"header": 2}],
            [15, 22, {"header": 3}],
        ]
        result = synapse_to_pdf(text, intervals)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_blockquote(self):
        text = "This is quoted"
        intervals = [[0, 14, {"blockquote": True}]]
        result = synapse_to_pdf(text, intervals)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_code_block(self):
        text = "print('hello')"
        intervals = [[0, 14, {"code": True}]]
        result = synapse_to_pdf(text, intervals)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_missing_image_degrades_gracefully(self):
        text = "Before \uFFFC After"
        intervals = [[7, 8, {"image": "nonexistent-id", "width": 300, "height": 200}]]
        result = synapse_to_pdf(text, intervals)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_empty_document(self):
        result = synapse_to_pdf("", [])
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_multiline(self):
        text = "Line one\nLine two\nLine three"
        result = synapse_to_pdf(text, [])
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
