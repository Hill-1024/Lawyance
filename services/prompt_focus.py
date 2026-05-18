"""
模块描述：当前轮动态 prompt 焦点选择。三类焦点常驻，由 prompt 文本自行判定是否激活。
"""


DEFAULT_PROMPT_FOCUS = ("general_gate", "file_processing", "legal_retrieval")


def current_focus(_content: str, _history: list[dict]) -> list[str]:
    return list(DEFAULT_PROMPT_FOCUS)
