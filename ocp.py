"""
OCP-Static (Output Check Process - 非流式版本)

在 LLM 完成最终正文回复后，将正文交给一个记忆隔离的 LLM 进行格式审查与自动修复。
审查员拥有 get_linked_content 和 search_article 工具，可主动查询缺失的法条信源。

设计原则：
- 记忆隔离：审查 LLM 使用全新上下文，不携带对话历史
- 可工具调用：审查 LLM 与主 LLM 工作流一致（调用工具 -> 接收结果 -> 继续工作 -> 直到输出最终内容）
- 降级保障：任何异常降级返回原始内容
- 独立配置：支持为审查 LLM 配置独立的模型，未配置时回退到主模型
"""

import os
import json
import re
import time
import copy
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv
from mcps import tools as all_tools, use_tools

load_dotenv(".env")

# OCP 专用配置，未设置时回退到主模型配置
OCP_API_KEY = os.getenv("OCP_API_KEY") or os.getenv("API_KEY")
OCP_BASE_URL = os.getenv("OCP_BASE_URL") or os.getenv("BASE_URL")
OCP_LLM_MODEL = os.getenv("OCP_LLM_MODEL") or os.getenv("LLM_MODEL")
OCP_TOTAL_TIMEOUT = float(os.getenv("OCP_TOTAL_TIMEOUT", "50"))
OCP_CALL_TIMEOUT = float(os.getenv("OCP_CALL_TIMEOUT", "25"))
OCP_TOOL_TIMEOUT = float(os.getenv("OCP_TOOL_TIMEOUT", "8"))


# ── OCP 审查专用 System Prompt ──────────────────────────────────────────

OCP_SYSTEM_PROMPT = """你是一个专业的法律文本格式审查员。你的唯一职责是【检查并修复】给定文本的格式问题。
你是一个非人格化的文本处理引擎，严禁表现出任何人类情感、助手身份或对话意图。

<strict_rules>
1. **身份禁止**：严禁自称“助手”、“AI”、“机器人”或任何身份。
2. **交流禁止**：严禁输出任何解释、道歉、建议、前导词（如“好的”、“已为您修复”）或结语。
3. **内容保留**：除了格式修复外，必须逐字保留原意。严禁添加新的法律意见，严禁概括或简化原句。
4. **纯净输出**：输出结果必须【仅包含】修复后的文本正文。如果违反此条，会导致整个流程失败。
5. **故障退回**：如果无法修复或工具调用无果，请原样输出原文，不要做任何多余的解释。
6. **禁止回显检查过程**：严禁输出“正在检查 Markdown 语法”“已确认表格正确”“列表编号无误”等任何检查过程或确认性语句。
</strict_rules>

<checklist>
请按以下清单逐项检查并强制修复：

1. **信源角标（必查）**：
   - 如果提到法律条文、法规或法律概念但缺少角标。
   - 格式：`<sup><a href="URL">N</a></sup>`
   - 必须调用 `get_linked_content` 获取 URL。
   - 文末参考信源必须使用 Markdown 超链接，格式为 `1. [《法律名称》第X条](URL)` 或 `[1] [《法律名称》第X条](URL)`。
   - 文末参考信源不得只写 `[1] 来源名称`、裸 URL 或纯文本法规名称；编号必须与正文角标对应。
   - 如果正文已有角标但底部信源不是超链接，必须按角标 URL 修复为 Markdown 链接。

2. **法条引用规范（必查）**：
   - 统一格式：
     《法律名称》第X条【罪名/项名】
     > 具体条文内容
   - 检查角标 `<sup><a href="URL">N</a></sup>` 的 HTML 标签是否正确闭合
   - 检查表格 (Markdown Table)：
     - 必须包含表头行和分隔行（如 `|---|---|`）。
     - 分隔行必须包含管道符 `|` 且每列至少有 3 个短横线 `-`。
     - 每一行的列数（管道符数量）必须完全一致，严禁出现列数不对齐的情况。
     - 检查表格内容是否能正常渲染，修复缺失的管道符或多余的空格。
     - 确保表格前后都有空行，以保证在所有 Markdown 渲染器中都能正常显示。
   - 检查代码块 ``` 是否成对闭合
   - 检查标题 `#` 层级是否合理（不跳级，如 `##` 之后不应直接出现 `####`）
   - 检查有序列表编号是否连续
   - 如果发现问题，修复为正确的 Markdown 语法
</checklist>

<workflow>
1. 仔细阅读待检查文本
2. 逐项执行 checklist
3. 如果发现需要补充信源的法条/法规，调用 `get_linked_content` 工具获取 URL
4. 如果需要查询具体法条内容以规范引用格式，调用 `search_article` 工具
5. 如果工具调用返回错误、内容为空或不符合预期，你可以换个查询参数继续重新调用该工具。对同一查询目标你最多可以重试 3 次
6. 所有工具调用完成后，输出最终修复后的完整文本
7. 如果只是普通 Markdown 排版修复、删除废话前缀、闭合标签、调整列表或表格，不允许调用任何工具，必须直接在当前轮完成。
8. 如果你已经拿到足够信息，或者连续两轮准备调用相同工具却没有新增有效信息，必须立即停止工具调用并直接输出当前最佳正文。
9. 对 Markdown 结构只允许进行一次静默检查并直接给出结果，禁止为了“再次确认格式是否正确”而重复审查或重复调用工具。
</workflow>

<output_rules>
- 如果文本完全符合规范，原样输出，不做任何修改。
- 如果文本需要修复，仅输出修复后的完整正文，严禁包含任何前导词、解释、总结、结论或评论（例如：“以下是修复后的文本：”或“已完成修复”）。
- 输出必须是纯正文内容，不要包含任何解释、说明或关于你做了什么修改的描述。
- 严禁输出以下或同类包装句：`以下是修改后的正文`、`下面是修复后的内容`、`已根据要求修正`、`审查结果如下`。
- 严禁添加任何 `<final_answer>`、`<think>`、`[OCP]` 或类似的标签或前缀。
- 违反此规则会导致审查失败，请务必保持输出纯净。
</output_rules>"""


