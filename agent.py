from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Cookie, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import json
import os
import re
import copy
import time
import asyncio
import shutil
from typing import List, Optional

from function_calling import call, memory as system_memory, create_assistant_message
from agents import ReActAgent, PlanAndSolveAgent, DefaultAgent
from mcps import use_tools
from auth import authenticate_user, create_token, verify_token

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    task = asyncio.create_task(cleanup_task())
    yield
    # Shutdown logic
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 认证依赖
def get_current_user(auth_token: Optional[str] = Cookie(None)):
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    success, msg = authenticate_user(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail=msg)
    
    token = create_token(req.username)
    response.set_cookie(key="auth_token", value=token, httponly=True, max_age=7*24*3600, samesite="lax")
    return {"status": "success", "message": "登录成功"}

@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(key="auth_token")
    return {"status": "success"}

@app.get("/api/verify_auth")
async def verify_auth_endpoint(current_user: str = Depends(get_current_user)):
    return {"status": "success", "username": current_user}


# 全局在线状态记录
active_conversations: dict[str, float] = {}

async def cleanup_task():
    """
    后台清理任务：每10分钟运行一次，删除超过1小时未活跃会话的 TEMP 和 Result 缓存。
    """
    while True:
        try:
            now = time.time()
            one_hour_ago = now - 3600

            # 清理过期的心跳记录
            stale_keys = [k for k, v in active_conversations.items() if v < one_hour_ago]
            for k in stale_keys:
                del active_conversations[k]

            for folder in ["TEMP", "Result"]:
                if not os.path.exists(folder):
                    continue

                for conv_id in os.listdir(folder):
                    conv_dir = os.path.join(folder, conv_id)
                    if not os.path.isdir(conv_dir):
                        continue

                    # 检查是否在线
                    if conv_id in active_conversations:
                        continue

                    # 会话已离线，且目录也闲置超过一小时，直接清理整个目录
                    try:
                        mtime = os.path.getmtime(conv_dir)
                        if mtime < one_hour_ago:
                            shutil.rmtree(conv_dir, ignore_errors=True)
                            print(f"[清理] 已彻底删除过期会话缓存: {conv_dir}")
                    except Exception as e:
                        print(f"[清理] 删除会话缓存失败 {conv_dir}: {e}")

        except Exception as e:
            print(f"[清理] 任务运行出错: {e}")

        await asyncio.sleep(600)  # 每10分钟检查一次


# 定义数据模型
class Message(BaseModel):
    role: str
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    conversation_id: str = "default"
    stream: bool = True
    agent_mode: str = "default"
    use_ocp: bool = True


class SummarizeRequest(BaseModel):
    history: List[dict]


async def compress_history(history: List[dict]) -> List[dict]:
    """
    对超出20条范围的记忆上下文启用“摘要 + 最近10条”的压缩方式
    """
    # 过滤掉 system 消息进行计数
    non_system_msgs = [m for m in history if m.get("role") != "system"]

    if len(non_system_msgs) <= 20:
        return history

    print(f"[历史压缩] 当前消息数 {len(non_system_msgs)} > 20，开始压缩...")

    # 保留最近的 10 条
    last_10 = non_system_msgs[-10:]
    # 需要摘要的部分
    to_summarize = non_system_msgs[:-10]

    # 构造摘要请求
    summary_prompt = "请简要总结以下对话的核心内容和已达成的共识，以便作为后续对话的上下文参考。注意：只输出纯文本总结，不要包含任何标签（如 <final_answer> 或 <think>）。\n\n"
    for m in to_summarize:
        role = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content") or ""
        summary_prompt += f"{role}: {content[:200]}...\n"

    try:
        # 调用 LLM 进行摘要
        summary_res = await call([{"role": "user", "content": summary_prompt}], stream=False)
        content = summary_res.content or ""
        # 强制移除可能存在的 <final_answer> 标签
        content = re.sub(r'</?(final_answer|think)[^>]*>', '', content, flags=re.IGNORECASE | re.DOTALL).strip()
        summary_text = f"[前情提要]: {content}"
        print("[历史压缩] 摘要生成成功")

        # 重新构造历史：System + 摘要消息 + 最近10条
        new_history = copy.deepcopy(system_memory)
        new_history.append({"role": "assistant", "content": summary_text})
        new_history.extend(last_10)
        return new_history
    except Exception as e:
        print(f"[历史压缩] 摘要生成失败: {e}，回退到截断模式")
        # 如果摘要失败，回退到只保留最近 20 条
        new_history = copy.deepcopy(system_memory)
        new_history.extend(non_system_msgs[-20:])
        return new_history


