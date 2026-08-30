"""
Unit and Convergence Tests for Operational Transformation (OT).
"""

import random
import unittest
from backend.rope import Rope
from backend.ot import Operation, InsertOp, DeleteOp, NoOp, transform, invert
from backend.document_manager import Document


class TestOT(unittest.TestCase):

    def _apply_op(self, rope: Rope, op: Operation) -> None:
        if isinstance(op, InsertOp):
            pos = min(rope.length(), max(0, op.pos))
            rope.insert(pos, op.text)
        elif isinstance(op, DeleteOp):
            start = min(rope.length(), max(0, op.pos))
            end = min(rope.length(), start + op.length)
            rope.delete(start, end)

    def _verify_tp1(self, initial_text: str, op1: Operation, op2: Operation) -> None:
        """
        Verifies Transformation Property 1 (TP1):
        S o op1 o transform(op2, op1)[0] == S o op2 o transform(op1, op2)[0]
        """
        op1_prime, op2_prime = transform(op1, op2)

        # Path 1: Apply op1 then op2_prime
        rope1 = Rope(initial_text)
        self._apply_op(rope1, op1)
        self._apply_op(rope1, op2_prime)
        result1 = rope1.to_string()

        # Path 2: Apply op2 then op1_prime
        rope2 = Rope(initial_text)
        self._apply_op(rope2, op2)
        self._apply_op(rope2, op1_prime)
        result2 = rope2.to_string()

        self.assertEqual(
            result1,
            result2,
            f"TP1 violation!\nInitial: {initial_text!r}\nOp1: {op1}\nOp2: {op2}\nOp1': {op1_prime}\nOp2': {op2_prime}\nPath1 result: {result1!r}\nPath2 result: {result2!r}"
        )

    def test_insert_insert_concurrent(self):
        # Case 1: op1 before op2
        op1 = InsertOp(pos=2, text="AA", user_id="u1")
        op2 = InsertOp(pos=5, text="BB", user_id="u2")
        self._verify_tp1("0123456789", op1, op2)

        # Case 2: op2 before op1
        op1 = InsertOp(pos=7, text="XYZ", user_id="u1")
        op2 = InsertOp(pos=1, text="123", user_id="u2")
        self._verify_tp1("0123456789", op1, op2)

        # Case 3: Same position with tie-breaking
        op1 = InsertOp(pos=4, text="AAA", user_id="alice")
        op2 = InsertOp(pos=4, text="BBB", user_id="bob")
        self._verify_tp1("Hello World", op1, op2)

    def test_insert_delete_concurrent(self):
        # Case 1: Insert before Delete
        op1 = InsertOp(pos=2, text="INSERT", user_id="u1")
        op2 = DeleteOp(pos=5, length=3, user_id="u2")
        self._verify_tp1("abcdefghijk", op1, op2)

        # Case 2: Insert after Delete
        op1 = InsertOp(pos=8, text="INSERT", user_id="u1")
        op2 = DeleteOp(pos=2, length=3, user_id="u2")
        self._verify_tp1("abcdefghijk", op1, op2)

        # Case 3: Insert inside Delete range
        op1 = InsertOp(pos=4, text="INSIDE", user_id="u1")
        op2 = DeleteOp(pos=2, length=5, user_id="u2")
        self._verify_tp1("abcdefghijk", op1, op2)

    def test_delete_delete_concurrent(self):
        # Disjoint deletes
        op1 = DeleteOp(pos=1, length=2, user_id="u1")
        op2 = DeleteOp(pos=6, length=3, user_id="u2")
        self._verify_tp1("0123456789abcdef", op1, op2)

        # Overlapping deletes
        op1 = DeleteOp(pos=3, length=5, user_id="u1")  # [3, 8)
        op2 = DeleteOp(pos=5, length=4, user_id="u2")  # [5, 9)
        self._verify_tp1("0123456789abcdef", op1, op2)

        # Identical deletes
        op1 = DeleteOp(pos=4, length=3, user_id="u1")
        op2 = DeleteOp(pos=4, length=3, user_id="u2")
        self._verify_tp1("0123456789abcdef", op1, op2)

        # Contained delete
        op1 = DeleteOp(pos=2, length=8, user_id="u1")  # [2, 10)
        op2 = DeleteOp(pos=4, length=3, user_id="u2")  # [4, 7)
        self._verify_tp1("0123456789abcdef", op1, op2)

    def test_invert_undo_redo(self):
        doc = Document(doc_id="test_doc", initial_text="Hello World")
        
        # Apply insert
        ins = InsertOp(pos=5, text=" Beautiful", user_id="u1")
        transformed_ins, v1 = doc.apply_client_operation(ins, client_base_version=0)
        self.assertEqual(doc.get_content(), "Hello Beautiful World")

        # Invert to Undo
        inv_ins = invert(transformed_ins)
        transformed_inv, v2 = doc.apply_client_operation(inv_ins, client_base_version=v1)
        self.assertEqual(doc.get_content(), "Hello World")

        # Redo
        redo_ins = invert(transformed_inv)
        _, v3 = doc.apply_client_operation(redo_ins, client_base_version=v2)
        self.assertEqual(doc.get_content(), "Hello Beautiful World")

    def test_document_concurrent_multi_client_convergence(self):
        """Simulates multiple clients sending concurrent operations with lagging base versions."""
        doc = Document(doc_id="multi_user_doc", initial_text="The quick brown fox.")

        # Client 1 types at base version 0
        c1_op = InsertOp(pos=4, text="very ", user_id="client1")
        # Client 2 deletes at base version 0
        c2_op = DeleteOp(pos=10, length=5, text="brown", user_id="client2")
        # Client 3 inserts at end at base version 0
        c3_op = InsertOp(pos=20, text=" jumps!", user_id="client3")

        # Server receives and processes in arbitrary arrival order
        t1, v1 = doc.apply_client_operation(c1_op, client_base_version=0)
        t2, v2 = doc.apply_client_operation(c2_op, client_base_version=0)
        t3, v3 = doc.apply_client_operation(c3_op, client_base_version=0)

        self.assertEqual(doc.version, 3)
        final_text = doc.get_content()
        # Verify content contains all concurrent edits merged cleanly
        self.assertIn("very", final_text)
        self.assertNotIn("brown", final_text)
        self.assertIn("jumps!", final_text)


if __name__ == "__main__":
    unittest.main()

