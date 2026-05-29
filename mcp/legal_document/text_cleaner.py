"""
模块描述：法律文书 block text 清洗器。
LLM 在 blocks.text 中常误塞对话场景的 HTML 标签（如 <sup><a> 角标、<final_answer> 包装），
本模块在渲染前把这些标签提取/剥离为纯文本，避免它们以字面量形式出现在 docx 中。

设计原则：
- HTML 标签是格式错位问题，清洗能彻底解决（标签集合可枚举）。
- 元评论是表达问题，清洗会误伤，统一由 prompt 注入与 soft warning 处理，不在本模块。
"""

from __future__ import annotations

import html
import re


# <sup><a href="URL">LABEL</a></sup> → "[LABEL]" + 收集 URL
_SUP_LINK_RE = re.compile(
    r'<\s*sup\s*>\s*<\s*a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)<\s*/\s*a\s*>\s*<\s*/\s*sup\s*>',
    flags=re.IGNORECASE | re.DOTALL,
)

# <sup>LABEL</sup>（不带 a 标签）→ "[LABEL]"
_SUP_PLAIN_RE = re.compile(
    r'<\s*sup\s*>(.*?)<\s*/\s*sup\s*>',
    flags=re.IGNORECASE | re.DOTALL,
)

# 包装标签：剥壳但保留内部内容
_WRAPPER_TAGS = ("final_answer", "response", "answer", "output")

# 思考/分析标签：整段移除，避免把模型内部推理写进 docx
_DROP_CONTENT_TAGS = ("think", "analysis")

# 其余残留的 HTML/XML 标签（含未闭合形式）
_GENERIC_TAG_RE = re.compile(r'<\s*/?\s*[a-zA-Z][^>]*>')