from tools import ToolExecutor


def build_agent(mode: str, memory: list, session_id: str, use_ocp: bool = True):
    if mode == "default":
        return DefaultAgent(memory=memory, session_id=session_id, use_ocp=use_ocp)
    if mode in ["react", "plan_and_solve"]:
        from mcps import tools as all_tools
        tool_executor = ToolExecutor()
        for tool_def in all_tools:
            name = tool_def["function"]["name"]
            desc = tool_def["function"]["description"]

            def create_tool_func(n):
                return lambda args_str: use_tools(n, json.loads(args_str) if isinstance(args_str,
                                                                                        str) and args_str.strip().startswith(
                    '{') else args_str, conv_id=session_id)

            tool_executor.registerTool(name, desc, create_tool_func(name))

        if mode == "react":
            return ReActAgent(tool_executor=tool_executor, memory=memory, session_id=session_id, use_ocp=use_ocp)
        if mode == "plan_and_solve":
            return PlanAndSolveAgent(tool_executor=tool_executor, memory=memory, session_id=session_id, use_ocp=use_ocp)
    return DefaultAgent(memory=memory, session_id=session_id, use_ocp=use_ocp)


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    content = request.message
    history = request.history
    session_id = request.conversation_id
    stream = request.stream
    agent_mode = request.agent_mode
    use_ocp = request.use_ocp

    # 为当前用户消息加上后端时间
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"[{current_time}] {content}"

    # Sanitize history: ensure content is always a string and no nulls
    sanitized_history = []
    for msg in history:
        m = copy.deepcopy(msg)
        # 确保 content 是字符串
        if "content" not in m or m["content"] is None:
            m["content"] = ""
        else:
            m["content"] = str(m["content"])

        # 确保 tool_calls 中的 arguments 是字符串
        if "tool_calls" in m and m["tool_calls"]:
            for tc in m["tool_calls"]:
                if "function" in tc and "arguments" in tc["function"]:
                    if not isinstance(tc["function"]["arguments"], str):
                        tc["function"]["arguments"] = json.dumps(tc["function"]["arguments"])

        # 移除空的 reasoning_content 以免某些 API 报错
        if "reasoning_content" in m and not m["reasoning_content"]:
            del m["reasoning_content"]

        if m.get("role") == "tool" and "tool_call_id" not in m:
            # Skip invalid tool messages
            continue
        sanitized_history.append(m)

    print(f"\n[收到请求] 会话ID: {session_id}, 模式: {agent_mode}, 流式: {stream}")

    # 确保历史记录包含系统提示词 (Lawver 的身份定义)
    full_history = copy.deepcopy(system_memory)
    full_history.extend(sanitized_history)

    # 1. 历史压缩逻辑
    processed_history = await compress_history(full_history)

    # 2. 添加当前消息
    processed_history.append({"role": "user", "content": content})

    agent = build_agent(agent_mode, processed_history, session_id, use_ocp=use_ocp)

    if stream:
        async def generate_agent():
            full_result = ""
            try:
                import inspect
                sig = inspect.signature(agent.run)
                if 'stream' in sig.parameters:
                    run_iter = agent.run(content, stream=True)
                else:
                    run_iter = agent.run(content)

                async for chunk in run_iter:
                    if isinstance(chunk, dict):
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif chunk:
                        chunk_str = str(chunk)
                        if "[THOUGHT_SIGNATURE:" in chunk_str:
                            ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk_str)
                            if ts_match:
                                ts = ts_match.group(1)
                                yield f"data: {json.dumps({'type': 'thought_signature', 'content': ts})}\n\n"
                                chunk_str = chunk_str.replace(ts_match.group(0), "")

                        if chunk_str:
                            full_result += chunk_str
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk_str})}\n\n"
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(generate_agent(), media_type="text/event-stream")
    else:
        try:
            full_result = ""
            thought_signature = None
            import inspect
            sig = inspect.signature(agent.run)
            if 'stream' in sig.parameters:
                run_iter = agent.run(content, stream=False)
            else:
                run_iter = agent.run(content)

            async for chunk in run_iter:
                if isinstance(chunk, dict):
                    if chunk.get('type') == 'content':
                        full_result += chunk.get('content', '')
                    elif chunk.get('type') == 'content_replace':
                        full_result = chunk.get('content', '')
                    elif chunk.get('type') == 'thought_signature':
                        thought_signature = chunk.get('content')
                elif chunk:
                    chunk_str = str(chunk)
                    if "[THOUGHT_SIGNATURE:" in chunk_str:
                        ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk_str)
                        if ts_match:
                            thought_signature = ts_match.group(1)
                            chunk_str = chunk_str.replace(ts_match.group(0), "")
                    full_result += chunk_str

            return {
                "reply": full_result,
                "download_path": None,
                "thought_signature": thought_signature
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}


