"""
模块描述：默认工具调用 Agent，使用模型原生 tool_calls 循环完成检索、工具执行和最终回答。
"""

import json
import os
import time
from typing import Callable, Any

from function_calling import call, create_assistant_message
from output_sanitizer import sanitize_llm_output, extract_final_answer, strip_think_blocks, strip_wrapper_tags


def _optional_positive_int_env(name: str, default: int | None = None):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    raw_value = raw_value.strip()
    if not raw_value:
        return default
    if raw_value.lower() in {"none", "unlimited", "off", "0", "-1"}:
        return None
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else None


class DefaultAgent:
    def __init__(
        self,
        memory: list = None,
        session_id: str = "default",
        workspace_scope: str = None,
        use_ocp: bool = True,
        execute_tool: Callable[[str, Any], str] | None = None,
    ):
        self.memory = memory or []
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp
        self.execute_tool = execute_tool or self._missing_tool_executor

    MAX_TOOL_ROUNDS = _optional_positive_int_env("LAWYANCE_MAX_TOOL_ROUNDS")
    MAX_NON_STREAM_ROUNDS = _optional_positive_int_env("LAWYANCE_MAX_NON_STREAM_TOOL_ROUNDS", MAX_TOOL_ROUNDS)

    @staticmethod
    def _missing_tool_executor(function_name: str, arguments: Any) -> str:
        return f"{function_name}工具执行器未配置,请检查主调度模块"

    @staticmethod
    def _sanitize_for_user(raw_content: str) -> str:
        """
        对 LLM 原始输出进行清洗：提取 <final_answer>，移除 <think>，清除噪声。
        使用 soft enforcement：如果 LLM 没有输出 <final_answer>，fallback 为清洗全文。
        """
        result = sanitize_llm_output(raw_content, enforce_final_answer=True)
        # 如果清洗后为空（身份泄漏或废话），fallback 为仅移除标签的版本
        if not result.strip():
            fallback = strip_think_blocks(raw_content)
            fallback = strip_wrapper_tags(fallback)
            return fallback.strip()
        return result

    @staticmethod
    def _history_context_message(message: dict) -> dict:
        allowed_keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
        return {key: value for key, value in message.items() if key in allowed_keys and value is not None}

    @staticmethod
    def _has_reached_round_limit(limit, round_num: int) -> bool:
        return isinstance(limit, int) and limit >= 0 and round_num >= limit

    async def run(self, content: str = None, stream: bool = True):
        # 默认模式下，主程序的 agent.py 已经将消息附加到 self.memory 中。
        current_mem = self.memory
        
        if stream:
            actual_content = ""  # 仅追踪正文内容（不含 reasoning），用于 OCP 审查
            try:
                round_num = 0
                while True:
                    if self._has_reached_round_limit(self.MAX_TOOL_ROUNDS, round_num):
                        msg = f"工具调用超过最大轮次 ({self.MAX_TOOL_ROUNDS})，已停止。"
                        print(f"[DefaultAgent 流式] {msg}")
                        yield {'type': 'error', 'content': msg}
                        return

                    round_num += 1
                    print(f"[DefaultAgent 流式] 第 {round_num} 轮调用")
                    response = await call(current_mem, True)
                    tool_calls = []
                    assistant_content = ""
                    reasoning_str = ""
                    thought_signature_str = ""
                    is_tool_call = False
                    is_drafting = False

                    async for chunk in response:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta

                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            reasoning_str += reasoning
                            yield {'type': 'thought', 'content': reasoning, 'thought_type': 'reasoning', 'mode': 'append'}

                        # 捕获 thought_signature
                        ts = getattr(delta, 'thought_signature', None)
                        if ts:
                            thought_signature_str = ts

                        if delta.content is not None:
                            assistant_content += delta.content
                            actual_content += delta.content
                            if self.use_ocp:
                                if not is_drafting:
                                    is_drafting = True
                                    yield {'type': 'thought', 'content': '正在拟定回答初稿\n', 'thought_type': 'draft', 'mode': 'new'}
                                yield {'type': 'thought', 'content': delta.content, 'thought_type': 'draft', 'mode': 'append'}
                            else:
                                yield {'type': 'thought', 'content': delta.content, 'thought_type': 'draft', 'mode': 'append'}

                        if delta.tool_calls:
                            is_tool_call = True
                            for tc in delta.tool_calls:
                                tc_index = tc.index
                                tc_dump = tc.model_dump(exclude_unset=True)

                                if tc_index is None:
                                    is_new_call = ("id" in tc_dump) or ("function" in tc_dump and "name" in tc_dump["function"])
                                    if len(tool_calls) == 0 or is_new_call:
                                        tc_index = len(tool_calls)
                                    else:
                                        tc_index = len(tool_calls) - 1

                                while len(tool_calls) <= tc_index:
                                    tool_calls.append({"id": f"call_{int(time.time())}_{tc_index}", "type": "function",
                                                       "function": {"name": "", "arguments": ""}})

                                if "id" in tc_dump and tc_dump["id"]:
                                    tool_calls[tc_index]["id"] = tc_dump["id"]
                                if "function" in tc_dump:
                                    for k, v in tc_dump["function"].items():
                                        if v: tool_calls[tc_index]["function"][k] += v

                    if is_tool_call:
                        yield {'type': 'thought', 'content': '**正在调用工具处理中...**\n', 'thought_type': 'tool', 'mode': 'new'}

                        assistant_msg = create_assistant_message(
                            content=assistant_content or "",
                            reasoning_content=reasoning_str,
                            tool_calls=tool_calls,
                            thought_signature=thought_signature_str
                        )
                        current_mem.append(assistant_msg)
                        yield {'type': 'history_trace', 'content': [self._history_context_message(assistant_msg)]}
                        for tc in tool_calls:
                            func_name = tc["function"]["name"]
                            args_str = tc["function"]["arguments"]
                            print(f"[工具调用] 函数: {func_name}, 参数: {args_str}")

                            try:
                                args = json.loads(args_str) if args_str else {}
                            except Exception as je:
                                print(f"[JSON 解析失败] 参数: {args_str}, 错误: {je}")
                                args = {}

                            yield {'type': 'thought', 'content': f'执行: `{func_name}`\n', 'thought_type': 'tool', 'mode': 'new'}
                            result = self.execute_tool(func_name, args)

                            tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": func_name, "content": str(result)}
                            current_mem.append(tool_msg)
                            yield {'type': 'history_trace', 'content': [self._history_context_message(tool_msg)]}
                        
                        yield {'type': 'thought', 'content': '**工具执行完毕，正在生成最终回复...**\n', 'thought_type': 'tool', 'mode': 'new'}
                        actual_content = ""  # 工具调用后重置，下一轮的 content 才是最终正文
                        continue
                    else:
                        if thought_signature_str:
                            yield {'type': 'thought_signature', 'content': thought_signature_str}
                        break

                # ── 后处理管道：<final_answer> 提取 → OCP 审查 ──
                sanitized_content = self._sanitize_for_user(actual_content)

                if self.use_ocp and sanitized_content.strip():
                    # 发送未经 OCP 的版本作为 memory 候选
                    yield {'type': 'memory_candidate', 'content': sanitized_content}
                    from ocp import OCPStream
                    ocp = OCPStream(session_id=self.workspace_scope)
                    async for ocp_chunk in ocp.check_stream(sanitized_content):
                        yield ocp_chunk
                else:
                    # 不使用 OCP 时，直接输出清洗后的内容
                    yield {'type': 'content_replace', 'content': sanitized_content}

            except Exception as e:
                print(f"[DefaultAgent 流式调用失败]: {type(e).__name__}: {e}")
                yield {'type': 'error', 'content': str(e)}
        else:
            # 非流式：多轮工具调用循环（与流式路径行为一致）
            content_output = ""
            round_num = 0
            while True:
                if self._has_reached_round_limit(self.MAX_NON_STREAM_ROUNDS, round_num):
                    print(f"[DefaultAgent 非流式] 达到最大工具调用轮次 ({self.MAX_NON_STREAM_ROUNDS})")
                    yield {'type': 'content', 'content': f"工具调用超过最大轮次 ({self.MAX_NON_STREAM_ROUNDS})，已停止。"}
                    return

                round_num += 1
                print(f"[DefaultAgent 非流式] 第 {round_num} 轮调用")
                res = await call(current_mem, stream=False)
                content_output = res.content or ""

                if not res.tool_calls:
                    # 没有工具调用，LLM 已输出最终内容
                    break

                # 有工具调用，执行工具并继续循环
                tool_calls = [t.model_dump(exclude_unset=True) for t in res.tool_calls]
                assistant_msg = create_assistant_message(content=content_output, tool_calls=tool_calls)
                current_mem.append(assistant_msg)
                yield {'type': 'history_trace', 'content': [self._history_context_message(assistant_msg)]}

                for tc in res.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    print(f"[工具调用] 函数: {func_name}, 参数: {json.dumps(args, ensure_ascii=False)[:200]}")
                    result = self.execute_tool(func_name, args)
                    tool_msg = {"role": "tool", "tool_call_id": tc.id, "name": func_name, "content": str(result)}
                    current_mem.append(tool_msg)
                    yield {'type': 'history_trace', 'content': [self._history_context_message(tool_msg)]}

            # ── 后处理管道 ──
            content_output = self._sanitize_for_user(content_output)

            if self.use_ocp:
                if content_output.strip():
                    yield {'type': 'memory_candidate', 'content': content_output}
                # OCP-Static: 非流式输出格式审查
                from ocp import OCPStatic
                checker = OCPStatic(session_id=self.workspace_scope)
                content_output = await checker.check(content_output)

            yield {'type': 'content', 'content': content_output}
