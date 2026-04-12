"""
ReAct 范式：Reasoning + Acting
每一轮循环包含三个步骤：
    Thought  —— 模型输出推理过程
    Action   —— 模型决定调用哪个工具（或输出 Final Answer）
    Observation —— 执行工具后把结果喂回模型

循环直到模型输出 "Final Answer: ..." 或达到最大轮次。
"""
import asyncio
import json
import re
from typing import Generator

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
    from mcps import use_tools

from tools import ToolExecutor, search

#  Prompt 模板
REACT_PROMPT_TEMPLATE = """
请注意，你是由广东工业大学工大法智团队开发的，有能力调用外部工具的名为Lawver的AI助手。

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
    def __init__(self, tool_executor: ToolExecutor, memory: list = None, max_steps: int = 3):
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.history = []
        self.memory = memory or []

    async def run(self, question: str):
        self.history = []
        current_step = 0

        yield "<think>\n"

        while current_step < self.max_steps:
            current_step += 1
            yield f"\n\n--- 第 {current_step} 步推理 ---\n\n"

            tools_desc = self.tool_executor.getAvailableTools()
            history_str = "\n".join(self.history)
            prompt = REACT_PROMPT_TEMPLATE.format(tools=tools_desc, question=question, history=history_str)

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
                        full_response_text += reasoning
                        yield reasoning

                    ts = getattr(delta, 'thought_signature', None)
                    if ts:
                        current_signature = ts

                    if delta.content:
                        full_response_text += delta.content
                        yield delta.content

            if not full_response_text:
                yield "\n错误：LLM未能返回有效响应。\n"
                break

            thought, action = self._parse_output(full_response_text)

            if not action:
                yield "\n警告：未能解析出有效的Action，流程终止。\n"
                break

            if action.startswith("Finish"):
                # 提取最终答案
                final_answer = self._parse_action_input(action)
                yield "\n</think>\n\n"
                yield f"{final_answer}"
                if current_signature:
                    yield f"\n[THOUGHT_SIGNATURE:{current_signature}]"
                return

            tool_name, tool_input = self._parse_action(action)
            if not tool_name or not tool_input:
                obs_err = "Observation: 无效的Action格式，请检查。"
                self.history.append(obs_err)
                yield f"\n{obs_err}\n"
                continue

            yield f"\n\n**行动**: `{tool_name}[{tool_input}]`"

            tool_function = self.tool_executor.getTool(tool_name)
            observation = tool_function(tool_input) if tool_function else f"错误：未找到名为 '{tool_name}' 的工具。"

            yield f"\n\n**观察**: {observation}\n"

            self.history.append(f"Action: {action}")
            self.history.append(f"Observation: {observation}")

        yield "\n已达到最大步数，流程终止。\n</think>\n"

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


if __name__ == '__main__':
    tool_executor = ToolExecutor()
    search_desc = "一个网页搜索引擎。当你需要回答关于时事、事实以及在你的知识库中找不到的信息时，应使用此工具。"
    tool_executor.registerTool("Search", search_desc, search)
    agent = ReActAgent(tool_executor=tool_executor)
    question = "美伊以战争最新报道"
    asyncio.run(agent.run(question))