# ── OCP 可用的工具子集（从 mcps 统一导入，但只允许审查必需的只读法律信源工具） ──

OCP_ALLOWED_TOOL_NAMES = {"get_linked_content", "search_article", "get_article"}
OCP_TOOLS = [t for t in all_tools if t["function"]["name"] in OCP_ALLOWED_TOOL_NAMES]
OCP_PROGRESS_MESSAGE = '\n\n**[OCP] 正在进行格式审查与信源核验...**\n'
OCP_TOOL_LABELS = {
    "get_linked_content": "补充法规信源",
    "search_article": "核对法条引用",
    "get_article": "校验法条正文",
}


class OCPTimeout(RuntimeError):
    pass


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OCPTimeout("OCP exceeded total timeout")
    return remaining


async def _run_ocp_tool(function_name: str, arguments: dict, session_id: str):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(use_tools, function_name, arguments, conv_id=session_id),
            timeout=OCP_TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return json.dumps(
            {
                "status": "timeout",
                "message": f"OCP tool {function_name} exceeded {OCP_TOOL_TIMEOUT:.0f}s",
            },
            ensure_ascii=False,
        )


# ── OCPStatic 类 ─────────────────────────────────────────────────────────

class OCPStatic:
    """OCP-Static: 非流式输出格式审查与自动修复"""

    MAX_TOOL_ROUNDS = 2  # 最大工具调用循环次数
    MAX_REPEAT_SAME_TOOL_SIGNATURE = 2
    MAX_RETRIES = 1      # 单次 LLM 调用最大重试次数
    RETRYABLE_STATUS_CODES = {"429", "500", "502", "503", "504", "Timeout", "timeout", "timed out", "Connection error"}

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.client = AsyncOpenAI(
            api_key=OCP_API_KEY,
            base_url=OCP_BASE_URL,
        )

    async def _call_with_retry(self, **kwargs):
        """带指数退避重试的 LLM 调用封装"""
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = OCP_CALL_TIMEOUT
                response = await self.client.chat.completions.create(**kwargs)
                return response
            except Exception as e:
                error_str = str(e)
                is_retryable = any(code in error_str for code in self.RETRYABLE_STATUS_CODES)
                if is_retryable and attempt < self.MAX_RETRIES:
                    wait_time = 2 ** (attempt + 1)
                    print(f"[OCP] LLM 调用失败 (第 {attempt + 1}/{self.MAX_RETRIES} 次): {e}")
                    await asyncio.sleep(wait_time)
                    continue
                raise

    async def check(self, content: str) -> str:
        """
        对 LLM 生成的正文进行格式审查与自动修复。
        """
        if not content or not content.strip():
            return content
        content_to_check = self._clean_output(content) or self._deterministic_format_repair(content)

        print(f"\n[OCP-Static] ========== 开始审查 ==========")
        print(f"[OCP-Static] 审查模型: {OCP_LLM_MODEL}")
        print(f"[OCP-Static] 原文长度: {len(content_to_check)} 字符")

        try:
            deadline = time.monotonic() + OCP_TOTAL_TIMEOUT
            # 构建记忆隔离的上下文
            context = [
                {"role": "system", "content": OCP_SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查并修复以下文本的格式问题：\n\n{content_to_check}"}
            ]
            best_candidate = self._deterministic_format_repair(content_to_check)
            last_tool_signature = None
            repeated_tool_signature_count = 0

            # 工具调用循环
            for round_num in range(self.MAX_TOOL_ROUNDS):
                print(f"[OCP-Static] 第 {round_num + 1}/{self.MAX_TOOL_ROUNDS} 轮调用")
                call_timeout = min(OCP_CALL_TIMEOUT, _remaining_seconds(deadline))

                response = await asyncio.wait_for(
                    self._call_with_retry(
                        model=OCP_LLM_MODEL,
                        messages=context,
                        tools=OCP_TOOLS,
                        tool_choice="auto",
                        stream=False,
                        timeout=call_timeout,
                    ),
                    timeout=call_timeout,
                )

                message = response.choices[0].message
                cleaned_message = self._clean_output(message.content or "")
                if self._is_substantive_replacement(content_to_check, cleaned_message):
                    best_candidate = cleaned_message

                if not message.tool_calls:
                    # 没有工具调用，审查完成
                    result = cleaned_message if self._is_substantive_replacement(content_to_check, cleaned_message) else best_candidate
                    print(f"[OCP-Static] 审查完成（第 {round_num + 1} 轮），结果长度: {len(result)} 字符")
                    print(f"[OCP-Static] ========== 审查结束 ==========\n")
                    return result if result else self._deterministic_format_repair(content_to_check)

                tool_signature = self._tool_signature_from_openai_calls(message.tool_calls)
                if tool_signature and tool_signature == last_tool_signature:
                    repeated_tool_signature_count += 1
                else:
                    repeated_tool_signature_count = 0
                last_tool_signature = tool_signature

                if repeated_tool_signature_count >= self.MAX_REPEAT_SAME_TOOL_SIGNATURE:
                    print(f"[OCP-Static] 检测到重复工具调用签名，提前终止审查")
                    print(f"[OCP-Static] ========== 审查结束 ==========\n")
                    return best_candidate if best_candidate else content_to_check

                # 有工具调用
                assistant_msg = {"role": "assistant", "content": message.content or ""}
                tool_calls_data = []
                for tc in message.tool_calls:
                    tool_calls_data.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
                assistant_msg["tool_calls"] = tool_calls_data
                context.append(assistant_msg)

                for tc in message.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}

                    print(f"[OCP-Static]   工具调用: {func_name}")
                    _remaining_seconds(deadline)
                    tool_result = await _run_ocp_tool(func_name, args, self.session_id)

                    context.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })

            # 达到最大循环次数
            print(f"[OCP-Static] 达到最大工具轮次，返回当前最佳正文")
            return best_candidate if best_candidate else self._deterministic_format_repair(content_to_check)

        except (asyncio.TimeoutError, OCPTimeout) as e:
            print(f"[OCP-Static] 审查超时，降级返回原始内容: {e}")
            return self._deterministic_format_repair(content_to_check)
        except Exception as e:
            print(f"[OCP-Static] 审查失败，降级返回原始内容: {e}")
            return self._deterministic_format_repair(content_to_check)

    @staticmethod
    def _extract_final_answer(text: str) -> str | None:
        tag_pairs = [
            (r'<\s*final_answer\s*>', r'<\s*/\s*final_answer\s*>'),
            (r'&lt;\s*final_answer\s*&gt;', r'&lt;\s*/\s*final_answer\s*&gt;'),
        ]
        for open_pattern, close_pattern in tag_pairs:
            close_matches = list(re.finditer(close_pattern, text, flags=re.IGNORECASE))
            if close_matches:
                close_match = close_matches[-1]
                open_matches = list(re.finditer(open_pattern, text[:close_match.start()], flags=re.IGNORECASE))
                if open_matches:
                    open_match = open_matches[-1]
                    candidate = text[open_match.end():close_match.start()]
                    if candidate.strip():
                        return candidate.strip()

        unclosed = re.search(
            r'.*<\s*final_answer\s*>(.*)$',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not unclosed:
            unclosed = re.search(
                r'.*&lt;\s*final_answer\s*&gt;(.*)$',
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if unclosed and unclosed.group(1).strip():
            return unclosed.group(1).strip()

        return None

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理审查 LLM 输出中可能残留的标签及内部内容"""
        if not text:
            return ""

        final_answer = OCPStatic._extract_final_answer(text)
        if final_answer is not None:
            text = final_answer
            
        # 1. 移除已闭合的 <think> 块及其内部内容
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.IGNORECASE | re.DOTALL)
        
        # 2. 如果存在未闭合的 <think>，拦截其后的所有内容
        if re.search(r'<think>(?!.*?</think>)', text, flags=re.IGNORECASE | re.DOTALL):
            text = re.sub(r'<think>.*$', '', text, flags=re.IGNORECASE | re.DOTALL)
        
        # 3. 剥离干扰标签
        text = re.sub(r'</?think[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'</?final_answer[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<\|.*?\|>', '', text, flags=re.IGNORECASE | re.DOTALL)
        
        # 4. 强力清除 AI 常用废话前缀和引导语
        noise_patterns = [
            r'^好的，.*?：', r'^好的。.*?：', r'^以下是.*?：', r'^修复后的文本如下：',
            r'^根据您的要求，.*?', r'^我已经为您.*?。', r'^审查结果：', r'^Assistant:',
            r'^修正方案：', r'^这里是修复后的内容：'
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE).strip()

        # 5. 安全拦截：如果输出中包含明显的 AI 身份声明，且内容异常，则判定为失控
        identity_keywords = ["作为AI助手", "我无法完成", "我的职责是", "抱歉，作为", "AI模型"]
        if any(kw in text for kw in identity_keywords):
            # 如果检测到身份声明，返回空，由上层逻辑触发降级
            return ""

        wrapper_line_patterns = [
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
            r'^执行:\s*`?(get_linked_content|search_article|get_article|pdf_text_reader|word_reader)[^`]*`?.*$',
            r'^工具执行完毕.*$',
        ]
        trailing_noise_patterns = [
            r'^(以上|上述)为.{0,30}(正文|文本|内容|结果)[:：]?$',
            r'^如需进一步.*$',
        ]

        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and any(re.match(pattern, lines[0].strip(), flags=re.IGNORECASE) for pattern in wrapper_line_patterns):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
        while lines and any(re.match(pattern, lines[-1].strip(), flags=re.IGNORECASE) for pattern in trailing_noise_patterns):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
        text = "\n".join(lines).strip()

        return OCPStatic._deterministic_format_repair(text)

    @staticmethod
    def _deterministic_format_repair(text: str) -> str:
        if not text:
            return ""
        return OCPStatic._repair_markdown_tables(text).strip()

    @staticmethod
    def _repair_markdown_tables(text: str) -> str:
        """Normalize obvious Markdown table defects without using the OCP LLM."""
        if "|" not in text:
            return text

        def split_quote_prefix(line: str) -> tuple[str, str]:
            match = re.match(r'^(\s*(?:>\s*)*)(.*)$', line)
            if not match:
                return "", line
            return match.group(1), match.group(2)

        def expand_collapsed_table_lines(raw_text: str) -> list[str]:
            expanded: list[str] = []
            for original_line in raw_text.splitlines():
                prefix, body = split_quote_prefix(original_line)
                if body.count("|") < 6:
                    expanded.append(original_line)
                    continue

                first_pipe_index = body.find("|")
                if first_pipe_index <= 0:
                    table_tail = body.strip()
                    before_table = ""
                else:
                    before_table = body[:first_pipe_index].rstrip()
                    table_tail = body[first_pipe_index:].strip()

                has_collapsed_boundary = (
                    re.search(r'\|\s+\|\s*:?-{3,}', table_tail) is not None or
                    len(re.findall(r'\|\s+\|', table_tail)) >= 2
                )
                if not has_collapsed_boundary:
                    expanded.append(original_line)
                    continue

                if before_table:
                    expanded.append(f"{prefix}{before_table}".rstrip())
                for row in re.sub(r'\|\s+(?=\|)', '|\n', table_tail).splitlines():
                    if row.strip():
                        expanded.append(f"{prefix}{row.strip()}".rstrip())
            return expanded

        def is_table_like_line(line: str) -> bool:
            _, body = split_quote_prefix(line)
            stripped = body.strip()
            if not stripped or "|" not in stripped:
                return False
            return stripped.count("|") >= 2

        def parse_cells(line: str) -> tuple[str, list[str]]:
            prefix, body = split_quote_prefix(line)
            row = body.strip()
            if not row.startswith("|"):
                row = f"| {row}"
            if not row.endswith("|"):
                row = f"{row} |"
            return prefix, [cell.strip() for cell in row.strip("|").split("|")]

        def is_separator_cells(cells: list[str]) -> bool:
            if not cells:
                return False
            return all(re.fullmatch(r':?-{3,}:?', cell.replace(" ", "")) for cell in cells)

        def normalize_row(prefix: str, cells: list[str], width: int, separator: bool = False) -> str:
            if separator:
                normalized_cells = ["---"] * width
            else:
                normalized_cells = (cells + [""] * width)[:width]
            return f"{prefix}| " + " | ".join(normalized_cells) + " |"

        def append_blank_around_table(target: list[str], prefix: str) -> None:
            if not target or not target[-1].strip():
                return
            if ">" in prefix:
                target.append(prefix.rstrip())
            else:
                target.append("")

        def flush_table(buffer: list[str], target: list[str]) -> None:
            if not buffer:
                return
            parsed_rows = [parse_cells(line) for line in buffer]
            data_rows = [(prefix, cells) for prefix, cells in parsed_rows if not is_separator_cells(cells)]
            if len(data_rows) < 2:
                target.extend(buffer)
                buffer.clear()
                return

            table_prefix = parsed_rows[0][0]
            separator_rows = [cells for _, cells in parsed_rows if is_separator_cells(cells)]
            width = max(2, len(separator_rows[0]) if separator_rows else max(len(cells) for _, cells in data_rows))
            append_blank_around_table(target, table_prefix)
            target.append(normalize_row(parsed_rows[0][0], parsed_rows[0][1], width))

            second_is_separator = len(parsed_rows) > 1 and is_separator_cells(parsed_rows[1][1])
            if second_is_separator:
                target.append(normalize_row(parsed_rows[1][0], parsed_rows[1][1], width, separator=True))
                row_start = 2
            else:
                target.append(normalize_row(table_prefix, [], width, separator=True))
                row_start = 1

            trailing_texts: list[tuple[str, str]] = []
            for prefix, cells in parsed_rows[row_start:]:
                if is_separator_cells(cells):
                    continue
                if len(cells) > width:
                    trailing_text = " | ".join(cells[width:]).strip()
                    if trailing_text:
                        trailing_texts.append((prefix, trailing_text))
                target.append(normalize_row(prefix, cells, width))
            for prefix, trailing_text in trailing_texts:
                target.append(f"{prefix}{trailing_text}".rstrip())
            if target and target[-1].strip():
                target.append(table_prefix.rstrip() if ">" in table_prefix else "")
            buffer.clear()

        lines = expand_collapsed_table_lines(text)
        repaired: list[str] = []
        table_buffer: list[str] = []
        in_fence = False

        for line in lines:
            if line.strip().startswith("```"):
                flush_table(table_buffer, repaired)
                in_fence = not in_fence
                repaired.append(line)
                continue

            if not in_fence and is_table_like_line(line):
                table_buffer.append(line)
            else:
                flush_table(table_buffer, repaired)
                repaired.append(line)

        flush_table(table_buffer, repaired)
        return "\n".join(repaired)

    @staticmethod
    def _normalize_tool_arguments(arguments: str) -> str:
        if not arguments:
            return ""
        try:
            return json.dumps(json.loads(arguments), ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(arguments).strip()

    @classmethod
    def _tool_signature_from_openai_calls(cls, tool_calls) -> str:
        signature_parts = []
        for tc in tool_calls or []:
            signature_parts.append(
                f"{tc.function.name}:{cls._normalize_tool_arguments(tc.function.arguments)}"
            )
        return " || ".join(signature_parts)

    @classmethod
    def _tool_signature_from_dict_calls(cls, tool_calls: list[dict]) -> str:
        signature_parts = []
        for tc in tool_calls or []:
            function = tc.get("function", {})
            signature_parts.append(
                f"{function.get('name', '')}:{cls._normalize_tool_arguments(function.get('arguments', ''))}"
            )
        return " || ".join(signature_parts)

    @staticmethod
    def _describe_tool(function_name: str) -> str:
        return OCP_TOOL_LABELS.get(function_name, function_name)

    @staticmethod
    def _is_substantive_replacement(original: str, candidate: str) -> bool:
        """OCP is allowed to repair format, not collapse a full answer into a status line."""
        candidate_text = (candidate or "").strip()
        if not candidate_text:
            return False

        original_compact = re.sub(r"\s+", "", original or "")
        candidate_compact = re.sub(r"\s+", "", candidate_text)
        if not original_compact:
            return True

        status_only_patterns = [
            r"^\[?OCP\]?.{0,80}(审查|检查|修复|完成|异常|超时).*$",
            r"^审查(完成|通过|结束).{0,20}$",
            r"^已(完成|通过).{0,30}(审查|检查|修复).*$",
            r"^格式(正确|无误|已修复).{0,20}$",
            r"^.*请提供.{0,40}(文本|内容).{0,40}(检查|修复).*$",
            r"^(我来|现在|首先|接下来).{0,100}(检查|审查|确认|调用工具|获取链接).*$",
            r"^.*(调用工具|get_linked_content|search_article|get_article).{0,80}$",
        ]
        if any(re.match(pattern, candidate_text, flags=re.IGNORECASE | re.DOTALL) for pattern in status_only_patterns):
            return False

        if (
            len(original_compact) <= 8 and
            re.fullmatch(r"[\w\s.,!?，。！？-]+", original or "") and
            candidate_compact != original_compact
        ):
            return False

        if len(original_compact) >= 80:
            minimum_length = max(40, int(len(original_compact) * 0.35))
            if len(candidate_compact) < minimum_length:
                return False

        return True


# ── OCPStream 类 ─────────────────────────────────────────────────────────

class OCPStream:
    """OCP-Stream: 完全流式的格式审查与自动修复"""

    MAX_TOOL_ROUNDS = 2
    MAX_REPEAT_SAME_TOOL_SIGNATURE = 2
    MAX_RETRIES = 1
    RETRYABLE_STATUS_CODES = {"429", "500", "502", "503", "504", "Timeout", "timeout", "timed out", "Connection error"}

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.client = AsyncOpenAI(
            api_key=OCP_API_KEY,
            base_url=OCP_BASE_URL,
        )

    async def _call_with_retry(self, **kwargs):
        return await OCPStatic(self.session_id)._call_with_retry(**kwargs)

    async def check_stream(self, content: str):
        if not content or not content.strip():
            return
        content_to_check = OCPStatic._clean_output(content) or OCPStatic._deterministic_format_repair(content)

        print(f"\n[OCP-Stream] ========== 开始流式审查 ==========")
        
        try:
            context = [
                {"role": "system", "content": OCP_SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查并修复以下文本的格式问题：\n\n{content_to_check}"}
            ]
            best_candidate = OCPStatic._deterministic_format_repair(content_to_check)
            last_tool_signature = None
            repeated_tool_signature_count = 0
            has_announced_structure_check = False
            deadline = time.monotonic() + OCP_TOTAL_TIMEOUT

            yield {'type': 'thought', 'content': OCP_PROGRESS_MESSAGE.strip() + "\n", 'thought_type': 'ocp', 'mode': 'new'}
            
            for round_num in range(self.MAX_TOOL_ROUNDS):
                print(f"[OCP-Stream] 第 {round_num + 1} 轮流式调用")
                if round_num == 0:
                    yield {'type': 'thought', 'content': '- OCP 正在检查正文结构、引用角标和 Markdown 语法\n', 'thought_type': 'ocp', 'mode': 'new'}

                content_str = ""
                full_raw_content = ""
                reasoning_str = ""
                tool_calls = []

                round_timeout = min(OCP_CALL_TIMEOUT, _remaining_seconds(deadline))
                async with asyncio.timeout(round_timeout):
                    stream_res = await self.client.chat.completions.create(
                        model=OCP_LLM_MODEL,
                        messages=context,
                        tools=OCP_TOOLS,
                        tool_choice="auto",
                        stream=True,
                        timeout=round_timeout
                    )

                    async for chunk in stream_res:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta

                        # 推理内容
                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            reasoning_str += reasoning
                            yield {'type': 'thought', 'content': reasoning, 'thought_type': 'ocp', 'mode': 'append'}

                        # 正文内容
                        if delta.content:
                            if not has_announced_structure_check:
                                has_announced_structure_check = True
                                yield {'type': 'thought', 'content': '- OCP 正在整理修正版正文\n', 'thought_type': 'ocp', 'mode': 'new'}
                            content_str += delta.content
                            full_raw_content += delta.content
                            clean_text = OCPStatic._clean_output(full_raw_content)
                            if OCPStatic._is_substantive_replacement(content_to_check, clean_text):
                                best_candidate = clean_text

                        # 工具调用
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                tc_index = tc.index
                                if tc_index is None:
                                    tc_index = len(tool_calls) - 1 if tool_calls else 0

                                while len(tool_calls) <= tc_index:
                                    tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})

                                if tc.id: tool_calls[tc_index]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name: tool_calls[tc_index]["function"]["name"] += tc.function.name
                                    if tc.function.arguments: tool_calls[tc_index]["function"]["arguments"] += tc.function.arguments

                if not tool_calls:
                    final_clean = OCPStatic._clean_output(full_raw_content)
                    final_content = (
                        final_clean
                        if OCPStatic._is_substantive_replacement(content_to_check, final_clean)
                        else best_candidate if OCPStatic._is_substantive_replacement(content_to_check, best_candidate)
                        else OCPStatic._deterministic_format_repair(content_to_check)
                    )
                    yield {'type': 'content_replace', 'content': final_content}
                    yield {'type': 'thought', 'content': '- OCP 审查完成，已应用修正版\n', 'thought_type': 'ocp', 'mode': 'new'}
                    print(f"[OCP-Stream] 审查完成")
                    return

                tool_signature = OCPStatic._tool_signature_from_dict_calls(tool_calls)
                if tool_signature and tool_signature == last_tool_signature:
                    repeated_tool_signature_count += 1
                else:
                    repeated_tool_signature_count = 0
                last_tool_signature = tool_signature

                if repeated_tool_signature_count >= self.MAX_REPEAT_SAME_TOOL_SIGNATURE:
                    print(f"[OCP-Stream] 检测到重复工具调用签名，提前终止审查")
                    yield {'type': 'thought', 'content': '- OCP 检测到重复检查，已停止自循环并保留当前最佳版本\n', 'thought_type': 'ocp', 'mode': 'new'}
                    fallback_content = (
                        best_candidate
                        if OCPStatic._is_substantive_replacement(content_to_check, best_candidate)
                        else OCPStatic._deterministic_format_repair(content_to_check)
                    )
                    yield {'type': 'content_replace', 'content': fallback_content}
                    return

                # 执行工具并继续
                context.append({"role": "assistant", "content": content_str, "tool_calls": tool_calls, "reasoning_content": reasoning_str})
                for tc in tool_calls:
                    f_name = tc["function"]["name"]
                    f_args = tc["function"]["arguments"]
                    yield {'type': 'thought', 'content': f'- OCP 正在{OCPStatic._describe_tool(f_name)}\n', 'thought_type': 'ocp', 'mode': 'new'}
                    try:
                        parsed_args = json.loads(f_args) if f_args else {}
                    except json.JSONDecodeError:
                        parsed_args = {}
                    _remaining_seconds(deadline)
                    res = await _run_ocp_tool(f_name, parsed_args, self.session_id)
                    context.append({"role": "tool", "tool_call_id": tc["id"], "name": f_name, "content": str(res)})
                    yield {'type': 'thought', 'content': f'- OCP 已接收{OCPStatic._describe_tool(f_name)}结果，继续修订\n', 'thought_type': 'ocp', 'mode': 'new'}

            print(f"[OCP-Stream] 达到最大工具轮次，保留当前最佳正文")
            fallback_content = (
                best_candidate
                if OCPStatic._is_substantive_replacement(content_to_check, best_candidate)
                else OCPStatic._deterministic_format_repair(content_to_check)
            )
            yield {'type': 'thought', 'content': '- OCP 达到最大检查轮次，已保留当前最佳版本\n', 'thought_type': 'ocp', 'mode': 'new'}
            yield {'type': 'content_replace', 'content': fallback_content}

        except (asyncio.TimeoutError, OCPTimeout) as e:
            print(f"[OCP-Stream] 超时，保留原文: {e}")
            yield {'type': 'thought', 'content': '**[OCP] 审查超时，已保留原文。**\n', 'thought_type': 'ocp', 'mode': 'new'}
            yield {'type': 'content_replace', 'content': OCPStatic._deterministic_format_repair(content_to_check)}
        except Exception as e:
            print(f"[OCP-Stream] 异常: {e}")
            yield {'type': 'thought', 'content': '**[OCP] 审查过程遇到异常，保留原文。**\n', 'thought_type': 'ocp', 'mode': 'new'}
            yield {'type': 'content_replace', 'content': OCPStatic._deterministic_format_repair(content_to_check)}
