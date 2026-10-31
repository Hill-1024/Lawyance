"""会话导出为 Word：正式消息抽取 + Markdown 结构化转换 + python-docx 排版。

路由只做认证、取数与状态判定；这里负责消息整理、版式与 DOCX 生成。
Markdown 不做正则剥除，统一走 markdown-it-py（CommonMark + GFM 表格/删除线）
的 token 流逐块转换；模型正文里的原生 HTML（联网引用的 <sup><a> 角标等）
经白名单状态机转成可见编号和安全链接，标签本身不进正文，也不执行任何 HTML。
"""

from __future__ import annotations

import html as html_module
import io
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from fastapi import HTTPException

# 资源上限：超限明确报错，绝不静默截断（与文档导出的 MAX_TEXT 同量级）。
MAX_EXPORT_MESSAGES = 2000
MAX_EXPORT_CHARS = 2_000_000

FORMAL_ROLES = ("user", "assistant")
ROLE_LABELS = {"user": "用户", "assistant": "Lawver 助手"}

_PARSER = None

# XML 1.0 permits tabs/newlines/CR, but not the other C0 controls, surrogate
# code points or U+FFFE/U+FFFF. Keep word boundaries when replacing bad input.
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _xml_text(text):
    return _INVALID_XML.sub(" ", text)


def _parser():
    global _PARSER
    if _PARSER is None:
        from markdown_it import MarkdownIt

        # commonmark 规范 + GFM 表格与删除线；不需要 linkify（显式链接已覆盖）。
        _PARSER = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    return _PARSER


def formal_messages(messages):
    """抽取正式消息：只要 user/assistant 且 content 为非空字符串。

    会话里的其他内容（system/developer、trace 内部历史、工具参数与原始输出）
    一概不进文档；正文普通文字原样保留，不做任何关键词删改。
    """
    picked = []
    total = 0
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if (
            message.get("role") not in FORMAL_ROLES
            or not isinstance(content, str)
            or not content.strip()
        ):
            continue
        picked.append(
            {
                "role": message["role"],
                "content": content,
                "created_at": message.get("created_at"),
            }
        )
        total += len(content)
    if len(picked) > MAX_EXPORT_MESSAGES or total > MAX_EXPORT_CHARS:
        raise HTTPException(422, {"code": "export_too_large", "message": "会话内容过多，暂不支持导出"})
    return picked


def safe_filename(title):
    """会话标题 → 安全文件名主干：去路径/控制字符，防响应头注入与跨目录。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f\r\n]', "_", (title or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:80] or "会话导出"


def _safe_url(url):
    """只有 http/https 能成为超链接；其余协议（javascript: 等）按纯文本渲染。"""
    if not isinstance(url, str):
        return None
    if _INVALID_XML.search(url) or any(ord(char) < 32 for char in url):
        return None
    value = url.strip()
    return value if value.lower().startswith(("http://", "https://")) else None


# ─── HTML 白名单状态机 ─────────────────────────────────────────────────────
# html_inline 每个 token 恰好一个标签（CommonMark 分词规则）；用正则识别开/闭
# 标签并维护效果栈，只放行排版语义（上下标/链接/换行/强调/图片替代文字）。
# 未知名标签丢弃但保留其内部文本，script/style 的内容整体丢弃。

_CLOSE_TAG = re.compile(r"^</\s*([a-zA-Z][a-zA-Z0-9:-]*)\s*>$")
_OPEN_TAG = re.compile(r"^<\s*([a-zA-Z][a-zA-Z0-9:-]*)[^<>]*?(\s*/)?\s*>$")
_ATTR = re.compile(
    r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
)

# 标签 → 效果键：闭合标签按栈回退。
_TAG_EFFECTS = {
    "b": "bold",
    "strong": "bold",
    "i": "italic",
    "em": "italic",
    "u": "underline",
    "s": "strike",
    "del": "strike",
    "strike": "strike",
    "sup": "sup",
    "sub": "sub",
    "a": "link",
}


def _parse_tag(token_content):
    """单个 html_inline token → ("open", tag, attrs) / ("close", tag) / None。"""
    text = token_content.strip()
    closed = _CLOSE_TAG.match(text)
    if closed:
        return ("close", closed.group(1).lower())
    opened = _OPEN_TAG.match(text)
    if not opened:
        return None  # 注释 / DOCTYPE / 无法识别的片段：丢弃
    tag = opened.group(1).lower()
    attrs = {}
    for match in _ATTR.finditer(text):
        value = next((g for g in match.groups()[1:] if g is not None), "")
        attrs[match.group(1).lower()] = html_module.unescape(value)
    return ("open", tag, attrs)


class _HTMLBlockParser(HTMLParser):
    """html_block → 与 html_inline 同一事件流（script/style 内容整体丢弃）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if not self._skip:
            self.events.append(("open", tag, {k: v or "" for k, v in attrs}))

    def handle_startendtag(self, tag, attrs):
        if tag in ("script", "style") or self._skip:
            return
        self.events.append(("open", tag, {k: v or "" for k, v in attrs}))
        self.events.append(("close", tag))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if not self._skip:
            self.events.append(("close", tag))

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.events.append(("text", data.strip()))


