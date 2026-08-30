"""
Unit tests for the rich-text FormattingStore, FormatOp transformation, and
Document CRUD / persistence / export.
"""

import os
import tempfile
import unittest

from backend.rope import Rope
from backend.formatting import FormattingStore
from backend.ot import (
    InsertOp,
    DeleteOp,
    FormatOp,
    transform,
)


class TestFormattingStore(unittest.TestCase):
    def test_insert_shifts_intervals(self):
        fs = FormattingStore([[0, 5, {"bold": True}]])
        fs.insert(2, 3)  # insert 3 chars at index 2; adjacent equal intervals merge
        self.assertEqual(fs.to_list(), [[0, 8, {"bold": True}]])

    def test_delete_trims_intervals(self):
        fs = FormattingStore([[0, 10, {"italic": True}]])
        fs.delete(4, 7)  # remove 3 chars in the middle; neighbours merge back
        self.assertEqual(fs.to_list(), [[0, 7, {"italic": True}]])

    def test_format_set_and_clear(self):
        fs = FormattingStore()
        fs.format(0, 4, {"bold": True})
        self.assertEqual(fs.to_list(), [[0, 4, {"bold": True}]])
        # Clearing a different attribute should not remove bold.
        fs.format(0, 4, {"italic": False})
        self.assertEqual(fs.to_list(), [[0, 4, {"bold": True}]])
        # Clearing bold removes the interval.
        fs.format(0, 4, {"bold": False})
        self.assertEqual(fs.to_list(), [])

    def test_normalize_merges_adjacent(self):
        fs = FormattingStore()
        fs.format(0, 2, {"bold": True})
        fs.format(2, 4, {"bold": True})
        self.assertEqual(fs.to_list(), [[0, 4, {"bold": True}]])


class TestMarkdownExport(unittest.TestCase):
    def test_plain_text(self):
        fs = FormattingStore()
        self.assertEqual(fs.to_markdown("Hello world"), "Hello world")

    def test_inline_formatting(self):
        fs = FormattingStore()
        fs.format(0, 5, {"bold": True})        # "Hello"
        fs.format(6, 11, {"italic": True})     # "world"
        md = fs.to_markdown("Hello world")
        self.assertEqual(md, "**Hello** *world*")

    def test_heading(self):
        fs = FormattingStore()
        fs.format(0, 5, {"header": 1})
        self.assertEqual(fs.to_markdown("Title"), "# Title")

    def test_multiline_and_underline(self):
        fs = FormattingStore()
        fs.format(0, 2, {"underline": True})   # "My"
        fs.format(13, 18, {"bold": True})      # "world" on second line
        text = "My doc\nhello world"
        md = fs.to_markdown(text)
        self.assertEqual(md, "<u>My</u> doc\nhello **world**")


class TestFormatOpConvergence(unittest.TestCase):
    """Verify that concurrent operations converge (TP1-like property)."""

    def _apply_text(self, rope, fs, op):
        if isinstance(op, InsertOp):
            rope.insert(op.pos, op.text)
            fs.insert(op.pos, len(op.text))
        elif isinstance(op, DeleteOp):
            fs.delete(op.pos, op.pos + op.length)
            rope.delete(op.pos, op.pos + op.length)
        elif isinstance(op, FormatOp):
            fs.format(op.start, op.end, op.attributes)

    def _verify(self, initial_text, op1, op2):
        op1p, op2p = transform(op1, op2)

        # Path 1: op1 then op2'
        rope1 = Rope(initial_text)
        fs1 = FormattingStore()
        self._apply_text(rope1, fs1, op1)
        self._apply_text(rope1, fs1, op2p)

        # Path 2: op2 then op1'
        rope2 = Rope(initial_text)
        fs2 = FormattingStore()
        self._apply_text(rope2, fs2, op2)
        self._apply_text(rope2, fs2, op1p)

        self.assertEqual(rope1.to_string(), rope2.to_string())
        self.assertEqual(fs1.to_list(), fs2.to_list())

    def test_format_vs_insert(self):
        self._verify(
            "Hello world",
            FormatOp(0, 5, {"bold": True}, op_id="a"),
            InsertOp(5, " NEW", user_id="u", op_id="b"),
        )

    def test_format_vs_delete(self):
        self._verify(
            "abcdefghij",
            FormatOp(2, 8, {"italic": True}, op_id="a"),
            DeleteOp(4, 3, user_id="u", op_id="b"),  # deletes chars 4..6
        )

    def test_format_vs_format_overlap(self):
        # Concurrent overlapping formats must converge deterministically.
        self._verify(
            "collaborative editing",
            FormatOp(0, 11, {"bold": True}, op_id="a1"),
            FormatOp(5, 13, {"italic": True}, op_id="a2"),
        )

    def test_format_vs_format_same_range(self):
        self._verify(
            "shared text",
            FormatOp(0, 11, {"bold": True}, op_id="z9"),
            FormatOp(0, 11, {"bold": False}, op_id="z1"),
        )


if __name__ == "__main__":
    unittest.main()
