"""
模块描述：统一原生 tool_calls Agent 循环，承载默认模式与 Plan-and-Solve 模式。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from typing import Any, Callable

from function_calling import call, create_assistant_message
from output_sanitizer import sanitize_llm_output, strip_think_blocks, strip_wrapper_tags
from context_usage import record_openai_usage
from media import (
    IMAGE_SIGNAL_KEY,
    MAX_IMAGE_VIEWS_PER_TURN,
    MAX_VIEW_TOTAL_BYTES,
    flatten_content_to_text,
)


_DEFAULT_MAX_ROUNDS = object()
TOOL_ROUND_LIMIT_ERROR = "tool_round_limit"
TOOL_AUTHORIZATION_ERROR = "tool_not_authorized"
_TRANSIENT_STREAM_ERROR_MARKERS = (
    "peer closed connection",
    "incomplete chunked read",
    "remoteprotocolerror",
    "connection error",
    "readerror",
    "read timeout",
    "timeout",
    "timed out",
)
ASK_USER_TOOL_NAME = "ask_user"
CONTROL_PLANE_TOOLS = {"submit_plan", "submit_final_answer", ASK_USER_TOOL_NAME}
LEGAL_EVIDENCE_TOOLS = {"match_legal_case", "get_article", "search_article", "get_linked_content"}
FILE_CONTEXT_TOOLS = {"list_workspace_files", "pdf_text_reader", "word_reader", "txt_md_reader"}
PLAN_TOOL_WORK_MARKERS = (
    "检索",
    "查询",
    "搜索",
    "读取",
    "文件",
    "附件",
    "法条",
    "案例",
    "法规",
    "企业",
    "文书",
    "合同",
    "生成",
)


def _optional_positive_int_env(name: str, default: int | None = None):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    raw_value = raw_value.strip()
    if raw_value.lower() in {"none", "unlimited", "off", "0", "-1"}:
        return None
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else None


def _json_content(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _load_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _forced_tool_choice(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def plan_and_solve_tool_choice_policy(state: dict[str, Any]):
    if not state.get("plan_submitted"):
        return _forced_tool_choice("submit_plan")
    if state.get("force_final"):
        return _forced_tool_choice("submit_final_answer")
    return "auto"


def _is_transient_stream_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in error_text for marker in _TRANSIENT_STREAM_ERROR_MARKERS)


class ToolLoopAgent:
    # 无论环境变量或构造参数如何配置，单次运行都不能越过此上限。
    HARD_MAX_ROUNDS = 32
    DEFAULT_MAX_ROUNDS = _optional_positive_int_env("LAWVER_MAX_TOOL_ROUNDS")
    DEFAULT_NON_STREAM_MAX_ROUNDS = _optional_positive_int_env(
        "LAWVER_MAX_NON_STREAM_TOOL_ROUNDS",
        DEFAULT_MAX_ROUNDS,
    )

    def __init__(
        self,
        memory: list | None = None,
        session_id: str = "default",
        workspace_scope: str | None = None,
        use_ocp: bool = True,
        execute_tool: Callable[[str, Any], str] | None = None,
        *,
        mode: str = "default",
        tools: list | None = None,
        max_rounds: int | None | object = _DEFAULT_MAX_ROUNDS,
        final_answer_source: str = "tagged_text",
        tool_choice_policy: Callable[[dict[str, Any]], str | dict] | None = None,
        execution_policy: dict[str, Any] | None = None,
        output_review: Any | None = None,
    ):
        self.memory = memory or []
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp
        self.output_review = output_review
        self.execute_tool = execute_tool or self._missing_tool_executor
        self.mode = mode
        self.tools = tools
        self.final_answer_source = final_answer_source
        self.tool_choice_policy = tool_choice_policy
        self.execution_policy = execution_policy or {}
        self._memory_candidate_emitted = False
        self._allowed_tool_names = self._tool_names(tools) if tools is not None else None

        if max_rounds is _DEFAULT_MAX_ROUNDS:
            configured_stream_limit = self.DEFAULT_MAX_ROUNDS
            configured_non_stream_limit = self.DEFAULT_NON_STREAM_MAX_ROUNDS
        else:
            configured_stream_limit = max_rounds
            configured_non_stream_limit = max_rounds
        self.max_rounds = self._effective_round_limit(configured_stream_limit)
        self.non_stream_max_rounds = self._effective_round_limit(configured_non_stream_limit)

    @staticmethod
    def _missing_tool_executor(function_name: str, arguments: Any) -> str:
        return f"{function_name}工具执行器未配置,请检查主调度模块"

    @staticmethod
    def _sanitize_tagged_answer(raw_content: str) -> str:
        result = sanitize_llm_output(raw_content, enforce_final_answer=True)
        if not result.strip():
            fallback = strip_think_blocks(raw_content)
            fallback = strip_wrapper_tags(fallback)
            return fallback.strip()
        return result

    @staticmethod
    def _sanitize_tool_answer(raw_content: str) -> str:
        result = sanitize_llm_output(raw_content, enforce_final_answer=False)
        if not result.strip():
            fallback = strip_think_blocks(raw_content)
            fallback = strip_wrapper_tags(fallback)
            return fallback.strip()
        return result

    @staticmethod
    def _sanitize_plain_answer(raw_content: str) -> str:
        fallback = strip_think_blocks(raw_content)
        fallback = strip_wrapper_tags(fallback)
        return fallback.strip()

    @staticmethod
    def _history_context_message(message: dict) -> dict:
        allowed_keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
        # history_trace 会原样回到前端渲染，多模态 parts 必须压成文本，否则 base64 会灌进 UI。
        trace: dict[str, Any] = {}
        for key, value in message.items():
            if key not in allowed_keys or value is None:
                continue
            trace[key] = flatten_content_to_text(value) if key == "content" else value
        return trace

    @staticmethod
    def _message_reasoning_content(message: Any) -> str:
        return getattr(message, "reasoning_content", None) or ""

    @staticmethod
    def _message_thought_signature(message: Any) -> str:
        return getattr(message, "thought_signature", None) or ""

    @staticmethod
    def _tool_names(tools: list | None) -> frozenset[str]:
        names: set[str] = set()
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if isinstance(function, dict) and function.get("name"):
                names.add(str(function["name"]))
        return frozenset(names)

    @classmethod
    def _effective_round_limit(cls, configured: Any) -> int:
        if isinstance(configured, int) and configured >= 0:
            return min(configured, cls.HARD_MAX_ROUNDS)
        return cls.HARD_MAX_ROUNDS

    def _tool_is_exposed(self, function_name: str) -> bool:
        if function_name in {"submit_plan", "submit_final_answer"} and self.mode != "plan_and_solve":
            return False
        if self._allowed_tool_names is None:
            return True
        return function_name in self._allowed_tool_names

    @staticmethod
    def _authorization_error(function_name: str, capability: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": TOOL_AUTHORIZATION_ERROR,
            "tool": function_name,
            "capability": capability,
        }

    @staticmethod
    def _is_authorization_error(result: Any) -> bool:
        return isinstance(result, dict) and result.get("error") == TOOL_AUTHORIZATION_ERROR

    @staticmethod
    def _round_limit_event(limit: int, *, stream: bool) -> dict[str, Any]:
        return {
            "type": "error" if stream else "content",
            "code": TOOL_ROUND_LIMIT_ERROR,
            "content": f"工具调用超过最大轮次 ({limit})，已停止。",
            "max_rounds": limit,
        }

    @staticmethod
    def _has_reached_round_limit(limit, round_num: int) -> bool:
        return isinstance(limit, int) and limit >= 0 and round_num >= limit

    @staticmethod
    def _tool_call_dict(tool_call: Any) -> dict[str, Any]:
        if isinstance(tool_call, dict):
            return tool_call
        if hasattr(tool_call, "model_dump"):
            return tool_call.model_dump(exclude_unset=True)
        function = getattr(tool_call, "function", None)
        return {
            "id": getattr(tool_call, "id", f"call_{int(time.time())}"),
            "type": "function",
            "function": {
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", ""),
            },
        }

    @staticmethod
    def _parse_arguments(function_name: str, arguments: Any) -> tuple[dict[str, Any], str | None]:
        if isinstance(arguments, dict):
            return arguments, None
        if arguments is None or arguments == "":
            return {}, None
        if not isinstance(arguments, str):
            return {}, json.dumps(
                {"error": "invalid_json_arguments", "raw": str(arguments), "tool": function_name},
                ensure_ascii=False,
            )
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}, json.dumps(
                {"error": "invalid_json_arguments", "raw": arguments, "tool": function_name},
                ensure_ascii=False,
            )
        if not isinstance(parsed, dict):
            return {}, json.dumps(
                {"error": "invalid_json_arguments", "raw": arguments, "tool": function_name},
                ensure_ascii=False,
            )
        return parsed, None

    @staticmethod
    def _format_plan_steps(steps: list[str]) -> str:
        if not steps:
            return "已收到计划，但计划步骤为空。"
        lines = ["已生成执行计划："]
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps, 1))
        return "\n".join(lines)

    @staticmethod
    def _user_choice_payload(result_content: str, fallback_args: dict[str, Any]) -> dict[str, Any]:
        payload = _load_json_object(result_content)
        if not payload:
            payload = fallback_args

        question = str(payload.get("question") or fallback_args.get("question") or "").strip()
        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            raw_options = fallback_args.get("options") if isinstance(fallback_args.get("options"), list) else []

        options: list[dict[str, str]] = []
        for index, raw_option in enumerate(raw_options or [], 1):
            if isinstance(raw_option, dict):
                label = str(raw_option.get("label") or raw_option.get("value") or "").strip()
                value = str(raw_option.get("value") or label).strip()
                description = str(raw_option.get("description") or "").strip()
                option_id = str(raw_option.get("id") or f"option_{index}").strip()
            else:
                label = str(raw_option or "").strip()
                value = label
                description = ""
                option_id = f"option_{index}"
            if not label:
                continue
            item = {"id": option_id or f"option_{index}", "label": label, "value": value or label}
            if description:
                item["description"] = description
            options.append(item)

        return {
            "id": f"ask_{int(time.time() * 1000)}",
            "question": question or "我需要你补充一个选择后才能继续。",
            "options": options,
            "allow_free_text": False if payload.get("allow_free_text") is False else True,
            "allow_ignore": False if payload.get("allow_ignore") is False else True,
            "free_text_label": str(payload.get("free_text_label") or "自定义"),
            "ignore_label": str(payload.get("ignore_label") or "忽略此问题"),
            "ignore_value": str(payload.get("ignore_value") or "忽略此问题，请根据现有信息自行判断并继续。"),
        }

    def _tool_choice(self, state: dict[str, Any]):
        if self.tool_choice_policy:
            return self.tool_choice_policy(state)
        return "auto"

    def _new_state(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "plan_submitted": False,
            "force_final": self.final_answer_source == "tool_arg" and self.mode == "plan_and_solve",
            "final_answer_submitted": False,
            "awaiting_user": False,
            "tool_history": [],
            "submitted_plan_steps": [],
            "policy_repair_attempted": False,
        }

    @staticmethod
    def _plan_steps_need_tools(steps: list[str]) -> bool:
        return any(
            marker in step
            for step in steps
            for marker in PLAN_TOOL_WORK_MARKERS
        )

    @staticmethod
    def _has_any_tool(state: dict[str, Any], names: set[str]) -> bool:
        return any(name in names for name in state.get("tool_history", []))

    @staticmethod
    def _has_business_tool_after_plan(state: dict[str, Any]) -> bool:
        return any(name not in CONTROL_PLANE_TOOLS for name in state.get("tool_history", []))

    def _policy_repair_message(self, state: dict[str, Any]) -> str | None:
        policy = self.execution_policy or {}
        if not policy.get("soft_repair_enabled", True):
            return None
        if state.get("policy_repair_attempted"):
            return None

        missing: list[str] = []
        if policy.get("requires_legal_evidence") and not self._has_any_tool(state, LEGAL_EVIDENCE_TOOLS):
            missing.append(
                "本轮涉及法律依据或法律结论，但尚未调用法条/案例检索工具。请先调用 match_legal_case、get_article、search_article 或 get_linked_content 获取可核验依据。"
            )
        if (policy.get("requires_file_read") or policy.get("requires_workspace_listing")) and not self._has_any_tool(state, FILE_CONTEXT_TOOLS):
            missing.append(
                "本轮涉及文件或工作区材料，但尚未列出或读取文件。请先调用 list_workspace_files 或对应 reader 工具确认文件内容。"
            )

        plan_steps = state.get("submitted_plan_steps") or []
        if (
            self.mode == "plan_and_solve"
            and plan_steps
            and self._plan_steps_need_tools(plan_steps)
            and not self._has_business_tool_after_plan(state)
        ):
            missing.append("已提交的计划包含检索、查询、读取或生成等工具性步骤，但尚未执行任何业务工具。请先补齐计划中的工具步骤。")

        if not missing:
            return None
        state["policy_repair_attempted"] = True
        state["force_final"] = False
        state["final_answer_submitted"] = False
        return "\n".join(
            [
                "<execution_policy_repair>",
                "最终回答前发现执行缺口。不要向用户解释内部策略；请继续调用必要工具或明确补齐依据后再提交最终回答。",
                *[f"- {item}" for item in missing],
                "</execution_policy_repair>",
            ]
        )

    async def _process_tool_calls(
        self,
        current_mem: list[dict],
        tool_calls: list[dict[str, Any]],
        *,
        assistant_content: str = "",
        reasoning_content: str = "",
        thought_signature: str = "",
        state: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        events: list[dict[str, Any]] = []
        assistant_msg = create_assistant_message(
            content=assistant_content or "",
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            thought_signature=thought_signature,
        )
        current_mem.append(assistant_msg)
        events.append({"type": "history_trace", "content": [self._history_context_message(assistant_msg)]})

        final_answer: str | None = None
        awaiting_user = False
        loaded_images: list[dict[str, Any]] = []
        loaded_image_names: list[str] = []
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            func_name = function.get("name") or ""
            args_str = function.get("arguments") or ""
            args, parse_error_content = self._parse_arguments(func_name, args_str)
            result: Any = None
            if parse_error_content is not None:
                result_content = parse_error_content
            else:
                if self._tool_is_exposed(func_name):
                    # PDF/DOCX parsing、HTTP 检索和 SQLite 记忆工具均为同步
                    # 实现；在事件循环内直接调用会冻结所有 SSE/心跳连接。
                    result = await asyncio.to_thread(self.execute_tool, func_name, args)
                    if inspect.isawaitable(result):
                        result = await result
                else:
                    result = self._authorization_error(func_name, self.mode)
                result_content = _json_content(result)

                if self._is_authorization_error(result):
                    events.append({
                        "type": "thought",
                        "content": f"工具 `{func_name}` 未获当前模式授权，已拒绝执行。\n",
                        "thought_type": "tool",
                        "mode": "new",
                    })
                else:
                    state.setdefault("tool_history", []).append(func_name)
                    # 控制面分支只能在 executor/registry 已确认授权后改变状态。
                    if func_name == "submit_plan":
                        steps = [str(step).strip() for step in args.get("steps", []) if str(step).strip()]
                        state["submitted_plan_steps"] = steps
                        state["plan_submitted"] = True
                        state["force_final"] = False
                        events.append({
                            "type": "thought",
                            "thought_type": "plan",
                            "mode": "new",
                            "content": self._format_plan_steps(steps),
                        })
                    elif func_name == "submit_final_answer":
                        final_answer = str(args.get("answer") or "")
                        state["final_answer_submitted"] = True
                    elif func_name == ASK_USER_TOOL_NAME:
                        events.append({"type": "thought", "content": "等待用户确认下一步\n", "thought_type": "tool", "mode": "new"})
                        state["awaiting_user"] = True
                        awaiting_user = True
                    else:
                        events.append({"type": "thought", "content": f"执行: `{func_name}`\n", "thought_type": "tool", "mode": "new"})

            # image_reader 无法用纯文本返回画面：载荷先收集起来，等本轮所有 tool 消息
            # 追加完毕后再统一挂到一条 user 消息上。
            # 两个约束叠加导致的：
            #   1. OpenAI 规范里 tool 消息的 content 必须是字符串（数组实测被端点 400 拒绝）；
            #   2. tool_calls 之后必须连续跟满对应的 tool 消息，
            #      逐条插入 user 消息会把 tool 块切断，触发
            #      "insufficient tool messages following tool_calls message"。
            if isinstance(result, dict) and IMAGE_SIGNAL_KEY in result:
                part = result.get(IMAGE_SIGNAL_KEY)
                views = int(state.get("image_views", 0))
                used_bytes = int(state.get("image_view_bytes", 0))
                part_bytes = int(result.get("bytes") or 0)
                if views >= MAX_IMAGE_VIEWS_PER_TURN:
                    result_content = f"本轮已读取 {views} 张图片，达到上限，请基于已看到的画面继续作答。"
                elif used_bytes + part_bytes > MAX_VIEW_TOTAL_BYTES:
                    result_content = "图片总量超过本轮上限，未加载。请让用户提供更小的图片或改用文字说明。"
                else:
                    state["image_views"] = views + 1
                    state["image_view_bytes"] = used_bytes + part_bytes
                    loaded_images.append(part)
                    loaded_image_names.append(str(result.get("name") or "图片"))
                    result_content = f"图片 {result.get('name')} 已加载，画面见随后的消息，请直接依据画面作答。"

            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.get("id") or f"call_{int(time.time())}",
                "name": func_name,
                "content": result_content,
            }
            current_mem.append(tool_msg)
            events.append({"type": "history_trace", "content": [self._history_context_message(tool_msg)]})

            if awaiting_user:
                events.append({
                    "type": "user_choice_request",
                    "content": self._user_choice_payload(result_content, args),
                })
                break
            if final_answer is not None:
                break

        # 所有 tool 消息都已追加完毕，此时再挂图片，保证 tool 块连续完整。
        if loaded_images:
            image_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": "以下是本轮通过 image_reader 读取到的图片画面。"},
                    *loaded_images,
                ],
            }
            current_mem.append(image_msg)
            events.append({"type": "history_trace", "content": [self._history_context_message(image_msg)]})
            for name in loaded_image_names:
                events.append({
                    "type": "thought",
                    "content": f"已查看图片: `{name}`\n",
                    "thought_type": "tool",
                    "mode": "new",
                })

        return events, final_answer, awaiting_user

    async def _final_answer_events(self, raw_answer: str, *, stream: bool):
        if self.final_answer_source == "plain_text":
            answer = self._sanitize_plain_answer(raw_answer)
        elif self.final_answer_source == "tool_arg":
            answer = self._sanitize_tool_answer(raw_answer)
        else:
            answer = self._sanitize_tagged_answer(raw_answer)

        should_emit_memory_candidate = self.final_answer_source == "tool_arg" or (
            self.use_ocp and self.final_answer_source != "plain_text"
        )
        if should_emit_memory_candidate and answer.strip() and not self._memory_candidate_emitted:
            self._memory_candidate_emitted = True
            yield {"type": "memory_candidate", "content": answer}

        if self.use_ocp and self.output_review is not None and answer.strip():
            # output_review 由 services.agent_builder 统一注入；agent 循环不直接依赖 OCP。
            if stream:
                async for ocp_chunk in self.output_review.stream(answer):
                    yield ocp_chunk
            else:
                checked = await self.output_review.complete(answer)
                yield {"type": "content", "content": checked}
        else:
            if self.use_ocp and self.output_review is None and answer.strip():
                print("[ToolLoopAgent] use_ocp=True 但未注入 output_review，已跳过 OCP 审查")
            yield {"type": "content_replace" if stream else "content", "content": answer}

    async def run(self, content: str = None, stream: bool = True):
        self._memory_candidate_emitted = False
        state = self._new_state()
        if stream:
            async for event in self._run_stream(state):
                yield event
        else:
            async for event in self._run_non_stream(state):
                yield event

    async def _run_stream(self, state: dict[str, Any]):
        current_mem = self.memory
        accumulated_content = ""
        round_num = 0
        while True:
            if self._has_reached_round_limit(self.max_rounds, round_num):
                event = self._round_limit_event(self.max_rounds, stream=True)
                print(f"[ToolLoopAgent 流式] {event['content']}")
                yield event
                return

            round_num += 1
            print(f"[ToolLoopAgent 流式] 第 {round_num} 轮调用 mode={self.mode}")
            tool_choice = self._tool_choice(state)
            response = await call(
                current_mem,
                True,
                tools_override=self.tools,
                tool_choice=tool_choice,
            )
            tool_calls: list[dict[str, Any]] = []
            assistant_content = ""
            reasoning_str = ""
            thought_signature_str = ""
            saw_delta = False
            is_drafting = False

            try:
                async for chunk in response:
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        record_openai_usage(usage)

                    if not getattr(chunk, "choices", None):
                        continue
                    saw_delta = True
                    delta = chunk.choices[0].delta

                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        reasoning_str += reasoning
                        yield {"type": "thought", "content": reasoning, "thought_type": "reasoning", "mode": "append"}

                    ts = getattr(delta, "thought_signature", None)
                    if ts:
                        thought_signature_str = ts

                    delta_content = getattr(delta, "content", None)
                    if delta_content is not None:
                        assistant_content += delta_content
                        accumulated_content += delta_content
                        if self.final_answer_source == "plain_text":
                            yield {"type": "content", "content": delta_content}
                        elif self.use_ocp or self.final_answer_source == "tool_arg":
                            if not is_drafting:
                                is_drafting = True
                                yield {"type": "thought", "content": "正在拟定回答初稿\n", "thought_type": "draft", "mode": "new"}
                            yield {"type": "thought", "content": delta_content, "thought_type": "draft", "mode": "append"}
                        else:
                            yield {"type": "thought", "content": delta_content, "thought_type": "draft", "mode": "append"}

                    for tc in getattr(delta, "tool_calls", None) or []:
                        tc_index = getattr(tc, "index", None)
                        tc_dump = self._tool_call_dict(tc)
                        if tc_index is None:
                            is_new_call = ("id" in tc_dump) or ("function" in tc_dump and "name" in tc_dump["function"])
                            tc_index = len(tool_calls) if len(tool_calls) == 0 or is_new_call else len(tool_calls) - 1
                        while len(tool_calls) <= tc_index:
                            tool_calls.append({
                                "id": f"call_{int(time.time())}_{tc_index}",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                        if tc_dump.get("id"):
                            tool_calls[tc_index]["id"] = tc_dump["id"]
                        if "type" in tc_dump and tc_dump["type"]:
                            tool_calls[tc_index]["type"] = tc_dump["type"]
                        if isinstance(tc_dump.get("function"), dict):
                            for key, value in tc_dump["function"].items():
                                if value:
                                    tool_calls[tc_index]["function"][key] += value
            except Exception as exc:
                if not _is_transient_stream_error(exc):
                    raise
                print(f"[ToolLoopAgent 流式] 上游流式连接中断，改用非流式重试本轮: {exc}")
                yield {
                    "type": "thought",
                    "content": "上游流式连接中断，正在切换为非流式重试本轮\n",
                    "thought_type": "draft",
                    "mode": "new",
                }
                res = await call(
                    current_mem,
                    stream=False,
                    tools_override=self.tools,
                    tool_choice=tool_choice,
                )
                assistant_content = getattr(res, "content", None) or ""
                accumulated_content = assistant_content
                reasoning_str = self._message_reasoning_content(res)
                thought_signature_str = self._message_thought_signature(res)
                tool_calls = [self._tool_call_dict(tool_call) for tool_call in (getattr(res, "tool_calls", None) or [])]
                saw_delta = bool(assistant_content or tool_calls)

            if tool_calls:
                yield {"type": "thought", "content": "**正在调用工具处理中...**\n", "thought_type": "tool", "mode": "new"}
                events, final_answer, awaiting_user = await self._process_tool_calls(
                    current_mem,
                    tool_calls,
                    assistant_content=assistant_content,
                    reasoning_content=reasoning_str,
                    thought_signature=thought_signature_str,
                    state=state,
                )
                for event in events:
                    yield event
                if awaiting_user:
                    if thought_signature_str:
                        yield {"type": "thought_signature", "content": thought_signature_str}
                    return
                if final_answer is not None:
                    repair_message = self._policy_repair_message(state)
                    if repair_message:
                        current_mem.append({"role": "system", "content": repair_message})
                        yield {
                            "type": "thought",
                            "content": "发现执行缺口，正在补充必要工具步骤\n",
                            "thought_type": "tool",
                            "mode": "new",
                        }
                        accumulated_content = ""
                        continue
                    async for event in self._final_answer_events(final_answer, stream=True):
                        yield event
                    if thought_signature_str:
                        yield {"type": "thought_signature", "content": thought_signature_str}
                    return
                accumulated_content = ""
                continue

            if not saw_delta or not assistant_content:
                yield {"type": "error", "content": "模型响应为空：未返回 content 或 tool_calls"}
                return

            if self.final_answer_source == "tool_arg":
                if not state.get("plan_submitted"):
                    yield {"type": "error", "content": "Plan-and-Solve 规划阶段未调用 submit_plan，流程已停止。"}
                    return
                if state.get("force_final"):
                    yield {"type": "error", "content": "Plan-and-Solve 汇总阶段未调用 submit_final_answer，流程已停止。"}
                    return
                current_mem.append(create_assistant_message(content=assistant_content, reasoning_content=reasoning_str, thought_signature=thought_signature_str))
                state["force_final"] = True
                accumulated_content = ""
                continue

            if thought_signature_str:
                yield {"type": "thought_signature", "content": thought_signature_str}
            repair_message = self._policy_repair_message(state)
            if repair_message:
                current_mem.append(create_assistant_message(content=assistant_content, reasoning_content=reasoning_str, thought_signature=thought_signature_str))
                current_mem.append({"role": "system", "content": repair_message})
                yield {
                    "type": "thought",
                    "content": "发现执行缺口，正在补充必要工具步骤\n",
                    "thought_type": "tool",
                    "mode": "new",
                }
                accumulated_content = ""
                continue
            async for event in self._final_answer_events(accumulated_content, stream=True):
                yield event
            return

    async def _run_non_stream(self, state: dict[str, Any]):
        current_mem = self.memory
        content_output = ""
        round_num = 0
        while True:
            if self._has_reached_round_limit(self.non_stream_max_rounds, round_num):
                event = self._round_limit_event(self.non_stream_max_rounds, stream=False)
                print(f"[ToolLoopAgent 非流式] {event['content']}")
                yield event
                return

            round_num += 1
            print(f"[ToolLoopAgent 非流式] 第 {round_num} 轮调用 mode={self.mode}")
            res = await call(
                current_mem,
                stream=False,
                tools_override=self.tools,
                tool_choice=self._tool_choice(state),
            )
            content_output = getattr(res, "content", None) or ""
            reasoning_content = self._message_reasoning_content(res)
            thought_signature = self._message_thought_signature(res)
            raw_tool_calls = getattr(res, "tool_calls", None) or []

            if raw_tool_calls:
                tool_calls = [self._tool_call_dict(tool_call) for tool_call in raw_tool_calls]
                events, final_answer, awaiting_user = await self._process_tool_calls(
                    current_mem,
                    tool_calls,
                    assistant_content=content_output,
                    reasoning_content=reasoning_content,
                    thought_signature=thought_signature,
                    state=state,
                )
                for event in events:
                    yield event
                if awaiting_user:
                    if thought_signature:
                        yield {"type": "thought_signature", "content": thought_signature}
                    return
                if final_answer is not None:
                    repair_message = self._policy_repair_message(state)
                    if repair_message:
                        current_mem.append({"role": "system", "content": repair_message})
                        yield {
                            "type": "history_trace",
                            "content": [self._history_context_message({"role": "system", "content": repair_message})],
                        }
                        continue
                    async for event in self._final_answer_events(final_answer, stream=False):
                        yield event
                    if thought_signature:
                        yield {"type": "thought_signature", "content": thought_signature}
                    return
                continue

            if self.final_answer_source == "tool_arg":
                if not content_output:
                    yield {"type": "error", "content": "模型响应为空：未返回 content 或 tool_calls"}
                    return
                if not state.get("plan_submitted"):
                    yield {"type": "error", "content": "Plan-and-Solve 规划阶段未调用 submit_plan，流程已停止。"}
                    return
                if state.get("force_final"):
                    yield {"type": "error", "content": "Plan-and-Solve 汇总阶段未调用 submit_final_answer，流程已停止。"}
                    return
                current_mem.append(create_assistant_message(
                    content=content_output,
                    reasoning_content=reasoning_content,
                    thought_signature=thought_signature,
                ))
                state["force_final"] = True
                continue

            repair_message = self._policy_repair_message(state)
            if repair_message:
                current_mem.append(create_assistant_message(
                    content=content_output,
                    reasoning_content=reasoning_content,
                    thought_signature=thought_signature,
                ))
                current_mem.append({"role": "system", "content": repair_message})
                yield {
                    "type": "history_trace",
                    "content": [self._history_context_message({"role": "system", "content": repair_message})],
                }
                continue
            async for event in self._final_answer_events(content_output, stream=False):
                yield event
            if thought_signature:
                yield {"type": "thought_signature", "content": thought_signature}
            return
