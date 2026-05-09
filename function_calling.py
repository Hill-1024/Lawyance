from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import json
import time
import copy
from mcps import tools
from prompt_loader import build_system_memory

# 工具定义保持常态加载：从 mcps 导入后原样传给 API，不进入动态 prompt 加载链路。

# 加载.env文件中的环境变量
load_dotenv(".env")

API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")

# 异常检测
if not API_KEY:
    raise ValueError("API_KEY is not set in the environment variables.")
if not BASE_URL:
    raise ValueError("BASE_URL is not set in the environment variables.")
if not LLM_MODEL:
    raise ValueError("LLM_MODEL is not set in the environment variables.")

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)

memory = build_system_memory()


def sanitize_messages(messages):
    """
    极度严格的消息清洗，确保所有字段符合 OpenAI API 规范，防止 400 错误。
    """
    sanitized = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = copy.deepcopy(msg)

        # 1. 角色校验
        if "role" not in m:
            continue

        # 2. 内容强制字符串化 (OpenAI 要求 content 必须是字符串，即使为空)
        if "content" not in m or m["content"] is None:
            m["content"] = ""
        else:
            m["content"] = str(m["content"])

        # 3. 工具调用校验
        if "tool_calls" in m and m["tool_calls"]:
            valid_tool_calls = []
            for tc in m["tool_calls"]:
                if not isinstance(tc, dict):
                    continue
                tc_copy = copy.deepcopy(tc)
                # 确保 id 存在且非空
                if "id" not in tc_copy or not tc_copy["id"]:
                    tc_copy["id"] = f"call_{int(time.time())}_{len(valid_tool_calls)}"

                if "type" not in tc_copy or not tc_copy["type"]:
                    tc_copy["type"] = "function"

                # 确保 function 结构正确
                if "function" not in tc_copy or not isinstance(tc_copy["function"], dict):
                    continue
                func = tc_copy["function"]
                if "name" not in func or not func["name"]:
                    continue
                if "arguments" not in func or func["arguments"] is None:
                    func["arguments"] = "{}"
                elif not isinstance(func["arguments"], str):
                    func["arguments"] = json.dumps(func["arguments"])
                valid_tool_calls.append(tc_copy)
            if valid_tool_calls:
                m["tool_calls"] = valid_tool_calls
            else:
                m.pop("tool_calls", None)

        # 4. 移除空的推理内容与签名 (某些模型不支持空字符串或 None)
        if "reasoning_content" in m:
            if not m["reasoning_content"]:
                del m["reasoning_content"]
            else:
                m["reasoning_content"] = str(m["reasoning_content"])

        if "thought_signature" in m:
            if not m["thought_signature"]:
                del m["thought_signature"]
            else:
                m["thought_signature"] = str(m["thought_signature"])

        # 5. 工具返回消息校验
        if m["role"] == "tool":
            if "tool_call_id" not in m or not m["tool_call_id"]:
                # 丢弃没有 ID 的工具消息，因为它会导致 API 报错
                continue
            # OpenAI API 规范中，tool 角色不需要 name 字段，某些模型可能会严格校验
            if "name" in m:
                del m["name"]

        sanitized.append(m)
    return sanitized


async def call(context, stream=False, include_tools=True):
    # 执行清洗
    modified_context = sanitize_messages(context)

    # 提取系统提示词并确保其位于列表首位，且只有一份
    final_context = []
    system_msg = None

    for msg in modified_context:
        if msg["role"] == "system":
            if not system_msg:
                system_msg = msg
        else:
            final_context.append(msg)

    if system_msg:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        system_msg["content"] += f"\n\n【当前系统时间】：{current_time}"
        final_context.insert(0, system_msg)

    print(f"[LLM 调用] 模型: {LLM_MODEL}, 流式: {stream}, 上下文长度: {len(final_context)}, 包含工具: {include_tools}")

    # 打印最后两条消息的摘要，方便调试
    if len(final_context) > 0:
        last_msg = final_context[-1]
        print(f"  [最后一条消息] 角色: {last_msg['role']}, 内容长度: {len(last_msg['content'])}")
        if "tool_calls" in last_msg:
            print(f"  [最后一条消息] 包含 {len(last_msg['tool_calls'])} 个工具调用")

    kwargs = {
        "model": LLM_MODEL,
        "messages": final_context,
        "stream": stream,
    }

    if include_tools and tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # 瞬时错误重试配置
    MAX_RETRIES = 3
    RETRYABLE_STATUS_CODES = {"429", "500", "502", "503", "504"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(**kwargs)
            print(f"[LLM 调用成功]")
            if stream:
                return response
            return response.choices[0].message
        except Exception as e:
            error_str = str(e)

            # 403 安全过滤 —— 不可重试，直接抛出友好异常
            if "403" in error_str and "Terms Of Service" in error_str:
                print(f"[LLM 触发安全过滤]: {error_str}")
                raise Exception(
                    "请求被服务商的安全策略拦截。这通常是因为输入内容或生成的回复触发了内容安全过滤（如涉及敏感话题或过于直接的法律建议）。请尝试调整提问方式，或添加更多背景信息。")

            # 判断是否为可重试的瞬时错误
            is_retryable = any(code in error_str for code in RETRYABLE_STATUS_CODES)

            if is_retryable and attempt < MAX_RETRIES:
                wait_time = 2 ** (attempt + 1)  # 2s, 4s, 8s
                print(f"[LLM 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)]: {e}")
                print(f"[LLM 重试] 等待 {wait_time}s 后重试...")
                import asyncio
                await asyncio.sleep(wait_time)
                continue

            # 不可重试或已耗尽重试次数
            print(f"[LLM 调用失败]: {e}")
            messages = kwargs.get("messages") or []
            print(
                "[LLM 调用失败的请求摘要]: "
                f"model={kwargs.get('model')} "
                f"stream={kwargs.get('stream')} "
                f"messages={len(messages)} "
                f"tools={len(kwargs.get('tools') or [])}"
            )
            raise e


def create_assistant_message(content="", reasoning_content=None, tool_calls=None, thought_signature=None):
    msg = {"role": "assistant", "content": content or ""}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls

    if reasoning_content:
        msg["reasoning_content"] = reasoning_content

    if thought_signature:
        msg["thought_signature"] = thought_signature

    return msg
