from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
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
from agents import ReActAgent, PlanAndSolveAgent
from mcps import use_tools

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


async def cleanup_task():
    """
    后台清理任务：每10分钟运行一次，删除 TEMP 和 Result 目录中超过 1 小时未修改的文件。
    """
    while True:
        try:
            now = time.time()
            one_hour_ago = now - 3600
            for folder in ["TEMP", "Result"]:
                if not os.path.exists(folder):
                    continue
                for root, dirs, files in os.walk(folder, topdown=False):
                    for name in files:
                        file_path = os.path.join(root, name)
                        if os.path.getmtime(file_path) < one_hour_ago:
                            try:
                                os.remove(file_path)
                                print(f"[清理] 已删除过期文件: {file_path}")
                            except Exception as e:
                                print(f"[清理] 删除文件失败 {file_path}: {e}")

                    # 如果目录为空，也将其删除
                    if not os.listdir(root) and root != folder:
                        try:
                            os.rmdir(root)
                            print(f"[清理] 已删除空目录: {root}")
                        except Exception as e:
                            print(f"[清理] 删除空目录失败 {root}: {e}")
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


def build_agent(mode: str, memory: list, session_id: str):
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
            return ReActAgent(tool_executor=tool_executor, memory=memory)
        if mode == "plan_and_solve":
            return PlanAndSolveAgent(tool_executor=tool_executor, memory=memory)
    return None


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    content = request.message
    history = request.history
    session_id = request.conversation_id
    stream = request.stream
    agent_mode = request.agent_mode

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

    agent = build_agent(agent_mode, processed_history, session_id)

    if agent:
        if stream:
            async def generate_agent():
                full_result = ""
                try:
                    async for chunk in agent.run(content):
                        if chunk:
                            # 检查是否包含特殊标记
                            if "[THOUGHT_SIGNATURE:" in chunk:
                                ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk)
                                if ts_match:
                                    ts = ts_match.group(1)
                                    yield f"data: {json.dumps({'type': 'thought_signature', 'content': ts})}\n\n"
                                    # 移除标记，避免显示在正文中
                                    chunk = chunk.replace(ts_match.group(0), "")

                            if chunk:
                                full_result += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

            return StreamingResponse(generate_agent(), media_type="text/event-stream")
        else:
            try:
                full_result = ""
                download_path = None
                thought_signature = None
                async for chunk in agent.run(content):
                    full_result += chunk

                # 提取特殊标记
                if "[THOUGHT_SIGNATURE:" in full_result:
                    ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", full_result)
                    if ts_match:
                        thought_signature = ts_match.group(1)
                        full_result = full_result.replace(ts_match.group(0), "")

                return {
                    "reply": full_result,
                    "download_path": None,
                    "thought_signature": thought_signature
                }
            except Exception as e:
                return {"error": str(e)}

    if stream:
        async def generate():
            try:
                current_mem = processed_history
                while True:
                    response = await call(current_mem, True)
                    tool_calls = []
                    content_str = ""
                    reasoning_str = ""
                    thought_signature_str = ""
                    is_tool_call = False
                    has_started_reasoning = False
                    has_finished_reasoning = False
                    download_path = None

                    async for chunk in response:
                        if not chunk.choices: continue
                        delta = chunk.choices[0].delta

                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            content_str += reasoning
                            reasoning_str += reasoning
                            yield f"data: {json.dumps({'type': 'thought', 'content': reasoning})}\n\n"

                        # 捕获 thought_signature (Gemini 规范)
                        ts = getattr(delta, 'thought_signature', None)
                        if ts:
                            thought_signature_str = ts

                        if delta.content is not None:
                            content_str += delta.content
                            yield f"data: {json.dumps({'type': 'content', 'content': delta.content})}\n\n"

                        if delta.tool_calls:
                            is_tool_call = True
                            for tc in delta.tool_calls:
                                tc_index = tc.index
                                tc_dump = tc.model_dump(exclude_unset=True)

                                if tc_index is None:
                                    # 如果没有提供 index，通过判断是否包含 name 或 id 来决定是新建还是追加
                                    is_new_call = ("id" in tc_dump) or (
                                                "function" in tc_dump and "name" in tc_dump["function"])
                                    if len(tool_calls) == 0 or is_new_call:
                                        tc_index = len(tool_calls)
                                    else:
                                        tc_index = len(tool_calls) - 1

                                while len(tool_calls) <= tc_index:
                                    # 为工具调用生成默认 ID，防止模型未返回 ID 导致 400 错误
                                    tool_calls.append({"id": f"call_{int(time.time())}_{tc_index}", "type": "function",
                                                       "function": {"name": "", "arguments": ""}})

                                if "id" in tc_dump and tc_dump["id"]:
                                    tool_calls[tc_index]["id"] = tc_dump["id"]
                                if "function" in tc_dump:
                                    for k, v in tc_dump["function"].items():
                                        if v: tool_calls[tc_index]["function"][k] += v

                    if is_tool_call:
                        thought_payload = {'type': 'thought', 'content': '️ **正在调用工具处理中...**\n'}
                        yield f"data: {json.dumps(thought_payload)}\n\n"

                        assistant_msg = create_assistant_message(
                            content=content_str or "",
                            reasoning_content=reasoning_str,
                            tool_calls=tool_calls,
                            thought_signature=thought_signature_str
                        )
                        current_mem.append(assistant_msg)
                        for tc in tool_calls:
                            func_name = tc["function"]["name"]
                            args_str = tc["function"]["arguments"]
                            # 后台详细日志
                            print(f"[工具调用] 函数: {func_name}, 参数: {args_str}")

                            try:
                                args = json.loads(args_str) if args_str else {}
                            except Exception as je:
                                print(f"[JSON 解析失败] 参数: {args_str}, 错误: {je}")
                                args = {}

                            thought_payload = {'type': 'thought', 'content': f'️ 执行: `{func_name}`\n'}
                            yield f"data: {json.dumps(thought_payload)}\n\n"
                            result = use_tools(func_name, args, conv_id=session_id)

                            current_mem.append(
                                {"role": "tool", "tool_call_id": tc["id"], "name": func_name, "content": str(result)})
                        
                        thought_payload_end = {'type': 'thought', 'content': ' **工具执行完毕，正在生成最终回复...**\n'}
                        yield f"data: {json.dumps(thought_payload_end)}\n\n"
                        continue
                    else:
                        # 正常结束，输出签名（如果有）以供前端捕获并存入历史
                        if thought_signature_str:
                            yield f"data: {json.dumps({'type': 'thought_signature', 'content': thought_signature_str})}\n\n"
                        break
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        res = await call(processed_history, stream=False)
        content = res.content or ""
        if res.tool_calls:
            # 简单处理非流式下的工具调用（递归一次）
            tool_calls = [t.model_dump(exclude_unset=True) for t in res.tool_calls]
            processed_history.append(create_assistant_message(content=content, tool_calls=tool_calls))
            for tc in res.tool_calls:
                result = use_tools(tc.function.name, json.loads(tc.function.arguments))
                processed_history.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": str(result)})
            final_res = await call(processed_history, stream=False)
            return {"reply": final_res.content}
        return {"reply": content}


@app.post("/api/summarize")
async def summarize_endpoint(request: SummarizeRequest):
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


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), conversation_id: str = Form(...)):
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
async def list_workspace_files_api(conversation_id: str):
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
        file_type: str = Form(...)  # "upload" or "generated"
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
async def delete_workspace(conversation_id: str):
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


@app.get("/api/download")
async def download_file(file_path: str):
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
