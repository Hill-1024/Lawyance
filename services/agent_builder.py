"""
模块描述：Agent 构造服务，保持工具调用只能通过 mcps 转发。
"""

import json

from agents import DefaultAgent, PlanAndSolveAgent, ReActAgent
from mcps import format_tool_descriptions, use_tools


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
    if mode == "default":
        return DefaultAgent(
            memory=memory,
            session_id=session_id,
            workspace_scope=workspace_scope,
            use_ocp=use_ocp,
            execute_tool=execute_tool,
        )
    if mode in ["react", "plan_and_solve"]:
        tools_description = format_tool_descriptions()
        agent_memory = memory[:-1] if memory and memory[-1].get("role") == "user" else memory

        if mode == "react":
            return ReActAgent(
                tools_description=tools_description,
                execute_tool=execute_tool,
                memory=agent_memory,
                session_id=session_id,
                workspace_scope=workspace_scope,
                use_ocp=use_ocp,
            )
        if mode == "plan_and_solve":
            return PlanAndSolveAgent(
                tools_description=tools_description,
                execute_tool=execute_tool,
                memory=agent_memory,
                session_id=session_id,
                workspace_scope=workspace_scope,
                use_ocp=use_ocp,
            )
    return DefaultAgent(
        memory=memory,
        session_id=session_id,
        workspace_scope=workspace_scope,
        use_ocp=use_ocp,
        execute_tool=execute_tool,
    )