# ─── DOCX 小工具 ───────────────────────────────────────────────────────────


def _hyperlink(paragraph, text, url, *, sup=False, sub=False, bold=False, italic=False):
    """python-docx 没有超链接 API：手工挂 w:hyperlink 关系并按链接样式着色。

    rPr 子元素按 schema 顺序排列（b, i, color, sz, u, vertAlign）。
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    if bold:
        props.append(OxmlElement("w:b"))
    if italic:
        props.append(OxmlElement("w:i"))
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    props.append(color)
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "22")  # 11pt，与正文一致
    props.append(size)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(underline)
    if sup or sub:
        vert = OxmlElement("w:vertAlign")
        vert.set(qn("w:val"), "superscript" if sup else "subscript")
        props.append(vert)
    run.append(props)
    text_node = OxmlElement("w:t")
    text_node.set(qn("xml:space"), "preserve")
    text_node.text = _xml_text(text)
    run.append(text_node)
    link.append(run)
    paragraph._p.append(link)


def _shade_paragraph(paragraph, fill):
    """按 OOXML 顺序插入底纹，必须在 spacing / ind 之前。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shade = OxmlElement("w:shd")
    shade.set(qn("w:val"), "clear")
    shade.set(qn("w:fill"), fill)
    paragraph._p.get_or_add_pPr().insert_element_before(
        shade, "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
        "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
        "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
        "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
        "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
        "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
    )


def _bottom_rule(paragraph):
    """水平分割线：空段落加下边框，比一行破折号更像正文分隔。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "BFBFBF")
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().insert_element_before(
        borders, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr", "w:sectPr",
    )


def _full_width_table(table):
    """表宽 = 版心宽度（pct 5000）：Word 自动折行，长表不超页。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    for existing in tbl_pr.findall(qn("w:tblW")):
        tbl_pr.remove(existing)
    width = OxmlElement("w:tblW")
    width.set(qn("w:w"), "5000")
    width.set(qn("w:type"), "pct")
    tbl_pr.append(width)


def _east_asia(style, name):
    from docx.oxml.ns import qn

    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def _run_font(run, latin, east):
    from docx.oxml.ns import qn

    run.font.name = latin
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), east)


# ─── 转换器主体 ────────────────────────────────────────────────────────────


