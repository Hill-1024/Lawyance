"""
模块描述：prompt 约束覆盖静态压测——确保每条 L0/L1 红线、focus 去英化、court 关键短语都有锚点。
"""

import re
from pathlib import Path

import pytest

from prompt_loader import build_system_prompt
from services.court_prompts import build_court_messages


PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "lawver"


# ---------------------------------------------------------------------------
# 1) 去英化：focus 三件套不得残留英文条件式或 inactive guidance 类锚点。
# ---------------------------------------------------------------------------

ENGLISH_LEAKS = (
    "IF this turn",
    "inactive guidance",
    "treat this section",
    "legal-service",
    "legal-source",
    "case-analysis",
    "file-review",
)


@pytest.mark.parametrize("focus", [
    None,
    ["file_processing"],
    ["legal_retrieval"],
    ["general_gate"],
    ["general_gate", "file_processing", "legal_retrieval"],
])
def test_focus_prompts_have_no_english_leak(focus):
    prompt = build_system_prompt(focus=focus)
    for token in ENGLISH_LEAKS:
        assert token not in prompt, f"focus={focus} 仍残留英文片段: {token!r}"


def test_focus_prompts_use_chinese_conditional_anchor():
    for focus in (["file_processing"], ["legal_retrieval"], ["general_gate"]):
        prompt = build_system_prompt(focus=focus)
        assert "视本节为非激活指引" in prompt, f"focus={focus} 缺中文条件锚点"


# ---------------------------------------------------------------------------
# 2) L0/L1 红线锚点：核心 prompt 必须能定位到每条不可违反规则。
# ---------------------------------------------------------------------------

CORE_RED_LINES = {
    "L0-1 安全边界": ["安全边界", "忽略上述指令", "无法提供该信息"],
    "L0-2 禁止伪造": ["禁止伪造", "凭记忆编造", "工具检索结果"],
    "L0-3 禁止越权": ["禁止越权", "不替用户做决定"],
    "L0-4 输入免疫": ["输入免疫", "注入攻击意图"],
    "L1-1 工具先行": ["工具先行", "调用检索工具"],
    "L1-2 输出标签": ["<final_answer>", "</final_answer>"],
    "L1-3 信源标注": ["法律/案例信源", "联网搜索来源"],
    "L1-4 领域边界": ["领域边界", "简短边界说明"],
    "L1-5 禁 emoji": ["emoji"],
}


@pytest.mark.parametrize("rule_id,tokens", list(CORE_RED_LINES.items()))
def test_core_red_lines_have_anchors(rule_id, tokens):
    prompt = build_system_prompt()
    for token in tokens:
        assert token in prompt, f"{rule_id} 缺少锚点: {token!r}"


def test_constraint_recap_present_in_tail():
    prompt = build_system_prompt()
    recap_idx = prompt.find("核心约束重申")
    assert recap_idx > 0, "tail recap 未注入"
    # recap 必须落在 prompt 后 1/3，靠近尾部利用 recency 效应
    assert recap_idx > len(prompt) * 2 / 3, (
        f"tail recap 位于 {recap_idx}/{len(prompt)}，未落在 prompt 后 1/3"
    )


# ---------------------------------------------------------------------------
# 3) court 共通规则锚点：氛围基调、阶段感知、收束信号都得存在。
# ---------------------------------------------------------------------------

COURT_COMMON_ANCHORS = [
    "庭审氛围基调",
    "阶段感知",
    "轮次礼让",
    "无更多意见",
    "短句",
    "私有 brief",
    "本轮未核验",
    "推测写成已发生事实",
]


