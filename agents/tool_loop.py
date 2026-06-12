"""
模块描述：统一原生 tool_calls Agent 循环，承载默认模式与 Plan-and-Solve 模式。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from function_calling import call, create_assistant_message
from output_sanitizer import sanitize_llm_output, strip_think_blocks, strip_wrapper_tags
from services.context_usage import record_openai_usage


_DEFAULT_MAX_ROUNDS = object()
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
    ):
        self.memory = memory or []
        self.session_id = session_id
        self.workspace_scope = workspace_scope or session_id
        self.use_ocp = use_ocp
        self.execute_tool = execute_tool or self._missing_tool_executor
        self.mode = mode
        self.tools = tools
        self.final_answer_source = final_answer_source
        self.tool_choice_policy = tool_choice_policy
        self._memory_candidate_emitted = False

        if max_rounds is _DEFAULT_MAX_ROUNDS:
            self.max_rounds = self.DEFAULT_MAX_ROUNDS
            self.non_stream_max_rounds = self.DEFAULT_NON_STREAM_MAX_ROUNDS
        else:
            self.max_rounds = max_rounds
            self.non_stream_max_rounds = max_rounds

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
        return {key: value for key, value in message.items() if key in allowed_keys and value is not None}

    @staticmethod
    def _message_reasoning_content(message: Any) -> str:
        return getattr(message, "reasoning_content", None) or ""

    @staticmethod
    def _message_thought_signature(message: Any) -> str:
        return getattr(message, "thought_signature", None) or ""

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
        }

    def _process_tool_calls(
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
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            func_name = function.get("name") or ""
            args_str = function.get("arguments") or ""
            args, parse_error_content = self._parse_arguments(func_name, args_str)

            if parse_error_content is not None:
                result_content = parse_error_content
            elif func_name == "submit_plan":
                result_content = _json_content(self.execute_tool(func_name, args))
                steps = [str(step).strip() for step in args.get("steps", []) if str(step).strip()]
                state["plan_submitted"] = True
                state["force_final"] = False
                events.append({
                    "type": "thought",
                    "thought_type": "plan",
                    "mode": "new",
                    "content": self._format_plan_steps(steps),
                })
            elif func_name == "submit_final_answer":
                result_content = _json_content(self.execute_tool(func_name, args))
                final_answer = str(args.get("answer") or "")
                state["final_answer_submitted"] = True
            elif func_name == ASK_USER_TOOL_NAME:
                events.append({"type": "thought", "content": "等待用户确认下一步\n", "thought_type": "tool", "mode": "new"})
                result_content = _json_content(self.execute_tool(func_name, args))
                state["awaiting_user"] = True
                awaiting_user = True
            else:
                events.append({"type": "thought", "content": f"执行: `{func_name}`\n", "thought_type": "tool", "mode": "new"})
                result_content = _json_content(self.execute_tool(func_name, args))

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

        if self.use_ocp and answer.strip():
            if stream:
                from ocp import OCPStream
                ocp = OCPStream(session_id=self.workspace_scope)
                async for ocp_chunk in ocp.check_stream(answer):
                    yield ocp_chunk
            else:
                from ocp import OCPStatic
                checker = OCPStatic(session_id=self.workspace_scope)
                checked = await checker.check(answer)
                yield {"type": "content", "content": checked}
        else:
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
                msg = f"工具调用超过最大轮次 ({self.max_rounds})，已停止。"
                print(f"[ToolLoopAgent 流式] {msg}")
                yield {"type": "error", "content": msg}
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
                events, final_answer, awaiting_user = self._process_tool_calls(
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
            async for event in self._final_answer_events(accumulated_content, stream=True):
                yield event
            return

    async def _run_non_stream(self, state: dict[str, Any]):
        current_mem = self.memory
        content_output = ""
        round_num = 0
        while True:
            if self._has_reached_round_limit(self.non_stream_max_rounds, round_num):
                msg = f"工具调用超过最大轮次 ({self.non_stream_max_rounds})，已停止。"
                print(f"[ToolLoopAgent 非流式] {msg}")
                yield {"type": "content", "content": msg}
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
                events, final_answer, awaiting_user = self._process_tool_calls(
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

            async for event in self._final_answer_events(content_output, stream=False):
                yield event
            if thought_signature:
                yield {"type": "thought_signature", "content": thought_signature}
            return
