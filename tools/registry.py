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

    def schemas_by_name(self, names: Iterable[str], *, pool: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """按名称从完整 schema 池中取出子集，保持 pool / 注册表原有顺序。"""
        wanted = {str(name) for name in names if name}
        if not wanted:
            return []
        source = pool if pool is not None else [entry.schema for entry in self._entries]
        selected: list[dict[str, Any]] = []
        for tool in source:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            if name in wanted:
                selected.append(tool)
        return selected

    def format_descriptions(
        self,
        tool_defs: list[dict[str, Any]] | None = None,
        *,
        max_desc_chars: int | None = None,
        exclude_names: Iterable[str] | None = None,
    ) -> str:
        selected_tools = tool_defs if tool_defs is not None else self.schemas("agent")
        excluded = {str(name) for name in (exclude_names or ()) if name}
        lines: list[str] = []
        for tool in selected_tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            if not name or name in excluded:
                continue
            description = str(function.get("description") or "").strip()
            if max_desc_chars is not None and max_desc_chars > 0 and len(description) > max_desc_chars:
                description = description[: max_desc_chars - 1].rstrip() + "…"
            lines.append(f"- {name}: {description}" if description else f"- {name}")
        return "\n".join(lines)

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
        # 计数在真正执行前：拒绝、报错都算一次调用尝试之后的真实成本节点，
        # 但工具不存在/无权限的早期返回不计费（它们没有产生任何成本）。
        try:
            from billing import metering

            metering.record_tool(function_name)
        except Exception:  # pragma: no cover - 计量不影响工具执行
            pass
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
