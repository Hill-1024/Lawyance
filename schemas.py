"""
模块描述：FastAPI 请求体模型，集中定义后端 API 的稳定 wire shape。
"""

from typing import List, Optional

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


class SummarizeRequest(BaseModel):
    history: List[dict]


class MemorySyncRequest(BaseModel):
    conversation_id: str
    memory_snapshot: Optional[dict] = None
    history: List[dict] = Field(default_factory=list)
    mode: str = "rebuild"
    expected_revision: Optional[int] = None
    memory_conflict_strategy: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"
