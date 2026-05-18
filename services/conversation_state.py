"""
模块描述：进程内对话活跃状态，供聊天、心跳和清理任务共享。
"""

active_conversations: dict[str, float] = {}
