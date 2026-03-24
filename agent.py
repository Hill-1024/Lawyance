from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
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

from function_calling import call, memory as system_memory
from mcps import use_tools
from agents import ReActAgent, PlanAndSolveAgent

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
    return {"status": "ok"}


async def check_heartbeat():
    global last_heartbeat_time
    # Give frontend 30 seconds to connect initially
    last_heartbeat_time = time.time() + 30
    while True:
        await asyncio.sleep(5)
        if time.time() - last_heartbeat_time > 15:
            print("No heartbeat received from frontend for 15 seconds. Shutting down backend...")
            save_sessions()
            os.kill(os.getpid(), signal.SIGTERM)


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


SESSIONS_FILE = "sessions.json"
TITLES_FILE = "titles.json"
sessions = {}
titles = {}


def load_sessions():
    global sessions, titles
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)
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
    except Exception as e:
        print(f"保存会话失败: {e}")


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
    content = request.message
    session_id = request.conversation_id
    stream = request.stream
    agent_mode = request.agent_mode

    mem = get_session_memory(session_id)
    mem.append({"role": "user", "content": content})
    save_sessions()

    agent = build_agent(agent_mode, mem)

    if agent:
        if stream:
            async def generate_agent():
                yield "Agent is thinking...\n\n"
                await asyncio.sleep(0.1)
                try:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, agent.run, content)
                    if result:
                        yield result
                        mem.append({"role": "assistant", "content": result})
                    else:
                        yield "Agent failed to produce a result."
                        mem.append({"role": "assistant", "content": "Agent failed to produce a result."})
                    save_sessions()
                except Exception as e:
                    yield f"Error: {e}"

            return StreamingResponse(generate_agent(), media_type="text/plain")
        else:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, agent.run, content)
                if not result:
                    result = "Agent failed to produce a result."
            except Exception as e:
                result = f"Error: {e}"
            mem.append({"role": "assistant", "content": result})
            save_sessions()
            return {"reply": result}

    if stream:
        async def generate():
            yield "思考中...\n\n"
            try:
                # 使用 loop.run_in_executor 处理同步的 OpenAI 调用，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, call, mem, True)

                tool_calls = []
                content_str = ""
                is_tool_call = False

                for chunk in response:
                    if not chunk.choices: continue
                    delta = chunk.choices[0].delta
                    if delta.tool_calls:
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
                    elif delta.content:
                        content_str += delta.content
                        yield delta.content

                if is_tool_call:
                    print("模型请求调用工具:", [tc["function"]["name"] for tc in tool_calls])
                    mem.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls
                    })
                    save_sessions()

                    for tc in tool_calls:
                        func_name = tc["function"]["name"]
                        args = json.loads(tc["function"]["arguments"])
                        result = use_tools(func_name, args)
                        mem.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": func_name,
                            "content": str(result)
                        })
                    save_sessions()

                    # 第二次调用
                    second_response = await loop.run_in_executor(None, call, mem, True)

                    final_content = ""
                    for chunk in second_response:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta
                        if delta.content:
                            final_content += delta.content
                            yield delta.content

                    print("最终回复:", final_content)
                    mem.append({"role": "assistant", "content": final_content})
                    save_sessions()
                else:
                    if content_str:
                        print("模型回复:", content_str)
                        mem.append({"role": "assistant", "content": content_str})
                        save_sessions()
            except Exception as e:
                error_msg = f"\n\n[后端错误]: {str(e)}"
                print(error_msg)
                yield error_msg

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        res = call(mem, stream=False)

        if res.tool_calls:
            print("模型请求调用工具:", [t.function.name for t in res.tool_calls])
            mem.append({
                "role": "assistant",
                "content": res.content,
                "tool_calls": [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {
                            "name": t.function.name,
                            "arguments": t.function.arguments
                        }
                    } for t in res.tool_calls
                ]
            })
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

            final_message = call(mem, stream=False)
            print("最终回复:", final_message.content)
            mem.append({"role": "assistant", "content": final_message.content})
            save_sessions()
            return {"reply": final_message.content}
        else:
            print("模型回复:", res.content)
            mem.append({"role": "assistant", "content": res.content})
            save_sessions()
            return {"reply": res.content}


@app.get("/api/conversations")
async def get_conversations():
    # 返回所有会话的摘要信息和消息
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

    response = call(temp_mem, stream=False)
    title = response.content.strip()
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
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
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
    if not setup():
        print("\n环境检查失败，请手动解决上述问题后重试。")
        sys.exit(1)

    print("\n正在启动 GDUT-Lawver 系统...")

    # 尝试自动启动前端开发服务器
    if not os.path.exists("dist"):
        print("\n" + "-" * 40)
        print("正在启动前端开发服务器 (Vite)...")
        print("-" * 40 + "\n")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            # 在 Windows 上使用 shell=True 启动 npm 脚本更稳定
            is_win = sys.platform == "win32"
            frontend_process = subprocess.Popen([npm_cmd, "run", "dev:frontend"], shell=is_win)


            def cleanup():
                print("\n正在关闭系统...")
                save_sessions()
                if 'frontend_process' in locals():
                    frontend_process.terminate()
                print("系统已关闭。")


            atexit.register(cleanup)
        except Exception as e:
            print(f"前端启动失败: {e}")

        port = 8000
    else:
        print("\n检测到 dist 目录，将直接提供静态文件服务。")
        port = 3000

    print(f"\n后端服务启动中，监听 {port} 端口...")
    # 启动 FastAPI 服务
    uvicorn.run(app, host="0.0.0.0", port=port)