@app.post("/api/summarize")
async def summarize_endpoint(request: SummarizeRequest, current_user: str = Depends(get_current_user)):
    history = request.history
    if not history or len(history) == 0:
        return {"title": "New Chat"}
    temp_mem = copy.deepcopy(history)
    temp_mem.append({"role": "user",
                     "content": "请用一句话（不超过10个字）总结我们目前的对话内容，作为对话标题。只输出标题文本，不要包含任何标点符号，也不要使用任何标签（如 <final_answer> 或 <think>）。"})
    response = await call(temp_mem, stream=False)
    content = response.content or ""
    # 强制移除可能存在的 <final_answer> 标签
    content = re.sub(r'</?(final_answer|think)[^>]*>', '', content, flags=re.IGNORECASE | re.DOTALL)
    title = content.strip().strip('"').strip("'")
    return {"title": title or "New Chat"}


@app.get("/api/upload")
async def upload_file_get(current_user: str = Depends(get_current_user)):
    raise HTTPException(status_code=405, detail="Method Not Allowed: Please use POST request to upload files.")

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), conversation_id: str = Form(...), current_user: str = Depends(get_current_user)):
    # 修复上传漏洞：限制文件类型并清理文件名
    # 1. 限制允许上传的扩展名
    ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # 1.5 限制文件大小为 50MB
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 50MB limit")

    # 2. 清理文件名，防止路径穿越，保留中文字符和常用字符
    # 只过滤掉路径分隔符和一些极其危险的控制字符，保留中文、字母、数字和常用标点
    # [^\w\s\u4e00-\u9fa5._-] 这种写法在 Python re 中通常能很好工作
    safe_filename = re.sub(r'[\\/:*?"<>|]', '_', file.filename)
    # 进一步防止路径穿越
    safe_filename = os.path.basename(safe_filename)

    # 3. 确保目录安全
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)
    temp_dir = os.path.join("TEMP", safe_conv_id)
    os.makedirs(temp_dir, exist_ok=True)

    file_path = os.path.join(temp_dir, safe_filename)

    # 4. 写入文件
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@app.get("/api/workspace/files")
async def list_workspace_files_api(conversation_id: str, current_user: str = Depends(get_current_user)):
    """
    列出当前对话工作区（Workspace）中的所有文件。
    扫描服务器上的 TEMP/{conv_id} 和 Result/{conv_id} 目录。
    """
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)
    files = []

    # 查找 TEMP 目录 (上传的文件)
    temp_dir = os.path.join("TEMP", safe_conv_id)
    if os.path.exists(temp_dir):
        for f in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, f)
            if os.path.isfile(file_path):
                files.append({
                    "name": f,
                    "path": file_path.replace('\\', '/'),
                    "type": "upload"
                })

    # 查找 Result 目录 (生成的文件)
    result_dir = os.path.join("Result", safe_conv_id)
    if os.path.exists(result_dir):
        for f in os.listdir(result_dir):
            file_path = os.path.join(result_dir, f)
            if os.path.isfile(file_path):
                files.append({
                    "name": f,
                    "path": file_path.replace('\\', '/'),
                    "type": "generated"
                })

    return {"files": files}


