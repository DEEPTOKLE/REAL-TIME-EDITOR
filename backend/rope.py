"""
AVL-Balanced Rope Data Structure for Efficient Text Representation and Manipulation.

A Rope is a binary tree where leaf nodes contain character strings (chunks), and internal
nodes contain the weight (length of left subtree) and references to children.
AVL tree concatenation with spine descent and rotations guarantees O(log N) operations for
insert, delete, substring, and indexing.
"""

from typing import Optional, Tuple, List


class RopeNode:
    """Node in an AVL-balanced Rope data structure."""

    __slots__ = ('text', 'weight', 'height', 'left', 'right')

    def __init__(
        self,
        text: Optional[str] = None,
        left: Optional['RopeNode'] = None,
        right: Optional['RopeNode'] = None,
    ):
        self.text: Optional[str] = text
        self.left: Optional['RopeNode'] = left
        self.right: Optional['RopeNode'] = right

        if self.is_leaf():
            self.weight: int = len(self.text) if self.text is not None else 0
            self.height: int = 1
        else:
            self.weight = self.left.length() if self.left is not None else 0
            left_h = self.left.height if self.left is not None else 0
            right_h = self.right.height if self.right is not None else 0
            self.height = 1 + max(left_h, right_h)

    def is_leaf(self) -> bool:
        """Returns True if this node is a leaf containing string content."""
        return self.left is None and self.right is None

    def length(self) -> int:
        """Returns total character length in the subtree rooted at this node."""
        if self.is_leaf():
            return len(self.text) if self.text is not None else 0
        left_len = self.left.length() if self.left is not None else 0
        right_len = self.right.length() if self.right is not None else 0
        return left_len + right_len

    def balance_factor(self) -> int:
        """Returns AVL balance factor: height(left) - height(right)."""
        left_h = self.left.height if self.left is not None else 0
        right_h = self.right.height if self.right is not None else 0
        return left_h - right_h

    def update(self) -> None:
        """Recalculates weight and height after child modifications."""
        if self.is_leaf():
            self.weight = len(self.text) if self.text is not None else 0
            self.height = 1
        else:
            self.weight = self.left.length() if self.left is not None else 0
            left_h = self.left.height if self.left is not None else 0
            right_h = self.right.height if self.right is not None else 0
            self.height = 1 + max(left_h, right_h)

    def __repr__(self) -> str:
        if self.is_leaf():
            return f"Leaf({self.text!r}, len={self.weight})"
        return f"Node(weight={self.weight}, h={self.height})"