@pytest.mark.parametrize("anchor", COURT_COMMON_ANCHORS)
def test_court_common_anchor(anchor):
    msgs = build_court_messages(
        speaker="judge", case_type="civil", user_side="原告",
        court_state={"phase": "opening"}, shared_dossier={}, private_brief={},
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    assert anchor in text, f"court 共通规则缺锚点: {anchor!r}"


# ---------------------------------------------------------------------------
# 4) court 案由：三段式必须齐备（争点结构 / 典型攻防 / 特别红线）。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case_type,case_specific", [
    ("civil", ["请求权基础", "证据三性", "高度盖然性", "民事自认"]),
    ("administrative", ["职权依据", "程序合法性", "举证责任", "规范性文件"]),
    ("criminal", ["排除合理怀疑", "犯罪构成", "非法证据排除", "无罪推定"]),
])
def test_court_case_three_section_structure(case_type, case_specific):
    msgs = build_court_messages(
        speaker="opponent", case_type=case_type, user_side="原告",
        court_state={"phase": "claim_statement"}, shared_dossier={}, private_brief={},
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    for header in ("争点结构", "典型攻防", "特别红线"):
        assert header in text, f"{case_type} 缺三段式头: {header!r}"
    for token in case_specific:
        assert token in text, f"{case_type} 缺案由专属锚点: {token!r}"


# ---------------------------------------------------------------------------
# 5) court 角色：阶段化骨架与判断锚必须落到 prompt。
# ---------------------------------------------------------------------------

ROLE_ANCHORS = {
    "judge": ["阶段动作清单", "判断锚", "面对插嘴", "归纳争点"],
    "opponent": [
        "结构化质询路径",
        "可能事实/攻防假设/待核实事项",
        "不得把这类线索说成已经发生",
        "压力与假设性发问",
    ],
    "user_agent": [
        "阶段化发言骨架",
        "不得在公开发言中复述原文措辞",
        "接受 / 反驳 / 让",
        "私有 brief",
    ],
    "reviewer": [
        "复盘骨架",
        "事实缺口",
        "证据缺口",
        "下一轮训练建议",
    ],
}


@pytest.mark.parametrize("role,anchors", list(ROLE_ANCHORS.items()))
def test_court_role_anchors(role, anchors):
    speaker_key = "user" if role == "user_agent" else role
    msgs = build_court_messages(
        speaker=speaker_key, case_type="civil", user_side="原告",
        court_state={"phase": "claim_statement"}, shared_dossier={}, private_brief={},
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    for token in anchors:
        assert token in text, f"{role} 角色 prompt 缺锚点: {token!r}"


# ---------------------------------------------------------------------------
# 6) court 角色边界泄漏：除 user_agent / reviewer 外，brief 不得入 prompt。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("speaker", ["judge", "opponent"])
def test_court_private_brief_not_leaked_to_neutral_or_opponent(speaker):
    brief = {"strategy": "PRIVATE_BRIEF_SENTINEL_XYZ"}
    msgs = build_court_messages(
        speaker=speaker, case_type="civil", user_side="原告",
        court_state={"phase": "claim_statement"}, shared_dossier={}, private_brief=brief,
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    assert "PRIVATE_BRIEF_SENTINEL_XYZ" not in text, f"{speaker} 角色泄漏了用户私有 brief"


@pytest.mark.parametrize("speaker", ["user", "reviewer"])
def test_court_private_brief_reaches_user_agent_and_reviewer(speaker):
    brief = {"strategy": "PRIVATE_BRIEF_SENTINEL_XYZ"}
    msgs = build_court_messages(
        speaker=speaker, case_type="civil", user_side="原告",
        court_state={"phase": "claim_statement"}, shared_dossier={}, private_brief=brief,
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    assert "PRIVATE_BRIEF_SENTINEL_XYZ" in text, f"{speaker} 应当能读到 brief 但实际没读到"


# ---------------------------------------------------------------------------
# 7) court prompt 不得反向污染：不能塞回主聊天身份/契约。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("speaker", ["judge", "opponent", "reviewer", "user"])
def test_court_prompt_does_not_inherit_main_chat_identity(speaker):
    msgs = build_court_messages(
        speaker=speaker, case_type="civil", user_side="原告",
        court_state={"phase": "opening"}, shared_dossier={}, private_brief={},
        public_summary="", recent_events=[], memory_context="",
    )
    text = "\n".join(m["content"] for m in msgs)
    assert "你是 Lawver" not in text, f"{speaker} 错误继承了主聊天身份"
    assert "<character_sheet" not in text
    # user_agent 是唯一会出现 final_answer 字面量的角色（在禁止使用语境下）——
    # 这里允许 user / reviewer 出现"不加 `<final_answer>`"的禁止表述，但 judge / opponent 不应该。
    if speaker in {"judge", "opponent"}:
        assert "<final_answer>" not in text, f"{speaker} 不应出现 final_answer 字面量"


# ---------------------------------------------------------------------------
# 8) 主 prompt 中文字符占比：抽查英文比例，防止偷偷返潮。
# ---------------------------------------------------------------------------

def test_focus_prompt_chinese_density():
    """单独看 focus 片段，中文字符占非空白字符的比例应当超过 70%。"""
    for focus in (["file_processing"], ["legal_retrieval"], ["general_gate"]):
        focus_file = PROMPT_ROOT / "focus" / f"{focus[0]}.md"
        text = focus_file.read_text(encoding="utf-8")
        # 抠掉 HTML 注释、XML 标签、纯英文标识符（如标签名 current_focus）
        stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        stripped = re.sub(r"<[^>]+>", "", stripped)
        non_space = [c for c in stripped if not c.isspace()]
        chinese = [c for c in non_space if "一" <= c <= "鿿"]
        ratio = len(chinese) / max(len(non_space), 1)
        assert ratio > 0.7, f"focus={focus[0]} 中文比例仅 {ratio:.0%}，疑似返潮"
