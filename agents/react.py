"""
ReAct 范式：Reasoning + Acting
每一轮循环包含三个步骤：
    Thought  —— 模型输出推理过程
    Action   —— 模型决定调用哪个工具（或输出 Final Answer）
    Observation —— 执行工具后把结果喂回模型

循环直到模型输出 "Final Answer: ..." 或达到最大轮次。
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

#  Prompt 模板
REACT_PROMPT_TEMPLATE = """
请注意，你是由工大法智团队开发的，有能力调用外部工具的名为Lawver的AI助手。

可用工具如下：
{tools}

请严格按照以下格式进行回应：

Thought: 你的思考过程，用于分析问题、拆解任务和规划下一步行动。
Action: 你决定采取的行动，必须是以下格式之一：
- {{tool_name}}[{{tool_input}}]：调用一个可用工具。
- Finish[最终答案]：当你认为已经获得最终答案时。
- 当你收集到足够的信息，能够回答用户的最终问题时，你必须在`Action:`字段后使用 `Finish[最终答案]` 来输出最终答案。

Few Shot Example:
Question: 苹果最新的手机是哪一款？它的主要卖点是什么？
Thought: 首先，我需要确定现在的日期为 2026年3月份，然后查询苹果最新的手机型号。然后，我需要查找该型号的主要卖点。
Action: Search[苹果最新的手机型号 2026年3月份]
Observation: 苹果最新的手机是iPhone 15。它的主要卖点是搭载了A17 Pro芯片，支持120Hz ProMotion显示屏
...

现在，请开始解决以下问题：
Question: {question}
History: {history}
"""


class ReActAgent:
    def __init__(self, tools_description: str, execute_tool: Callable[[str, str], str], memory: list = None, max_steps: int = 3, session_id: str = "default", workspace_scope: str = None, use_ocp: bool = False):
        self.tools_description = tools_description
        self.execute_tool = execute_tool
        self.max_steps = max_steps
        self.history = []
        self.memory = memory or []
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp

    async def run(self, question: str):
        self.history = []
        current_step = 0

        while current_step < self.max_steps:
            current_step += 1
            yield {'type': 'thought', 'content': f"\n\n--- 第 {current_step} 步推理 ---\n\n"}

            history_str = "\n".join(self.history)
            prompt = REACT_PROMPT_TEMPLATE.format(tools=self.tools_description, question=question, history=history_str)

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
                yield {'type': 'thought', 'content': "\n错误：LLM未能返回有效响应。\n"}
                break

            thought, action = self._parse_output(full_response_text)

            if not action:
                yield {'type': 'thought', 'content': "\n警告：未能解析出有效的Action，流程终止。\n"}
                break

            if action.startswith("Finish"):
                # 提取最终答案
                final_answer = self._parse_action_input(action)
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

        yield {'type': 'thought', 'content': "\n已达到最大步数，流程终止。\n"}

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
