"""
模块描述：OpenAI 兼容模型调用封装，集中处理静态工具 schema、重试和工具消息配对。
"""

from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime
import os
import json
import logging
import time
import copy
from mcps import tools
from services.context_usage import extract_cache_stats, record_context_usage
from tools import registry
from llm.retry import with_retry

# 工具定义保持常态加载：从 mcps 导入后原样传给 API，不进入动态 prompt 加载链路。

logger = logging.getLogger(__name__)

# 加载.env文件中的环境变量
load_dotenv(".env")

_ENV_API_KEY = os.getenv("API_KEY") or ""
_ENV_BASE_URL = os.getenv("BASE_URL") or ""
LLM_MODEL = os.getenv("LLM_MODEL") or ""

if not _ENV_API_KEY:
    logger.warning("API_KEY 未在环境变量中设置，将仅使用管理后台保存的模型档案。")
if not _ENV_BASE_URL:
    logger.warning("BASE_URL 未在环境变量中设置，将仅使用管理后台保存的模型档案。")
if not LLM_MODEL:
    logger.warning("LLM_MODEL 未在环境变量中设置，将仅使用管理后台保存的模型档案。")

# 环境变量是基线配置。管理后台启用模型档案后，这里会被热替换成档案对应的 client，
# 因此管理员切换模型无需重启进程；未配置档案时行为与纯环境变量时代完全一致。
client = AsyncOpenAI(
    api_key=_ENV_API_KEY or "lawver-missing-api-key",
    base_url=_ENV_BASE_URL or "http://127.0.0.1/v1",
)
_client_signature: tuple[str, str, str] = ("", _ENV_BASE_URL, _ENV_API_KEY)


class LLMConfigurationError(RuntimeError):
    """环境变量与模型档案都没有提供可用的 LLM 配置。"""


def _runtime_llm_config() -> tuple[str, str, str, str]:
    """返回 (profile_id, model, base_url, api_key)，活动档案优先于环境变量。"""
    model, base_url, api_key, profile_id = LLM_MODEL, _ENV_BASE_URL, _ENV_API_KEY, ""
    try:
        from services import settings_service
        cfg = settings_service.resolve_active_llm_config() or {}
    except Exception:
        logger.debug("读取模型档案失败，回退到环境变量", exc_info=True)
        cfg = {}
    if cfg.get("profile_id"):
        profile_id = str(cfg["profile_id"])
        base_url = str(cfg.get("base_url") or base_url)
        model = str(cfg.get("model") or model)
        api_key = str(cfg.get("api_key") or api_key)
    return profile_id, model, base_url, api_key


def _refresh_client() -> tuple[str, str]:
    """活动档案变化时就地重建 client；未启用档案时保持环境变量 client 不动。"""
    global client, _client_signature
    profile_id, model, base_url, api_key = _runtime_llm_config()
    if not profile_id:
        return model, api_key
    signature = (profile_id, base_url, api_key)
    if signature != _client_signature and base_url and api_key:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        _client_signature = signature
        logger.info("已切换到模型档案 %s：%s @ %s", profile_id, model, base_url)
    return model, api_key


def _require_llm_credentials(api_key: str) -> None:
    if not api_key:
        raise LLMConfigurationError(
            "未配置大模型凭据：请在管理后台「模型配置」中保存 API Key，或设置环境变量 API_KEY。"
        )


class EmptyModelResponseError(RuntimeError):
    """Raised when a non-streaming model response contains neither content nor tool calls."""


def _now():
    return datetime.now()


def _extract_cache_stats(usage) -> tuple[int, int, int]:
    """返回 (prompt_tokens, cached_tokens, cache_miss_tokens)，缺失字段按 0 处理。"""
    return extract_cache_stats(usage)


def _record_response_usage(usage) -> tuple[int, int, int]:
    prompt, cached, miss = _extract_cache_stats(usage)
    record_context_usage(prompt, cached, miss)
    return prompt, cached, miss


def _is_unsupported_tool_choice_error(error: str) -> bool:
    lowered = error.lower()
    return "tool_choice" in lowered and (
        "does not support" in lowered
        or "not support" in lowered
        or "unsupported" in lowered
    )


def _sanitize_content(content):
    """多模态 parts 原样透传，其余内容按 OpenAI 规范字符串化。

    历史实现无条件 str()，会把 [{"type":"image_url",...}] 变成 Python repr，
    导致图片被丢弃且模型收到乱码文本。
    """
    if content is None:
        return ""
    if isinstance(content, list):
        parts = [part for part in content if isinstance(part, dict)]
        return parts or ""
    return str(content)


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

        # 2. 内容规范化：文本字符串化，多模态 parts 列表保持原样。
        m["content"] = _sanitize_content(m.get("content"))

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


