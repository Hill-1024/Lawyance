from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import json
import subprocess
import sys
import atexit
import os

from function_calling import call, memory
from mcps import use_tools

app = FastAPI()

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


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    content = request.message
    memory.append({"role": "user", "content": content})

    res = call(memory)

    if res.tool_calls:
        print("模型请求调用工具:", [t.function.name for t in res.tool_calls])
        # 把模型的调用请求先存入上下文，保持对话历史完整
        memory.append(res)
        # 遍历大模型请求调用的工具（可能会同时调用多个）
        for tool_call in res.tool_calls:
            function_name = tool_call.function.name
            # 解析大模型提取出来的参数
            arguments = json.loads(tool_call.function.arguments)
            # 转交工具请求给mcps.py
            result = use_tools(function_name, arguments)
            memory.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": result
            })
        # 携带查询到的结果，再次调用大模型
        final_message = call(memory)
        print("最终回复:", final_message.content)
        memory.append({"role": "assistant", "content": final_message.content})
        return {"reply": final_message.content}
    else:
        print("模型回复:", res.content)
        memory.append({"role": "assistant", "content": res.content})
        return {"reply": res.content}


# 挂载 React 编译后的静态文件（用于生产环境）
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
else:
    @app.get("/")
    async def root():
        return {"message": "Agent is running. Send POST requests to /api/chat"}

# Agent
if __name__ == '__main__':
    print("正在初始化 Agent...")

    # 尝试自动启动前端开发服务器
    if not os.path.exists("dist"):
        print("\n========================================")
        print("未检测到 dist 目录，正在启动前端开发服务器 (npm run dev)...")
        print("========================================\n")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            frontend_process = subprocess.Popen([npm_cmd, "run", "dev"])


            def cleanup():
                print("正在关闭前端服务...")
                frontend_process.terminate()


            atexit.register(cleanup)
        except Exception as e:
            print(f"前端启动失败，请确保已安装 Node.js 并在项目根目录执行过 npm install。错误: {e}")
    else:
        print("\n========================================")
        print("检测到 dist 目录，将直接通过 8000 端口提供前端页面访问。")
        print("========================================\n")

    print("\n启动 Web 服务，监听 8000 端口...")
    # 启动 FastAPI 服务，提供 HTTP 接口给 React
    uvicorn.run(app, host="0.0.0.0", port=8000)
