from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import json
import subprocess
import sys
import atexit
import os
import copy
import time
import asyncio
import signal
import shutil

from function_calling import call, memory as system_memory, create_assistant_message, fix_sessions_reasoning
from agents import ReActAgent, PlanAndSolveAgent
from mcps import use_tools

from contextlib import asynccontextmanager

last_heartbeat_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(check_heartbeat())
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/api/heartbeat")
async def heartbeat():
    global last_heartbeat_time
    last_heartbeat_time = time.time()
    # print("[心跳] 收到前端活跃信号")
    return {"status": "ok"}


async def check_heartbeat():
    global last_heartbeat_time
    print("[心跳检查] 启动心跳检查任务")
    # 给前端更多时间进行初始连接（特别是在开发模式下 Vite 编译较慢时）
    last_heartbeat_time = time.time() + 120
    while True:
        await asyncio.sleep(5)
        # 如果超过 120 秒没有收到心跳，则认为前端已关闭
        diff = time.time() - last_heartbeat_time
        if diff > 120:
            print(f"检测到长时间无页面活动（{diff:.1f}秒内无心跳），正在自动关闭后端服务以节省资源...")
            try:
                save_sessions()
                print("会话数据已保存。")
            except Exception as e:
                print(f"保存会话失败: {e}")

            os._exit(0)


# 配置 CORS，允许 React 前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境下允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 定义前端请求的数据格式
class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"
    stream: bool = True
    agent_mode: str = "default"


class SummarizeRequest(BaseModel):
    conversation_id: str


class DeleteRequest(BaseModel):
    conversation_id: str


# 确保数据目录存在
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
TITLES_FILE = os.path.join(DATA_DIR, "titles.json")
sessions = {}
titles = {}


def load_sessions():
    global sessions, titles
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)

                sessions = fix_sessions_reasoning(sessions)

                print(f"已加载 {len(sessions)} 个历史会话。")
        except Exception as e:
            print(f"加载历史会话失败: {e}")
            sessions = {}
    else:
        sessions = {}

    if os.path.exists(TITLES_FILE):
        try:
            with open(TITLES_FILE, "r", encoding="utf-8") as f:
                titles = json.load(f)
        except Exception as e:
            print(f"加载标题失败: {e}")
            titles = {}
    else:
        titles = {}


def save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
        with open(TITLES_FILE, "w", encoding="utf-8") as f:
            json.dump(titles, f, ensure_ascii=False, indent=2)
        print("会话数据已保存。")
    except Exception as e:
        print(f"保存会话失败: {e}")


def signal_handler(sig, frame):
    print(f"\n接收到信号 {sig}，正在保存数据并退出...")
    save_sessions()
    sys.exit(0)


# 注册信号处理程序
signal.signal(signal.SIGINT, signal_handler)
if sys.platform == "win32":
    # SIGBREAK 在 Windows 上用于处理控制台窗口关闭
    signal.signal(signal.SIGBREAK, signal_handler)

atexit.register(save_sessions)

load_sessions()


def get_session_memory(session_id: str):
    if session_id not in sessions:
        sessions[session_id] = copy.deepcopy(system_memory)
        save_sessions()
    return sessions[session_id]


import asyncio
from tools import ToolExecutor, search


