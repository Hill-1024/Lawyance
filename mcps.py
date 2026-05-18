"""
模块描述：业务工具转发中间件，统一暴露法律检索、文件处理、企业查询和记忆工具。
"""

from tools import registry
from workspace import (
    WorkspacePathError,
    get_result_path,
    is_within_directory as _is_within_directory,
    resolve_workspace_file,
    validate_workspace_scope as _validate_workspace_scope,
    workspace_dir as _workspace_dir,
)


tools = registry.schemas("agent")


def format_tool_descriptions(tool_defs=None):
    return registry.format_descriptions(tool_defs)


def _coerce_arguments(function_name, arguments):
    return registry.coerce_arguments(function_name, arguments)


def use_tools(function_name, arguments, conv_id=None):
    # conv_id 在这里实际承载的是工作区作用域，保持参数名兼容既有调用方。
    return registry.dispatch(function_name, arguments, conv_id)


if __name__ == "__main__":
    use_tools("match_legal_case", {"keywords": ["上班途中车祸工伤案例"], "start_year": "2020-08-05", "end_year": "2025-08-05"})
