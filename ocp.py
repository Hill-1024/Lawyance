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
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(".env")

# OCP 专用配置，未设置时回退到主模型配置
OCP_API_KEY = os.getenv("OCP_API_KEY") or os.getenv("API_KEY")
OCP_BASE_URL = os.getenv("OCP_BASE_URL") or os.getenv("BASE_URL")
OCP_LLM_MODEL = os.getenv("OCP_LLM_MODEL") or os.getenv("LLM_MODEL")


# ── OCP 审查专用 System Prompt ──────────────────────────────────────────

OCP_SYSTEM_PROMPT = """你是一个专业的法律文本格式审查员。你的唯一职责是检查并修复给定文本的格式问题。
你不是对话助手，不要与用户闲聊，不要改变文本的实质内容或法律观点。你只负责格式合规性。

<checklist>
请按以下清单逐项检查：

1. **信源角标检查**：文本中是否提到了法律条文、法规名称、或法律概念，但缺少信源角标？
   - 正确格式：在引用句子末尾添加 `<sup><a href="URL">N</a></sup>`
   - 如果缺少信源，你必须调用 `get_linked_content` 工具获取对应 URL，然后插入角标

2. **法条引用格式检查**：引用法条时是否使用了规范格式？
   - 正确格式：
     《法律名称》第X条【罪名/项名】
     > 具体条文内容
   - 要点解释：专业解读
   - 如果格式不规范，请修正为标准格式

3. **参考信源列表检查**：如果文本包含信源角标，底部是否有参考信源列表？
   - 正确格式：
     ---
     **参考信源：**
     [1] [信源名称](URL)
   - 如果缺少，请补充

4. **Emoji 检查**：文本中是否包含任何 emoji 表情符号？
   - 如果有，删除所有 emoji

5. **标签残留检查**：文本中是否残留 `<final_answer>`、`</final_answer>`、`<think>`、`</think>` 等标签？
   - 如果有，剥离标签，仅保留标签内的纯内容

6. **Markdown 格式检查**：文本的 Markdown 语法是否正确？
   - 检查加粗 `**text**` 和斜体 `*text*` 标记是否成对闭合
   - 检查链接 `[text](url)` 格式是否完整，有无残缺的括号或缺失URL
   - 检查角标 `<sup><a href="URL">N</a></sup>` 的 HTML 标签是否正确闭合
   - 检查表格的列数是否对齐，分隔行 `|---|` 是否完整
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
- 如果文本完全符合规范，原样输出，不做任何修改
- 如果文本需要修复，输出修复后的完整文本
- 只输出最终文本内容本身，不要包含任何解释、评论或元数据
- 不要添加任何 `<final_answer>` 或 `<think>` 标签
</output_rules>"""


# ── OCP 可用的工具子集（从 mcps 统一导入，黑名单过滤具有文件写入权限的工具） ──

