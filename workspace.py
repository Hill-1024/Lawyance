"""
模块描述：工作区路径边界工具，集中校验对话级 TEMP/Result 文件访问范围。
"""

import os


class WorkspacePathError(ValueError):
    pass


def is_within_directory(path: str, directory: str) -> bool:
    # realpath 同时解析已有父目录中的符号链接；仅用 abspath 会把
    # `TEMP/user/conv/link/secret` 错判为仍在工作区内。
    real_path = os.path.realpath(os.path.abspath(path))
    real_dir = os.path.realpath(os.path.abspath(directory))
    try:
        return os.path.commonpath((real_path, real_dir)) == real_dir
    except ValueError:
        # Windows 跨盘符路径没有共同根。
        return False


def validate_workspace_scope(workspace_scope: str | None) -> str:
    if not workspace_scope or os.path.isabs(workspace_scope):
        raise WorkspacePathError("无法获取当前工作区作用域。")
    parts = str(workspace_scope).replace("\\", "/").split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise WorkspacePathError("工作区作用域格式非法。")
    return os.path.join(*parts)


def workspace_dir(root: str, workspace_scope: str | None) -> str:
    return os.path.abspath(os.path.join(root, validate_workspace_scope(workspace_scope)))


def resolve_workspace_file(
    input_path: str | None,
    workspace_scope: str | None,
    allowed_roots: tuple[str, ...] = ("TEMP", "Result"),
) -> str:
    if not input_path:
        raise WorkspacePathError("未提供文件路径。")

    normalized_path = str(input_path).replace("\\", "/").strip()
    if os.path.isabs(normalized_path):
        raise WorkspacePathError("不允许使用绝对路径。")

    candidate = os.path.abspath(normalized_path)
    allowed_dirs = [workspace_dir(root, workspace_scope) for root in allowed_roots]
    if not any(is_within_directory(candidate, directory) for directory in allowed_dirs):
        raise WorkspacePathError("文件路径不属于当前工作区。")
    return candidate


def get_result_path(input_path: str | None, workspace_scope: str | None) -> str:
    source_path = resolve_workspace_file(input_path, workspace_scope, allowed_roots=("TEMP", "Result"))
    filename = os.path.basename(source_path)
    base, ext = os.path.splitext(filename)
    if not base.endswith("_lawver"):
        base = f"{base}_lawver"

    result_dir = os.path.join("Result", validate_workspace_scope(workspace_scope))
    os.makedirs(result_dir, exist_ok=True)
    return os.path.join(result_dir, f"{base}{ext}").replace("\\", "/")
