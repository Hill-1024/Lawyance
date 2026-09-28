"""
模块描述：业务工具转发中间件，统一暴露法律检索、文件处理、企业查询和记忆工具。

本模块是能力子系统的唯一路由：`tools`、`mcp/*`、`memory_system`、`RAG` 只允许在
这里被 import，业务层（`services/`、`agents/`、`routes/`）一律经此接受和转发请求。
"""

from tools import registry

# 转发暴露给业务测试与外部调用方的工作区路径工具，保持向后兼容。
from workspace import WorkspacePathError, get_result_path, resolve_workspace_file  # noqa: F401

# 记忆读写的公共入口与异常类型，业务层不再直接 import memory_system。
from mcp.memory_client import (
    reset_current_memory_turn_id,
    set_current_memory_turn_id,
)
from memory_system import MemoryRevisionConflict, prune_conversation_memory
from mcp.pkulaw_client import ensure_law_database_ready


default_tools = registry.schemas("agent")
plan_and_solve_tools = registry.schemas("plan_and_solve")
court_tools = registry.schemas("court")
ocp_tools = registry.schemas("ocp_reviewer")
tools = default_tools


def schemas(exposure=None):
    return registry.schemas(exposure)


def names(exposure=None):
    return registry.names(exposure)


def format_tool_descriptions(tool_defs=None):
    return registry.format_descriptions(tool_defs)


def _coerce_arguments(function_name, arguments):
    return registry.coerce_arguments(function_name, arguments)


def use_tools(function_name, arguments, conv_id=None, *, capability="agent"):
    # conv_id 在这里实际承载的是工作区作用域，保持参数名兼容既有调用方。
    # 公开转发默认只具有 agent 能力；内部控制工具必须由受信代码显式授权。
    return registry.dispatch(function_name, arguments, conv_id, capability=capability)


# 语义化别名：核心路由"接受并转发请求"的显式入口。
dispatch = use_tools


def prune_memory(max_age_seconds=None):
    """内部记忆裁剪：不注册成 LLM 可见工具，只经核心路由转发。"""
    return prune_conversation_memory(max_age_seconds)


if __name__ == "__main__":
    use_tools("match_legal_case", {"keywords": ["上班途中车祸工伤案例"], "start_year": "2020-08-05", "end_year": "2025-08-05"})
