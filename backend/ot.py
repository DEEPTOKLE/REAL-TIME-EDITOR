"""
Operational Transformation (OT) Engine for Collaborative Real-Time Text Editing.

Implements standard transformation functions for text operations (Insert, Delete, NoOp)
satisfying Transformation Property 1 (TP1):
    S o Op1 o T(Op2, Op1) == S o Op2 o T(Op1, Op2)

Includes support for client-side and server-side transformation loops, operation inversion
(for local undo/redo), and operation serialization.
"""

from typing import Optional, Dict, Any, Tuple
import uuid


class Operation:
    """Base class for document operations."""

    def __init__(self, user_id: str = "", op_id: Optional[str] = None):
        self.user_id = user_id
        self.op_id = op_id or str(uuid.uuid4())[:8]

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Operation':
        op_type = data.get("type")
        user_id = data.get("userId", "")
        op_id = data.get("opId", "")

        if op_type == "insert":
            return InsertOp(
                pos=data["pos"],
                text=data["text"],
                user_id=user_id,
                op_id=op_id,
            )
        elif op_type == "delete":
            return DeleteOp(
                pos=data["pos"],
                length=data.get("length", len(data.get("text", ""))),
                text=data.get("text", ""),
                user_id=user_id,
                op_id=op_id,
            )
        elif op_type == "format":
            return FormatOp(
                start=data["start"],
                end=data["end"],
                attributes=data.get("attributes", {}),
                user_id=user_id,
                op_id=op_id,
                prev_attributes=data.get("prevAttributes", {}),
            )
        elif op_type == "noop":
            return NoOp(user_id=user_id, op_id=op_id)
        else:
            raise ValueError(f"Unknown operation type: {op_type}")

    def is_noop(self) -> bool:
        return False


