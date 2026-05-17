"""
模块描述：动态系统 prompt 加载器，按 profile、模式、焦点和任务组合提示词片段。
"""

import os
import re
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT_PROFILE = "lawyance"
PROMPT_MODULE_DESCRIPTION_RE = re.compile(r"\A\s*<!--\s*模块描述：.*?-->\s*", re.DOTALL)

# 这里只加载系统提示词文本。工具 schema 必须由 function_calling.call 直接 tools=tools 传入。

CORE_SECTIONS = (
    "core/00-identity.md",
    "core/10-hard-constraints.md",
    "core/20-tool-source-policy.md",
    "core/30-output-contract.md",
    "core/40-file-processing.md",
    "core/90-disclaimer.md",
)

# 约束重申段 — 必须放在 system prompt 最尾部（利用 recency 效应）
CONSTRAINT_RECAP_SECTION = "core/50-constraint-recap.md"

MODE_SECTIONS = {
    "default": ("modes/default.md",),
    "react": ("modes/react.md",),
    "plan_and_solve": ("modes/plan_and_solve.md",),
}

FOCUS_SECTIONS = {
    "legal_retrieval": "focus/legal_retrieval.md",
    "file_processing": "focus/file_processing.md",
    "general_gate": "focus/general_gate.md",
}

TASK_ONLY_SECTIONS = {
    "history_summary": ("tasks/history_summary.md",),
}

OPTIONAL_SECTIONS = {
    "examples": ("examples/legal_consultation.md", "examples/file_review.md"),
}


def _prompt_root() -> Path:
    configured_root = os.getenv("LAWYANCE_PROMPT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    profile = os.getenv("LAWYANCE_PROMPT_PROFILE", DEFAULT_PROMPT_PROFILE)
    return (BASE_DIR / "prompts" / profile).resolve()


def _read_section(root: Path, relative_path: str, *, required: bool = True) -> str:
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Prompt section escapes prompt root: {relative_path}") from exc

    if not path.exists():
        if required:
            raise FileNotFoundError(f"Prompt section not found: {path}")
        return ""

    content = path.read_text(encoding="utf-8")
    return PROMPT_MODULE_DESCRIPTION_RE.sub("", content).strip()


def _read_sections(root: Path, relative_paths: Iterable[str], *, required: bool = True) -> list[str]:
    sections = []
    for relative_path in relative_paths:
        content = _read_section(root, relative_path, required=required)
        if content:
            sections.append(content)
    return sections


def _normalise_focus(focus: Iterable[str] | None) -> list[str]:
    seen = set()
    ordered_focus = []
    for item in focus or ():
        key = str(item or "").strip()
        if not key or key not in FOCUS_SECTIONS or key in seen:
            continue
        seen.add(key)
        ordered_focus.append(key)
    return ordered_focus


def build_system_prompt(
    agent_mode: str = "default",
    *,
    task: str = "chat",
    focus: Iterable[str] | None = None,
    memory_context: str = "",
) -> str:
    root = _prompt_root()

    if task in TASK_ONLY_SECTIONS:
        sections = _read_sections(root, TASK_ONLY_SECTIONS[task])
        return "\n\n".join(sections)

    mode = agent_mode if agent_mode in MODE_SECTIONS else "default"
    sections = _read_sections(root, CORE_SECTIONS)
    sections.extend(_read_sections(root, MODE_SECTIONS[mode]))

    focus_sections = [FOCUS_SECTIONS[key] for key in _normalise_focus(focus)]
    sections.extend(_read_sections(root, focus_sections, required=False))

    if os.getenv("LAWYANCE_PROMPT_INCLUDE_EXAMPLES") == "1":
        sections.extend(_read_sections(root, OPTIONAL_SECTIONS["examples"], required=False))

    memory = str(memory_context or "").strip()
    if memory:
        sections.append(f"<active_conversation_context>\n{memory}\n</active_conversation_context>")

    # 约束重申段放在 system prompt 最末尾，利用 recency 效应强化核心约束
    recap = _read_section(root, CONSTRAINT_RECAP_SECTION, required=False)
    if recap:
        sections.append(recap)

    return "\n\n".join(section for section in sections if section)


def build_system_memory(
    agent_mode: str = "default",
    *,
    task: str = "chat",
    focus: Iterable[str] | None = None,
    memory_context: str = "",
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                agent_mode=agent_mode,
                task=task,
                focus=focus,
                memory_context=memory_context,
            ),
        }
    ]
