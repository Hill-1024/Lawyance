import json
import time
from typing import Callable, Any

from function_calling import call, create_assistant_message

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

    MAX_NON_STREAM_ROUNDS = 10  # 非流式工具调用最大轮次，防止无限循环

    @staticmethod
    def _missing_tool_executor(function_name: str, arguments: Any) -> str:
        return f"{function_name}工具执行器未配置,请检查主调度模块"

    async def run(self, content: str = None, stream: bool = True):
        # 默认模式下，主程序的 agent.py 已经将消息附加到 self.memory 中。
        current_mem = self.memory
        
        if stream:
            actual_content = ""  # 仅追踪正文内容（不含 reasoning），用于 OCP 审查
            try:
                while True:
                    response = await call(current_mem, True)
                    tool_calls = []
                    content_str = ""
                    reasoning_str = ""
                    thought_signature_str = ""
                    is_tool_call = False
                    is_drafting = False

                    async for chunk in response:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta

                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            content_str += reasoning
                            reasoning_str += reasoning
                            yield {'type': 'thought', 'content': reasoning, 'thought_type': 'reasoning', 'mode': 'append'}

                        # 捕获 thought_signature
                        ts = getattr(delta, 'thought_signature', None)
                        if ts:
                            thought_signature_str = ts

                        if delta.content is not None:
                            content_str += delta.content
                            actual_content += delta.content
                            if self.use_ocp:
                                if not is_drafting:
                                    is_drafting = True
                                    yield {'type': 'thought', 'content': '**[拟定初稿]**\n', 'thought_type': 'draft', 'mode': 'new'}
                                yield {'type': 'thought', 'content': delta.content, 'thought_type': 'draft', 'mode': 'append'}
                            else:
                                yield {'type': 'content', 'content': delta.content}

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
                            content=content_str or "",
                            reasoning_content=reasoning_str,
                            tool_calls=tool_calls,
                            thought_signature=thought_signature_str
                        )
                        current_mem.append(assistant_msg)
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

                            current_mem.append(
                                {"role": "tool", "tool_call_id": tc["id"], "name": func_name, "content": str(result)})
                        
                        yield {'type': 'thought', 'content': '**工具执行完毕，正在生成最终回复...**\n', 'thought_type': 'tool', 'mode': 'new'}
                        actual_content = ""  # 工具调用后重置，下一轮的 content 才是最终正文
                        continue
                    else:
                        if thought_signature_str:
                            yield {'type': 'thought_signature', 'content': thought_signature_str}
                        break

                # OCP-Stream: 流式输出格式审查
                if self.use_ocp and actual_content.strip():
                    yield {'type': 'memory_candidate', 'content': actual_content}
                    from ocp import OCPStream
                    ocp = OCPStream(session_id=self.workspace_scope)
                    async for ocp_chunk in ocp.check_stream(actual_content):
                        yield ocp_chunk

            except Exception as e:
                print(f"[DefaultAgent 流式调用失败]: {type(e).__name__}: {e}")
                yield {'type': 'error', 'content': str(e)}
        else:
            # 非流式：多轮工具调用循环（与流式路径行为一致）
            for round_num in range(self.MAX_NON_STREAM_ROUNDS):
                print(f"[DefaultAgent 非流式] 第 {round_num + 1} 轮调用")
                res = await call(current_mem, stream=False)
                content_output = res.content or ""

                if not res.tool_calls:
                    # 没有工具调用，LLM 已输出最终内容
                    break

                # 有工具调用，执行工具并继续循环
                tool_calls = [t.model_dump(exclude_unset=True) for t in res.tool_calls]
                current_mem.append(create_assistant_message(content=content_output, tool_calls=tool_calls))

                for tc in res.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    print(f"[工具调用] 函数: {func_name}, 参数: {json.dumps(args, ensure_ascii=False)[:200]}")
                    result = self.execute_tool(func_name, args)
                    current_mem.append(
                        {"role": "tool", "tool_call_id": tc.id, "name": func_name, "content": str(result)})
            else:
                print(f"[DefaultAgent 非流式] 达到最大工具调用轮次 ({self.MAX_NON_STREAM_ROUNDS})")

            if self.use_ocp:
                if content_output.strip():
                    yield {'type': 'memory_candidate', 'content': content_output}
                # OCP-Static: 非流式输出格式审查
                from ocp import OCPStatic
                checker = OCPStatic(session_id=self.workspace_scope)
                content_output = await checker.check(content_output)

            yield {'type': 'content', 'content': content_output}