def _strip_wrapper(text: str, tag: str) -> str:
    """剥离 <tag>...</tag> 的包装，保留内部内容。"""
    pair_re = re.compile(
        r'<\s*' + tag + r'\s*[^>]*>(.*?)<\s*/\s*' + tag + r'\s*>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = pair_re.sub(r'\1', text)
    # 残留的孤立开/闭标签
    text = re.sub(
        r'<\s*/?\s*' + tag + r'\s*[^>]*>',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return text


def _drop_tagged_content(text: str, tag: str) -> str:
    """移除 <tag>...</tag> 及其内部内容。"""
    pair_re = re.compile(
        r'<\s*' + tag + r'\s*[^>]*>.*?<\s*/\s*' + tag + r'\s*>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = pair_re.sub('', text)
    text = re.sub(
        r'<\s*/?\s*' + tag + r'\s*[^>]*>',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return text


def clean_block_text(text: str) -> tuple[str, list[dict]]:
    """清洗 block.text 中的 HTML 残留，返回 (纯文本, 提取的引用列表)。

    引用列表元素：{"label": "1", "url": "https://..."}
      - label：角标内部的文字（法律角标如 "1"，联网角标如 "网1"）
      - url：仅当 <sup><a href="..."> 才有

    清洗顺序：
    1. HTML 实体解码，便于识别被转义的标签
    2. <think>/<analysis> 整段移除，避免推理内容进入文书
    3. <sup><a href=URL>N</a></sup> → "[N]"，URL 收集到 refs
    4. <sup>N</sup>（无 a） → "[N]"，无 URL
    5. <final_answer>/<response>/<answer>/<output> 整体剥包装，保留内容
    6. 其他残留 HTML 标签：直接删除
    7. 段内连续空白折叠、行末空白清理
    """
    if text is None:
        return "", []
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return "", []

    text = html.unescape(text)

    for tag in _DROP_CONTENT_TAGS:
        text = _drop_tagged_content(text, tag)

    refs: list[dict] = []

    def _sup_link_sub(match: re.Match) -> str:
        url = match.group(1).strip()
        label = _GENERIC_TAG_RE.sub('', match.group(2)).strip() or '?'
        refs.append({"label": label, "url": url})
        return f"[{label}]"

    text = _SUP_LINK_RE.sub(_sup_link_sub, text)

    def _sup_plain_sub(match: re.Match) -> str:
        label = _GENERIC_TAG_RE.sub('', match.group(1)).strip() or '?'
        return f"[{label}]"

    text = _SUP_PLAIN_RE.sub(_sup_plain_sub, text)

    for tag in _WRAPPER_TAGS:
        text = _strip_wrapper(text, tag)

    text = _GENERIC_TAG_RE.sub('', text)

    cleaned_lines = []
    for line in text.split('\n'):
        line = re.sub(r'[ \t]+', ' ', line).rstrip()
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines).strip()

    return text, refs


def merge_refs(existing: list[dict], new_refs: list[dict]) -> list[dict]:
    """跨 block 聚合 refs：按 url 去重，保留首次出现的 label。"""
    seen = {r["url"] for r in existing}
    merged = list(existing)
    for r in new_refs:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        merged.append(r)
    return merged


# ---------------------------------------------------------------------------
# 自测试代码：python -m mcp.legal_document.text_cleaner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys

    _PASS = 0
    _FAIL = 0

    def _check(desc: str, cond: bool, detail: str = ""):
        global _PASS, _FAIL
        if cond:
            _PASS += 1
            print("  [PASS] {}".format(desc))
        else:
            _FAIL += 1
            print("  [FAIL] {}  --  {}".format(desc, detail))

    print("=" * 60)
    print("block text 清洗器 — 自测试")
    print("=" * 60)

    # [1] sup + a 角标
    print("\n[1] <sup><a href=URL>N</a></sup>")
    t, r = clean_block_text('根据《民法典》第六百七十五条<sup><a href="https://example.com/law/675">1</a></sup>之规定...')
    _check("角标转为 [1]", t == "根据《民法典》第六百七十五条[1]之规定...", t)
    _check("URL 入 refs", r == [{"label": "1", "url": "https://example.com/law/675"}], str(r))

    # [2] 联网角标
    print("\n[2] 联网角标 <sup><a href=URL>网1</a></sup>")
    t, r = clean_block_text('据报道<sup><a href="https://news.example.com/a">网1</a></sup>...')
    _check("联网角标转为 [网1]", t == "据报道[网1]...", t)
    _check("联网 URL 入 refs", r[0]["label"] == "网1" and r[0]["url"] == "https://news.example.com/a", str(r))

    # [3] 连续多个角标
    print("\n[3] 连续多角标")
    t, r = clean_block_text(
        '《民法典》第一条<sup><a href="https://u1">1</a></sup>'
        '与《民法典》第二条<sup><a href="https://u2">2</a></sup>'
    )
    _check("两个角标都转换", "[1]" in t and "[2]" in t, t)
    _check("两个 URL 都入 refs", len(r) == 2, str(r))

    # [4] 无 a 标签的纯 sup
    print("\n[4] 纯 <sup>1</sup>")
    t, r = clean_block_text("脚注<sup>1</sup>说明")
    _check("纯 sup 转换", t == "脚注[1]说明", t)
    _check("纯 sup 不入 refs", r == [], str(r))

    # [5] <final_answer> 嵌入
    print("\n[5] <final_answer> 整段嵌入")
    t, r = clean_block_text("<final_answer>请求判令被告偿还借款本金</final_answer>")
    _check("剥 final_answer 包装", t == "请求判令被告偿还借款本金", t)

    # [6] <think> 整段
    print("\n[6] <think>...</think>")
    t, r = clean_block_text("<think>这里是我的思考</think>正文内容")
    _check("移除 think 内容", t == "正文内容", t)

    # [7] 其他 HTML 标签
    print("\n[7] 其他 HTML 标签 (b/i/span)")
    t, r = clean_block_text("<b>重点</b>请求<i>事项</i><span>说明</span>")
    _check("剥所有 HTML 标签", t == "重点请求事项说明", t)

    # [8] HTML 实体
    print("\n[8] HTML 实体")
    t, r = clean_block_text("金额 &lt; 200,000 元 &amp; 利息 &gt; 0")
    _check("解码 HTML 实体", t == "金额 < 200,000 元 & 利息 > 0", t)
    t, r = clean_block_text("空格&nbsp;之后")
    _check("解码 nbsp", " " in t or " " in t, t)

    # [9] 复合污染
    print("\n[9] 复合：角标 + final_answer + 元评论")
    t, r = clean_block_text(
        '<final_answer>根据《民法典》第六百七十五条<sup><a href="https://u">1</a></sup>，'
        '请求判令被告偿还本金。我这样写是因为体现了请求的具体性。</final_answer>'
    )
    _check("final_answer 已剥", "<final_answer>" not in t, t)
    _check("角标已转换", "[1]" in t, t)
    _check("元评论保留（不动）", "我这样写是因为" in t, t)
    _check("URL 入 refs", r and r[0]["url"] == "https://u", str(r))

    # [10] 边界
    print("\n[10] 边界")
    t, r = clean_block_text("")
    _check("空字符串", t == "" and r == [], "{!r} / {}".format(t, r))
    t, r = clean_block_text(None)
    _check("None 输入", t == "" and r == [])
    t, r = clean_block_text("<sup></sup>")
    _check("空 sup", t == "[?]", t)
    t, r = clean_block_text("   \n  \n  ")
    _check("纯空白", t == "", "{!r}".format(t))
    t, r = clean_block_text("纯文本无标签")
    _check("纯文本不变", t == "纯文本无标签", t)

    # [11] 段内换行保留
    print("\n[11] 段内换行")
    t, r = clean_block_text("第一行\n第二行\n第三行")
    _check("\\n 保留", t == "第一行\n第二行\n第三行", repr(t))

    # [12] 连续空白折叠
    print("\n[12] 连续空白折叠")
    t, r = clean_block_text("多      个     空格")
    _check("空格折叠", t == "多 个 空格", repr(t))
    t, r = clean_block_text("行末空格   \n下一行")
    _check("行末空格清理", t == "行末空格\n下一行", repr(t))

    # [13] merge_refs 去重
    print("\n[13] merge_refs")
    merged = merge_refs(
        [{"label": "1", "url": "https://a"}],
        [{"label": "2", "url": "https://a"}, {"label": "3", "url": "https://b"}],
    )
    _check("按 URL 去重", len(merged) == 2, str(merged))
    _check("保留首次 label", merged[0]["label"] == "1", str(merged))
    _check("新 URL 入列", merged[1]["url"] == "https://b", str(merged))

    # [14] 大小写与空白宽容
    print("\n[14] 大小写与空白宽容")
    t, r = clean_block_text('<SUP><A HREF="https://x">1</A></SUP>')
    _check("大写 SUP/A 也识别", t == "[1]" and r == [{"label": "1", "url": "https://x"}], "{} / {}".format(t, r))
    t, r = clean_block_text('< sup >< a href = "https://x" > 1 </ a >< / sup >')
    _check("标签内空白宽容", t == "[1]" and r and r[0]["url"] == "https://x", "{} / {}".format(t, r))

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print("结果: {}/{} 通过".format(_PASS, total), end="")
    if _FAIL > 0:
        print(", {} 失败".format(_FAIL))
        _sys.exit(1)
    else:
        print(" — 全部通过")
    print("=" * 60)
