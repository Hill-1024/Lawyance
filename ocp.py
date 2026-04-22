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


# ── OCP 审查专用 System Prompt ──────────────────────────────────────────

OCP_SYSTEM_PROMPT = """你是一个专业的法律文本格式审查员。你的唯一职责是【检查并修复】给定文本的格式问题。
你是一个非人格化的文本处理引擎，严禁表现出任何人类情感、助手身份或对话意图。

<strict_rules>
1. **身份禁止**：严禁自称“助手”、“AI”、“机器人”或任何身份。
2. **交流禁止**：严禁输出任何解释、道歉、建议、前导词（如“好的”、“已为您修复”）或结语。
3. **内容保留**：除了格式修复外，必须逐字保留原意。严禁添加新的法律意见，严禁概括或简化原句。
4. **纯净输出**：输出结果必须【仅包含】修复后的文本正文。如果违反此条，会导致整个流程失败。
5. **故障退回**：如果无法修复或工具调用无果，请原样输出原文，不要做任何多余的解释。
</strict_rules>

<checklist>
请按以下清单逐项检查并强制修复：

1. **信源角标（必查）**：
   - 如果提到法律条文、法规或法律概念但缺少角标。
   - 格式：`<sup><a href="URL">N</a></sup>`
   - 必须调用 `get_linked_content` 获取 URL。

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
</workflow>

<output_rules>
- 如果文本完全符合规范，原样输出，不做任何修改。
- 如果文本需要修复，仅输出修复后的完整正文，严禁包含任何前导词、解释、总结、结论或评论（例如：“以下是修复后的文本：”或“已完成修复”）。
- 输出必须是纯正文内容，不要包含任何解释、说明或关于你做了什么修改的描述。
- 严禁添加任何 `<final_answer>`、`<think>`、`[OCP]` 或类似的标签或前缀。
- 违反此规则会导致审查失败，请务必保持输出纯净。
</output_rules>"""


# ── OCP 可用的工具子集（从 mcps 统一导入，黑名单过滤具有文件写入权限的工具） ──

OCP_BANNED_TOOL_NAMES = {"pdf_commit_by_sentence", "word_writer"}
OCP_TOOLS = [t for t in all_tools if t["function"]["name"] not in OCP_BANNED_TOOL_NAMES]


# ── OCPStatic 类 ─────────────────────────────────────────────────────────

class OCPStatic:
    """OCP-Static: 非流式输出格式审查与自动修复"""

    MAX_TOOL_ROUNDS = 999  # 最大工具调用循环次数
    MAX_RETRIES = 3      # 单次 LLM 调用最大重试次数
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
                    kwargs['timeout'] = 90.0
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

        print(f"\n[OCP-Static] ========== 开始审查 ==========")
        print(f"[OCP-Static] 审查模型: {OCP_LLM_MODEL}")
        print(f"[OCP-Static] 原文长度: {len(content)} 字符")

        try:
            # 构建记忆隔离的上下文
            context = [
                {"role": "system", "content": OCP_SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查并修复以下文本的格式问题：\n\n{content}"}
            ]

            # 工具调用循环
            for round_num in range(self.MAX_TOOL_ROUNDS):
                print(f"[OCP-Static] 第 {round_num + 1}/{self.MAX_TOOL_ROUNDS} 轮调用")

                response = await self._call_with_retry(
                    model=OCP_LLM_MODEL,
                    messages=context,
                    tools=OCP_TOOLS,
                    tool_choice="auto",
                    stream=False,
                )

                message = response.choices[0].message

                if not message.tool_calls:
                    # 没有工具调用，审查完成
                    result = message.content or ""
                    result = self._clean_output(result)
                    print(f"[OCP-Static] 审查完成（第 {round_num + 1} 轮），结果长度: {len(result)} 字符")
                    print(f"[OCP-Static] ========== 审查结束 ==========\n")
                    return result if result else content

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
                    tool_result = use_tools(func_name, args, conv_id=self.session_id)

                    context.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })

            # 达到最大循环次数
            final_response = await self._call_with_retry(
                model=OCP_LLM_MODEL,
                messages=context,
                stream=False,
            )
            result = final_response.choices[0].message.content or ""
            result = self._clean_output(result)
            return result if result else content

        except Exception as e:
            print(f"[OCP-Static] 审查失败，降级返回原始内容: {e}")
            return content

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理审查 LLM 输出中可能残留的标签及内部内容"""
        if not text:
            return ""
            
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

        return text.strip()


# ── OCPStream 类 ─────────────────────────────────────────────────────────

class OCPStream:
    """OCP-Stream: 完全流式的格式审查与自动修复"""

    MAX_TOOL_ROUNDS = 999
    MAX_RETRIES = 3
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

        print(f"\n[OCP-Stream] ========== 开始流式审查 ==========")
        
        try:
            context = [
                {"role": "system", "content": OCP_SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查并修复以下文本的格式问题：\n\n{content}"}
            ]

            yield {'type': 'thought', 'content': '\n\n**[OCP] 正在进行输出格式审查与信源核验...**\n'}
            
            for round_num in range(self.MAX_TOOL_ROUNDS):
                print(f"[OCP-Stream] 第 {round_num + 1} 轮流式调用")
                
                stream_res = await self.client.chat.completions.create(
                    model=OCP_LLM_MODEL,
                    messages=context,
                    tools=OCP_TOOLS,
                    tool_choice="auto",
                    stream=True,
                    timeout=90.0
                )

                content_str = ""
                full_raw_content = ""
                reasoning_str = ""
                tool_calls = []

                async for chunk in stream_res:
                    if not chunk.choices: continue
                    delta = chunk.choices[0].delta

                    # 推理内容
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        reasoning_str += reasoning
                        yield {'type': 'thought', 'content': reasoning}

                    # 正文内容
                    if delta.content:
                        content_str += delta.content
                        full_raw_content += delta.content
                        clean_text = OCPStatic._clean_output(full_raw_content)
                        if clean_text:
                            yield {'type': 'content_replace', 'content': clean_text}

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
                    if not final_clean or len(final_clean) < 10:
                        yield {'type': 'content_replace', 'content': content}
                    print(f"[OCP-Stream] 审查完成")
                    return

                # 执行工具并继续
                context.append({"role": "assistant", "content": content_str, "tool_calls": tool_calls, "reasoning_content": reasoning_str})
                for tc in tool_calls:
                    f_name = tc["function"]["name"]
                    f_args = tc["function"]["arguments"]
                    yield {'type': 'thought', 'content': f'  - [OCP 工具调用] `{f_name}`\n'}
                    res = use_tools(f_name, json.loads(f_args) if f_args else {}, conv_id=self.session_id)
                    context.append({"role": "tool", "tool_call_id": tc["id"], "name": f_name, "content": str(res)})
                    yield {'type': 'thought', 'content': f'  - [OCP 工具返回] 接收到信息\n'}

        except Exception as e:
            print(f"[OCP-Stream] 异常: {e}")
            yield {'type': 'thought', 'content': '**[OCP] 审查过程遇到异常，保留原文。**\n'}
            yield {'type': 'content_replace', 'content': content}