from mcps import tools as all_tools

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
        import asyncio
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
                    print(f"[OCP-Static] LLM 调用失败 (第 {attempt + 1}/{self.MAX_RETRIES} 次): {e}")
                    print(f"[OCP-Static] 等待 {wait_time}s 后重试...")
                    await asyncio.sleep(wait_time)
                    continue
                raise

    async def check(self, content: str) -> str:
        """
        对 LLM 生成的正文进行格式审查与自动修复。

        工作流与主 LLM 一致：调用工具 -> 接收结果 -> 继续工作 -> 直到输出最终内容。

        Args:
            content: 原始正文内容

        Returns:
            审查通过则返回原文，不通过则返回修复后的内容。
            任何异常情况降级返回原始内容。
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

            # 工具调用循环（与主 LLM 工作流一致）
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
                    # 没有工具调用，审查完成，输出最终内容
                    result = message.content or ""
                    result = self._clean_output(result)
                    print(f"[OCP-Static] 审查完成（第 {round_num + 1} 轮），结果长度: {len(result)} 字符")
                    print(f"[OCP-Static] ========== 审查结束 ==========\n")
                    return result if result else content

                # 有工具调用 —— 将 assistant 消息追加到上下文
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

                # 执行每个工具调用并将结果追加到上下文
                from mcps import use_tools
                for tc in message.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}

                    print(f"[OCP-Static]   工具调用: {func_name}({json.dumps(args, ensure_ascii=False)[:100]})")
                    tool_result = use_tools(func_name, args, conv_id=self.session_id)

                    context.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })
                    print(f"[OCP-Static]   工具返回长度: {len(str(tool_result))} 字符")

            # 达到最大循环次数，做最后一次不带工具的调用，强制模型输出最终文本
            print(f"[OCP-Static] 达到最大工具调用轮次 ({self.MAX_TOOL_ROUNDS})，执行最终调用")
            final_response = await self._call_with_retry(
                model=OCP_LLM_MODEL,
                messages=context,
                stream=False,
                # 不传 tools，强制模型输出文本
            )
            result = final_response.choices[0].message.content or ""
            result = self._clean_output(result)
            print(f"[OCP-Static] 最终输出长度: {len(result)} 字符")
            print(f"[OCP-Static] ========== 审查结束 ==========\n")
            return result if result else content

        except Exception as e:
            print(f"[OCP-Static] 审查失败，降级返回原始内容: {e}")
            import traceback
            traceback.print_exc()
            return content

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理审查 LLM 输出中可能残留的标签及内部内容"""
        # 1. 移除整个 <think> 块及其内容
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.IGNORECASE | re.DOTALL)
        # 2. 移除游离的 <think> 和 </think> 标签（防止未闭合截断）
        text = re.sub(r'</?think[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
        # 3. 剥离 <final_answer> 标签本身，保留其中正文内容
        text = re.sub(r'</?final_answer[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
        return text.strip()


# ── OCPStream 类 ─────────────────────────────────────────────────────────

class OCPStream:
    """OCP-Stream: 流式输出格式审查与自动修复（async generator 版本）

    工作流程与 OCPStatic 一致，但以 async generator 形式 yield 思考过程和最终修正内容：
    - yield {'type': 'thought', ...}          审查过程的思考/工具调用信息
    - yield {'type': 'content_replace', ...}  最终修正后的完整正文（替换原内容）
    """

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
        """带指数退避重试的 LLM 调用封装"""
        import asyncio
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
                    print(f"[OCP-Stream] LLM 调用失败 (第 {attempt + 1}/{self.MAX_RETRIES} 次): {e}")
                    await asyncio.sleep(wait_time)
                    continue
                raise

    async def check_stream(self, content: str):
        """
        对 LLM 生成的正文进行流式格式审查与自动修复。

        Yields:
            {'type': 'thought', 'content': str}          - 审查过程信息（展示在思考块中）
            {'type': 'content_replace', 'content': str}  - 修正后的完整正文
        """
        if not content or not content.strip():
            return

        print(f"\n[OCP-Stream] ========== 开始审查 ==========")
        print(f"[OCP-Stream] 审查模型: {OCP_LLM_MODEL}")
        print(f"[OCP-Stream] 原文长度: {len(content)} 字符")

        try:
            # 构建记忆隔离的上下文
            context = [
                {"role": "system", "content": OCP_SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查并修复以下文本的格式问题：\n\n{content}"}
            ]

            yield {'type': 'thought', 'content': '\n**[OCP] 正在进行输出格式审查...**\n'}

            for round_num in range(self.MAX_TOOL_ROUNDS):
                print(f"[OCP-Stream] 第 {round_num + 1}/{self.MAX_TOOL_ROUNDS} 轮调用")

                response = await self._call_with_retry(
                    model=OCP_LLM_MODEL,
                    messages=context,
                    tools=OCP_TOOLS,
                    tool_choice="auto",
                    stream=False,
                )

                message = response.choices[0].message

                # 展示审查 LLM 的思考内容
                if message.content:
                    preview = message.content[:300] + '...' if len(message.content) > 300 else message.content
                    preview_clean = re.sub(r'</?think[^>]*>', '', preview, flags=re.IGNORECASE)
                    yield {'type': 'thought', 'content': f'[OCP 审查分析] {preview_clean}\n'}

                if not message.tool_calls:
                    # 无工具调用，审查完成
                    result = OCPStatic._clean_output(message.content or "")
                    if result:
                        yield {'type': 'thought', 'content': '**[OCP] 审查完成，输出已修正**\n'}
                        yield {'type': 'content_replace', 'content': result}
                    else:
                        yield {'type': 'thought', 'content': '**[OCP] 审查完成，内容无需修改**\n'}
                        yield {'type': 'content_replace', 'content': content}
                    print(f"[OCP-Stream] 审查完成（第 {round_num + 1} 轮）")
                    print(f"[OCP-Stream] ========== 审查结束 ==========\n")
                    return

                # 有工具调用 —— 展示工具调用过程
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

                # 执行每个工具调用
                from mcps import use_tools
                for tc in message.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}

                    yield {'type': 'thought', 'content': f'[OCP 工具调用] `{func_name}({json.dumps(args, ensure_ascii=False)[:80]})`\n'}
                    print(f"[OCP-Stream]   工具调用: {func_name}")

                    tool_result = use_tools(func_name, args, conv_id=self.session_id)
                    context.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })
                    yield {'type': 'thought', 'content': f'[OCP 工具返回] {len(str(tool_result))} 字符\n'}

            # 达到最大轮次，做最终调用
            print(f"[OCP-Stream] 达到最大工具调用轮次，执行最终调用")
            yield {'type': 'thought', 'content': '[OCP] 执行最终输出...\n'}
            final_response = await self._call_with_retry(
                model=OCP_LLM_MODEL,
                messages=context,
                stream=False,
            )
            result = OCPStatic._clean_output(final_response.choices[0].message.content or "")
            if result:
                yield {'type': 'thought', 'content': '**[OCP] 审查完成**\n'}
                yield {'type': 'content_replace', 'content': result}
            else:
                yield {'type': 'thought', 'content': '**[OCP] 审查完成，内容无需修改**\n'}
                yield {'type': 'content_replace', 'content': content}
            print(f"[OCP-Stream] ========== 审查结束 ==========\n")

        except Exception as e:
            print(f"[OCP-Stream] 审查失败，保留原始内容: {e}")
            import traceback
            traceback.print_exc()
            yield {'type': 'thought', 'content': '**[OCP] 审查异常，保留原始内容**\n'}
            yield {'type': 'content_replace', 'content': content}
