"""
模块描述：按「一轮」累计用量的计量器。

一轮（turn）= 一次用户请求引发的全部模型调用、工具调用与文档解析。
计量器用 ContextVar 承载，理由和 context_usage 一样：模型调用散落在
tool_loop、ocp、registry 等很多层里，逐层传参会污染几十个签名，而
`asyncio.to_thread` 会携带 ContextVar，工具线程里读得到。

设计取向是**只记账不拦截**：这里从不抛异常，任何计量失败都只是丢一条数据，
不能让一次正常的模型调用因为计费统计而失败。拦截是 ledger 与路由的职责。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional

from billing import pricing

_logger = logging.getLogger("lawver.billing")


@dataclass
class TurnUsage:
    """一轮的用量累计。金额用 micro-credit 整数，算完即定。"""

    username: str
    ref_id: str | None = None
    reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    documents: int = 0
    document_chars: int = 0
    model_calls: int = 0
    # 计费倍率与模型权重在轮次开始时快照，中途改档不影响已发生的用量。
    multiplier: float = 1.0
    calls: list[dict[str, Any]] = field(default_factory=list)

    # 未乘倍率的原始 credits，用于向用户解释「扣了多少、为什么」。
    base_credits: float = 0.0

    def add_model(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        model: str = "",
        weight: float = 1.0,
    ) -> None:
        prompt_tokens = max(int(prompt_tokens or 0), 0)
        completion_tokens = max(int(completion_tokens or 0), 0)
        if not prompt_tokens and not completion_tokens:
            return
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.model_calls += 1
        amount = pricing.model_credits(prompt_tokens, completion_tokens, weight)
        self.base_credits += amount
        self.calls.append(
            {
                "kind": "model",
                "model": model,
                "weight": weight,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "credits": round(amount, 4),
            }
        )

    def add_tool(self, name: str) -> None:
        self.tool_calls += 1
        amount = pricing.tool_price(name)
        self.base_credits += amount
        self.calls.append({"kind": "tool", "name": name, "credits": round(amount, 4)})

    def add_document(self, chars: int) -> None:
        chars = max(int(chars or 0), 0)
        if not chars:
            return
        self.documents += 1
        self.document_chars += chars
        amount = pricing.document_credits(chars)
        self.base_credits += amount
        self.calls.append(
            {"kind": "document", "chars": chars, "credits": round(amount, 4)}
        )

    @property
    def charged_micro(self) -> int:
        """实际扣除的 micro-credit（已乘计费倍率）。"""
        return pricing.credits(self.base_credits * self.multiplier)

    @property
    def is_empty(self) -> bool:
        return not (self.model_calls or self.tool_calls or self.documents)

    def summary(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "documents": self.documents,
            "document_chars": self.document_chars,
            "credits": pricing.as_credits(self.charged_micro),
            "multiplier": self.multiplier,
        }


_current_turn: ContextVar[Optional[TurnUsage]] = ContextVar(
    "lawver_turn_usage", default=None
)


def begin_turn(
    username: str,
    *,
    multiplier: float = 1.0,
    ref_id: str | None = None,
    reason: str = "",
) -> Optional[TurnUsage]:
    """开启一轮计量。返回句柄，调用方据此结算。"""
    if not username:
        return None
    turn = TurnUsage(
        username=username, multiplier=multiplier, ref_id=ref_id, reason=reason
    )
    _current_turn.set(turn)
    return turn


def current_turn() -> Optional[TurnUsage]:
    return _current_turn.get()


def end_turn() -> None:
    _current_turn.set(None)


# ─── 供底层调用点使用：没有开启轮次时静默忽略 ────────────────────────────


def record_model(prompt_tokens: int, completion_tokens: int, *, model: str = "", weight: float = 1.0) -> None:
    turn = _current_turn.get()
    if turn is None:
        return
    try:
        turn.add_model(prompt_tokens, completion_tokens, model=model, weight=weight)
    except Exception:  # pragma: no cover - 计量永不打断主流程
        _logger.exception("记录模型用量失败")


def record_tool(name: str) -> None:
    turn = _current_turn.get()
    if turn is None:
        return
    try:
        turn.add_tool(name)
    except Exception:  # pragma: no cover
        _logger.exception("记录工具调用失败")


def record_document(chars: int) -> None:
    turn = _current_turn.get()
    if turn is None:
        return
    try:
        turn.add_document(chars)
    except Exception:  # pragma: no cover
        _logger.exception("记录文档用量失败")
