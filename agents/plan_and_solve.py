"""
Plan & Solve 范式（两阶段）：

阶段一  Plan   —— 让模型先把复杂问题拆分成有序子任务列表
阶段二  Solve  —— 逐条执行子任务（可调用工具），收集中间结果，最终汇总

适合需要多步推理、长流程的任务，比 ReAct 更结构化。
"""

import os
import ast

import asyncio
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
你是由广东工业大学工大法智团队开发的规划专家，擅长为法律任务规划行动计划。
你的任务是将用户提出的任务分解成一个由多个简单步骤组成的行动计划。
请确保计划中的每个步骤都是一个独立的、可执行的子任务，并且严格按照逻辑顺序排列。
你的输出必须是一个Python列表，其中每个元素都是一个描述子任务的字符串。

问题: {question}

请严格按照以下格式输出你的计划，```python与```作为前后缀是必要的:
```python
["步骤1", "步骤2", "步骤3", ...]
```

Few Shot Examples:

示例1:
问题: 我被公司无故解雇，想申请劳动仲裁，应该怎么做？
```python
[
    "明确案件基本事实：梳理被解雇的时间、原因及公司给出的理由",
    "检索适用法律条文：查找《劳动合同法》中关于违法解除劳动合同的相关规定（如第48条、第87条）",
    "判断是否构成违法解除：对比公司行为与法定解除条件，评估公司是否存在违法情形",
    "计算可主张的赔偿金额：根据工作年限和月薪计算二倍经济补偿金（N×2）",
    "确认仲裁时效：确认劳动争议仲裁时效为1年，并核实是否在时效内",
    "准备仲裁申请材料：列明需收集的证据清单（劳动合同、工资流水、解雇通知书等）",
    "指引仲裁申请流程：说明向用人单位所在地劳动仲裁委员会提交申请的具体步骤"
]
```

示例2:
问题: 我借给朋友10万元，约定6个月还款，现在已经逾期3个月，我想通过法律途径追回借款。
```python
[
    "梳理借贷事实：确认借款金额、借款时间、约定还款期限及当前逾期情况",
    "审查债权凭证效力：评估借条、转账记录、微信聊天记录等证据的法律效力",
    "检索适用法律条文：查找《民法典》关于民间借贷、诉讼时效的相关规定（第667-680条）",
    "核实利息约定合法性：判断约定利率是否超过法定上限（LPR的4倍），评估逾期利息的可主张范围",
    "评估诉讼时效：确认普通诉讼时效为3年，核实是否存在时效中断情形",
    "选择诉讼策略：比较直接起诉与申请支付令两种途径的适用条件和效率",
    "确定管辖法院：根据被告住所地或合同履行地确定有管辖权的基层人民法院",
    "准备起诉材料：列明起诉状撰写要点及需提交的证据清单"
]
```

示例3:
问题: 我购买的新房存在严重质量问题，开发商拒绝维修，我该如何维权？
```python
[
    "固定房屋质量问题证据：说明如何通过拍照、录像、第三方检测报告等方式保全证据",
    "检索房屋质量法律标准：查找《建筑法》《商品房销售管理办法》及相关工程质量强制标准",
    "审查购房合同条款：分析合同中关于工程质量保修责任、违约责任的具体约定",
    "判断开发商违约责任：对比质量问题与合同约定及法定标准，认定开发商是否构成违约",
    "评估可主张的救济方式：分析要求维修、减少价款、赔偿损失乃至解除合同的适用条件",
    "尝试行政投诉途径：指引向当地住房和城乡建设局投诉的流程及预期效果",
    "制定诉讼方案：确定诉讼请求、管辖法院及诉讼费用预估"
]
```
"""

class Planner:
    def __init__(self):
        pass

    async def plan(self, question: str, memory: list = None):
        prompt = PLANNER_PROMPT_TEMPLATE.format(question=question)
        messages = (memory or []) + [{"role": "user", "content": prompt}]

        yield "\n\n📝 **正在制定计划...**\n\n"

        response_stream = await call(context=messages, stream=True)
        full_plan_text = ""
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_plan_text += content
                yield content

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

    async def execute(self, question: str, plan: list[str], memory: list = None):
        history = ""

        yield "\n\n🚀 **开始执行计划...**\n"

        for i, step in enumerate(plan, 1):
            yield f"\n\n--- 步骤 {i}/{len(plan)}: {step} ---\n\n"

            prompt = EXECUTOR_PROMPT_TEMPLATE.format(
                question=question, plan=plan, history=history if history else "无", current_step=step
            )
            messages = (memory or []) + [{"role": "user", "content": prompt}]

            response_stream = await call(context=messages, stream=True)
            step_result = ""
            async for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    step_result += content
                    yield content

            history += f"步骤 {i}: {step}\n结果: {step_result}\n\n"

        yield "\n\n✅ **任务执行完毕。**\n"

# --- 4. 智能体 (Agent) 整合 ---
class PlanAndSolveAgent:
    def __init__(self, memory: list = None):
        self.planner = Planner()
        self.executor = Executor()
        self.memory = memory or []

    async def run(self, question: str):
        # 1. 制定计划
        async for chunk in self.planner.plan(question, memory=self.memory):
            yield chunk

        plan = getattr(self.planner, "current_plan", [])
        if not plan:
            yield "\n\n❌ 无法生成有效的行动计划。\n"
            return

        # 2. 执行计划
        async for chunk in self.executor.execute(question, plan, memory=self.memory):
            yield chunk

# --- 5. 主函数入口 ---
if __name__ == '__main__':
    try:
        agent = PlanAndSolveAgent()
        question = "一个水果店周一卖出了15个西瓜。周二卖出的苹果数量是周一卖出西瓜数量的两倍。周三卖出的数量比周二少了5个。请问这三天总共卖出了多少个苹果？"
        asyncio.run(agent.run(question))
    except ValueError as e:
        print(e)
