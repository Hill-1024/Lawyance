"""
模块描述：后台清理任务，删除过期 workspace 缓存并裁剪服务端记忆缓存。
"""

import asyncio
import os
import shutil
import time

from fastapi import FastAPI

from memory_system import prune_conversation_memory
from services.conversation_state import active_conversations
from services.memory_coordinator import call_memory_tool


def safe_listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except (FileNotFoundError, NotADirectoryError):
        return []


def cleanup_expired_workspace_dirs(one_hour_ago: float, active_scopes: set[str]):
    for folder in ["TEMP", "Result"]:
        if not os.path.isdir(folder):
            continue

        for user_dir_name in safe_listdir(folder):
            user_dir = os.path.join(folder, user_dir_name)
            if not os.path.isdir(user_dir):
                continue

            for conv_id in safe_listdir(user_dir):
                conv_dir = os.path.join(user_dir, conv_id)
                if not os.path.isdir(conv_dir):
                    continue

                scope = f"{user_dir_name}/{conv_id}"
                if scope in active_scopes:
                    continue

                try:
                    mtime = os.path.getmtime(conv_dir)
                    if mtime < one_hour_ago:
                        shutil.rmtree(conv_dir, ignore_errors=True)
                        print(f"[清理] 已彻底删除过期会话缓存: {conv_dir}")
                except Exception as e:
                    print(f"[清理] 删除会话缓存失败 {conv_dir}: {e}")

            try:
                if not safe_listdir(user_dir):
                    os.rmdir(user_dir)
            except OSError:
                pass


async def cleanup_task():
    """
    后台清理任务：每10分钟运行一次，删除超过1小时未活跃会话的 TEMP 和 Result 缓存。
    """
    while True:
        try:
            now = time.time()
            one_hour_ago = now - 3600

            stale_keys = [k for k, v in active_conversations.items() if v < one_hour_ago]
            for k in stale_keys:
                del active_conversations[k]
                await asyncio.to_thread(call_memory_tool, "clear_conversation_memory", {}, k)

            await asyncio.to_thread(
                prune_conversation_memory,
                int(os.getenv("LAWYANCE_MEMORY_CACHE_TTL_SECONDS", str(7 * 24 * 3600))),
            )

            await asyncio.to_thread(
                cleanup_expired_workspace_dirs,
                one_hour_ago,
                set(active_conversations),
            )

        except Exception as e:
            print(f"[清理] 任务运行出错: {e}")

        await asyncio.sleep(600)


def start(app: FastAPI) -> None:
    app.state.workspace_cleanup_task = asyncio.create_task(cleanup_task())


async def stop(app: FastAPI) -> None:
    task = getattr(app.state, "workspace_cleanup_task", None)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        app.state.workspace_cleanup_task = None