# Agent 构建函数，根据前端传来的 agent_mode 返回对应的 Agent 实例
def build_agent(mode: str, memory: list):
    """
    根据 agent_mode 字段返回对应的 Agent 实例。
    mode 不合法时退回 None（走原有 default 逻辑）。
    """
    if mode == "react":
        tool_executor = ToolExecutor()
        tool_executor.registerTool("Search",
                                   "一个网页搜索引擎。当你需要回答关于时事、事实以及在你的知识库中找不到的信息时，应使用此工具。",
                                   search)
        return ReActAgent(tool_executor=tool_executor, memory=memory)
    if mode == "plan_and_solve":
        return PlanAndSolveAgent(memory=memory)
    return None


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    global last_heartbeat_time
    last_heartbeat_time = time.time()
    content = request.message
    session_id = request.conversation_id
    stream = request.stream
    agent_mode = request.agent_mode

    print(f"\n[收到请求] 会话ID: {session_id}, 模式: {agent_mode}, 流式: {stream}")
    print(f"[用户消息]: {content}")

    try:
        mem = get_session_memory(session_id)
        mem.append({"role": "user", "content": content})
        save_sessions()
        print(f"[会话已更新] 当前上下文消息数: {len(mem)}")
    except Exception as e:
        print(f"[会话更新失败]: {e}")
        return {"error": str(e)}

    agent = build_agent(agent_mode, mem)

    if agent:
        if stream:
            async def generate_agent():
                print(f"[Agent模式] 开始运行: {agent_mode}")
                full_result = ""
                try:
                    print(f"[Agent模式] 执行 agent.run...")
                    async for chunk in agent.run(content):
                        if chunk:
                            full_result += chunk
                            yield chunk

                    if full_result:
                        print(f"[Agent模式] 任务完成，结果长度: {len(full_result)}")
                        msg = create_assistant_message(content=full_result)
                        mem.append(msg)
                    else:
                        print("[Agent模式] 未生成结果")
                        yield "\nAgent未能生成有效结果。\n"
                        msg = create_assistant_message(content="Agent failed to produce a result.")
                        mem.append(msg)
                    save_sessions()
                except Exception as e:
                    print(f"[Agent模式] 异常: {e}")
                    yield f"\n[Agent 错误]: {e}\n"

            return StreamingResponse(
                generate_agent(),
                media_type="text/plain",
                headers={
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
        else:
            try:
                full_result = ""
                async for chunk in agent.run(content):
                    full_result += chunk
                result = full_result if full_result else "Agent failed to produce a result."
            except Exception as e:
                result = f"Error: {e}"
            msg = create_assistant_message(content=result)
            mem.append(msg)
            save_sessions()
            return {"reply": result}

    if stream:
        async def generate():
            print("[默认模式] 开始流式生成...")
            try:
                current_mem = mem
                while True:
                    print(f"[默认模式] 调用 LLM, 上下文长度: {len(current_mem)}")
                    response = await call(current_mem, True)
                    print("[默认模式] LLM 响应已开始")

                    tool_calls = []
                    content_str = ""
                    reasoning_str = ""
                    is_tool_call = False
                    has_started_reasoning = False
                    has_finished_reasoning = False

                    async for chunk in response:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta

                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            if not has_started_reasoning:
                                yield "<think>\n"
                                content_str += "<think>\n"
                                has_started_reasoning = True
                            content_str += reasoning
                            reasoning_str += reasoning
                            yield reasoning

                        if delta.content is not None:
                            if has_started_reasoning and not has_finished_reasoning:
                                yield "\n</think>\n"
                                content_str += "\n</think>\n"
                                has_finished_reasoning = True
                            content_str += delta.content
                            yield delta.content

                        if delta.tool_calls:
                            if has_started_reasoning and not has_finished_reasoning:
                                yield "\n</think>\n"
                                content_str += "\n</think>\n"
                                has_finished_reasoning = True
                            is_tool_call = True
                            for tc in delta.tool_calls:
                                while len(tool_calls) <= tc.index:
                                    tool_calls.append({
                                        "id": tc.id,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    })
                                if tc.id:
                                    tool_calls[tc.index]["id"] = tc.id
                                if tc.function.name:
                                    tool_calls[tc.index]["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls[tc.index]["function"]["arguments"] += tc.function.arguments

                    if has_started_reasoning and not has_finished_reasoning:
                        yield "\n</think>\n"
                        content_str += "\n</think>\n"
                        has_finished_reasoning = True

                    if is_tool_call:
                        print(f"[默认模式] 工具调用: {len(tool_calls)} 个请求")
                        # 提示用户正在调用工具
                        if "<think>" in content_str and "</think>" not in content_str.split("<think>")[-1]:
                            yield "\n</think>\n"
                        yield "\n<think>\n️ **正在调用工具处理中...**\n"

                        # 保存助手发出的工具调用请求
                        assistant_msg = create_assistant_message(
                            content=content_str or None,
                            reasoning_content=reasoning_str,
                            tool_calls=tool_calls
                        )
                        current_mem.append(assistant_msg)
                        save_sessions()

                        # 执行工具调用
                        for tc in tool_calls:
                            func_name = tc["function"]["name"]
                            args_str = tc["function"]["arguments"]
                            try:
                                args = json.loads(args_str)
                            except:
                                args = {}
                            print(f"  - 执行: {func_name}, 参数: {args}")
                            yield f"️ 执行: `{func_name}`\n"
                            result = use_tools(func_name, args)
                            current_mem.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": func_name,
                                "content": str(result)
                            })
                        save_sessions()
                        yield " **工具执行完毕，正在生成最终回复...**\n</think>\n"
                        # 继续循环，让模型根据工具结果生成回复
                        continue
                    else:
                        # 最终回复完成
                        if content_str:
                            print(f"[默认模式] 回复完成: {content_str[:50]}...")
                            assistant_msg = create_assistant_message(
                                content=content_str,
                                reasoning_content=reasoning_str
                            )
                            current_mem.append(assistant_msg)
                            save_sessions()
                        else:
                            print("[默认模式] 警告: 模型输出了空内容")
                        break
            except Exception as e:
                error_msg = f"\n\n[后端错误]: {str(e)}"
                print(f"[默认模式] 异常: {e}")
                yield error_msg

        return StreamingResponse(
            generate(),
            media_type="text/plain",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    else:
        res = await call(mem, stream=False)

        content = res.content or ""
        reasoning = getattr(res, 'reasoning_content', None)
        if reasoning:
            content = f"<think>\n{reasoning}\n</think>\n" + content

        if res.tool_calls:
            print("模型请求调用工具:", [t.function.name for t in res.tool_calls])
            tool_calls = [
                {
                    "id": t.id,
                    "type": "function",
                    "function": {
                        "name": t.function.name,
                        "arguments": t.function.arguments
                    }
                } for t in res.tool_calls
            ]
            assistant_msg = create_assistant_message(
                content=content,
                reasoning_content=reasoning,
                tool_calls=tool_calls
            )
            mem.append(assistant_msg)
            save_sessions()

            for tool_call in res.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                result = use_tools(function_name, arguments)
                mem.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": str(result)
                })
            save_sessions()

            final_message = await call(mem, stream=False)
            final_content = final_message.content or ""
            final_reasoning = getattr(final_message, 'reasoning_content', None)
            if final_reasoning:
                final_content = f"<think>\n{final_reasoning}\n</think>\n" + final_content
            print("最终回复:", final_content)
            final_msg = create_assistant_message(
                content=final_content,
                reasoning_content=final_reasoning
            )
            mem.append(final_msg)
            save_sessions()
            return {"reply": final_content}
        else:
            print("模型回复:", content)
            msg = create_assistant_message(
                content=content,
                reasoning_content=reasoning
            )
            mem.append(msg)
            save_sessions()
            return {"reply": content}


