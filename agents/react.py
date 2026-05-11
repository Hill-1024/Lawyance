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

from output_sanitizer import sanitize_llm_output, strip_think_blocks, strip_wrapper_tags

# ReAct Prompt 模板 — 不再硬编码身份声明，依赖 system prompt 中的 core constraints
REACT_PROMPT_TEMPLATE = """
请严格按照以下 ReAct 格式进行推理和行动。你必须遵守 system prompt 中的所有约束规则。

可用工具如下：
{tools}

格式要求（必须严格遵循）：

Thought: 你的思考过程，用于分析问题、拆解任务和规划下一步行动。
Action: 你决定采取的行动，必须是以下格式之一：
- {{tool_name}}[{{tool_input}}]：调用一个可用工具。
- Finish[最终答案]：当你收集到足够信息，能够回答用户问题时。

关键规则：
1. 涉及法律依据的回答，必须先通过工具检索获取依据，禁止凭记忆直接作答。
2. 工具返回空结果时，可换关键词重试，但禁止编造法条、案例或 URL。
3. Finish[] 中的最终答案必须包含信源引用，格式为 `<sup><a href="URL">N</a></sup>`。
4. 非法律问题直接 Finish[简短边界说明] 拒绝，不要调用工具。

Few Shot Example:
Question: 劳动合同到期不续签，公司需要赔偿吗？
Thought: 这是一个劳动法问题，我需要检索《劳动合同法》中关于合同期满不续签的赔偿规定。
Action: search_article[劳动合同期满不续签 经济补偿]
Observation: 《劳动合同法》第四十六条规定...
Thought: 已获得法律依据，可以给出最终答案。
Action: Finish[根据《劳动合同法》第四十六条... <sup><a href="URL">1</a></sup> ...]

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
