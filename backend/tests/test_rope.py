"""
Unit and Stress Tests for AVL-balanced Rope data structure.
"""

import math
import random
import unittest
from backend.rope import Rope, RopeNode


class TestRope(unittest.TestCase):

    def test_empty_rope(self):
        rope = Rope()
        self.assertEqual(rope.length(), 0)
        self.assertEqual(rope.to_string(), "")
        self.assertEqual(rope.substring(0, 0), "")

    def test_initial_text(self):
        text = "Hello, World! Collaborative Editor."
        rope = Rope(text)
        self.assertEqual(rope.length(), len(text))
        self.assertEqual(rope.to_string(), text)
        self.assertEqual(rope.substring(0, 5), "Hello")
        self.assertEqual(rope.substring(7, 12), "World")

    def test_insert_operations(self):
        rope = Rope("Hello World")
        # Insert at start
        rope.insert(0, ">> ")
        self.assertEqual(rope.to_string(), ">> Hello World")

        # Insert at end
        rope.insert(rope.length(), " <<")
        self.assertEqual(rope.to_string(), ">> Hello World <<")

        # Insert in middle
        rope.insert(9, "Beautiful ")
        self.assertEqual(rope.to_string(), ">> Hello Beautiful World <<")

    def test_delete_operations(self):
        rope = Rope("The quick brown fox jumps over the lazy dog")
        # Delete "quick "
        rope.delete(4, 10)
        self.assertEqual(rope.to_string(), "The brown fox jumps over the lazy dog")

        # Delete at start
        rope.delete(0, 4)
        self.assertEqual(rope.to_string(), "brown fox jumps over the lazy dog")

        # Delete at end (" dog")
        rope.delete(rope.length() - 4, rope.length())
        self.assertEqual(rope.to_string(), "brown fox jumps over the lazy")

        # Delete all
        rope.delete(0, rope.length())
        self.assertEqual(rope.to_string(), "")
        self.assertEqual(rope.length(), 0)

    def test_char_at(self):
        text = "abcdefghijklmnopqrstuvwxyz"
        rope = Rope(text)
        for i, char in enumerate(text):
            self.assertEqual(rope.char_at(i), char)

        with self.assertRaises(IndexError):
            rope.char_at(-1)
        with self.assertRaises(IndexError):
            rope.char_at(len(text))

    def test_substring_bounds(self):
        text = "Operational Transformation and Rope Structure"
        rope = Rope(text)
        self.assertEqual(rope.substring(0, 100), text)
        self.assertEqual(rope.substring(-5, 11), "Operational")
        self.assertEqual(rope.substring(10, 5), "")
        self.assertEqual(rope.substring(len(text), len(text) + 10), "")

    def _check_avl_balance(self, node: RopeNode):
        """Recursively validates AVL invariant: |height(left) - height(right)| <= 1."""
        if node is None or node.is_leaf():
            return
        bf = node.balance_factor()
        self.assertTrue(
            abs(bf) <= 1,
            f"Node violates AVL property: balance factor is {bf}"
        )
        if node.left:
            self._check_avl_balance(node.left)
        if node.right:
            self._check_avl_balance(node.right)

    def test_avl_balancing_on_large_text(self):
        rope = Rope()
        # Insert 100 separate small strings to trigger multiple splits and rebalancings
        chunks = [f"paragraph_{i} {('xyz ' * 20)}\n" for i in range(100)]
        for chunk in chunks:
            rope.insert(rope.length(), chunk)

        expected_str = "".join(chunks)
        self.assertEqual(rope.to_string(), expected_str)
        self.assertEqual(rope.length(), len(expected_str))

        # Check AVL balance
        self._check_avl_balance(rope.root)

        # Ensure tree height is logarithmic
        if rope.root:
            max_expected_height = 2.0 * math.log2(max(2, rope.length())) + 5
            self.assertLessEqual(rope.root.height, max_expected_height)

    def test_stress_fuzzing_vs_python_str(self):
        """Randomized stress test comparing Rope vs reference Python str for 500 operations."""
        random.seed(42)
        reference = "Initial text."
        rope = Rope(reference)

        words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", " ", "\n", "!@#$"]

        for step in range(500):
            op_choice = random.random()
            ref_len = len(reference)

            if op_choice < 0.55 or ref_len == 0:
                # Insert
                pos = random.randint(0, ref_len)
                text = random.choice(words) * random.randint(1, 3)
                reference = reference[:pos] + text + reference[pos:]
                rope.insert(pos, text)
            elif op_choice < 0.85:
                # Delete
                start = random.randint(0, ref_len - 1)
                end = random.randint(start, min(ref_len, start + 30))
                reference = reference[:start] + reference[end:]
                rope.delete(start, end)
            else:
                # Substring verification
                if ref_len > 0:
                    start = random.randint(0, ref_len - 1)
                    end = random.randint(start, ref_len)
                    self.assertEqual(rope.substring(start, end), reference[start:end])

            # Invariant checks
            self.assertEqual(rope.length(), len(reference), f"Length mismatch at step {step}")

        # Final content match
        self.assertEqual(rope.to_string(), reference)
        self._check_avl_balance(rope.root)


if __name__ == "__main__":
    unittest.main()