class _DocxBuilder:
    """markdown-it token 流 → python-docx 文档。一个实例负责一条消息。"""

    BULLET_STYLES = ("List Bullet", "List Bullet 2", "List Bullet 3")

    def __init__(self, doc):
        self.doc = doc

    # -- 行内渲染 ----------------------------------------------------------

    def _run(
        self,
        paragraph,
        text,
        *,
        bold=False,
        italic=False,
        strike=False,
        underline=False,
        code=False,
        url=None,
        sup=False,
        sub=False,
        gray=False,
    ):
        if not text:
            return
        if url:
            _hyperlink(paragraph, text, url, sup=sup, sub=sub, bold=bold, italic=italic)
            return
        run = paragraph.add_run(_xml_text(text))
        if bold:
            run.bold = True
        if italic:
            run.italic = True
        if underline:
            run.underline = True
        if strike:
            run.font.strike = True
        if sup:
            run.font.superscript = True
        if sub:
            run.font.subscript = True
        if code:
            _run_font(run, "Consolas", "宋体")
        if gray:
            from docx.shared import RGBColor

            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    @staticmethod
    def _stack_has(state, key):
        return any(key in layer for layer in state)

    @staticmethod
    def _stack_url(state, fallback=None):
        for layer in reversed(state):
            if "url" in layer:
                return layer["url"]
        return fallback

    def _html_event(self, paragraph, state, kind, tag=None, attrs=None):
        """处理一个 HTML 事件：维护效果栈并输出换行/图片替代文字。"""
        if kind == "open":
            if tag == "br":
                paragraph.add_run().add_break()
                return
            if tag == "img":
                alt = (attrs or {}).get("alt") or ""
                self._run(paragraph, f"〔图片{'：' + alt if alt else ''}〕", gray=True)
                return
            key = _TAG_EFFECTS.get(tag)
            if key:
                delta = {key: True}
                if key == "link":
                    # 不安全协议的 <a> 不产生链接，仅保留文字。
                    delta["url"] = _safe_url((attrs or {}).get("href"))
                state.append(delta)
            return
        # close：只回退最近一个同名效果层，允许标签轻微不配对。
        key = _TAG_EFFECTS.get(tag)
        if key:
            for index in range(len(state) - 1, -1, -1):
                if key in state[index]:
                    state.pop(index)
                    return

    def render_inline(self, paragraph, tokens):
        """行内 token 流 → 段落。HTML 效果与 Markdown 标记可叠加。"""
        state = []  # HTML 效果栈：[{bold: True}, {link: True, url: ...}, ...]
        marks = {"bold": 0, "italic": 0, "strike": 0}
        markdown_url = None

        def emit(text, *, code=False):
            self._run(
                paragraph,
                text,
                bold=self._stack_has(state, "bold") or marks["bold"] > 0,
                italic=self._stack_has(state, "italic") or marks["italic"] > 0,
                strike=self._stack_has(state, "strike") or marks["strike"] > 0,
                underline=self._stack_has(state, "underline"),
                code=code,
                url=self._stack_url(state, markdown_url),
                sup=self._stack_has(state, "sup"),
                sub=self._stack_has(state, "sub"),
            )

        toggles = {
            "strong_open": "bold",
            "strong_close": "bold",
            "em_open": "italic",
            "em_close": "italic",
            "s_open": "strike",
            "s_close": "strike",
        }
        for token in tokens or []:
            kind = token.type
            if kind == "text":
                emit(token.content)
            elif kind == "code_inline":
                emit(token.content, code=True)
            elif kind in toggles:
                key = toggles[kind]
                marks[key] = max(0, marks[key] + (1 if kind.endswith("open") else -1))
            elif kind == "link_open":
                target = _safe_url(token.attrGet("href"))
                if target is not None:
                    markdown_url = target
            elif kind == "link_close":
                markdown_url = None
            elif kind == "hardbreak":
                paragraph.add_run().add_break()
            elif kind == "softbreak":
                emit(" ")  # 与工作台网页渲染一致：软换行折叠为空格
            elif kind == "image":
                alt = token.attrGet("alt") or token.content or ""
                self._run(paragraph, f"〔图片{'：' + alt if alt else ''}〕", gray=True)
            elif kind == "html_inline":
                parsed = _parse_tag(token.content)
                if parsed:
                    self._html_event(paragraph, state, *parsed)

    def _render_events(self, paragraph, events):
        """HTML 事件流 → 段落（html_block 用；与 html_inline 共享效果栈逻辑）。"""
        state = []
        for event in events:
            if event[0] == "text":
                self._run(
                    paragraph,
                    event[1],
                    bold=self._stack_has(state, "bold"),
                    italic=self._stack_has(state, "italic"),
                    strike=self._stack_has(state, "strike"),
                    underline=self._stack_has(state, "underline"),
                    sup=self._stack_has(state, "sup"),
                    sub=self._stack_has(state, "sub"),
                    url=self._stack_url(state),
                )
            else:
                self._html_event(paragraph, state, *event)

    # -- 块级渲染 ----------------------------------------------------------

    def _paragraph(self, *, quote=False):
        paragraph = self.doc.add_paragraph(style="Quote" if quote else None)
        return paragraph

    def _list_paragraph(self, list_stack, in_quote):
        """列表项段落：引用块内退化为带前缀的引用段落（引用样式挂不了项目符号）。"""
        from docx.shared import Cm

        depth = max(0, len(list_stack) - 1)
        innermost = list_stack[-1]
        if in_quote:
            paragraph = self._paragraph(quote=True)
            if innermost["ordered"]:
                innermost["counter"] += 1
                self._run(paragraph, f"{innermost['counter']}. ")
            else:
                self._run(paragraph, "• ")
            return paragraph
        if innermost["ordered"]:
            # 有序号用文本前缀：Word 内置编号跨列表不复位，文本前缀每张表都从 1 开始。
            innermost["counter"] += 1
            paragraph = self._paragraph()
            paragraph.paragraph_format.left_indent = Cm(0.63 * (depth + 1))
            self._run(paragraph, f"{innermost['counter']}. ")
            return paragraph
        style = self.BULLET_STYLES[min(depth, len(self.BULLET_STYLES) - 1)]
        return self.doc.add_paragraph(style=style)

    def _code_block(self, info, content):
        from docx.shared import Cm, Pt

        label = (info or "").strip().split()[0].lower() if info and info.strip() else ""
        if label == "mermaid":
            self._run(self._paragraph(), "〔Mermaid 图表源码，未渲染〕", gray=True)
        elif label in ("math", "latex", "tex", "katex"):
            self._run(self._paragraph(), "〔公式源码，未渲染〕", gray=True)
        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(0.3)
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(2)
        _shade_paragraph(paragraph, "F2F2F2")
        run = paragraph.add_run()
        _run_font(run, "Consolas", "宋体")
        run.font.size = Pt(9.5)
        lines = content.rstrip("\n").split("\n")
        for index, line in enumerate(lines):
            if index:
                run.add_break()
            run.add_text(_xml_text(line) if line else " ")

    def _table(self, rows):
        """rows: [[([inline tokens], align), ...]]；首行为表头。"""
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt

        if not rows:
            return
        columns = max(len(row) for row in rows)
        table = self.doc.add_table(rows=len(rows), cols=columns)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _full_width_table(table)
        for r, row in enumerate(rows):
            for c in range(columns):
                cell = table.cell(r, c)
                paragraph = cell.paragraphs[0]
                if c < len(row):
                    tokens, align = row[c]
                    if align == "center":
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif align == "right":
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    self.render_inline(paragraph, tokens)
                    for run in paragraph.runs:
                        run.font.size = Pt(10.5)
                        if r == 0:
                            run.bold = True
                if r == 0:
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:val"), "clear")
                    shade.set(qn("w:fill"), "E7EEF7")
                    cell._tc.get_or_add_tcPr().append(shade)
        # 表格后留一个窄段落：连续两张表不会粘连成一个。
        tail = self.doc.add_paragraph()
        tail.paragraph_format.space_after = Pt(2)

    def render_markdown(self, text):
        """一条消息的 Markdown → 文档块。"""
        tokens = _parser().parse(text)
        list_stack = []  # [{ordered, counter}]，嵌套列表各占一层
        quote_depth = 0
        item_paragraphs = []  # one flag per open list_item, including parent items
        table_rows = []
        in_cell = None  # ([children], align)：单元格内容暂存，闭合时归行
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if kind == "table_open":
                table_rows = []
            elif kind == "tr_open":
                table_rows.append([])
            elif kind in ("th_open", "td_open"):
                style = token.attrGet("style") or ""
                align = "center" if "center" in style else "right" if "right" in style else None
                in_cell = ([], align)
            elif kind in ("th_close", "td_close"):
                if in_cell:
                    table_rows[-1].append(in_cell)
                    in_cell = None
            elif kind == "table_close":
                self._table([row for row in table_rows if row])
                table_rows = []
            elif kind == "inline":
                if in_cell is not None:
                    in_cell[0].extend(token.children or [])
                elif list_stack and item_paragraphs and not item_paragraphs[-1]:
                    paragraph = self._list_paragraph(list_stack, quote_depth > 0)
                    self.render_inline(paragraph, token.children)
                    item_paragraphs[-1] = True
                else:
                    paragraph = self._paragraph(quote=quote_depth > 0)
                    self.render_inline(paragraph, token.children)
            elif kind in ("bullet_list_open", "ordered_list_open"):
                list_stack.append(
                    {
                        "ordered": kind == "ordered_list_open",
                        "counter": int(token.attrGet("start") or 1) - 1,
                    }
                )
            elif kind in ("bullet_list_close", "ordered_list_close"):
                list_stack.pop()
            elif kind == "list_item_open":
                item_paragraphs.append(False)
            elif kind == "list_item_close":
                item_paragraphs.pop()
            elif kind == "blockquote_open":
                quote_depth += 1
            elif kind == "blockquote_close":
                quote_depth = max(0, quote_depth - 1)
            elif kind == "heading_open":
                # 内容标题让出 Heading 1（角色标题用）：h1→Heading 2，其余顺延、封顶 5。
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    level = min(5, max(2, int(token.tag[1]) + 1))
                    paragraph = self.doc.add_heading("", level=level)
                    self.render_inline(paragraph, tokens[i + 1].children)
                    i += 1  # inline 已在标题内消费，跳过下一轮
            elif kind in ("fence", "code_block"):
                self._code_block(token.info, token.content)
            elif kind == "hr":
                _bottom_rule(self.doc.add_paragraph())
            elif kind == "html_block":
                parser = _HTMLBlockParser()
                parser.feed(token.content)
                paragraph = self._paragraph(quote=quote_depth > 0)
                self._render_events(paragraph, parser.events)
            i += 1


