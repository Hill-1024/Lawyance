"""
模块描述：FastAPI 请求体模型，集中定义后端 API 的稳定 wire shape 与输入预算。
"""

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_USERNAME_CHARS = 128
MAX_PASSWORD_CHARS = 1024
MAX_IDENTIFIER_CHARS = 160
MAX_MESSAGE_CHARS = 200_000
MAX_HISTORY_ITEMS = 400
MAX_HISTORY_TOTAL_CHARS = 2_000_000
MAX_NESTING_DEPTH = 12
MAX_JSON_NODES = 20_000
MAX_NESTED_STRING_CHARS = 200_000
MAX_NESTED_KEY_CHARS = 256
WEBDAV_MAX_DECODED_BYTES = 25 * 1024 * 1024
WEBDAV_MAX_BASE64_CHARS = 4 * ((WEBDAV_MAX_DECODED_BYTES + 2) // 3)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}")

MessageRole = Literal["system", "user", "assistant", "tool"]
AgentMode = Literal["default", "plan_and_solve"]
MemorySyncMode = Literal["merge", "rebuild"]
MemoryConflictStrategy = Literal["server_merge"]
CourtRole = Literal["judge", "opponent", "reviewer", "user"]
AccountRole = Literal["sudo", "admin", "user"]
ProviderKey = Literal["llm", "deli", "searxng", "qcc", "embedding"]

MAX_ONLINE_LIMIT = 1000
MAX_USERS_QUOTA = 10_000


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_json_budget(
    value: Any,
    *,
    label: str,
    max_nodes: int = MAX_JSON_NODES,
    max_total_chars: int = MAX_HISTORY_TOTAL_CHARS,
) -> Any:
    """Bound arbitrary JSON before business code recursively copies or serializes it."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    total_chars = 0

    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise ValueError(f"{label} 结构项过多")
        if depth > MAX_NESTING_DEPTH:
            raise ValueError(f"{label} 嵌套层级过深")

        if isinstance(item, Mapping):
            if len(item) > 2_000:
                raise ValueError(f"{label} 单层字段过多")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > MAX_NESTED_KEY_CHARS:
                    raise ValueError(f"{label} 包含非法或过长字段名")
                total_chars += len(key)
                stack.append((child, depth + 1))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            if len(item) > 2_000:
                raise ValueError(f"{label} 单层列表过长")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > MAX_NESTED_STRING_CHARS:
                raise ValueError(f"{label} 包含超长字符串")
            total_chars += len(item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"{label} 包含非有限数字")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError(f"{label} 只能包含 JSON 值")

        if total_chars > max_total_chars:
            raise ValueError(f"{label} 文本总量过大")

    return value


def _validate_history(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    for message in value:
        if not isinstance(message, dict):
            raise ValueError("history 每项必须是对象")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("history 包含未知 role")
    return _validate_json_budget(value, label="history")


class Message(RequestModel):
    role: MessageRole
    content: Optional[str] = Field(default=None, max_length=MAX_MESSAGE_CHARS)
    reasoning_content: Optional[str] = Field(default=None, max_length=MAX_MESSAGE_CHARS)
    tool_calls: Optional[List[dict]] = Field(default=None, max_length=64)
    tool_call_id: Optional[str] = Field(default=None, max_length=256)
    name: Optional[str] = Field(default=None, max_length=256)

    @field_validator("tool_calls", mode="before")
    @classmethod
    def validate_tool_calls(cls, value: Any) -> Any:
        if value is not None:
            _validate_json_budget(value, label="tool_calls", max_nodes=2_000, max_total_chars=500_000)
        return value


class ChatRequest(RequestModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: List[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    conversation_id: str = Field(default="default", min_length=1, max_length=MAX_IDENTIFIER_CHARS)
    stream: bool = True
    resume_enabled: bool = False
    agent_mode: AgentMode = "default"
    use_ocp: bool = True
    memory_snapshot: Optional[dict] = None
    memory_sync_mode: Optional[MemorySyncMode] = None
    expected_revision: Optional[int] = Field(default=None, ge=0, le=2**63 - 1)
    memory_conflict_strategy: Optional[MemoryConflictStrategy] = None
    last_context_tokens: Optional[int] = Field(default=None, ge=0, le=10_000_000)

    _history_budget = field_validator("history", mode="before")(_validate_history)

    @field_validator("memory_snapshot", mode="before")
    @classmethod
    def validate_memory_snapshot(cls, value: Any) -> Any:
        if value is not None:
            _validate_json_budget(value, label="memory_snapshot")
        return value


class SummarizeRequest(RequestModel):
    history: List[dict] = Field(max_length=MAX_HISTORY_ITEMS)

    _history_budget = field_validator("history", mode="before")(_validate_history)


class MemorySyncRequest(RequestModel):
    conversation_id: str = Field(min_length=1, max_length=MAX_IDENTIFIER_CHARS)
    memory_snapshot: Optional[dict] = None
    history: List[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    mode: MemorySyncMode = "rebuild"
    expected_revision: Optional[int] = Field(default=None, ge=0, le=2**63 - 1)
    memory_conflict_strategy: Optional[MemoryConflictStrategy] = None

    _history_budget = field_validator("history", mode="before")(_validate_history)

    @field_validator("memory_snapshot", mode="before")
    @classmethod
    def validate_memory_snapshot(cls, value: Any) -> Any:
        if value is not None:
            _validate_json_budget(value, label="memory_snapshot")
        return value


class ResumeAckRequest(RequestModel):
    stream_id: str = Field(min_length=1, max_length=128)
    acked_seq: int = Field(ge=-1, le=2**63 - 1)


class StreamCancelRequest(RequestModel):
    stream_id: str = Field(min_length=1, max_length=128)


class CourtTurnRequest(RequestModel):
    court_session_id: str = Field(min_length=1, max_length=MAX_IDENTIFIER_CHARS)
    court_state: dict[str, Any] = Field(default_factory=dict, max_length=2_000)
    shared_dossier: dict[str, Any] = Field(default_factory=dict, max_length=2_000)
    private_brief: dict[str, Any] = Field(default_factory=dict, max_length=2_000)
    public_events_recent: List[dict[str, Any]] = Field(default_factory=list, max_length=400)
    public_summary: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    agent_states: dict[str, Any] = Field(default_factory=dict, max_length=32)

    @field_validator(
        "court_state",
        "shared_dossier",
        "private_brief",
        "public_events_recent",
        "agent_states",
        mode="before",
    )
    @classmethod
    def validate_court_json(cls, value: Any, info) -> Any:
        return _validate_json_budget(value, label=info.field_name)


class CourtMemoryClearRequest(RequestModel):
    court_session_id: str = Field(min_length=1, max_length=MAX_IDENTIFIER_CHARS)
    # 可选指定清哪些角色；缺省清所有 AI 角色。
    roles: Optional[List[CourtRole]] = Field(default=None, max_length=4)


class LoginRequest(RequestModel):
    username: str = Field(min_length=1, max_length=MAX_USERNAME_CHARS)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


class AccountRequest(RequestModel):
    username: str = Field(min_length=1, max_length=MAX_USERNAME_CHARS)
    password: str = Field(min_length=6, max_length=MAX_PASSWORD_CHARS)
    role: Optional[AccountRole] = "user"
    # 0 / -1 表示不限制；None 表示沿用原值。仅 sudo 有权设置这些字段。
    max_online: Optional[int] = Field(default=None, ge=0, le=MAX_ONLINE_LIMIT)
    max_users: Optional[int] = Field(default=None, ge=-1, le=MAX_USERS_QUOTA)
    user_max_online: Optional[int] = Field(default=None, ge=0, le=MAX_ONLINE_LIMIT)


class AccountLimitsRequest(RequestModel):
    max_online: Optional[int] = Field(default=None, ge=0, le=MAX_ONLINE_LIMIT)
    max_users: Optional[int] = Field(default=None, ge=-1, le=MAX_USERS_QUOTA)
    user_max_online: Optional[int] = Field(default=None, ge=0, le=MAX_ONLINE_LIMIT)


class WebDavConfig(RequestModel):
    url: str = Field(min_length=1, max_length=4_096)
    username: str = Field(max_length=MAX_USERNAME_CHARS)
    password: str = Field(max_length=MAX_PASSWORD_CHARS)
    directory: str = Field(default="/Lawver/", min_length=1, max_length=1_024)


class WebDavTestRequest(RequestModel):
    config: WebDavConfig


class WebDavListRequest(RequestModel):
    config: WebDavConfig


class WebDavUploadRequest(RequestModel):
    config: WebDavConfig
    filename: str = Field(min_length=1, max_length=255)
    data_b64: str = Field(min_length=4, max_length=WEBDAV_MAX_BASE64_CHARS)

    @field_validator("data_b64", mode="before")
    @classmethod
    def validate_base64_budget(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if len(value) > WEBDAV_MAX_BASE64_CHARS:
            raise HTTPException(status_code=413, detail="备份文件超过上限 25 MB。")
        if len(value) % 4 != 0 or not _BASE64_RE.fullmatch(value):
            raise ValueError("data_b64 不是合法的 base64 数据")
        padding = len(value) - len(value.rstrip("="))
        decoded_size = (len(value) // 4) * 3 - padding
        if decoded_size > WEBDAV_MAX_DECODED_BYTES:
            raise HTTPException(status_code=413, detail="备份文件超过上限 25 MB。")
        return value


class WebDavDownloadRequest(RequestModel):
    config: WebDavConfig
    filename: str = Field(min_length=1, max_length=255)


class WebDavDeleteRequest(RequestModel):
    config: WebDavConfig
    filename: str = Field(min_length=1, max_length=255)


class ProviderSettings(RequestModel):
    enabled: bool = False
    base_url: Optional[str] = Field(default=None, max_length=4_096)
    model: Optional[str] = Field(default=None, max_length=512)
    endpoint: Optional[str] = Field(default=None, max_length=4_096)
    language: Optional[str] = Field(default=None, max_length=64)
    safe_search: Optional[Literal["", "0", "1", "2"]] = None
    engines: Optional[str] = Field(default=None, max_length=1_024)
    categories: Optional[str] = Field(default=None, max_length=1_024)
    api_key: Optional[str] = Field(default=None, max_length=4_096)


class SettingsPayload(RequestModel):
    version: Optional[Literal[1]] = 1
    providers: dict[ProviderKey, ProviderSettings] = Field(default_factory=dict, max_length=5)