async def call(
    context,
    stream=False,
    include_tools=True,
    *,
    tools_override: list | None = None,
    tool_exposure: str | None = None,
    tool_choice="auto",
):
    # 执行清洗
    modified_context = sanitize_messages(context)

    # 每轮都重新解析生效中的模型档案，实现不重启进程的热切换。
    active_model, active_api_key = _refresh_client()
    _require_llm_credentials(active_api_key)

    # 提取所有系统提示词并确保它们位于列表首位，保持 system 间原有顺序。
    system_msgs = [msg for msg in modified_context if msg["role"] == "system"]
    other_msgs = [msg for msg in modified_context if msg["role"] != "system"]

    if system_msgs:
        current = _now()
        weekday_cn = "一二三四五六日"[current.weekday()]
        current_date = current.strftime("%Y-%m-%d") + f" 星期{weekday_cn}"
        system_msgs[0]["content"] += f"\n\n【当前系统日期】：{current_date}"

    final_context = system_msgs + other_msgs

    selected_tools = None
    if tools_override is not None:
        selected_tools = tools_override
    elif tool_exposure is not None:
        selected_tools = registry.schemas(tool_exposure)
    elif include_tools:
        selected_tools = tools

    logger.debug(
        "LLM 调用 模型=%s 流式=%s 上下文长度=%s 包含工具=%s",
        active_model, stream, len(final_context), bool(selected_tools),
    )

    # 打印最后两条消息的摘要，方便调试
    if len(final_context) > 0:
        last_msg = final_context[-1]
        logger.debug("最后一条消息 角色=%s 内容长度=%s", last_msg.get("role"), len(last_msg["content"]))
        if "tool_calls" in last_msg:
            logger.debug("最后一条消息包含 %s 个工具调用", len(last_msg["tool_calls"]))

    kwargs = {
        "model": active_model,
        "messages": final_context,
        "stream": stream,
    }
    if stream:
        kwargs["stream_options"] = {"include_usage": True}

    if selected_tools:
        kwargs["tools"] = selected_tools
        kwargs["tool_choice"] = tool_choice

    # 瞬时错误重试配置
    MAX_RETRIES = 3
    RETRYABLE_STATUS_CODES = {
        "429",
        "500",
        "502",
        "503",
        "504",
        "Connection error",
        "RemoteProtocolError",
        "ReadError",
        "Timeout",
        "timeout",
        "timed out",
        "peer closed connection",
        "incomplete chunked read",
    }

    def _on_retry(attempt: int, max_retries: int, wait_time: float, exc: Exception):
        logger.warning("LLM 调用失败 (第 %s/%s 次): %s", attempt, max_retries, exc)
        logger.info("LLM 重试，等待 %ss 后重试", int(wait_time))

    try:
        response = await with_retry(
            lambda: client.chat.completions.create(**kwargs),
            max_retries=MAX_RETRIES,
            retryable_codes=RETRYABLE_STATUS_CODES,
            backoff_base=2,
            on_retry=_on_retry,
        )
        logger.debug("LLM 调用成功")
        if stream:
            return response
        prompt, cached, miss = _record_response_usage(getattr(response, "usage", None))
        if prompt:
            logger.debug(
                "LLM 缓存 model=%s prompt=%s cached=%s miss=%s hit_rate=%.1f%%",
                active_model, prompt, cached, miss, cached / prompt * 100,
            )
        message = response.choices[0].message
        if not (getattr(message, "content", None) or getattr(message, "tool_calls", None)):
            raise EmptyModelResponseError("模型响应为空：未返回 content 或 tool_calls")
        return message
    except Exception as e:
        error_str = str(e)

        if selected_tools and tool_choice != "auto" and _is_unsupported_tool_choice_error(error_str):
            logger.info("当前端点不支持强制 tool_choice，降级为 auto 重试一次")
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["tool_choice"] = "auto"
            response = await with_retry(
                lambda: client.chat.completions.create(**fallback_kwargs),
                max_retries=MAX_RETRIES,
                retryable_codes=RETRYABLE_STATUS_CODES,
                backoff_base=2,
                on_retry=_on_retry,
            )
            logger.debug("LLM 调用成功")
            if stream:
                return response
            prompt, cached, miss = _record_response_usage(getattr(response, "usage", None))
            if prompt:
                logger.debug(
                    "LLM 缓存 model=%s prompt=%s cached=%s miss=%s hit_rate=%.1f%%",
                    active_model, prompt, cached, miss, cached / prompt * 100,
                )
            message = response.choices[0].message
            if not (getattr(message, "content", None) or getattr(message, "tool_calls", None)):
                raise EmptyModelResponseError("模型响应为空：未返回 content 或 tool_calls")
            return message

        # 403 安全过滤 —— 不可重试，直接抛出友好异常
        if "403" in error_str and "Terms Of Service" in error_str:
            logger.warning("LLM 触发安全过滤: %s", error_str)
            raise Exception(
                "请求被服务商的安全策略拦截。这通常是因为输入内容或生成的回复触发了内容安全过滤（如涉及敏感话题或过于直接的法律建议）。请尝试调整提问方式，或添加更多背景信息。")

        logger.error("LLM 调用失败: %s", e)
        messages = kwargs.get("messages") or []
        logger.error(
            "LLM 调用失败的请求摘要: model=%s stream=%s messages=%s tools=%s",
            kwargs.get("model"), kwargs.get("stream"), len(messages), len(kwargs.get("tools") or []),
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
