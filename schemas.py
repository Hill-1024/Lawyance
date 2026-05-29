"""
模块描述：FastAPI 请求体模型，集中定义后端 API 的稳定 wire shape。
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


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
    memory_sync_mode: Optional[str] = None
    expected_revision: Optional[int] = None
    memory_conflict_strategy: Optional[str] = None
    last_context_tokens: Optional[int] = None


class SummarizeRequest(BaseModel):
    history: List[dict]


class MemorySyncRequest(BaseModel):
    conversation_id: str
    memory_snapshot: Optional[dict] = None
    history: List[dict] = Field(default_factory=list)
    mode: str = "rebuild"
    expected_revision: Optional[int] = None
    memory_conflict_strategy: Optional[str] = None


class CourtTurnRequest(BaseModel):
    court_session_id: str
    court_state: dict[str, Any] = Field(default_factory=dict)
    shared_dossier: dict[str, Any] = Field(default_factory=dict)
    private_brief: dict[str, Any] = Field(default_factory=dict)
    public_events_recent: List[dict[str, Any]] = Field(default_factory=list)
    public_summary: str = ""
    agent_states: dict[str, Any] = Field(default_factory=dict)


class CourtMemoryClearRequest(BaseModel):
    court_session_id: str
    # 可选指定清哪些角色；缺省清所有 AI 角色。
    roles: Optional[List[str]] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"


class WebDavConfig(BaseModel):
    url: str
    username: str
    password: str
    directory: str = "/Lawver/"


class WebDavTestRequest(BaseModel):
    config: WebDavConfig


class WebDavListRequest(BaseModel):
    config: WebDavConfig


class WebDavUploadRequest(BaseModel):
    config: WebDavConfig
    filename: str
    data_b64: str  # base64 编码的 JSON 字节，上限 25MB


class WebDavDownloadRequest(BaseModel):
    config: WebDavConfig
    filename: str


class WebDavDeleteRequest(BaseModel):
    config: WebDavConfig
    filename: str
