from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import json
import os
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
    summary_prompt = "请简要总结以下对话的核心内容和已达成的共识，以便作为后续对话的上下文参考：\n\n"
    for m in to_summarize:
        role = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content") or ""
        summary_prompt += f"{role}: {content[:200]}...\n"

    try:
        # 调用 LLM 进行摘要
        summary_res = await call([{"role": "user", "content": summary_prompt}], stream=False)
        summary_text = f"[前情提要]: {summary_res.content}"
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


def build_agent(mode: str, memory: list):
    if mode in ["react", "plan_and_solve"]:
        from mcps import tools as all_tools
        tool_executor = ToolExecutor()
        for tool_def in all_tools:
            name = tool_def["function"]["name"]
            desc = tool_def["function"]["description"]

            def create_tool_func(n):
                return lambda args_str: use_tools(n, json.loads(args_str) if isinstance(args_str,
                                                                                        str) and args_str.strip().startswith(
                    '{') else args_str)

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

    agent = build_agent(agent_mode, processed_history)

    if agent:
        if stream:
            async def generate_agent():
                full_result = ""
                try:
                    async for chunk in agent.run(content):
                        if chunk:
                            full_result += chunk
                            yield chunk
                except Exception as e:
                    yield f"\n[Agent 错误]: {e}\n"

            return StreamingResponse(generate_agent(), media_type="text/plain")
        else:
            try:
                full_result = ""
                async for chunk in agent.run(content):
                    full_result += chunk
                return {"reply": full_result}
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
                                tc_index = tc.index if tc.index is not None else len(tool_calls)
                                while len(tool_calls) <= tc_index:
                                    # 为工具调用生成默认 ID，防止模型未返回 ID 导致 400 错误
                                    tool_calls.append({"id": f"call_{int(time.time())}_{tc_index}", "type": "function",
                                                       "function": {"name": "", "arguments": ""}})
                                tc_dump = tc.model_dump(exclude_unset=True)
                                if "id" in tc_dump and tc_dump["id"]:
                                    tool_calls[tc_index]["id"] = tc_dump["id"]
                                if "function" in tc_dump:
                                    for k, v in tc_dump["function"].items():
                                        if v: tool_calls[tc_index]["function"][k] += v

                    if has_started_reasoning and not has_finished_reasoning:
                        yield "\n</think>\n"
                        content_str += "\n</think>\n"
                        has_finished_reasoning = True

                    if is_tool_call:
                        yield "\n<think>\n️ **正在调用工具处理中...**\n"

                        assistant_msg = create_assistant_message(content=content_str or "",
                                                                 reasoning_content=reasoning_str, tool_calls=tool_calls)
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

                            yield f"️ 执行: `{func_name}`\n"
                            result = use_tools(func_name, args)
                            current_mem.append(
                                {"role": "tool", "tool_call_id": tc["id"], "name": func_name, "content": str(result)})
                        yield " **工具执行完毕，正在生成最终回复...**\n</think>\n"
                        continue
                    else:
                        break
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"\n\n[后端错误]: {str(e)}"

        return StreamingResponse(generate(), media_type="text/plain")
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
    temp_mem = copy.deepcopy(history)
    temp_mem.append({"role": "user",
                     "content": "请用一句话（不超过10个字）总结我们目前的对话内容，作为对话标题。只输出标题文本，不要包含任何标点符号。"})
    response = await call(temp_mem, stream=False)
    title = (response.content or "").strip().strip('"').strip("'")
    return {"title": title or "New Chat"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), conversation_id: str = Form(...)):
    temp_dir = os.path.join("TEMP", conversation_id)
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@app.get("/api/download")
async def download_file(file_path: str):
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=os.path.basename(file_path))
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    dist_path = os.path.join("dist", full_path)
    if os.path.isfile(dist_path):
        return FileResponse(dist_path)
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    return {"message": "Stateless Agent is running."}


if __name__ == '__main__':
    port = int(os.getenv("PORT", 3000))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, workers=4)
