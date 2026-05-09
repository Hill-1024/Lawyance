from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Cookie, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
import uvicorn
import json
import os
import re
import copy
import time
import asyncio
import shutil
import logging
from collections import defaultdict
from typing import Any, List, Optional

from function_calling import call
from prompt_loader import build_system_memory
from agents import ReActAgent, PlanAndSolveAgent, DefaultAgent
from mcps import use_tools, format_tool_descriptions
from auth import authenticate_user, create_token, verify_token, get_user_role, list_accounts, add_or_update_account, delete_account

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

# 日志和限流设置
os.makedirs("data", exist_ok=True)
usage_logger = logging.getLogger("usage_logger")
usage_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("data/usage.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
if not usage_logger.handlers:
    usage_logger.addHandler(file_handler)

ip_request_counts = defaultdict(lambda: {"count": 0, "reset_time": 0})
RATE_LIMIT = 100 # requests per minute per IP


def sanitize_path_component(value: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', value or "")


def get_workspace_scope(current_user: str, conversation_id: str) -> str:
    return os.path.join(
        sanitize_path_component(current_user),
        sanitize_path_component(conversation_id)
    )


def get_workspace_dirs(current_user: str, conversation_id: str) -> tuple[str, str]:
    scope = get_workspace_scope(current_user, conversation_id)
    return os.path.join("TEMP", scope), os.path.join("Result", scope)


def is_within_directory(path: str, directory: str) -> bool:
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(directory)
    return abs_path == abs_dir or abs_path.startswith(abs_dir + os.sep)

@app.middleware("http")
async def security_and_logging_middleware(request: Request, call_next):
    client_ip = request.client.host or "unknown"
    method = request.method
    path = request.url.path
    
    # Rate Limiting
    now = time.time()
    ip_data = ip_request_counts[client_ip]
    if now > ip_data["reset_time"]:
        ip_data["count"] = 1
        ip_data["reset_time"] = now + 60
    else:
        ip_data["count"] += 1
        if ip_data["count"] > RATE_LIMIT:
            if path.startswith("/api"):
                return Response(content="Rate limit exceeded", status_code=429)

    response = await call_next(request)
    
    # Logging
    if path.startswith("/api"):
        username = "anonymous"
        token = request.cookies.get("auth_token")
        if token:
            user = verify_token(token)
            if user:
                username = user
                
        status_code = response.status_code
        usage_logger.info(f"{client_ip} | {username} | {method} | {path} | {status_code}")
        
    return response

# 认证依赖
def get_current_user(auth_token: Optional[str] = Cookie(None)):
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username

def require_admin(current_user: str = Depends(get_current_user)):
    role = get_user_role(current_user)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

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
    return {"status": "success", "username": current_user, "role": get_user_role(current_user)}

# --- Admin Routes ---
@app.get("/api/admin/logs")
async def get_admin_logs(ip: Optional[str] = None, ignore_heartbeat: bool = False, admin_user: str = Depends(require_admin)):
    logs = []
    log_file = "data/usage.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if ip and ip not in line:
                    continue
                if ignore_heartbeat and "/api/heartbeat" in line:
                    continue
                logs.append(line.strip())
    # Return last 1000 matching logs, newest first
    return {"status": "success", "logs": logs[::-1][:1000]}

@app.get("/api/admin/accounts")
async def get_admin_accounts(admin_user: str = Depends(require_admin)):
    return {"status": "success", "accounts": list_accounts()}

class AccountRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"

@app.post("/api/admin/accounts")
async def set_admin_accounts(req: AccountRequest, admin_user: str = Depends(require_admin)):
    success, msg = add_or_update_account(req.username, req.password, req.role or "user")
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}
    
@app.delete("/api/admin/accounts/{username}")
async def delete_admin_account(username: str, admin_user: str = Depends(require_admin)):
    if username == admin_user:
        raise HTTPException(status_code=400, detail="不能在登录状态下删除自己")
    success, msg = delete_account(username)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


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
                _call_memory_tool("clear_conversation_memory", {}, k)

            for folder in ["TEMP", "Result"]:
                if not os.path.exists(folder):
                    continue

                for user_dir_name in os.listdir(folder):
                    user_dir = os.path.join(folder, user_dir_name)
                    if not os.path.isdir(user_dir):
                        continue

                    for conv_id in os.listdir(user_dir):
                        conv_dir = os.path.join(user_dir, conv_id)
                        if not os.path.isdir(conv_dir):
                            continue

                        scope = os.path.join(user_dir_name, conv_id)
                        if scope in active_conversations:
                            continue

                        try:
                            mtime = os.path.getmtime(conv_dir)
                            if mtime < one_hour_ago:
                                shutil.rmtree(conv_dir, ignore_errors=True)
                                print(f"[清理] 已彻底删除过期会话缓存: {conv_dir}")
                        except Exception as e:
                            print(f"[清理] 删除会话缓存失败 {conv_dir}: {e}")

                    try:
                        if not os.listdir(user_dir):
                            os.rmdir(user_dir)
                    except OSError:
                        pass

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
    history: List[dict] = Field(default_factory=list)
    conversation_id: str = "default"
    stream: bool = True
    agent_mode: str = "default"
    use_ocp: bool = True
    memory_snapshot: Optional[dict] = None


class SummarizeRequest(BaseModel):
    history: List[dict]


class MemorySyncRequest(BaseModel):
    conversation_id: str
    memory_snapshot: Optional[dict] = None
    history: List[dict] = Field(default_factory=list)


def _fallback_conversation_title(history: List[dict]) -> str:
    for msg in history:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "")
        content = re.sub(r'\[用户已上传以下文件.*?\]', '', content, flags=re.DOTALL)
        content = re.sub(r'</?(final_answer|think|response)[^>]*>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'\s+', ' ', content).strip().strip('"').strip("'")
        if content:
            return content[:20] + ("..." if len(content) > 20 else "")
    return "New Chat"


def _read_tool_json(tool_result: Any) -> dict:
    if isinstance(tool_result, dict):
        return tool_result
    if not isinstance(tool_result, str):
        return {}
    try:
        parsed = json.loads(tool_result)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _call_memory_tool(tool_name: str, arguments: dict, workspace_scope: str) -> dict:
    return _read_tool_json(use_tools(tool_name, arguments, conv_id=workspace_scope))


def _sync_memory_cache(workspace_scope: str, snapshot: Optional[dict], messages: List[dict]) -> dict:
    return _call_memory_tool(
        "sync_conversation_memory",
        {
            "snapshot": snapshot or {},
            "messages": messages,
        },
        workspace_scope,
    )


def _retrieve_memory_context(workspace_scope: str, query: str) -> tuple[str, dict]:
    payload = _call_memory_tool(
        "retrieve_conversation_memory",
        {
            "query": query,
            "limit": 8,
        },
        workspace_scope,
    )
    return str(payload.get("context") or ""), payload


def _remember_memory_turn(workspace_scope: str, user_message: str, assistant_message: str) -> dict:
    return _call_memory_tool(
        "remember_conversation_turn",
        {
            "user_message": user_message,
            "assistant_message": assistant_message,
        },
        workspace_scope,
    )


FILE_FOCUS_PATTERN = re.compile(
    r"(\[用户已上传以下文件|\.pdf\b|\.docx?\b|\.wps\b|文件|附件|批注|读取|上传)",
    re.IGNORECASE,
)
LEGAL_FOCUS_PATTERN = re.compile(
    r"(法律|法条|法规|司法解释|案例|判例|法院|起诉|诉讼|仲裁|合同|赔偿|侵权|劳动|婚姻|继承|借款|租赁|处罚|刑事|民事|行政|证据|律师|维权)"
)


def _infer_prompt_focus(content: str, history: List[dict]) -> list[str]:
    recent_texts = [content or ""]
    for msg in history[-6:]:
        if isinstance(msg, dict):
            recent_texts.append(str(msg.get("content") or ""))
    combined = "\n".join(recent_texts)

    focus = []
    if FILE_FOCUS_PATTERN.search(combined):
        focus.append("file_processing")
    if LEGAL_FOCUS_PATTERN.search(combined):
        focus.append("legal_retrieval")
    if not focus:
        focus.append("general_gate")
    return focus


async def compress_history(
    history: List[dict],
    agent_mode: str = "default",
    focus: Optional[list[str]] = None,
    memory_context: str = "",
) -> List[dict]:
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
        summary_messages = build_system_memory(task="history_summary")
        summary_messages.append({"role": "user", "content": summary_prompt})
        summary_res = await call(summary_messages, stream=False, include_tools=False)
        content = summary_res.content or ""
        # 强制移除可能存在的 <final_answer> 标签
        content = re.sub(r'</?(final_answer|think)[^>]*>', '', content, flags=re.IGNORECASE | re.DOTALL).strip()
        summary_text = f"[前情提要]: {content}"
        print("[历史压缩] 摘要生成成功")

        # 重新构造历史：System + 摘要消息 + 最近10条
        new_history = build_system_memory(
            agent_mode=agent_mode,
            focus=focus,
            memory_context=memory_context,
        )
        new_history.append({"role": "assistant", "content": summary_text})
        new_history.extend(last_10)
        return new_history
    except Exception as e:
        print(f"[历史压缩] 摘要生成失败: {e}，回退到截断模式")
        # 如果摘要失败，回退到只保留最近 20 条
        new_history = build_system_memory(
            agent_mode=agent_mode,
            focus=focus,
            memory_context=memory_context,
        )
        new_history.extend(non_system_msgs[-20:])
        return new_history

def _build_tool_executor(workspace_scope: str):
    def execute_tool(tool_name: str, raw_args):
        parsed_args = raw_args
        if isinstance(raw_args, str) and raw_args.strip().startswith('{'):
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed_args = raw_args
        return use_tools(tool_name, parsed_args, conv_id=workspace_scope)

    return execute_tool


def build_agent(mode: str, memory: list, session_id: str, workspace_scope: str, use_ocp: bool = True):
    execute_tool = _build_tool_executor(workspace_scope)
    if mode == "default":
        return DefaultAgent(
            memory=memory,
            session_id=session_id,
            workspace_scope=workspace_scope,
            use_ocp=use_ocp,
            execute_tool=execute_tool,
        )
    if mode in ["react", "plan_and_solve"]:
        tools_description = format_tool_descriptions()

        if mode == "react":
            return ReActAgent(tools_description=tools_description, execute_tool=execute_tool, memory=memory, session_id=session_id, workspace_scope=workspace_scope, use_ocp=use_ocp)
        if mode == "plan_and_solve":
            return PlanAndSolveAgent(tools_description=tools_description, execute_tool=execute_tool, memory=memory, session_id=session_id, workspace_scope=workspace_scope, use_ocp=use_ocp)
    return DefaultAgent(
        memory=memory,
        session_id=session_id,
        workspace_scope=workspace_scope,
        use_ocp=use_ocp,
        execute_tool=execute_tool,
    )


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    content = request.message
    history = request.history
    session_id = request.conversation_id
    stream = request.stream
    agent_mode = request.agent_mode
    use_ocp = request.use_ocp
    workspace_scope = get_workspace_scope(current_user, session_id)
    active_conversations[workspace_scope] = time.time()

    # 为当前用户消息加上后端时间
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"[{current_time}] {content}"

    # Sanitize history: ensure content is always a string and no nulls
    sanitized_history = []
    for msg in history:
        m = copy.deepcopy(msg)
        if m.get("role") == "system":
            continue
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
    _sync_memory_cache(workspace_scope, request.memory_snapshot, sanitized_history)
    memory_context, _ = _retrieve_memory_context(workspace_scope, content)
    prompt_focus = _infer_prompt_focus(content, sanitized_history)

    # 确保历史记录只使用服务端动态加载的系统提示词
    full_history = build_system_memory(
        agent_mode=agent_mode,
        focus=prompt_focus,
        memory_context=memory_context,
    )
    full_history.extend(sanitized_history)

    # 1. 历史压缩逻辑
    processed_history = await compress_history(
        full_history,
        agent_mode=agent_mode,
        focus=prompt_focus,
        memory_context=memory_context,
    )

    # 2. 添加当前消息
    processed_history.append({"role": "user", "content": content})

    agent = build_agent(agent_mode, processed_history, session_id, workspace_scope, use_ocp=use_ocp)

    if stream:
        async def generate_agent():
            full_result = ""
            memory_written = False
            try:
                import inspect
                sig = inspect.signature(agent.run)
                if 'stream' in sig.parameters:
                    run_iter = agent.run(content, stream=True)
                else:
                    run_iter = agent.run(content)

                async for chunk in run_iter:
                    if isinstance(chunk, dict):
                        chunk_type = chunk.get("type")
                        if chunk_type == "content":
                            full_result += str(chunk.get("content") or "")
                        elif chunk_type == "content_replace":
                            full_result = str(chunk.get("content") or "")
                        elif chunk_type == "memory_candidate":
                            if not memory_written:
                                memory_payload = _remember_memory_turn(
                                    workspace_scope,
                                    content,
                                    str(chunk.get("content") or full_result)
                                )
                                memory_written = True
                                if memory_payload.get("memory"):
                                    yield f"data: {json.dumps({'type': 'memory_sync', 'content': memory_payload['memory']}, ensure_ascii=False)}\n\n"
                            continue
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

                if not memory_written:
                    memory_payload = _remember_memory_turn(workspace_scope, content, full_result)
                    if memory_payload.get("memory"):
                        yield f"data: {json.dumps({'type': 'memory_sync', 'content': memory_payload['memory']}, ensure_ascii=False)}\n\n"
            except Exception as e:
                print(f"[聊天流生成失败]: {type(e).__name__}: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(generate_agent(), media_type="text/event-stream")
    else:
        try:
            full_result = ""
            thought_signature = None
            memory_payload = {}
            memory_written = False
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
                    elif chunk.get('type') == 'memory_candidate' and not memory_written:
                        memory_payload = _remember_memory_turn(
                            workspace_scope,
                            content,
                            str(chunk.get('content') or full_result)
                        )
                        memory_written = True
                elif chunk:
                    chunk_str = str(chunk)
                    if "[THOUGHT_SIGNATURE:" in chunk_str:
                        ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk_str)
                        if ts_match:
                            thought_signature = ts_match.group(1)
                            chunk_str = chunk_str.replace(ts_match.group(0), "")
                    full_result += chunk_str

            if not memory_written:
                memory_payload = _remember_memory_turn(workspace_scope, content, full_result)
            return {
                "reply": full_result,
                "download_path": None,
                "thought_signature": thought_signature,
                "memory_snapshot": memory_payload.get("memory")
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/summarize")
async def summarize_endpoint(request: SummarizeRequest, current_user: str = Depends(get_current_user)):
    history = request.history
    if not history or len(history) == 0:
        return {"title": "New Chat"}
    fallback_title = _fallback_conversation_title(history)
    temp_mem = copy.deepcopy(history)
    temp_mem.append({"role": "user",
                     "content": "请用一句话（不超过10个字）总结我们目前的对话内容，作为对话标题。只输出标题文本，不要包含任何标点符号，也不要使用任何标签（如 <final_answer> 或 <think>）。"})
    try:
        response = await call(temp_mem, stream=False, include_tools=False)
        content = response.content or ""
        # 强制移除可能存在的 <final_answer> 标签
        content = re.sub(r'</?(final_answer|think)[^>]*>', '', content, flags=re.IGNORECASE | re.DOTALL)
        title = content.strip().strip('"').strip("'")
        return {"title": title or fallback_title}
    except Exception as e:
        print(f"[标题摘要] 生成失败，使用兜底标题: {e}")
        return {"title": fallback_title}


@app.post("/api/memory/sync")
async def sync_memory_endpoint(request: MemorySyncRequest, current_user: str = Depends(get_current_user)):
    workspace_scope = get_workspace_scope(current_user, request.conversation_id)
    active_conversations[workspace_scope] = time.time()
    return _sync_memory_cache(workspace_scope, request.memory_snapshot, request.history)


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
    temp_dir, _ = get_workspace_dirs(current_user, conversation_id)
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
    扫描当前用户命名空间下的 TEMP 和 Result 目录。
    """
    files = []

    # 查找 TEMP 目录 (上传的文件)
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
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
    safe_filename = re.sub(r'[\\/:*?"<>|]', '_', file.filename)
    safe_filename = os.path.basename(safe_filename)

    if file_type == "upload":
        target_dir, _ = get_workspace_dirs(current_user, conversation_id)
    elif file_type == "generated":
        _, target_dir = get_workspace_dirs(current_user, conversation_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, safe_filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@app.delete("/api/workspace/file")
async def delete_workspace_file(conversation_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    """
    客户端删除特定文件时，清理服务器上的该文件。
    注意：此路由必须在 /api/workspace/{conversation_id} 之前声明，
    否则 FastAPI 会将 "file" 匹配为 conversation_id 参数。
    """
    # 规范化路径并验证安全性
    if not os.path.isabs(file_path):
        target_path = os.path.join(os.getcwd(), file_path)
    else:
        target_path = file_path

    abs_path = os.path.abspath(target_path)
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    allowed_dirs = [temp_dir, result_dir]
    is_allowed = any(is_within_directory(abs_path, d) for d in allowed_dirs)
    
    if not is_allowed:
        raise HTTPException(status_code=403, detail="File not found or access denied")

    if os.path.exists(abs_path):
        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=400, detail="Target path is not a file")
        try:
            os.remove(abs_path)
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # 幂等删除：如果文件已经不存在，也视为删除成功，便于客户端同步本地状态
    return {"status": "success"}

@app.delete("/api/workspace/{conversation_id}")
async def delete_workspace(conversation_id: str, current_user: str = Depends(get_current_user)):
    """
    当用户删除对话时，清理服务器上的相关文件
    """
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    if os.path.exists(result_dir):
        shutil.rmtree(result_dir, ignore_errors=True)
    _call_memory_tool("clear_conversation_memory", {}, get_workspace_scope(current_user, conversation_id))

    return {"status": "success"}

@app.post("/api/heartbeat/{conversation_id}")
async def heartbeat(conversation_id: str, current_user: str = Depends(get_current_user)):
    """
    接收客户端心跳，更新对话最后活跃时间
    """
    active_conversations[get_workspace_scope(current_user, conversation_id)] = time.time()
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
    safe_user = sanitize_path_component(current_user)
    allowed_dirs = [
        os.path.join(cwd, "TEMP", safe_user),
        os.path.join(cwd, "Result", safe_user)
    ]

    # 3. 校验路径是否在允许的目录内
    # 添加 os.sep 防止类似 TEMP_hack 的目录绕过前缀匹配
    is_allowed = any(is_within_directory(abs_path, d) for d in allowed_dirs)

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
    workers = max(int(os.getenv("UVICORN_WORKERS", "1")), 1)
    uvicorn.run("agent:app", host="0.0.0.0", port=port, workers=workers)
