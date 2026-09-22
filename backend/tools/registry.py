"""
模块描述：业务工具注册表，统一管理工具 schema、分发处理器和可见性标签。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable
import json
import logging


logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], str | None], Any]
ToolCoercer = Callable[[str], dict[str, Any]]
TRUSTED_INTERNAL_CAPABILITY = "internal"
AUTHORIZATION_ERROR = "tool_not_authorized"


@dataclass(frozen=True)
class ToolEntry:
    name: str
    schema: dict[str, Any]
    handler: ToolHandler
    exposure: frozenset[str]
    text_coercer: ToolCoercer | None = None


class ToolRegistry:
    def __init__(self):
        self._entries: list[ToolEntry] = []
        self._by_name: dict[str, ToolEntry] = {}

    def register(
        self,
        *,
        name: str,
        schema: dict[str, Any],
        handler: ToolHandler,
        exposure: Iterable[str],
        text_coercer: ToolCoercer | None = None,
    ) -> None:
        if name in self._by_name:
            raise ValueError(f"Tool already registered: {name}")
        entry = ToolEntry(
            name=name,
            schema=schema,
            handler=handler,
            exposure=frozenset(exposure),
            text_coercer=text_coercer,
        )
        self._entries.append(entry)
        self._by_name[name] = entry

    def names(self, exposure: str | None = None) -> list[str]:
        return [entry.name for entry in self._visible_entries(exposure)]

    def schemas(self, exposure: str | None = None) -> list[dict[str, Any]]:
        return [entry.schema for entry in self._visible_entries(exposure)]

    def format_descriptions(self, tool_defs: list[dict[str, Any]] | None = None) -> str:
        selected_tools = tool_defs if tool_defs is not None else self.schemas("agent")
        return "\n".join(
            f"- {tool['function']['name']}: {tool['function']['description']}"
            for tool in selected_tools
        )

    def coerce_arguments(self, function_name: str, arguments: Any) -> dict[str, Any]:
        entry = self._by_name.get(function_name)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                if entry and entry.text_coercer:
                    arguments = entry.text_coercer(arguments)

        if not isinstance(arguments, dict):
            return {}
        return arguments

    def dispatch(
        self,
        function_name: str,
        arguments: Any,
        workspace_scope: str | None = None,
        *,
        capability: str | None = None,
    ) -> Any:
        entry = self._by_name.get(function_name)
        if not entry:
            return function_name + "工具不存在,请重新检查"
        if capability != TRUSTED_INTERNAL_CAPABILITY and capability not in entry.exposure:
            return {
                "ok": False,
                "error": AUTHORIZATION_ERROR,
                "tool": function_name,
                "capability": capability or "missing",
            }
        normalized_arguments = self.coerce_arguments(function_name, arguments)
        try:
            return entry.handler(normalized_arguments, workspace_scope)
        except Exception as exc:  # noqa: BLE001 - 工具异常必须转成模型可读结果
            logger.exception("工具 %s 执行失败", function_name)
            return {
                "ok": False,
                "error": f"工具执行失败: {type(exc).__name__}: {exc}",
                "tool": function_name,
            }

    def _visible_entries(self, exposure: str | None) -> list[ToolEntry]:
        if exposure is None:
            return list(self._entries)
        return [entry for entry in self._entries if exposure in entry.exposure]


registry = ToolRegistry()