@app.post("/api/workspace/restore")
async def restore_workspace_file(
        file: UploadFile = File(...),
        conversation_id: str = Form(...),
        file_type: str = Form(...),
        current_user: str = Depends(get_current_user)
):
    """
    从客户端恢复丢失的文件到服务器缓存
    """
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)
    safe_filename = re.sub(r'[\\/:*?"<>|]', '_', file.filename)
    safe_filename = os.path.basename(safe_filename)

    if file_type == "upload":
        target_dir = os.path.join("TEMP", safe_conv_id)
    elif file_type == "generated":
        target_dir = os.path.join("Result", safe_conv_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, safe_filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@app.delete("/api/workspace/{conversation_id}")
async def delete_workspace(conversation_id: str, current_user: str = Depends(get_current_user)):
    """
    当用户删除对话时，清理服务器上的相关文件
    """
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)

    temp_dir = os.path.join("TEMP", safe_conv_id)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)

    result_dir = os.path.join("Result", safe_conv_id)
    if os.path.exists(result_dir):
        shutil.rmtree(result_dir, ignore_errors=True)

    return {"status": "success"}

@app.delete("/api/workspace/file")
async def delete_workspace_file(conversation_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    """
    客户端删除特定文件时，清理服务器上的该文件
    """
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)
    
    # 规范化路径并验证安全性
    if not os.path.isabs(file_path):
        target_path = os.path.join(os.getcwd(), file_path)
    else:
        target_path = file_path
        
    abs_path = os.path.abspath(target_path)
    cwd = os.getcwd()
    
    allowed_dirs = [
        os.path.join(cwd, "TEMP", safe_conv_id),
        os.path.join(cwd, "Result", safe_conv_id)
    ]
    
    is_allowed = any(
        abs_path.startswith(os.path.abspath(d) + os.sep) or abs_path == os.path.abspath(d)
        for d in allowed_dirs
    )
    
    if is_allowed and os.path.exists(abs_path) and os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    raise HTTPException(status_code=403, detail="File not found or access denied")

@app.post("/api/heartbeat/{conversation_id}")
async def heartbeat(conversation_id: str, current_user: str = Depends(get_current_user)):
    """
    接收客户端心跳，更新对话最后活跃时间
    """
    safe_conv_id = re.sub(r'[^a-zA-Z0-9_-]', '_', conversation_id)
    active_conversations[safe_conv_id] = time.time()
    return {"status": "success"}


@app.get("/api/download")
async def download_file(file_path: str, current_user: str = Depends(get_current_user)):
    # 修复任意文件下载漏洞：限制只能下载 TEMP 或 Result 目录下的文件
    # 1. 规范化路径，防止路径穿越攻击
    # 如果是相对路径，先拼接到当前工作目录
    if not os.path.isabs(file_path):
        target_path = os.path.join(os.getcwd(), file_path)
    else:
        target_path = file_path

    abs_path = os.path.abspath(target_path)
    cwd = os.getcwd()

    # 2. 定义允许下载的目录
    allowed_dirs = [
        os.path.join(cwd, "TEMP"),
        os.path.join(cwd, "Result")
    ]

    # 3. 校验路径是否在允许的目录内
    # 添加 os.sep 防止类似 TEMP_hack 的目录绕过前缀匹配
    is_allowed = any(
        abs_path.startswith(os.path.abspath(d) + os.sep) or abs_path == os.path.abspath(d)
        for d in allowed_dirs
    )

    if is_allowed and os.path.exists(abs_path) and os.path.isfile(abs_path):
        return FileResponse(path=abs_path, filename=os.path.basename(abs_path))

    raise HTTPException(status_code=403, detail=f"Access denied or file not found: {file_path}")


@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    
    # 防止路径穿越，确保解析后的绝对路径依然在 dist 目录下
    dist_dir = os.path.abspath("dist")
    dist_path = os.path.abspath(os.path.join("dist", full_path))
    
    if not dist_path.startswith(dist_dir + os.sep) and dist_path != dist_dir:
        raise HTTPException(status_code=403, detail="Access denied")

    if os.path.isfile(dist_path):
        return FileResponse(dist_path)
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    return {"message": "Stateless Agent is running."}


if __name__ == '__main__':
    port = int(os.getenv("PORT", 80))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, workers=4)
