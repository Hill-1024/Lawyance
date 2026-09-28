"""
模块描述：services.multimodal 兼容转发层，实现已迁至中性模块 media。

保留此 shim 只为兼容既有导入路径（tests）；新代码请直接 from media import ...。
"""

from media import (  # noqa: F401
    IMAGE_SIGNAL_KEY,
    MAX_IMAGE_VIEWS_PER_TURN,
    MAX_VIEW_TOTAL_BYTES,
    flatten_content_to_text,
    load_workspace_image,
)

__all__ = [
    "IMAGE_SIGNAL_KEY",
    "MAX_IMAGE_VIEWS_PER_TURN",
    "MAX_VIEW_TOTAL_BYTES",
    "flatten_content_to_text",
    "load_workspace_image",
]