@app.get("/api/conversations")
async def get_conversations():
    # 返回所有会话的摘要信息和消息
    print(f"[获取会话] 当前共有 {len(sessions)} 个会话")
    result = {}
    for session_id, mem in sessions.items():
        result[session_id] = {
            "title": titles.get(session_id, "New Chat"),
            "messages": mem
        }
    return result


@app.post("/api/summarize")
async def summarize_endpoint(request: SummarizeRequest):
    session_id = request.conversation_id
    mem = get_session_memory(session_id)

    temp_mem = copy.deepcopy(mem)
    temp_mem.append({"role": "user",
                     "content": "请用一句话（不超过10个字）总结我们目前的对话内容，作为对话标题。只输出标题文本，不要包含任何标点符号或其他说明。"})

    response = await call(temp_mem, stream=False)
    title = (response.content or "").strip()
    if not title:
        title = "New Chat"
    if title.startswith('"') and title.endswith('"'):
        title = title[1:-1]
    if title.startswith("'") and title.endswith("'"):
        title = title[1:-1]

    titles[session_id] = title
    save_sessions()

    return {"title": title}


@app.post("/api/delete_conversation")
async def delete_conversation(request: DeleteRequest):
    session_id = request.conversation_id
    if session_id in sessions:
        del sessions[session_id]
    if session_id in titles:
        del titles[session_id]
    save_sessions()
    return {"status": "success"}


