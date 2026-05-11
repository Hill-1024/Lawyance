"""
模块描述：ReAct 文本循环 Agent，解析 Thought/Action/Observation 并通过 mcps 中转执行工具。
"""

import re
from typing import Callable

try:
    # 作为包的一部分被导入时
    from ..function_calling import call
except ImportError:
    # 测试的时候直接运行 -> 需要调整导入方式
    import sys
    from pathlib import Path

    # 添加父目录到路径
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from function_calling import call

from output_sanitizer import sanitize_llm_output, strip_think_blocks, strip_wrapper_tags


REACT_TASK_TEMPLATE = """# 可用工具
{tools}

# 当前问题
{question}

# 已执行的 ReAct 步骤
{history}
"""


class ReActAgent:
    def __init__(self, tools_description: str, execute_tool: Callable[[str, str], str], memory: list = None, max_steps: int | None = None, session_id: str = "default", workspace_scope: str = None, use_ocp: bool = False):
        self.tools_description = tools_description
        self.execute_tool = execute_tool
        self.max_steps = max_steps
        self.history = []
        self.memory = memory or []
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp

    @staticmethod
    def _sanitize_final_answer(raw: str) -> str:
        """清洗 ReAct 的最终答案输出"""
        result = sanitize_llm_output(raw, enforce_final_answer=True)
        if not result.strip():
            fallback = strip_think_blocks(raw)
            fallback = strip_wrapper_tags(fallback)
            return fallback.strip()
        return result

    async def run(self, question: str):
        self.history = []
        current_step = 0

        while self.max_steps is None or current_step < self.max_steps:
            current_step += 1
            yield {'type': 'thought', 'content': f"\n\n--- 第 {current_step} 步推理 ---\n\n"}

            history_str = "\n".join(self.history) or "无"
            prompt = REACT_TASK_TEMPLATE.format(
                tools=self.tools_description or "无",
                question=question,
                history=history_str,
            )

            messages = self.memory + [{"role": "user", "content": prompt}]

            # 使用流式调用，让用户看到思考过程
            # 禁用原生工具调用，因为 ReAct 模式使用文本解析
            response_stream = await call(context=messages, stream=True, include_tools=False)

            full_response_text = ""
            current_signature = ""
            async for chunk in response_stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        yield {'type': 'thought', 'content': reasoning, 'thought_type': 'reasoning', 'mode': 'append'}

                    ts = getattr(delta, 'thought_signature', None)
                    if ts:
                        current_signature = ts

                    if delta.content:
                        full_response_text += delta.content
                        yield {'type': 'thought', 'content': delta.content}

            if not full_response_text:
                message = "ReAct 模式未能获得有效模型响应，流程已停止。"
                yield {'type': 'thought', 'content': f"\n错误：{message}\n"}
                yield {'type': 'content', 'content': message}
                return

            thought, action = self._parse_output(full_response_text)

            if not action:
                message = "ReAct 模式未能解析出有效 Action，流程已停止。"
                yield {'type': 'thought', 'content': f"\n警告：{message}\n"}
                yield {'type': 'content', 'content': message}
                return

            if action.startswith("Finish"):
                # 提取最终答案并清洗
                raw_answer = self._parse_action_input(action)
                final_answer = self._sanitize_final_answer(raw_answer)

                if self.use_ocp and final_answer.strip():
                    yield {'type': 'thought', 'content': '正在拟定回答初稿\n', 'thought_type': 'draft', 'mode': 'new'}
                    yield {'type': 'thought', 'content': final_answer, 'thought_type': 'draft', 'mode': 'append'}
                    from ocp import OCPStream
                    ocp = OCPStream(session_id=self.workspace_scope)
                    async for ocp_chunk in ocp.check_stream(final_answer):
                        yield ocp_chunk
                else:
                    yield {'type': 'content', 'content': final_answer}
                
                if current_signature:
                    yield {'type': 'thought_signature', 'content': current_signature}
                return

            tool_name, tool_input = self._parse_action(action)
            if not tool_name or not tool_input:
                obs_err = "Observation: 无效的Action格式，请检查。"
                self.history.append(obs_err)
                yield {'type': 'thought', 'content': f"\n{obs_err}\n"}
                continue

            yield {'type': 'thought', 'content': f"\n\n**行动**: `{tool_name}[{tool_input}]`"}

            observation = self.execute_tool(tool_name, tool_input)

            yield {'type': 'thought', 'content': f"\n\n**观察**: {observation}\n"}

            self.history.append(f"Action: {action}")
            self.history.append(f"Observation: {observation}")

        message = f"ReAct 模式已达到最大步数 ({self.max_steps})，已停止。"
        yield {'type': 'thought', 'content': f"\n{message}\n"}
        yield {'type': 'content', 'content': message}

    def _parse_output(self, text: str):
        # Thought: 匹配到 Action: 或文本末尾
        thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.DOTALL)
        # Action: 匹配到文本末尾
        action_match = re.search(r"Action:\s*(.*?)$", text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else None
        action = action_match.group(1).strip() if action_match else None
        return thought, action

    def _parse_action(self, action_text: str):
        match = re.match(r"(\w+)\[(.*)\]", action_text, re.DOTALL)
        return (match.group(1), match.group(2)) if match else (None, None)

    def _parse_action_input(self, action_text: str):
        match = re.match(r"\w+\[(.*)\]", action_text, re.DOTALL)
        return match.group(1) if match else ""