class NoOp(Operation):
    """No-operation (identity)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "noop",
            "userId": self.user_id,
            "opId": self.op_id,
        }

    def is_noop(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"NoOp(user={self.user_id})"


class InsertOp(Operation):
    """Inserts text at a given character position."""

    def __init__(
        self,
        pos: int,
        text: str,
        user_id: str = "",
        op_id: Optional[str] = None,
    ):
        super().__init__(user_id=user_id, op_id=op_id)
        self.pos = pos
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "insert",
            "pos": self.pos,
            "text": self.text,
            "userId": self.user_id,
            "opId": self.op_id,
        }

    def is_noop(self) -> bool:
        return len(self.text) == 0

    def __repr__(self) -> str:
        return f"Insert(pos={self.pos}, text={self.text!r}, user={self.user_id})"


class DeleteOp(Operation):
    """Deletes a range of characters at a given position."""

    def __init__(
        self,
        pos: int,
        length: int,
        text: str = "",
        user_id: str = "",
        op_id: Optional[str] = None,
    ):
        super().__init__(user_id=user_id, op_id=op_id)
        self.pos = pos
        self.length = length
        self.text = text  # Optional deleted text content for exact undo inversion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "delete",
            "pos": self.pos,
            "length": self.length,
            "text": self.text,
            "userId": self.user_id,
            "opId": self.op_id,
        }

    def is_noop(self) -> bool:
        return self.length <= 0

    def __repr__(self) -> str:
        return f"Delete(pos={self.pos}, len={self.length}, text={self.text!r}, user={self.user_id})"


class FormatOp(Operation):
    """Sets or clears attributes (bold, italic, underline, header, ...) on a range."""

    def __init__(
        self,
        start: int,
        end: int,
        attributes: Dict[str, Any],
        user_id: str = "",
        op_id: Optional[str] = None,
        prev_attributes: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(user_id=user_id, op_id=op_id)
        self.start = start
        self.end = end
        self.attributes = dict(attributes)
        self.prev_attributes = dict(prev_attributes) if prev_attributes else {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "format",
            "start": self.start,
            "end": self.end,
            "attributes": self.attributes,
            "prevAttributes": self.prev_attributes,
            "userId": self.user_id,
            "opId": self.op_id,
        }

    def is_noop(self) -> bool:
        return self.end <= self.start or not self.attributes

    def __repr__(self) -> str:
        return f"Format(start={self.start}, end={self.end}, attrs={self.attributes}, user={self.user_id})"


def transform(
    op1: Operation, op2: Operation, priority_user: Optional[str] = None
) -> Tuple[Operation, Operation]:
    """
    Transforms two concurrent operations (op1, op2) against each other.
    Returns (op1', op2') such that applying op1 then op2' produces the exact same
    state as applying op2 then op1'.
    """
    if op1.is_noop():
        return NoOp(op1.user_id, op1.op_id), op2
    if op2.is_noop():
        return op1, NoOp(op2.user_id, op2.op_id)

    # 1. Insert vs Insert
    if isinstance(op1, InsertOp) and isinstance(op2, InsertOp):
        return _transform_insert_insert(op1, op2, priority_user)

    # 2. Insert vs Delete
    elif isinstance(op1, InsertOp) and isinstance(op2, DeleteOp):
        return _transform_insert_delete(op1, op2)

    # 3. Delete vs Insert
    elif isinstance(op1, DeleteOp) and isinstance(op2, InsertOp):
        # Symmetry: swap arguments and return swapped result
        op2_prime, op1_prime = _transform_insert_delete(op2, op1)
        return op1_prime, op2_prime

    # 4. Delete vs Delete
    elif isinstance(op1, DeleteOp) and isinstance(op2, DeleteOp):
        return _transform_delete_delete(op1, op2)

    # 5. Text vs Format  (op2 already applied)
    elif isinstance(op1, (InsertOp, DeleteOp)) and isinstance(op2, FormatOp):
        shifted = _shift_format_by_text(op2, op1)
        return op1, shifted

    # 6. Format vs Text  (op2 already applied)
    elif isinstance(op1, FormatOp) and isinstance(op2, (InsertOp, DeleteOp)):
        shifted = _shift_format_by_text(op1, op2)
        return shifted, op2

    # 7. Format vs Format
    elif isinstance(op1, FormatOp) and isinstance(op2, FormatOp):
        return _transform_format_format(op1, op2)

    return op1, op2


def _shift_format_by_text(
    fmt: FormatOp, text_op: Operation
) -> FormatOp:
    """Returns a copy of `fmt` with its range shifted to account for a text
    operation (`text_op`) that has *already* been applied to the document."""
    s, e = fmt.start, fmt.end
    if isinstance(text_op, InsertOp):
        p, length = text_op.pos, len(text_op.text)
        if s >= p:
            s += length
        if e >= p:
            e += length
    elif isinstance(text_op, DeleteOp):
        p, length = text_op.pos, text_op.length
        if s >= p + length:
            s -= length
        elif s > p:
            s = p
        if e >= p + length:
            e -= length
        elif e > p:
            e = p
    return FormatOp(max(0, s), max(0, e), dict(fmt.attributes), fmt.user_id, fmt.op_id, fmt.prev_attributes)


def _transform_format_format(
    op1: FormatOp, op2: FormatOp
) -> Tuple[Operation, Operation]:
    """Transforms two concurrent format operations.

    Both clients apply the operations in the same server-determined order, so the
    only requirement is a deterministic winner for overlapping attribute keys.
    We pick the operation with the lexicographically smaller ``op_id`` as the
    winner; the loser's overlapping attribute keys are dropped so the winner's
    value is preserved in the overlap on both sides.
    """
    op1_prime = FormatOp(op1.start, op1.end, dict(op1.attributes), op1.user_id, op1.op_id, op1.prev_attributes)
    op2_prime = FormatOp(op2.start, op2.end, dict(op2.attributes), op2.user_id, op2.op_id, op2.prev_attributes)

    overlap_start = max(op1.start, op2.start)
    overlap_end = min(op1.end, op2.end)
    if overlap_end > overlap_start:
        winner_is_op1 = op1.op_id <= op2.op_id
        loser = op2_prime if winner_is_op1 else op1_prime
        for key in set(op1.attributes) & set(op2.attributes):
            loser.attributes.pop(key, None)

    return op1_prime, op2_prime


def _transform_insert_insert(
    op1: InsertOp, op2: InsertOp, priority_user: Optional[str] = None
) -> Tuple[Operation, Operation]:
    """Transforms two concurrent Insert operations."""
    if op1.pos < op2.pos:
        op1_prime = InsertOp(op1.pos, op1.text, op1.user_id, op1.op_id)
        op2_prime = InsertOp(op2.pos + len(op1.text), op2.text, op2.user_id, op2.op_id)
        return op1_prime, op2_prime

    elif op1.pos > op2.pos:
        op1_prime = InsertOp(op1.pos + len(op2.text), op1.text, op1.user_id, op1.op_id)
        op2_prime = InsertOp(op2.pos, op2.text, op2.user_id, op2.op_id)
        return op1_prime, op2_prime

    else:
        # Same position: deterministic tie-breaker by user ID or op ID
        tie_break = (op1.user_id < op2.user_id) if op1.user_id != op2.user_id else (op1.op_id < op2.op_id)
        if priority_user is not None:
            if op1.user_id == priority_user:
                tie_break = True
            elif op2.user_id == priority_user:
                tie_break = False

        if tie_break:
            op1_prime = InsertOp(op1.pos, op1.text, op1.user_id, op1.op_id)
            op2_prime = InsertOp(op2.pos + len(op1.text), op2.text, op2.user_id, op2.op_id)
        else:
            op1_prime = InsertOp(op1.pos + len(op2.text), op1.text, op1.user_id, op1.op_id)
            op2_prime = InsertOp(op2.pos, op2.text, op2.user_id, op2.op_id)

        return op1_prime, op2_prime


def _transform_insert_delete(
    ins: InsertOp, d: DeleteOp
) -> Tuple[Operation, Operation]:
    """Transforms concurrent Insert and Delete operations."""
    ins_pos = ins.pos
    del_start = d.pos
    del_end = d.pos + d.length

    if ins_pos <= del_start:
        # Insert is strictly before or at start of delete range:
        # Delete position shifts right by inserted text length
        ins_prime = InsertOp(ins.pos, ins.text, ins.user_id, ins.op_id)
        d_prime = DeleteOp(d.pos + len(ins.text), d.length, d.text, d.user_id, d.op_id)
        return ins_prime, d_prime

    elif ins_pos >= del_end:
        # Insert is strictly at or after end of delete range:
        # Insert position shifts left by deleted length
        ins_prime = InsertOp(ins.pos - d.length, ins.text, ins.user_id, ins.op_id)
        d_prime = DeleteOp(d.pos, d.length, d.text, d.user_id, d.op_id)
        return ins_prime, d_prime

    else:
        # Insert position falls strictly inside deleted range [del_start < ins_pos < del_end]
        # In state after delete: the position was deleted, so insert becomes NoOp
        ins_prime = NoOp(ins.user_id, ins.op_id)
        # In state after insert: delete length encompasses the inserted text
        d_prime = DeleteOp(d.pos, d.length + len(ins.text), d.text, d.user_id, d.op_id)
        return ins_prime, d_prime


def _transform_delete_delete(
    d1: DeleteOp, d2: DeleteOp
) -> Tuple[Operation, Operation]:
    """Transforms two concurrent Delete operations."""
    s1, e1 = d1.pos, d1.pos + d1.length
    s2, e2 = d2.pos, d2.pos + d2.length

    # Disjoint cases
    if e1 <= s2:
        # d1 is completely before d2
        d1_prime = DeleteOp(d1.pos, d1.length, d1.text, d1.user_id, d1.op_id)
        d2_prime = DeleteOp(d2.pos - d1.length, d2.length, d2.text, d2.user_id, d2.op_id)
        return d1_prime, d2_prime

    elif e2 <= s1:
        # d2 is completely before d1
        d1_prime = DeleteOp(d1.pos - d2.length, d1.length, d1.text, d1.user_id, d1.op_id)
        d2_prime = DeleteOp(d2.pos, d2.length, d2.text, d2.user_id, d2.op_id)
        return d1_prime, d2_prime

    # Overlapping cases
    overlap_start = max(s1, s2)
    overlap_end = min(e1, e2)
    overlap_len = max(0, overlap_end - overlap_start)

    # Calculate remaining characters for d1
    new_len1 = d1.length - overlap_len
    if new_len1 <= 0:
        d1_prime = NoOp(d1.user_id, d1.op_id)
    else:
        # Start position of d1' is shifted left by how many chars before s1 were deleted by d2
        shift1 = max(0, min(d2.length, s1 - s2))
        d1_prime = DeleteOp(s1 - shift1, new_len1, "", d1.user_id, d1.op_id)

    # Calculate remaining characters for d2
    new_len2 = d2.length - overlap_len
    if new_len2 <= 0:
        d2_prime = NoOp(d2.user_id, d2.op_id)
    else:
        shift2 = max(0, min(d1.length, s2 - s1))
        d2_prime = DeleteOp(s2 - shift2, new_len2, "", d2.user_id, d2.op_id)

    return d1_prime, d2_prime


def invert(op: Operation) -> Operation:
    """
    Creates an inverse operation for local undo/redo.
    Insert(p, t) -> Delete(p, len(t), text=t)
    Delete(p, l, text=t) -> Insert(p, t)
    """
    if isinstance(op, InsertOp):
        return DeleteOp(
            pos=op.pos,
            length=len(op.text),
            text=op.text,
            user_id=op.user_id,
        )
    elif isinstance(op, DeleteOp):
        return InsertOp(
            pos=op.pos,
            text=op.text if op.text else " " * op.length,
            user_id=op.user_id,
        )
    elif isinstance(op, FormatOp):
        # Invert by restoring the previously-captured attributes (or clearing).
        return FormatOp(
            start=op.start,
            end=op.end,
            attributes=dict(op.prev_attributes),
            user_id=op.user_id,
            op_id=op.op_id,
        )
    return NoOp(op.user_id)