class Rope:
    """
    High-performance AVL-balanced Rope for text document representation.
    Supports insert, delete, substring, and char_at in O(log N) time.
    """

    MAX_LEAF_LEN: int = 256
    MIN_LEAF_LEN: int = 64

    def __init__(self, initial_text: str = ""):
        if not initial_text:
            self.root: Optional[RopeNode] = RopeNode(text="")
        else:
            self.root = self._build_from_text(initial_text)

    def length(self) -> int:
        """Returns the total number of characters in the document."""
        return self.root.length() if self.root is not None else 0

    def __len__(self) -> int:
        return self.length()

    def char_at(self, index: int) -> str:
        """
        Retrieves the character at a given 0-based index in O(log N) time.
        Raises IndexError if index is out of bounds.
        """
        if index < 0 or index >= self.length():
            raise IndexError(f"Index {index} out of range for Rope of length {self.length()}")
        return self._char_at_node(self.root, index)

    def _char_at_node(self, node: Optional[RopeNode], index: int) -> str:
        if node is None:
            raise IndexError("Index out of bounds")
        if node.is_leaf():
            return node.text[index]  # type: ignore

        if index < node.weight:
            return self._char_at_node(node.left, index)
        return self._char_at_node(node.right, index - node.weight)

    def substring(self, start: int, end: Optional[int] = None) -> str:
        """
        Retrieves a substring from start to end (exclusive) in O(log N + K) time.
        Clamps indices to valid range like standard Python slicing.
        """
        total_len = self.length()
        if end is None:
            end = total_len
        start = max(0, min(start, total_len))
        end = max(start, min(end, total_len))

        if start >= end:
            return ""

        chunks: List[str] = []
        self._collect_substring(self.root, start, end, chunks)
        return "".join(chunks)

    def _collect_substring(
        self, node: Optional[RopeNode], start: int, end: int, out: List[str]
    ) -> None:
        if node is None or start >= end:
            return

        if node.is_leaf():
            text = node.text or ""
            out.append(text[start:end])
            return

        left_len = node.weight
        if start < left_len:
            left_end = min(end, left_len)
            self._collect_substring(node.left, start, left_end, out)

        if end > left_len:
            right_start = max(0, start - left_len)
            right_end = end - left_len
            self._collect_substring(node.right, right_start, right_end, out)

    def insert(self, position: int, text: str) -> None:
        """
        Inserts text at the given character position (0 <= position <= length).
        Maintains AVL balance with O(log N) time complexity.
        """
        if not text:
            return

        total_len = self.length()
        if position < 0 or position > total_len:
            raise IndexError(f"Position {position} out of bounds for Rope of length {total_len}")

        new_tree = self._build_from_text(text)
        if self.root is None or self.root.length() == 0:
            self.root = new_tree
            return

        if position == 0:
            self.root = self._concat(new_tree, self.root)
        elif position == total_len:
            self.root = self._concat(self.root, new_tree)
        else:
            left_part, right_part = self._split(self.root, position)
            merged_left = self._concat(left_part, new_tree)
            self.root = self._concat(merged_left, right_part)

    def delete(self, start: int, end: int) -> None:
        """
        Deletes characters in range [start, end) (0 <= start <= end <= length).
        Maintains AVL balance with O(log N) time complexity.
        """
        total_len = self.length()
        start = max(0, min(start, total_len))
        end = max(start, min(end, total_len))

        if start >= end or self.root is None:
            return

        if start == 0 and end == total_len:
            self.root = RopeNode(text="")
            return

        if start == 0:
            _, right_part = self._split(self.root, end)
            self.root = right_part if right_part is not None else RopeNode(text="")
        elif end == total_len:
            left_part, _ = self._split(self.root, start)
            self.root = left_part if left_part is not None else RopeNode(text="")
        else:
            left_part, remainder = self._split(self.root, start)
            del_len = end - start
            _, right_part = self._split(remainder, del_len)
            self.root = self._concat(left_part, right_part)

    def to_string(self) -> str:
        """Returns the full document content as a single string."""
        return self.substring(0, self.length())

    def __str__(self) -> str:
        return self.to_string()

    # --------------------------------------------------------------------------
    # AVL Tree Balancing & Rotations
    # --------------------------------------------------------------------------

    def _rotate_right(self, y: RopeNode) -> RopeNode:
        """Right rotation around node y."""
        x = y.left
        if x is None:
            return y
        b = x.right

        x.right = y
        y.left = b

        y.update()
        x.update()
        return x

    def _rotate_left(self, x: RopeNode) -> RopeNode:
        """Left rotation around node x."""
        y = x.right
        if y is None:
            return x
        b = y.left

        y.left = x
        x.right = b

        x.update()
        y.update()
        return y

    def _rebalance(self, node: Optional[RopeNode]) -> Optional[RopeNode]:
        """Rebalances an AVL node using single or double rotations."""
        if node is None or node.is_leaf():
            return node

        node.update()
        bf = node.balance_factor()

        # Left Heavy
        if bf > 1:
            if node.left is not None and node.left.balance_factor() < 0:
                node.left = self._rotate_left(node.left)
            return self._rotate_right(node)

        # Right Heavy
        if bf < -1:
            if node.right is not None and node.right.balance_factor() > 0:
                node.right = self._rotate_right(node.right)
            return self._rotate_left(node)

        return node

    def _concat_right(self, left: RopeNode, right: RopeNode) -> RopeNode:
        """
        Concatenates when left is taller than right:
        Descends right spine of left tree until height is comparable, then attaches right.
        """
        h_right = right.height
        if left.height <= h_right + 1:
            new_node = RopeNode(left=left, right=right)
            return self._rebalance(new_node) or new_node

        left.right = self._concat_right(left.right, right) if left.right else right
        return self._rebalance(left) or left

    def _concat_left(self, left: RopeNode, right: RopeNode) -> RopeNode:
        """
        Concatenates when right is taller than left:
        Descends left spine of right tree until height is comparable, then attaches left.
        """
        h_left = left.height
        if right.height <= h_left + 1:
            new_node = RopeNode(left=left, right=right)
            return self._rebalance(new_node) or new_node

        right.left = self._concat_left(left, right.left) if right.left else left
        return self._rebalance(right) or right

    def _concat(
        self, left: Optional[RopeNode], right: Optional[RopeNode]
    ) -> Optional[RopeNode]:
        """Concatenates two AVL rope trees and maintains O(log N) balance."""
        if left is None or left.length() == 0:
            return right
        if right is None or right.length() == 0:
            return left

        # If both are small leaves, merge into a single leaf
        if (
            left.is_leaf()
            and right.is_leaf()
            and (left.weight + right.weight) <= self.MAX_LEAF_LEN
        ):
            merged_text = (left.text or "") + (right.text or "")
            return RopeNode(text=merged_text)

        # AVL spine descent based on relative heights
        if left.height > right.height + 1:
            return self._concat_right(left, right)
        elif right.height > left.height + 1:
            return self._concat_left(left, right)
        else:
            new_node = RopeNode(left=left, right=right)
            return self._rebalance(new_node)

    def _split(
        self, node: Optional[RopeNode], index: int
    ) -> Tuple[Optional[RopeNode], Optional[RopeNode]]:
        """
        Splits the rope subtree at `index` into (left_tree, right_tree).
        Returns two balanced subtrees.
        """
        if node is None:
            return None, None

        if index <= 0:
            return None, node
        if index >= node.length():
            return node, None

        if node.is_leaf():
            text = node.text or ""
            left_leaf = RopeNode(text=text[:index]) if index > 0 else None
            right_leaf = RopeNode(text=text[index:]) if index < len(text) else None
            return left_leaf, right_leaf

        left_len = node.weight
        if index < left_len:
            left_l, right_l = self._split(node.left, index)
            merged_right = self._concat(right_l, node.right)
            return left_l, merged_right
        elif index > left_len:
            left_r, right_r = self._split(node.right, index - left_len)
            merged_left = self._concat(node.left, left_r)
            return merged_left, right_r
        else:
            # Exact split at left subtree boundary
            return node.left, node.right

    def _build_from_text(self, text: str) -> RopeNode:
        """Constructs a balanced Rope binary tree from a string."""
        if len(text) <= self.MAX_LEAF_LEN:
            return RopeNode(text=text)

        chunks = [
            text[i : i + self.MAX_LEAF_LEN]
            for i in range(0, len(text), self.MAX_LEAF_LEN)
        ]
        nodes: List[RopeNode] = [RopeNode(text=chunk) for chunk in chunks]

        while len(nodes) > 1:
            next_level: List[RopeNode] = []
            for i in range(0, len(nodes), 2):
                if i + 1 < len(nodes):
                    merged = self._concat(nodes[i], nodes[i + 1])
                    if merged is not None:
                        next_level.append(merged)
                else:
                    next_level.append(nodes[i])
            nodes = next_level

        return nodes[0]

