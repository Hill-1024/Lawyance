"""
模块描述：进程内对话活跃状态，供聊天、心跳和清理任务共享。
"""

active_conversations: dict[str, float] = {}

# 正在执行的工作台 run 的 workspace scope（TEMP/<user>/<run_id>）。
# run 的目录按 run_id 建，与会话 scope（user/<conversation_id>）不同，且长任务可能
# 超过 1 小时不写盘；清理任务必须把活跃 run 的 scope 一并视作活跃，否则归档前的
# 中间产物会被当成过期缓存整目录删除。
active_run_scopes: set[str] = set()
