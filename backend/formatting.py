"""
Formatting model for rich-text documents.

The plain text of a document lives in the AVL Rope (backend/rope.py).  This
module stores *attributes* (bold, italic, underline, heading, ...) over
character ranges in a lightweight interval list.  It is kept in lock-step with
the Rope: every text insert/delete shifts or trims the intervals, and a
``format`` operation sets/clears attributes on a range.

Convergence is achieved by treating formatting as operations over the same
character positions used by the text OT engine (see backend/ot.py).
"""

from typing import Dict, List, Any, Optional, Tuple

# Inline attributes rendered with explicit open/close markers, in nesting order.
INLINE_ORDER = ["bold", "italic", "underline"]
INLINE_MARKERS = {
    "bold": ("**", "**"),
    "italic": ("*", "*"),
    "underline": ("<u>", "</u>"),
}

# Block attribute handled at the line level.
HEADER_ATTR = "header"


class FormattingStore:
    """Stores attribute intervals over a character-addressed document."""

    def __init__(self, intervals: Optional[List[List[Any]]] = None):
        # Each interval is [start, end, {attr: value}]
        self.intervals: List[List[Any]] = []
        if intervals:
            for start, end, attrs in intervals:
                if end > start and attrs:
                    self.intervals.append([int(start), int(end), dict(attrs)])

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_list(self) -> List[List[Any]]:
        return [[s, e, dict(a)] for s, e, a in self.intervals]

    # ------------------------------------------------------------------ #
    # Text-operation aware adjustments
    # ------------------------------------------------------------------ #
    def insert(self, pos: int, length: int) -> None:
        if length <= 0:
            return
        for iv in self.intervals:
            if iv[0] >= pos:
                iv[0] += length
            if iv[1] >= pos:
                iv[1] += length

    def delete(self, start: int, end: int) -> None:
        if end <= start:
            return
        length = end - start
        new_intervals: List[List[Any]] = []
        for iv in self.intervals:
            s, e, a = iv[0], iv[1], iv[2]
            if e <= start or s >= end:
                # No overlap with the deleted range.
                if s >= end:
                    s -= length
                    e -= length
                new_intervals.append([s, e, a])
                continue
            # Overlap: keep the left and right surviving fragments.
            if s < start:
                new_intervals.append([s, start, dict(a)])
            if e > end:
                new_intervals.append([end - length, e - length, dict(a)])
        self.intervals = new_intervals
        self._normalize()

    def format(self, start: int, end: int, attributes: Dict[str, Any]) -> None:
        """Apply a formatting change to [start, end).

        A truthy value sets the attribute; a falsy value (False/None/0) clears it.
        """
        if end <= start:
            return

        set_attrs = {
            k: v
            for k, v in attributes.items()
            if v not in (False, None, 0, "")
        }
        remove_attrs = {k for k, v in attributes.items() if v in (False, None, 0, "")}

        affected = set(set_attrs.keys()) | remove_attrs

        new_intervals: List[List[Any]] = []
        for iv in self.intervals:
            s, e, a = iv[0], iv[1], iv[2]
            if e <= start or s >= end:
                new_intervals.append([s, e, a])
                continue
            # Split the overlapping interval around the new range, dropping the
            # affected attribute keys from the middle fragment.
            if s < start:
                new_intervals.append([s, start, dict(a)])
            if e > end:
                new_intervals.append([end, e, dict(a)])
            mid_s, mid_e = max(s, start), min(e, end)
            if mid_e > mid_s:
                mid = {k: v for k, v in a.items() if k not in affected}
                if mid:
                    new_intervals.append([mid_s, mid_e, mid])

        if set_attrs:
            new_intervals.append([start, end, dict(set_attrs)])

        self.intervals = new_intervals
        self._normalize()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def attrs_at(self, index: int) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for s, e, a in self.intervals:
            if s <= index < e:
                result.update(a)
        return result

    def attrs_in_range(self, start: int, end: int) -> Dict[str, Any]:
        """Union of all attribute keys present anywhere in [start, end).

        Used to capture the previous state of a range so a format operation can
        be inverted (undone) later.
        """
        result: Dict[str, Any] = {}
        for s, e, a in self.intervals:
            if e > start and s < end:
                result.update(a)
        return result

    def get_images(self) -> List[Dict[str, Any]]:
        """Return all image intervals as a list of dicts.

        Each dict contains: pos, imgId, width, height.
        """
        images: List[Dict[str, Any]] = []
        for s, e, a in self.intervals:
            img_id = a.get("image")
            if img_id:
                images.append({
                    "pos": s,
                    "imgId": img_id,
                    "width": a.get("width", 300),
                    "height": a.get("height", 200),
                })
        return images

    def _normalize(self) -> None:
        """Sort and merge adjacent intervals with identical attributes."""
        self.intervals.sort(key=lambda x: (x[0], x[1]))
        merged: List[List[Any]] = []
        for s, e, a in self.intervals:
            if e <= s:
                continue
            if merged and merged[-1][1] == s and merged[-1][2] == a:
                merged[-1][1] = e
            else:
                merged.append([s, e, dict(a)])
        self.intervals = merged

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #
    def _attr_index(self, text: str) -> Dict[int, Dict[str, Any]]:
        index: Dict[int, Dict[str, Any]] = {}
        for s, e, a in self.intervals:
            for i in range(s, e):
                if i < len(text):
                    index.setdefault(i, {}).update(a)
        return index

    def to_text(self, text: str) -> str:
        """Plain text export (formatting stripped)."""
        return text

    def to_markdown(self, text: str) -> str:
        """Convert the document to Markdown.

        Headings are emitted per line; inline attributes (bold/italic/underline)
        are wrapped with their markers.  Underline has no standard Markdown
        representation, so it uses the explicit ``<u>`` tag.
        """
        lines = text.split("\n")
        attr_index = self._attr_index(text)
        out: List[str] = []

        pos = 0
        for line in lines:
            line_len = len(line)
            header = 0
            if line_len > 0:
                header = attr_index.get(pos, {}).get(HEADER_ATTR) or 0
            try:
                header = int(header)
            except (TypeError, ValueError):
                header = 0

            rendered = self._render_inline(line, attr_index, pos, line_len)
            if header > 0:
                rendered = ("#" * header) + " " + rendered
            out.append(rendered)
            pos += line_len + 1  # +1 for the newline character

        return "\n".join(out)

    def _render_inline(
        self,
        text: str,
        attr_index: Dict[int, Dict[str, Any]],
        start: int,
        length: int,
    ) -> str:
        active: List[str] = []
        parts: List[str] = []
        for i in range(length):
            attrs = attr_index.get(start + i, {})
            new_active = [k for k in INLINE_ORDER if attrs.get(k)]
            # Close attributes that turned off (reverse order).
            for k in reversed(active):
                if k not in new_active:
                    parts.append(INLINE_MARKERS[k][1])
            # Open attributes that turned on.
            for k in new_active:
                if k not in active:
                    parts.append(INLINE_MARKERS[k][0])
            parts.append(text[i])
            active = new_active
        for k in reversed(active):
            parts.append(INLINE_MARKERS[k][1])
        return "".join(parts)
