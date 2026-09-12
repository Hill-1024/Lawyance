"""
模块描述：工作区路径边界工具，集中校验对话级 TEMP/Result 文件访问范围。
"""

import os


class WorkspacePathError(ValueError):
    pass


# 工作区两棵根目录：TEMP 存上传/中间产物，Result 存生成文件。
WORKSPACE_ROOTS = ("TEMP", "Result")


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
    allowed_roots: tuple[str, ...] = WORKSPACE_ROOTS,
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
    source_path = resolve_workspace_file(input_path, workspace_scope, allowed_roots=WORKSPACE_ROOTS)
    filename = os.path.basename(source_path)
    base, ext = os.path.splitext(filename)
    if not base.endswith("_lawver"):
        base = f"{base}_lawver"

    result_dir = os.path.join("Result", validate_workspace_scope(workspace_scope))
    os.makedirs(result_dir, exist_ok=True)
    return os.path.join(result_dir, f"{base}{ext}").replace("\\", "/")


def to_workspace_relative_path(path: str | None) -> str:
    """把任意形态的工作区路径折算成 `TEMP/…` 或 `Result/…` 相对形式。

    上传接口历史版本返回绝对路径，而列表接口、工具读取（resolve_workspace_file）
    和前端附件上传都以上述相对形式为准：绝对路径会被判为越界而静默丢弃，
    也会被前端误判成"生成文件"重复回灌到 Result 工作区。
    这里只做形式归一，越界校验仍由 resolve_workspace_file 按会话 scope 执行。
    """
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate:
        return ""
    parts = candidate.split("/")
    for root in WORKSPACE_ROOTS:
        if root in parts:
            return "/".join(parts[parts.index(root):])
    return candidate
