"""
Plan & Solve 范式（两阶段）：

阶段一  Plan   —— 让模型先把复杂问题拆分成有序子任务列表
阶段二  Solve  —— 逐条执行子任务（可调用工具），收集中间结果，最终汇总

适合需要多步推理、长流程的任务，比 ReAct 更结构化。
"""

import ast
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

# Planner 模板 — 不再硬编码身份，依赖 system prompt 的 core constraints
PLANNER_PROMPT_TEMPLATE = """
你的任务是将用户提出的法律问题分解成一个由多个简单步骤组成的行动计划。

关键规则：
1. 规划阶段只拆解任务，不输出任何法律结论或法条引用。
2. 涉及法律依据的步骤必须明确标注"需要检索"（如"检索《XX法》关于XX的规定"）。
3. 每个步骤必须是独立的、可执行的子任务。
4. 输出必须是一个 Python 列表格式。

问题: {question}

请严格按照以下格式输出你的计划，```python与```作为前后缀是必要的:
```python
["步骤1", "步骤2", "步骤3", ...]
```

示例:
问题: 我被公司无故解雇，想申请劳动仲裁，应该怎么做？
```python
[
    "梳理案件事实：确认被解雇的时间、原因及公司给出的理由",
    "检索适用法律：查找《劳动合同法》中关于违法解除劳动合同的规定",
    "判断违法情形：对比公司行为与法定解除条件",
    "计算赔偿金额：根据工作年限和月薪计算经济补偿金",
    "确认仲裁时效：核实劳动争议仲裁时效",
    "准备申请材料：列明需收集的证据清单",
    "指引申请流程：说明向劳动仲裁委员会提交申请的步骤"
]
```
"""

class Planner:
    def __init__(self):
        pass

    async def plan(self, question: str, memory: list = None):
        prompt = PLANNER_PROMPT_TEMPLATE.format(question=question)
        messages = (memory or []) + [{"role": "user", "content": prompt}]

        yield "\n\n**正在制定计划...**\n\n"

        # 规划阶段不需要工具
        response_stream = await call(context=messages, stream=True, include_tools=False)
        full_plan_text = ""
        async for chunk in response_stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    yield reasoning
                if delta.content:
                    full_plan_text += delta.content
                    yield delta.content

        # 解析计划
        try:
            plan_str = full_plan_text.split("```python")[1].split("```")[0].strip()
            plan = ast.literal_eval(plan_str)
            if isinstance(plan, list):
                self.current_plan = plan
            else:
                self.current_plan = []
        except Exception:
            self.current_plan = []

# --- 执行器 (Executor) ---
# 执行器模板中注入核心约束
EXECUTOR_PROMPT_TEMPLATE = """
你的任务是严格按照给定的计划，一步步地解决法律问题。

核心约束（执行过程中必须遵守）：
- 涉及法律依据的步骤，必须通过工具检索获取，禁止凭记忆作答。
- 如果当前步骤需要调用工具，使用格式 `Action: tool_name[tool_input]`。
- 每步只输出该步骤的执行结果，不要输出额外的对话或解释。

# 原始问题:
{question}

# 完整计划:
{plan}

# 历史步骤与结果:
{history}

# 当前步骤:
{current_step}

请仅输出针对"当前步骤"的回答:
"""

class Executor:
    def __init__(self):
        self.history = ""

    async def execute(self, question: str, plan: list[str], memory: list = None):
        self.history = ""

        yield "\n\n**开始执行计划...**\n"

        for i, step in enumerate(plan, 1):
            yield f"\n\n--- 步骤 {i}/{len(plan)}: {step} ---\n\n"

            prompt = EXECUTOR_PROMPT_TEMPLATE.format(
                question=question, plan=plan, history=self.history if self.history else "无", current_step=step
            )
            messages = (memory or []) + [{"role": "user", "content": prompt}]

            # 执行器不需要原生工具
            response_stream = await call(context=messages, stream=True, include_tools=False)
            step_result = ""
            async for chunk in response_stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        yield reasoning
                    if delta.content:
                        step_result += delta.content
                        yield delta.content

            self.history += f"步骤 {i}: {step}\n结果: {step_result}\n\n"

        yield "\n\n**任务执行完毕。**\n"

# --- 智能体 (Agent) 整合 ---
# 最终总结模板 — 注入输出格式要求
FINAL_SUMMARY_TEMPLATE = """
请根据以下执行过程，给出最终的详细法律分析回答。

要求：
1. 所有法律依据必须引用执行过程中工具检索到的内容，禁止自行添加未经检索的法条。
2. 正文引用法条时附带信源角标 `<sup><a href="URL">N</a></sup>`。
3. 文末必须包含 `## 参考信源` 区域。
4. 最终回复必须包裹在 `<final_answer>` 与 `</final_answer>` 标签中。

问题：{question}

执行过程：
{history}
"""