# ─── 文档组装 ──────────────────────────────────────────────────────────────


def _configure_document(doc):
    """A4、页边距与中文字体；只引用系统字体名，不打包字体文件。"""
    from docx.shared import Cm, Pt, RGBColor

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.54)
    section.left_margin = section.right_margin = Cm(2.54)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    _east_asia(normal, "宋体")
    # 默认模板的标题样式是蓝色大字，长会话导出里过于醒目：收紧字号、改黑体系。
    for name, size in (
        ("Heading 1", 12.5),
        ("Heading 2", 12),
        ("Heading 3", 11),
        ("Heading 4", 11),
        ("Heading 5", 11),
    ):
        style = doc.styles[name]
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0x21, 0x21, 0x21)
        _east_asia(style, "黑体")


def _local_time_text(value):
    """消息时间（UTC ISO）→ 本地时区可读文本；解析失败返回 None。"""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def build_conversation_docx(title, messages):
    """正式消息列表 → DOCX 字节流（内存生成，不落盘）。"""
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    _configure_document(doc)

    _east_asia(doc.add_heading(_xml_text(title or "会话导出").strip() or "会话导出", level=0).style, "黑体")

    local = datetime.now().astimezone()
    offset = local.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rem = divmod(abs(minutes), 60)
    meta = doc.add_paragraph()
    run = meta.add_run(
        f"导出时间：{local.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（UTC{sign}{hours:02d}:{rem:02d}，{local.tzname() or '本地时间'}）"
    )
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    builder = _DocxBuilder(doc)
    for message in messages:
        label = ROLE_LABELS.get(message["role"], message["role"])
        header = doc.add_heading("", level=1)
        created = _local_time_text(message.get("created_at"))
        if created:
            header.add_run(f"{label} · ")
            when = header.add_run(created)
            when.font.size = Pt(9)
            when.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            when.bold = False
        else:
            header.add_run(label)
        builder.render_markdown(message["content"])

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
