"""
模块描述：法律文书排版常量与样式应用。
中文法律文书通用规范：宋体/仿宋/黑体、A4 页边距、首行缩进 2 字符、1.5 倍行距。
"""

from __future__ import annotations

from docx.document import Document as _Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


FONT_HEITI = "黑体"
FONT_SONGTI = "宋体"
FONT_FANGSONG = "仿宋_GB2312"
FONT_FANGSONG_FALLBACK = "仿宋"


def _set_run_font(run, font_name: str, size_pt: float, bold: bool = False) -> None:
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)


def configure_page(doc: _Document) -> None:
    """A4 + 上下 2.54cm / 左右 3.17cm，标准 Word 默认。"""
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)


def apply_title_style(paragraph) -> None:
    """文书主标题：黑体二号、居中、段后 1 行。"""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(18)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    for run in paragraph.runs:
        _set_run_font(run, FONT_HEITI, 22, bold=True)


def apply_heading_style(paragraph, level: int) -> None:
    """章节标题：黑体三号(L1)/小三(L2)/四号(L3)、左对齐、段前后留白。"""
    size_map = {1: 16, 2: 15, 3: 14}
    size = size_map.get(level, 14)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = paragraph.paragraph_format
    pf.space_before = Pt(8)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.5
    for run in paragraph.runs:
        _set_run_font(run, FONT_HEITI, size, bold=True)


def apply_body_style(paragraph, indent: bool = True, align: str = "justify") -> None:
    """正文：仿宋小三号、首行缩进 2 字符、1.5 倍行距。"""
    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    paragraph.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.JUSTIFY)
    pf = paragraph.paragraph_format
    pf.line_spacing = 1.5
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    if indent:
        pf.first_line_indent = Pt(15) * 2
    else:
        pf.first_line_indent = Pt(0)
    for run in paragraph.runs:
        _set_run_font(run, FONT_FANGSONG, 15, bold=False)


def apply_signature_style(paragraph) -> None:
    """落款行：仿宋小三、右对齐、无缩进、段前 1 行。"""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pf = paragraph.paragraph_format
    pf.line_spacing = 1.5
    pf.first_line_indent = Pt(0)
    pf.space_before = Pt(12)
    pf.space_after = Pt(0)
    for run in paragraph.runs:
        _set_run_font(run, FONT_FANGSONG, 15, bold=False)


def apply_table_cell_style(cell, header: bool = False) -> None:
    """表格单元格：仿宋五号、单倍行距、垂直居中。"""
    for paragraph in cell.paragraphs:
        pf = paragraph.paragraph_format
        pf.line_spacing = 1.15
        pf.first_line_indent = Pt(0)
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in paragraph.runs:
            _set_run_font(run, FONT_FANGSONG, 10.5, bold=header)