class PlanAndSolveAgent:
    def __init__(self, tools_description: str = "", execute_tool: Callable[[str, str], str] = None, memory: list = None, session_id: str = "default", workspace_scope: str = None, use_ocp: bool = False):
        self.planner = Planner()
        self.executor = Executor()
        self.memory = memory or []
        self.tools_description = tools_description
        self.execute_tool = execute_tool
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp

    @staticmethod
    def _sanitize_final_answer(raw: str) -> str:
        """清洗最终答案输出"""
        result = sanitize_llm_output(raw, enforce_final_answer=True)
        if not result.strip():
            fallback = strip_think_blocks(raw)
            fallback = strip_wrapper_tags(fallback)
            return fallback.strip()
        return result

    async def run(self, question: str):
        # 1. 制定计划
        async for chunk in self.planner.plan(question, memory=self.memory):
            yield {'type': 'thought', 'content': chunk}

        plan = getattr(self.planner, "current_plan", [])
        if not plan:
            yield {'type': 'thought', 'content': "\n\n无法生成有效的行动计划。\n"}
            return

        # 2. 执行计划
        yield {'type': 'thought', 'content': "\n\n**开始执行计划...**\n"}

        for i, step in enumerate(plan, 1):
            yield {'type': 'thought', 'content': f"\n\n--- 步骤 {i}/{len(plan)}: {step} ---\n\n"}

            # 在执行每个步骤前，让模型判断是否需要调用工具
            thought_prompt = f"""
原始问题: {question}
当前步骤: {step}
历史执行结果: {self.executor.history if self.executor.history else "无"}

可用工具:
{self.tools_description or "无"}

核心约束：涉及法律依据的内容必须通过工具检索获取，禁止凭记忆作答。

请分析当前步骤，如果需要调用工具，请输出：
Action: {{tool_name}}[{{tool_input}}]
否则直接输出你的分析和结果。
"""
            messages = (self.memory or []) + [{"role": "user", "content": thought_prompt}]

            # 执行阶段使用文本解析工具调用，禁用原生工具
            response_stream = await call(context=messages, stream=True, include_tools=False)
            step_result = ""
            async for chunk in response_stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        yield {'type': 'thought', 'content': reasoning, 'thought_type': 'reasoning', 'mode': 'append'}
                    if delta.content:
                        step_result += delta.content
                        yield {'type': 'thought', 'content': delta.content}

            # 检查是否有 Action 调用
            action_match = re.search(r"Action:\s*(\w+)\[(.*?)\]", step_result, re.DOTALL)
            if action_match and self.execute_tool:
                tool_name = action_match.group(1)
                tool_input = action_match.group(2)
                yield {'type': 'thought', 'content': f"\n\n**执行工具**: `{tool_name}[{tool_input}]`"}

                try:
                    observation = self.execute_tool(tool_name, tool_input)
                    yield {'type': 'thought', 'content': f"\n\n**观察**: {observation}\n"}

                    # 将工具结果喂回模型进行总结
                    summary_prompt = f"工具执行结果如下：\n{observation}\n请根据此结果完成当前步骤：{step}"
                    messages.append({"role": "assistant", "content": step_result})
                    messages.append({"role": "user", "content": summary_prompt})

                    # 总结阶段不需要工具
                    final_step_stream = await call(context=messages, stream=True, include_tools=False)
                    final_step_result = ""
                    async for chunk in final_step_stream:
                        if chunk.choices:
                            delta = chunk.choices[0].delta
                            if delta.content:
                                final_step_result += delta.content
                                yield {'type': 'thought', 'content': delta.content}
                    step_result = final_step_result
                except Exception as e:
                    yield {'type': 'thought', 'content': f"\n\n**工具执行失败**: {e}\n"}

            self.executor.history += f"步骤 {i}: {step}\n结果: {step_result}\n\n"

        # 3. 最终总结 — 使用带约束的模板
        summary_prompt = FINAL_SUMMARY_TEMPLATE.format(
            question=question,
            history=self.executor.history,
        )
        messages = (self.memory or []) + [{"role": "user", "content": summary_prompt}]
        # 最终总结不需要工具
        response_stream = await call(context=messages, stream=True, include_tools=False)
        current_signature = ""
        is_drafting = False
        final_answer = ""

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
                    final_answer += delta.content
                    if not is_drafting:
                        yield {'type': 'thought', 'content': '正在拟定回答初稿\n', 'thought_type': 'draft', 'mode': 'new'}
                        is_drafting = True
                    yield {'type': 'thought', 'content': delta.content, 'thought_type': 'draft', 'mode': 'append'}

        # ── 后处理管道 ──
        sanitized_answer = self._sanitize_final_answer(final_answer)

        if self.use_ocp and sanitized_answer.strip():
            yield {'type': 'memory_candidate', 'content': sanitized_answer}
            from ocp import OCPStream
            ocp = OCPStream(session_id=self.workspace_scope)
            async for ocp_chunk in ocp.check_stream(sanitized_answer):
                yield ocp_chunk
        else:
            yield {'type': 'content_replace', 'content': sanitized_answer}

        if current_signature:
            yield {'type': 'thought_signature', 'content': current_signature}
