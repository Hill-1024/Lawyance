"""
Plan & Solve 范式（两阶段）：

阶段一  Plan   —— 让模型先把复杂问题拆分成有序子任务列表
阶段二  Solve  —— 逐条执行子任务（可调用工具），收集中间结果，最终汇总

适合需要多步推理、长流程的任务，比 ReAct 更结构化。
"""

import os
import ast
from dotenv import load_dotenv
from typing import List, Dict

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

from tools import ToolExecutor

# Planner 定义
PLANNER_PROMPT_TEMPLATE = """
你是一个小学学生，在学习小学难度的数学。你的任务是将用户提出的数学问题分解成一个由多个简单步骤组成的行动计划。
请确保计划中的每个步骤都是一个独立的、可执行的子任务，并且严格按照逻辑顺序排列。
你的输出必须是一个Python列表，其中每个元素都是一个描述子任务的字符串。

问题: {question}

请严格按照以下格式输出你的计划，```python与```作为前后缀是必要的:
```python
["步骤1", "步骤2", "步骤3", ...]
```
"""

class Planner:
    def __init__(self):
        pass

    def plan(self, question: str, memory: list = None) -> list[str]:
        prompt = PLANNER_PROMPT_TEMPLATE.format(question=question)
        messages = (memory or []) + [{"role": "user", "content": prompt}]

        print("--- 正在生成计划 ---")
        response = call(context=messages)

        if response.tool_calls:
            # 触发了 function calling
            response_text = response.tool_calls
        else:
            # 普通文本回复
            response_text = response.content
        print(f"✅ 计划已生成:\n{response_text}")

        try:
            plan_str = response_text.split("```python")[1].split("```")[0].strip()
            plan = ast.literal_eval(plan_str)
            return plan if isinstance(plan, list) else []
        except (ValueError, SyntaxError, IndexError) as e:
            print(f"❌ 解析计划时出错: {e}")
            print(f"原始响应: {response_text}")
            return []
        except Exception as e:
            print(f"❌ 解析计划时发生未知错误: {e}")
            return []

# --- 3. 执行器 (Executor) 定义 ---
EXECUTOR_PROMPT_TEMPLATE = """
你是一位顶级的AI执行专家。你的任务是严格按照给定的计划，一步步地解决问题。
你将收到原始问题、完整的计划、以及到目前为止已经完成的步骤和结果。
请你专注于解决“当前步骤”，并仅输出该步骤的最终答案，不要输出任何额外的解释或对话。

# 原始问题:
{question}

# 完整计划:
{plan}

# 历史步骤与结果:
{history}

# 当前步骤:
{current_step}

请仅输出针对“当前步骤”的回答:
"""

class Executor:
    def __init__(self):
        pass

    def execute(self, question: str, plan: list[str], memory: list = None) -> str:
        history = ""
        final_answer = ""

        print("\n--- 正在执行计划 ---")
        for i, step in enumerate(plan, 1):
            print(f"\n-> 正在执行步骤 {i}/{len(plan)}: {step}")
            prompt = EXECUTOR_PROMPT_TEMPLATE.format(
                question=question, plan=plan, history=history if history else "无", current_step=step
            )
            messages = (memory or []) + [{"role": "user", "content": prompt}]

            response = call(context=messages)

            if response.tool_calls:
                # 触发了 function calling
                response_text = response.tool_calls
            else:
                # 普通文本回复
                response_text = response.content

            history += f"步骤 {i}: {step}\n结果: {response_text}\n\n"
            final_answer = response_text
            print(f"✅ 步骤 {i} 已完成，结果: {final_answer}")

        return final_answer

# --- 4. 智能体 (Agent) 整合 ---
class PlanAndSolveAgent:
    def __init__(self, memory: list = None):
        self.planner = Planner()
        self.executor = Executor()
        self.memory = memory or []

    def run(self, question: str):
        print(f"\n--- 开始处理问题 ---\n问题: {question}")
        plan = self.planner.plan(question, memory=self.memory)
        if not plan:
            print("\n--- 任务终止 --- \n无法生成有效的行动计划。")
            return "无法生成有效的行动计划。"
        final_answer = self.executor.execute(question, plan, memory=self.memory)
        print(f"\n--- 任务完成 ---\n最终答案: {final_answer}")
        return final_answer

# --- 5. 主函数入口 ---
if __name__ == '__main__':
    try:
        agent = PlanAndSolveAgent()
        question = "一个水果店周一卖出了15个西瓜。周二卖出的苹果数量是周一卖出西瓜数量的两倍。周三卖出的数量比周二少了5个。请问这三天总共卖出了多少个苹果？"
        agent.run(question)
    except ValueError as e:
        print(e)
