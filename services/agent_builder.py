"""
模块描述：Agent 构造服务，保持工具调用只能通过 mcps 转发。
"""

from agents import ToolLoopAgent
from agents.tool_loop import plan_and_solve_tool_choice_policy
from mcps import default_tools, plan_and_solve_tools
from tools import registry


def build_tool_executor(workspace_scope: str, capability: str = "agent"):
    # ToolLoopAgent._parse_arguments 已经把 raw arguments 解析成 dict；
    # registry.dispatch 也会再做一次 coerce_arguments，这里只需直接转发。
    def execute_tool(tool_name: str, arguments):
        return registry.dispatch(
            tool_name,
            arguments,
            workspace_scope,
            capability=capability,
        )

    return execute_tool


def build_agent(
    mode: str,
    memory: list,
    session_id: str,
    workspace_scope: str,
    use_ocp: bool = True,
    execution_policy: dict | None = None,
):
    if mode == "react":
        print("[agent_builder] 收到已废弃模式 react，自动降级为 default")
        mode = "default"

    if mode == "plan_and_solve":
        execute_tool = build_tool_executor(workspace_scope, "plan_and_solve")
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
            execution_policy=execution_policy,
        )

    execute_tool = build_tool_executor(workspace_scope, "agent")
    return ToolLoopAgent(
        memory=memory,
        session_id=session_id,
        workspace_scope=workspace_scope,
        use_ocp=use_ocp,
        execute_tool=execute_tool,
        mode="default",
        tools=default_tools,
        final_answer_source="tagged_text",
        execution_policy=execution_policy,
    )