# 挂载 React 编译后的静态文件（用于生产环境）
if os.path.exists("dist"):
    # API 路由必须在静态文件挂载之前定义（FastAPI 按顺序匹配）
    # 挂载静态资源目录（js, css, images 等）
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")


    # 处理 SPA 路由：所有非 /api 开头的请求如果找不到文件，都返回 index.html
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        if full_path.startswith("api/"):
            return {"error": "API route not found"}, 404

        # 检查文件是否存在
        file_path = os.path.join("dist", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # 默认返回 index.html
        return FileResponse("dist/index.html")
else:
    @app.get("/")
    async def root():
        return {"message": "Agent is running. Send POST requests to /api/chat"}


# Agent
def setup():
    """检查并安装必要的依赖"""
    print("\n" + "=" * 40)
    print("正在检查项目环境...")
    print("=" * 40 + "\n")

    # 1. 检查 Node.js 环境
    node_cmd = "node.exe" if sys.platform == "win32" else "node"
    if not shutil.which(node_cmd):
        print("错误: 未检测到 Node.js。请先安装 Node.js (https://nodejs.org/)。")
        return False

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if not shutil.which(npm_cmd):
        print("错误: 未检测到 npm。请先安装 Node.js (https://nodejs.org/)。")
        return False

    # 2. 检查 node_modules
    if not os.path.exists("node_modules"):
        print("未检测到 node_modules，正在执行 npm install...")
        try:
            subprocess.run([npm_cmd, "install"], check=True)
            print("npm install 执行成功。")
        except subprocess.CalledProcessError as e:
            print(f"npm install 执行失败: {e}")
            return False

    # 3. 检查 Python 依赖
    if os.path.exists("requirements.txt"):
        print("正在检查 Python 依赖...")
        try:
            # 使用列表形式避免路径空格问题
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
            print("Python 依赖检查/安装完成。")
        except subprocess.CalledProcessError as e:
            print(f"Python 依赖安装失败: {e}")
            # 继续执行，可能已经安装过了

    return True


if __name__ == '__main__':
    # 执行环境检查与依赖安装
    setup()

    # 默认端口
    env_port = int(os.getenv("PORT", 3000))

    print("\n" + "=" * 50)
    print(f"系统启动中...")
    print(f"本地访问地址: http://127.0.0.1:{env_port}")
    print(f"外部访问地址: http://0.0.0.0:{env_port}")
    print("=" * 50 + "\n")

    # 只有在开发模式（无 dist）下才尝试启动 Vite
    if not os.path.exists("dist"):
        print("\n检测到开发环境，正在尝试启动前端开发服务器...")
        # 开发模式下：
        # 1. 后端监听 8000 端口
        # 2. 前端 (Vite) 监听 3000 端口并代理到 8000
        backend_port = 8000

        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        if shutil.which(npm_cmd):
            try:
                is_win = sys.platform == "win32"
                frontend_process = subprocess.Popen([npm_cmd, "run", "dev:frontend"], shell=is_win)


                def cleanup():
                    print("\n正在关闭系统...")
                    save_sessions()
                    if 'frontend_process' in locals():
                        frontend_process.terminate()


                atexit.register(cleanup)
            except Exception as e:
                print(f"前端启动失败: {e}")
    else:
        print("\n检测到生产环境 (dist)，将由 FastAPI 提供全栈服务。")
        # 生产模式下：
        backend_port = env_port

    print(f"\n后端服务启动中，监听 {backend_port} 端口...")
    uvicorn.run(app, host="0.0.0.0", port=backend_port)
