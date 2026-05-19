"""
模块描述：Agent 构造服务，保持工具调用只能通过 mcps 转发。
"""

import json

from agents import ToolLoopAgent
from agents.tool_loop import plan_and_solve_tool_choice_policy
from mcps import default_tools, plan_and_solve_tools, use_tools


def build_tool_executor(workspace_scope: str):
    def execute_tool(tool_name: str, raw_args):
        parsed_args = raw_args
        if isinstance(raw_args, str) and raw_args.strip().startswith("{"):
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed_args = raw_args
        return use_tools(tool_name, parsed_args, conv_id=workspace_scope)

    return execute_tool


def build_agent(mode: str, memory: list, session_id: str, workspace_scope: str, use_ocp: bool = True):
    execute_tool = build_tool_executor(workspace_scope)
    if mode == "react":
        print("[agent_builder] 收到已废弃模式 react，自动降级为 default")
        mode = "default"

    if mode == "plan_and_solve":
        return ToolLoopAgent(
            memory=memory,
            session_id=session_id,
            workspace_scope=workspace_scope,
            use_ocp=use_ocp,
            execute_tool=execute_tool,
            mode="plan_and_solve",
            tools=plan_and_solve_tools,
            final_answer_source="tool_arg",
            tool_choice_policy=plan_and_solve_tool_choice_policy,
        )

    return ToolLoopAgent(
        memory=memory,
        session_id=session_id,
        workspace_scope=workspace_scope,
        use_ocp=use_ocp,
        execute_tool=execute_tool,
        mode="default",
        tools=default_tools,
        final_answer_source="tagged_text",
    )
