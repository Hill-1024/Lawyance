"""
output_sanitizer.py — 统一输出清洗模块

所有 Agent（Default / ReAct / PlanAndSolve）和 OCP 共同使用此模块，
确保 LLM 原始输出经过一致的清洗后再交给用户。

主要职责：
1. 提取 <final_answer> 标签内容（soft enforcement）
2. 移除 <think> 块及推理过程
3. 清除 AI 身份声明和废话前缀/后缀
4. 清除残留的内部标签和 prompt 泄漏
"""

import re

# ── 提取 <final_answer> ─────────────────────────────────────────────────

_FA_TAG_PAIRS = [
    (r'<\s*final_answer\s*>', r'<\s*/\s*final_answer\s*>'),
    (r'&lt;\s*final_answer\s*&gt;', r'&lt;\s*/\s*final_answer\s*&gt;'),
]


def extract_final_answer(text: str) -> str | None:
    """
    从 LLM 原始输出中提取 <final_answer>…</final_answer> 的内容。
    如果存在多组，取最后一组闭合的配对。
    如果只有开标签没有闭标签，取开标签之后的全部内容。
    返回 None 表示文本中不包含 final_answer 标签。
    """
    if not text:
        return None

    for open_pattern, close_pattern in _FA_TAG_PAIRS:
        close_matches = list(re.finditer(close_pattern, text, flags=re.IGNORECASE))
        if close_matches:
            close_match = close_matches[-1]
            open_matches = list(re.finditer(open_pattern, text[:close_match.start()], flags=re.IGNORECASE))
            if open_matches:
                open_match = open_matches[-1]
                candidate = text[open_match.end():close_match.start()]
                if candidate.strip():
                    return candidate.strip()

    # 未闭合的 <final_answer>：取开标签后的全部内容
    for open_pattern, _ in _FA_TAG_PAIRS:
        unclosed = re.search(
            r'.*' + open_pattern + r'(.*)$',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if unclosed and unclosed.group(1).strip():
            return unclosed.group(1).strip()

    return None


# ── 移除 <think> 块 ─────────────────────────────────────────────────────

def strip_think_blocks(text: str) -> str:
    """移除 <think>…</think> 块及其内部内容，包括未闭合的 <think>"""
    if not text:
        return ""

    # 1. 移除已闭合的 <think> 块
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 2. 未闭合的 <think>：截断其后所有内容
    if re.search(r'<think>(?!.*?</think>)', text, flags=re.IGNORECASE | re.DOTALL):
        text = re.sub(r'<think>.*$', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 3. 清除残留的标签碎片
    text = re.sub(r'</?think[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    return text


# ── 清除标签壳 ───────────────────────────────────────────────────────────

def strip_wrapper_tags(text: str) -> str:
    """移除 <final_answer>, <think>, <response> 等包装标签本身（保留内部内容）"""
    text = re.sub(r'</?final_answer[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<\|.*?\|>', '', text, flags=re.IGNORECASE | re.DOTALL)
    return text


# ── AI 身份声明检测 ──────────────────────────────────────────────────────

_IDENTITY_KEYWORDS = [
    "作为AI助手", "作为一个AI", "作为人工智能",
    "我无法完成", "我的职责是", "抱歉，作为",
    "AI模型", "我是一个语言模型", "我是AI",
]


def detect_identity_leak(text: str) -> bool:
    """检测输出是否包含 AI 身份泄漏声明"""
    return any(kw in text for kw in _IDENTITY_KEYWORDS)


# ── 废话前缀/后缀清除 ────────────────────────────────────────────────────

_LEADING_NOISE_PATTERNS = [
    r'^好的，.*?[：:]', r'^好的。.*?[：:]', r'^以下是.*?[：:]',
    r'^修复后的文本如下[：:]', r'^根据您的要求，.*?',
    r'^我已经为您.*?。', r'^审查结果[：:]', r'^Assistant:',
    r'^修正方案[：:]', r'^这里是修复后的内容[：:]',
]

_WRAPPER_LINE_PATTERNS = [
    r'^(以下|下面|这是|现将|现把).{0,30}(修改后|修复后|调整后|审查后).{0,20}(正文|文本|内容|版本|结果)(如下)?[:：]?$',
    r'^(修改后|修复后|调整后|审查后).{0,20}(正文|文本|内容|版本|结果)(如下)?[:：]?$',
    r'^(以下|下面)是.{0,30}(正文|文本|内容|版本|结果)[:：]?$',
    r'^已根据.{0,30}(修正|修改|调整)[:：]?$',
    r'^审查结果如下[:：]?$',
    r'^最终版本如下[:：]?$',
    r'^文本内容.{0,80}(无需修复|原样输出).*$',
    r'^\[?OCP\]?.{0,60}(正在|审查|检查|修复|完成|超时|异常).*$',
    r'^OCP\s*.{0,80}$',
    r'^正在调用工具处理中.*$',
    r'^执行：\s*`?(get_linked_content|search_article|get_article|pdf_text_reader|word_reader)[^`]*`?.*$',
    r'^工具执行完毕.*$',
]

_TRAILING_NOISE_PATTERNS = [
    r'^(以上|上述)为.{0,30}(正文|文本|内容|结果)[:：]?$',
    r'^如需进一步.*$',
]


def strip_noise(text: str) -> str:
    """清除 LLM 输出中的废话前缀、引导句和尾部噪声"""
    if not text:
        return ""

    # 1. 逐行移除前导噪声
    for pattern in _LEADING_NOISE_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE).strip()

    # 2. 按行处理前缀/后缀包装句
    lines = text.splitlines()

    # 移除前导空行和包装句
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and any(re.match(p, lines[0].strip(), flags=re.IGNORECASE) for p in _WRAPPER_LINE_PATTERNS):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    # 移除尾部噪声
    while lines and any(re.match(p, lines[-1].strip(), flags=re.IGNORECASE) for p in _TRAILING_NOISE_PATTERNS):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()

    return "\n".join(lines).strip()


# ── 主清洗管道 ───────────────────────────────────────────────────────────

def sanitize_llm_output(raw_text: str, *, enforce_final_answer: bool = True) -> str:
    """
    完整的 LLM 输出清洗管道。

    Args:
        raw_text: LLM 的原始输出文本
        enforce_final_answer: 是否尝试提取 <final_answer> 内容。
            True = 先尝试提取 <final_answer>，fallback 为全文清洗
            False = 跳过 <final_answer> 提取，直接清洗全文（用于 OCP 等场景）

    Returns:
        清洗后的纯净文本
    """
    if not raw_text or not raw_text.strip():
        return raw_text or ""

    text = raw_text

    # Step 1: 如果启用 final_answer 提取，先尝试提取
    if enforce_final_answer:
        extracted = extract_final_answer(text)
        if extracted is not None:
            text = extracted

    # Step 2: 移除 <think> 块
    text = strip_think_blocks(text)

    # Step 3: 移除残留标签壳
    text = strip_wrapper_tags(text)

    # Step 4: 清除废话噪声
    text = strip_noise(text)

    # Step 5: 身份泄漏检测（如果检测到，返回空让上层降级）
    if detect_identity_leak(text):
        return ""

    return text.strip()
