"""
PDF export for the Synapse collaborative editor.

Converts plain text + formatting intervals into a PDF using reportlab.
"""

import io
import pathlib
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
)
from reportlab.lib.enums import TA_LEFT

from .image_store import load_image_file


IMAGE_DIR = pathlib.Path("data/images")


def synapse_to_pdf(text: str, formatting_intervals: list, title: str = "") -> bytes:
    """Convert Synapse text + formatting intervals to a PDF file.

    Args:
        text: Plain text document content (may contain \uFFFC image placeholders).
        formatting_intervals: List of [start, end, {attr: val}] intervals.
        title: Document title for PDF metadata.

    Returns:
        Raw bytes of the generated PDF.
    """
    buffer = io.BytesIO()

    page_width, page_height = A4
    margin = 72  # 1 inch
    frame_width = page_width - 2 * margin
    frame_height = page_height - 2 * margin

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        title=title or "Synapse Document",
        author="Synapse Collaborative Editor",
        subject="Exported document",
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    frame = Frame(
        margin, margin, frame_width, frame_height, id="normal", showBoundary=0
    )

    template = PageTemplate(id="main", frames=frame)
    doc.addPageTemplates([template])

    styles = getSampleStyleSheet()

    h1_style = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=24,
        leading=28,
        spaceBefore=18,
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=18,
        leading=22,
        spaceBefore=14,
        spaceAfter=4,
    )
    h3_style = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=2,
    )
    quote_style = ParagraphStyle(
        "Quote",
        parent=styles["Normal"],
        leftIndent=36,
        textColor=colors.HexColor("#555555"),
        fontName="Times-Italic",
        leading=16,
        spaceBefore=4,
        spaceAfter=4,
    )
    code_style = ParagraphStyle(
        "Code",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=10,
        leading=13,
        backColor=colors.HexColor("#f4f4f4"),
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=4,
    )
    normal_style = ParagraphStyle(
        "Normal",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        spaceBefore=1,
        spaceAfter=1,
    )

    attr_index: Dict[int, Dict[str, Any]] = {}
    for start, end, attrs in formatting_intervals:
        for i in range(start, end):
            if i < len(text):
                attr_index.setdefault(i, {}).update(attrs)

    flowables: List[Any] = []
    pos = 0
    lines = text.split("\n")

    for line_idx, line in enumerate(lines):
        line_len = len(line)

        if line_len == 0:
            flowables.append(Spacer(1, 8))
            pos += 1
            continue

        first_attrs = attr_index.get(pos, {})
        header_level = first_attrs.get("header")
        is_blockquote = bool(first_attrs.get("blockquote"))
        is_code_block = bool(first_attrs.get("code"))

        if header_level == 1:
            style = h1_style
        elif header_level == 2:
            style = h2_style
        elif header_level == 3:
            style = h3_style
        elif is_blockquote:
            style = quote_style
        elif is_code_block:
            style = code_style
        else:
            style = normal_style

        if is_code_block:
            flowables.append(_build_code_flowable(line, pos, attr_index))
        else:
            flowables.append(_build_paragraph(line, pos, attr_index, style))

        pos += line_len + 1

    doc.build(flowables)
    return buffer.getvalue()


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _build_paragraph(line: str, pos: int, attr_index: Dict[int, Dict[str, Any]], style) -> Paragraph:
    """Build a reportlab Paragraph with inline formatting tags."""
    parts = []
    i = 0
    while i < len(line):
        char = line[i]

        if char == "\uFFFC":
            attrs = attr_index.get(pos + i, {})
            img_id = attrs.get("image")
            if img_id:
                try:
                    img_bytes, _ = load_image_file(img_id)
                    img_buffer = io.BytesIO(img_bytes)
                    width = min(int(attrs.get("width") or 300), 400)
                    orig_w = float(attrs.get("width") or 300)
                    orig_h = float(attrs.get("height") or 200)
                    scale = width / orig_w if orig_w > 0 else 1.0
                    height = orig_h * scale
                    parts.append(
                        f'<img src="file://{_image_path(img_id)}" width="{width}" height="{height}" valign="middle"/>'
                    )
                except FileNotFoundError:
                    parts.append('<font color="#999999">[Image unavailable]</font>')
            i += 1
            continue

        attrs = attr_index.get(pos + i, {})
        open_tags = ""
        close_tags = ""
        if attrs.get("bold"):
            open_tags += "<b>"
            close_tags = "</b>" + close_tags
        if attrs.get("italic"):
            open_tags += "<i>"
            close_tags = "</i>" + close_tags
        if attrs.get("underline"):
            open_tags += "<u>"
            close_tags = "</u>" + close_tags
        if attrs.get("code"):
            open_tags += '<font name="Courier">'
            close_tags = "</font>" + close_tags

        j = i + 1
        while j < len(line):
            c = line[j]
            if c == "\uFFFC":
                break
            next_attrs = attr_index.get(pos + j, {})
            if (
                next_attrs.get("bold") != attrs.get("bold")
                or next_attrs.get("italic") != attrs.get("italic")
                or next_attrs.get("underline") != attrs.get("underline")
                or next_attrs.get("code") != attrs.get("code")
            ):
                break
            j += 1

        chunk = _escape_xml(line[i:j])
        parts.append(f"{open_tags}{chunk}{close_tags}")
        i = j

    xml = "".join(parts)
    return Paragraph(xml, style)


def _build_code_flowable(line: str, pos: int, attr_index: Dict[int, Dict[str, Any]]) -> Preformatted:
    """Build a Preformatted flowable for code lines."""
    escaped = _escape_xml(line)
    style = ParagraphStyle(
        "CodeInline",
        fontName="Courier",
        fontSize=10,
        leading=13,
    )
    return Preformatted(escaped, style)


def _image_path(img_id: str) -> str:
    for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        p = IMAGE_DIR / f"{img_id}{ext}"
        if p.exists():
            return str(p.resolve())
    raise FileNotFoundError(img_id)
