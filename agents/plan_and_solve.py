"""
模块描述：Plan & Solve Agent，先规划任务步骤，再逐步执行工具调用并汇总最终回答。
"""

import ast
import os
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


def _optional_positive_int_env(name: str, default: int | None = None):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    raw_value = raw_value.strip()
    if raw_value.lower() in {"none", "unlimited", "off", "0", "-1"}:
        return None
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else None


PLANNER_TASK_TEMPLATE = """# 当前问题
{question}

请根据系统中的 Plan-and-Solve 模式要求输出行动计划。
"""

EXECUTOR_TASK_TEMPLATE = """# 原始问题
{question}

# 可用工具
{tools}

# 完整计划
{plan}

# 历史步骤与结果
{history}

# 当前步骤
{current_step}

请执行当前步骤。
"""

TOOL_OBSERVATION_TASK_TEMPLATE = """# 当前步骤
{step}

# 工具执行结果
{observation}

请基于工具结果完成当前步骤，只输出该步骤结果。
"""

FINAL_SUMMARY_TASK_TEMPLATE = """# 原始问题
{question}

# 执行过程
{history}

请根据系统中的最终回复要求输出最终答案。
"""


def _parse_plan_list(raw_text: str) -> list[str]:
    if not raw_text:
        return []

    fence_match = re.search(r"```(?:python|json)?\s*(.*?)```", raw_text, flags=re.IGNORECASE | re.DOTALL)
    candidates = []
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    bracket_match = re.search(r"\[[\s\S]*\]", raw_text)
    if bracket_match:
        candidates.append(bracket_match.group(0).strip())

    candidates.append(raw_text.strip())
    for candidate in candidates:
        try:
            parsed = ast.literal_eval(candidate)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]

    return []

class Planner:
    def __init__(self):
        pass

    async def plan(self, question: str, memory: list = None):
        prompt = PLANNER_TASK_TEMPLATE.format(question=question)
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

        self.current_plan = _parse_plan_list(full_plan_text)

# --- 执行器 (Executor) ---

class Executor:
    def __init__(self):
        self.history = ""

    async def execute(self, question: str, plan: list[str], memory: list = None, tools_description: str = ""):
        self.history = ""

        yield "\n\n**开始执行计划...**\n"

        for i, step in enumerate(plan, 1):
            yield f"\n\n--- 步骤 {i}/{len(plan)}: {step} ---\n\n"

            prompt = EXECUTOR_TASK_TEMPLATE.format(
                question=question,
                tools=tools_description or "无",
                plan=plan,
                history=self.history if self.history else "无",
                current_step=step,
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
class PlanAndSolveAgent:
    MAX_PLAN_STEPS = _optional_positive_int_env("LAWVER_PLAN_MAX_STEPS", 8)

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
            message = "Plan-and-Solve 模式无法生成有效行动计划，流程已停止。"
            yield {'type': 'thought', 'content': f"\n\n{message}\n"}
            yield {'type': 'content', 'content': message}
            return
        if isinstance(self.MAX_PLAN_STEPS, int) and len(plan) > self.MAX_PLAN_STEPS:
            yield {
                'type': 'thought',
                'content': f"\n\n计划步骤超过最大限制 ({self.MAX_PLAN_STEPS})，已截断后续步骤以避免循环失控。\n",
            }
            plan = plan[:self.MAX_PLAN_STEPS]

        # 2. 执行计划
        yield {'type': 'thought', 'content': "\n\n**开始执行计划...**\n"}

        for i, step in enumerate(plan, 1):
            yield {'type': 'thought', 'content': f"\n\n--- 步骤 {i}/{len(plan)}: {step} ---\n\n"}

            # 在执行每个步骤前，让模型判断是否需要调用工具；范式规则来自动态 system prompt。
            thought_prompt = EXECUTOR_TASK_TEMPLATE.format(
                question=question,
                tools=self.tools_description or "无",
                plan=plan,
                history=self.executor.history if self.executor.history else "无",
                current_step=step,
            )
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
                    summary_prompt = TOOL_OBSERVATION_TASK_TEMPLATE.format(step=step, observation=observation)
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

        # 3. 最终总结 — 输出契约来自动态 system prompt
        summary_prompt = FINAL_SUMMARY_TASK_TEMPLATE.format(
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
