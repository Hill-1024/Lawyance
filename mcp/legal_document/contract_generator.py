"""
模块描述：定制化合同生成器。
对外暴露两个 MCP 工具：
  - get_contract_skeleton: 返回通用合同 block 骨架 + 写作守则
  - compose_contract: 根据 blocks 数组渲染定制化合同 docx

与 generator.py 的区别：
  - 不依赖预置 guide JSON 文件——合同结构由 LLM 根据用户需求自由设计。
  - 软约束更宽松——不强制 required_sections，只检查标题/落款/元评论。
  - 输出文件后缀为 _contract.docx 而非 _lawver.docx。
"""

from __future__ import annotations

import json
import os
import re
import time

from .composer import compose_docx
from .errors import (
    DocumentGenerationError,
    FieldValidationError,
    LegalDocumentError,
)
from .logger import (
    log_generation_complete,
    log_generation_error,
    log_generation_start,
    log_unexpected_error,
)
from .validator import evaluate_soft_constraints, validate_blocks
from workspace import WorkspacePathError, validate_workspace_scope


_GLOBAL_HARD_CONSTRAINTS = """## 文书写作硬约束（最高优先级，违反者后端将自动剥离或返回告警）

### A. blocks.text 是纯文本，直进 docx
- **禁止任何 HTML/XML 标签**:`<sup>` 角标、`<final_answer>` 包装、`<think>`、`<b>`、`<i>`、`<span>` 等一律不能出现在 block 的 text/items/header/rows 中。
- 引用法条直接写正文,不加角标、不加链接:
  - ❌ 错误:`根据《民法典》第六百七十五条<sup><a href="https://...">1</a></sup>之规定`
  - ✅ 正确:`根据《中华人民共和国民法典》第六百七十五条之规定`
- 你在工具检索中拿到的 URL 仅供你自行核实条文标准用语;**不要**塞进任何 block 字段,也**不要**在文书末尾追加「参考资料」「信源」等区块 —— 法律文书没有这种规范结构。

### B. 文书中严禁元评论与思绪解释
文书是当事人的法律文书,**不是**对话回复。下列内容**绝对不能**出现在任何 block.text 中:
- ❌ 「我这样写是因为...」「我之所以这样起草...」「我认为应当...」
- ❌ 「以下是修改后的合同条款:」「这里是付款方式部分:」「下面给出违约责任部分:」
- ❌ 「以上为草拟稿,仅供参考」「如有疑问请咨询执业律师」(这类提示属于工具调用语境,不属于文书本身)
- ❌ 任何带「(作者注:...)」「(此处补充:...)」的括号注释
- 合同必须以**当事人立场**写作:
  - ✅ 「甲方委托乙方...」「双方协商一致...」
  - ❌ 「我认为」「我希望」「咱们」「您」「你」(除非引用对话原话)

### C. 不要把工具调用上下文写入文书
- `<final_answer>`、`<think>`、「正在调用工具处理中」等属于 Agent 协议或运行时提示,绝不能进入 blocks。
- 检索结果的标题、来源说明、网页摘要也不能直接复制为 paragraph,需自行转译为符合法律文书语体的陈述。

---

（以下为合同写作具体守则）

"""

_CONTRACT_HARD_CONSTRAINTS = """## 合同定制化硬约束（以下内容绝对不能出现在任何 block 中）

### A. 合同是法律文件，不是普法教材
以下内容类型**绝对禁止**出现在合同中：
- ❌ 通俗解释 / 名词解释（如"（通俗地说，这指的是...）""术语说明：..."）
- ❌ 法律知识科普（如"法律小贴士：根据《民法典》...""普法提示"）
- ❌ 风险提示独立段落（作为独立章节标题单独成立，如 heading="风险提示"；但作为合同条款内的"免责声明"子条款除外——那应放在违约责任条款中表述）
- ❌ 权益告知书（如"消费者权益告知书""个人信息保护告知"等独立告知文书，不得嵌入或附加在合同里）
- ❌ 操作建议（如"建议您在签署前咨询律师""温馨提示：请仔细阅读每一条款"——这些是工具调用语境中的提示，不是合同内容）
- ❌ 政策解读（如"根据 2024 年最新司法解释...""近年来司法实践中..."等背景阐述）

✅ 正确做法：合同条款应**直接陈述权利义务**，不解释为什么、不科普背景、不插入告知书。
  - ✅ "乙方交付的软件应符合甲方提供的《技术规格书》要求。"
  - ❌ "乙方交付的软件应符合甲方提供的《技术规格书》要求。（通俗地说，就是乙方做的软件要和甲方要求的完全一样，不能偷工减料）"

### B. 合同是双方协议，不是多方会议纪要
- 合同仅限**甲方与乙方**两方，不出现丙方、丁方等多方。
- 落款（signature_block）仅限甲、乙两方签字，不出现第三方见证人、担保人（如需担保，应另签担保合同）。

### C. 附件处理
- 附件在正文中以条款引用（如"本合同附件一《需求规格说明书》为本合同不可分割的组成部分"）。
- 不要单独生成附件内容块，不要把附件内容展开写进合同正文。

---

"""

_CONTRACT_GUIDE_MARKDOWN = """## 合同写作通用守则

### A. 基本格式
- 使用"甲方""乙方"指代合同双方，明确各自身份。
- 条款编号清晰，使用"第一条""第二条"或"1.""2."等。
- 涉及金额、期限、比例的必须明确具体数字，不得使用"合理""适当"等模糊表述。

### B. 必备要素
根据《中华人民共和国民法典》第四百七十条，合同一般包括：
1. 当事人姓名/名称和住所
2. 标的（合同指向的对象或服务）
3. 数量
4. 质量
5. 价款或报酬
6. 履行期限、地点和方式
7. 违约责任
8. 争议解决方法

### C. 文体要求
- 语言严谨、无歧义。
- 金额同时使用阿拉伯数字和中文大写（如"人民币 100,000 元（壹拾万元整）"）。
- 日期使用中文大写（如"二〇二六年六月十一日"）。
- 涉及免责条款、违约责任、争议解决等关键条款应醒目、明确。

### D. 常见误区
- ❌ 金额不明确："约 10 万元" → ✅ "人民币 100,000 元（壹拾万元整）"
- ❌ 违约责任缺失或过于笼统
- ❌ 未约定争议解决方式（诉讼/仲裁，管辖地）
- ❌ 甲方乙方信息不完整（缺少证件号、地址）

"""

_CONTRACT_SKELETON = [
    {"type": "title", "text": "合同标题"},
    {"type": "paragraph", "text": "甲方：[名称/姓名]，统一社会信用代码/身份证号：[号码]，住所地/住址：[地址]，法定代表人：[姓名]，联系电话：[电话]。", "indent": False},
    {"type": "paragraph", "text": "乙方：[名称/姓名]，统一社会信用代码/身份证号：[号码]，住所地/住址：[地址]，法定代表人：[姓名]，联系电话：[电话]。", "indent": False},
    {"type": "heading", "level": 1, "text": "第一条  合同标的"},
    {"type": "paragraph", "text": "[在此处描述合同标的、数量、质量标准等具体内容]", "indent": True},
    {"type": "blank_line"},
    {"type": "signature_block", "signer": "甲方（盖章）：", "entity": "乙方（盖章）：", "date": "年  月  日"},
]

_CONTRACT_GUIDE = {
    "doc_type": "定制合同",
    "category": "合同",
    "description": "根据用户需求自由定制的通用合同。",
    "applicable_law": ["《中华人民共和国民法典》合同编"],
    "required_sections": [],
    "soft_warnings": [
        "应有合同标题。",
        "应明确甲乙方基本信息。",
        "应有合同标的条款。",
        "应有价款/报酬条款。",
        "应有违约责任条款。",
        "应有争议解决条款。",
        "应有双方签字盖章。",
    ],
    "guide_markdown": _CONTRACT_GUIDE_MARKDOWN,
}

_OUTPUT_NAME_SAFE = re.compile(r"[^\w一-龥\-]+")
_MAX_OUTPUT_NAME_CHARS = 120

# 合同不宜内容检测正则：(pattern, 告警描述)
_CONTRACT_PROHIBITED_PATTERNS = [
    (re.compile(r'通俗[的得地]?[说来]?(?:解释|讲|表述)'), "含'通俗解释/通俗地说'等普法用语"),
    (re.compile(r'名词解释|术语[说明释表]'), "含'名词解释/术语说明'等科普内容"),
    (re.compile(r'风险提示[：:]'), "含'风险提示'独立段落或章节标题"),
    (re.compile(r'权益告知'), "含'权益告知书'等独立告知文书内容"),
    (re.compile(r'法律[知识]?小贴士|普法提示|温馨提示|操作建议'), "含法律科普或操作建议用语"),
    (re.compile(r'[（(]通俗[的得地]?[说来]?[：:，][^)）]*[)）]'), "含括号括注的通俗解释"),
    (re.compile(r'丙方|丁方'), "含超出甲乙两方的多方签署（丙方/丁方）"),
]


def _collect_contract_text(blocks: list[dict]) -> str:
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype in ("title", "heading", "paragraph"):
            parts.append(str(b.get("text", "")))
        elif btype in ("ordered_list", "unordered_list"):
            for item in b.get("items") or []:
                parts.append(str(item))
        elif btype == "table":
            for cell in b.get("header") or []:
                parts.append(str(cell))
            for row in b.get("rows") or []:
                for cell in row or []:
                    parts.append(str(cell))
        elif btype == "signature_block":
            for line in b.get("lines") or []:
                parts.append(str(line))
            for key in ("signer", "entity", "date"):
                if b.get(key):
                    parts.append(str(b[key]))
    return "\n".join(parts)


def _scan_contract_content(blocks: list[dict]) -> list[str]:
    """扫描 blocks 中是否出现了合同不宜内容（通俗解释、风险提示、多方签署等），返回告警列表。"""
    warnings: list[str] = []
    full_text = _collect_contract_text(blocks)
    for pat, desc in _CONTRACT_PROHIBITED_PATTERNS:
        m = pat.search(full_text)
        if m:
            sample = m.group(0)
            if len(sample) > 50:
                sample = sample[:50] + "…"
            warnings.append(
                "检测到合同不宜内容（{}）：'{}'。"
                "合同是法律文件而非普法教材，请移除通俗解释、风险提示独立段落、多方签署等内容，"
                "直接以甲方/乙方立场陈述合同条款。".format(desc, sample)
            )
    return warnings


def _make_response(success: bool, data: dict | None = None, meta: dict | None = None) -> str:
    result: dict = {"success": success}
    if data is not None:
        result["data"] = data
    if meta is not None:
        result["meta"] = meta
    return json.dumps(result, ensure_ascii=False, indent=2)


def _make_error_response(error: LegalDocumentError, meta: dict | None = None) -> str:
    result = error.to_dict()
    if meta is not None:
        result["meta"] = meta
    return json.dumps(result, ensure_ascii=False, indent=2)


def _sanitize_output_name(name: str) -> str:
    name = name.strip()[:_MAX_OUTPUT_NAME_CHARS]
    name = _OUTPUT_NAME_SAFE.sub("_", name)
    return name.strip("_") or "定制合同"


def _get_output_path(workspace_scope: str | None, output_name: str | None) -> str:
    safe_scope = validate_workspace_scope(workspace_scope)
    result_dir = os.path.join("Result", safe_scope)
    os.makedirs(result_dir, exist_ok=True)
    if output_name:
        base = _sanitize_output_name(output_name)
    else:
        base = "定制合同"
    return os.path.join(result_dir, "{}_contract.docx".format(base)).replace("\\", "/")


def get_contract_skeleton() -> str:
    """返回通用合同 block 骨架。LLM 在此基础上根据用户需求修改、扩展后，调用 compose_contract 渲染。"""
    return _make_response(success=True, data={
        "doc_type": "定制合同",
        "description": "根据用户需求自由定制的通用合同。适用于预置 12 种法律文书之外的任意合同类型（如买卖、服务、租赁、承揽、合作、保密、股权转让等）。",
        "skeleton": _CONTRACT_SKELETON,
        "guide": _GLOBAL_HARD_CONSTRAINTS + _CONTRACT_HARD_CONSTRAINTS + _CONTRACT_GUIDE_MARKDOWN,
        "block_schema": {
            "supported_types": [
                "title", "heading", "paragraph", "ordered_list",
                "unordered_list", "table", "signature_block",
                "page_break", "blank_line",
            ],
            "examples": {
                "title": {"type": "title", "text": "软件开发合同"},
                "heading": {"type": "heading", "level": 1, "text": "第一条  项目内容"},
                "paragraph": {"type": "paragraph", "text": "条款正文…", "indent": True, "align": "justify"},
                "ordered_list": {"type": "ordered_list", "items": ["1. 功能 A", "2. 功能 B"]},
                "unordered_list": {"type": "unordered_list", "items": ["要点 A", "要点 B"]},
                "table": {"type": "table", "header": ["阶段", "交付物", "时间"], "rows": [["1", "...", "..."]]},
                "signature_block": {"type": "signature_block", "signer": "甲方（盖章）：", "entity": "乙方（盖章）：", "date": "二〇二六年六月十一日"},
                "page_break": {"type": "page_break"},
                "blank_line": {"type": "blank_line"},
            },
        },
        "usage_note": "请在拿到 skeleton 后，根据用户的具体合同需求：1) 修改 title 为具体合同名称；2) 填写甲乙方真实信息；3) 设计合同条款（用 heading 做条款标题 + paragraph 做条款内容，可用 ordered_list/table 辅助）；4) 调整落款格式。修改完成后调用 compose_contract 渲染。",
    })


def compose_contract(
    blocks: list[dict],
    output_name: str | None = None,
    workspace_scope: str | None = None,
) -> str:
    """根据 blocks 数组渲染定制化合同 DOCX。"""
    start_time = time.time()

    if output_name is not None and (
        not isinstance(output_name, str) or len(output_name) > _MAX_OUTPUT_NAME_CHARS
    ):
        error = FieldValidationError("定制合同", ["output_name 必须是长度不超过 120 的字符串"])
        return _make_error_response(error)

    try:
        normalized_blocks = validate_blocks(blocks, "定制合同")
    except FieldValidationError as e:
        return _make_error_response(e)

    generation_id = log_generation_start("定制合同", len(normalized_blocks))

    soft_warnings = evaluate_soft_constraints(normalized_blocks, _CONTRACT_GUIDE)

    contract_warnings = _scan_contract_content(normalized_blocks)
    if contract_warnings:
        soft_warnings = list(soft_warnings) + contract_warnings

    try:
        output_path = _get_output_path(workspace_scope, output_name)
    except WorkspacePathError as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError("定制合同", "工作区作用域非法: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={
            "generation_id": generation_id, "duration_ms": round(duration_ms, 1),
        })

    try:
        compose_stats = compose_docx(normalized_blocks, output_path)
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        log_unexpected_error("render_contract", exc, generation_id)
        error = DocumentGenerationError("定制合同", "DOCX 渲染失败，请稍后重试。")
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={
            "generation_id": generation_id, "duration_ms": round(duration_ms, 1),
        })

    duration_ms = (time.time() - start_time) * 1000
    log_generation_complete(generation_id, duration_ms, output_path)

    extracted_refs = compose_stats.get("extracted_refs", [])
    if extracted_refs:
        soft_warnings = list(soft_warnings) + [
            "检测到 {} 处 HTML 角标(如 <sup><a>),已自动剥离为 [N] 形式;"
            "请勿在合同 block.text 中使用 <sup> 角标，引用法条直接写正文。"
            .format(len(extracted_refs))
        ]

    return _make_response(success=True, data={
        "output_path": output_path,
        "soft_warnings": soft_warnings,
        "rendered_block_counts": compose_stats["rendered_block_counts"],
        "skipped_unknown_types": compose_stats["skipped_unknown_types"],
        "extracted_refs": extracted_refs,
    }, meta={
        "generation_id": generation_id,
        "status": "completed",
        "duration_ms": round(duration_ms, 1),
        "doc_type": "定制合同",
        "blocks_provided": len(normalized_blocks),
    })


# ---------------------------------------------------------------------------
# 自测试代码：python -m mcp.legal_document.contract_generator
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys

    _PASS = 0
    _FAIL = 0

    def _check(desc: str, condition: bool, detail: str = ""):
        global _PASS, _FAIL
        if condition:
            _PASS += 1
            print("  [PASS] {}".format(desc))
        else:
            _FAIL += 1
            print("  [FAIL] {}  --  {}".format(desc, detail))

    print("=" * 60)
    print("定制化合同生成器 — 自测试")
    print("=" * 60)

    # [1] get_contract_skeleton
    print("\n[1] get_contract_skeleton")
    r = json.loads(get_contract_skeleton())
    _check("返回 success=True", r["success"])
    _check("含 doc_type", r["data"]["doc_type"] == "定制合同")
    _check("含 skeleton", isinstance(r["data"]["skeleton"], list) and len(r["data"]["skeleton"]) == 7)
    _check("含 guide", "合同写作通用守则" in r["data"]["guide"])
    _check("含 contract 硬约束", "合同定制化硬约束" in r["data"]["guide"])
    _check("含 block_schema", "supported_types" in r["data"]["block_schema"])
    _check("含 usage_note", bool(r["data"].get("usage_note")))
    _check("skeleton 含 title", any(b["type"] == "title" for b in r["data"]["skeleton"]))
    _check("skeleton 含 signature_block", any(b["type"] == "signature_block" for b in r["data"]["skeleton"]))

    # [2] compose_contract — 完整合同渲染
    print("\n[2] compose_contract — 完整合同渲染")
    test_blocks = [
        {"type": "title", "text": "软件开发外包合同"},
        {"type": "paragraph", "text": "甲方：XX 科技有限公司，统一社会信用代码：91110108MA01XXXXX，住所地：北京市海淀区中关村南大街 5 号，法定代表人：张三，联系电话：13800138001。", "indent": False},
        {"type": "paragraph", "text": "乙方：YY 信息技术有限公司，统一社会信用代码：91110105MA02YYYYY，住所地：北京市朝阳区望京 SOHO T1-XXXX，法定代表人：李四，联系电话：13900139002。", "indent": False},
        {"type": "heading", "level": 1, "text": "第一条  项目内容与技术标准"},
        {"type": "paragraph", "text": "甲方委托乙方开发一套企业客户关系管理系统（CRM），具体功能需求详见附件一《需求规格说明书》。乙方应按照国家标准 GB/T 9386-2008《计算机软件测试文档编制规范》进行测试并交付测试报告。", "indent": True},
        {"type": "heading", "level": 1, "text": "第二条  开发周期与交付"},
        {"type": "ordered_list", "items": [
            "第一阶段：需求分析确认，自合同生效之日起 15 个工作日内完成；",
            "第二阶段：系统设计，自需求确认之日起 30 个工作日内完成；",
            "第三阶段：开发与内部测试，自设计评审通过之日起 90 个工作日内完成；",
            "第四阶段：用户验收测试与正式上线，自内部测试通过之日起 20 个工作日内完成。",
        ]},
        {"type": "heading", "level": 1, "text": "第三条  费用与支付方式"},
        {"type": "paragraph", "text": "本合同总价款为人民币 500,000 元（伍拾万元整），含税。分四期支付：", "indent": True},
        {"type": "table", "header": ["期次", "支付条件", "金额（元）"], "rows": [
            ["第一期", "合同签订后 5 个工作日内", "150,000"],
            ["第二期", "系统设计评审通过后 5 个工作日内", "150,000"],
            ["第三期", "用户验收测试通过后 5 个工作日内", "150,000"],
            ["第四期", "系统正式上线运行满 3 个月后 5 个工作日内", "50,000"],
        ]},
        {"type": "heading", "level": 1, "text": "第四条  知识产权归属"},
        {"type": "paragraph", "text": "本合同项下开发的软件系统（包括但不限于源代码、目标代码、技术文档、数据库设计等）的著作权及相关知识产权，在甲方付清全部合同价款后归甲方所有。乙方享有署名权。未经甲方书面同意，乙方不得将本项目成果的任何部分用于其他客户或项目。", "indent": True},
        {"type": "heading", "level": 1, "text": "第五条  保密义务"},
        {"type": "paragraph", "text": "双方应对在合同履行过程中知悉的对方商业秘密（包括但不限于技术资料、客户信息、财务数据等）承担保密义务。保密期限自合同签订之日起至合同终止后三年止。违反保密义务的一方应赔偿对方因此遭受的全部损失。", "indent": True},
        {"type": "heading", "level": 1, "text": "第六条  违约责任"},
        {"type": "unordered_list", "items": [
            "乙方逾期交付的，每逾期一日按合同总价款的千分之一向甲方支付违约金，逾期超过 30 日的，甲方有权单方解除合同，乙方应返还已收取全部款项并赔偿甲方损失；",
            "甲方逾期付款的，每逾期一日按逾期金额的千分之一向乙方支付违约金；",
            "乙方交付的系统经三次整改仍无法通过用户验收测试的，甲方有权单方解除合同，乙方应返还已收取全部款项。",
        ]},
        {"type": "heading", "level": 1, "text": "第七条  争议解决"},
        {"type": "paragraph", "text": "因本合同引起的或与本合同有关的任何争议，双方应首先友好协商解决；协商不成的，任何一方均有权向甲方住所地有管辖权的人民法院提起诉讼。", "indent": True},
        {"type": "heading", "level": 1, "text": "第八条  其他"},
        {"type": "paragraph", "text": "本合同一式四份，甲方执两份、乙方执两份，自双方签字盖章之日起生效。未尽事宜由双方协商签订书面补充协议，补充协议与本合同具有同等法律效力。", "indent": True},
        {"type": "blank_line"},
        {"type": "signature_block", "signer": "甲方（盖章）：XX 科技有限公司", "entity": "乙方（盖章）：YY 信息技术有限公司", "date": "二〇二六年六月十一日"},
    ]
    r = json.loads(compose_contract(
        test_blocks, output_name="self_test_开发合同",
        workspace_scope="test/self_test",
    ))
    _check("返回 success=True", r["success"])
    _check("含 output_path", bool(r["data"].get("output_path")))
    output_path = r["data"].get("output_path", "")
    _check("文件已生成", os.path.exists(output_path), output_path)
    _check("输出后缀为 _contract.docx", output_path.endswith("_contract.docx"), output_path)
    if os.path.exists(output_path):
        _check("文件大小 > 5KB", os.path.getsize(output_path) > 5120, "{} bytes".format(os.path.getsize(output_path)))
    _check("rendered_block_counts 含 title", r["data"]["rendered_block_counts"].get("title") == 1)
    _check("rendered_block_counts 含 signature_block", r["data"]["rendered_block_counts"].get("signature_block") == 1)
    _check("rendered_block_counts 含 heading", r["data"]["rendered_block_counts"].get("heading", 0) >= 7)
    _check("rendered_block_counts 含 ordered_list", r["data"]["rendered_block_counts"].get("ordered_list") == 1)
    _check("rendered_block_counts 含 unordered_list", r["data"]["rendered_block_counts"].get("unordered_list") == 1)
    _check("rendered_block_counts 含 table", r["data"]["rendered_block_counts"].get("table") == 1)
    _check("无 unknown 类型", len(r["data"]["skipped_unknown_types"]) == 0)

    # [3] compose_contract — 软警告（缺标题/落款）
    print("\n[3] compose_contract — 软警告（缺标题和落款）")
    minimal_blocks = [
        {"type": "paragraph", "text": "甲方：张三…"},
        {"type": "paragraph", "text": "乙方：李四…"},
    ]
    r = json.loads(compose_contract(
        minimal_blocks, output_name="self_test_minimal",
        workspace_scope="test/self_test",
    ))
    _check("仍然 success=True（软约束不阻断）", r["success"])
    _check("返回 soft_warnings", len(r["data"]["soft_warnings"]) > 0)
    warnings_text = " ".join(r["data"]["soft_warnings"])
    _check("告警缺少标题", "缺少标题" in warnings_text)
    _check("告警缺少落款", "缺少落款" in warnings_text)

    # [4] compose_contract — 错误场景
    print("\n[4] compose_contract — 错误场景")
    r = json.loads(compose_contract(
        [], workspace_scope="test/self_test",
    ))
    _check("空 blocks → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    r = json.loads(compose_contract(
        [{"type": "未知块类型"}], workspace_scope="test/self_test",
    ))
    _check("未知 block 类型 → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    r = json.loads(compose_contract(
        [{"type": "title"}], workspace_scope="test/self_test",
    ))
    _check("title 无 text → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    # [5] compose_contract — 元评论告警
    print("\n[5] compose_contract — 元评论告警")
    meta_blocks = [
        {"type": "title", "text": "测试合同"},
        {"type": "paragraph", "text": "甲方委托乙方开发系统。我这样写是因为需要明确开发范围，以下为修改后的合同条款内容。"},
        {"type": "paragraph", "text": "乙方应按期交付。以上为草拟稿，仅供参考，如有疑问请咨询执业律师。"},
        {"type": "signature_block", "signer": "甲方", "date": "二〇二六年六月十一日"},
    ]
    r = json.loads(compose_contract(
        meta_blocks, output_name="self_test_meta",
        workspace_scope="test/self_test",
    ))
    _check("success=True（元评论不阻断）", r["success"])
    _check("含元评论告警", any("元评论" in w or "起草过程" in w for w in r["data"]["soft_warnings"]))

    # [6] compose_contract — 合同不宜内容检测
    print("\n[6] compose_contract — 合同不宜内容检测")
    bad_blocks = [
        {"type": "title", "text": "测试合同"},
        {"type": "paragraph", "text": "甲方委托乙方开发系统。（通俗地说，就是甲方出钱让乙方写代码）", "indent": True},
        {"type": "heading", "level": 1, "text": "风险提示："},
        {"type": "paragraph", "text": "本合同涉及金额较大，建议双方在签署前咨询专业律师。", "indent": True},
        {"type": "paragraph", "text": "法律小贴士：根据《民法典》，合同双方应诚实守信。"},
        {"type": "heading", "level": 1, "text": "丙方权利义务"},
        {"type": "paragraph", "text": "丙方作为担保人，应对乙方的履约行为承担连带保证责任。"},
        {"type": "heading", "level": 1, "text": "名词解释"},
        {"type": "paragraph", "text": "知识产权：指依法享有的专利权、商标权、著作权等。"},
        {"type": "signature_block", "signer": "甲方", "entity": "乙方", "date": "二〇二六年六月十一日"},
    ]
    r = json.loads(compose_contract(
        bad_blocks, output_name="self_test_bad",
        workspace_scope="test/self_test",
    ))
    _check("success=True（软约束不阻断）", r["success"])
    _check("检测到通俗解释告警", any("通俗" in w for w in r["data"]["soft_warnings"]))
    _check("检测到风险提示告警", any("风险提示" in w for w in r["data"]["soft_warnings"]))
    _check("检测到普法告警", any("小贴士" in w or "科普" in w for w in r["data"]["soft_warnings"]))
    _check("检测到多方签署告警", any("丙方" in w or "多方" in w for w in r["data"]["soft_warnings"]))
    _check("检测到名词解释告警", any("名词解释" in w or "术语" in w for w in r["data"]["soft_warnings"]))

    # [7] MCP registry 集成
    print("\n[7] MCP registry 集成")
    try:
        from tools.registry import registry as _reg
        agent_tools = _reg.names("agent")
        _check("get_contract_skeleton 在 agent 中", "get_contract_skeleton" in agent_tools)
        _check("compose_contract 在 agent 中", "compose_contract" in agent_tools)
        r = json.loads(_reg.dispatch("get_contract_skeleton", {}, None))
        _check("registry.dispatch get_contract_skeleton 成功", r["success"])
        r = json.loads(_reg.dispatch(
            "compose_contract",
            {
                "blocks": [
                    {"type": "title", "text": "测试合同"},
                    {"type": "paragraph", "text": "甲方：张三，身份证号：110108199001010001。"},
                    {"type": "paragraph", "text": "乙方：李四，身份证号：110108199002020002。"},
                    {"type": "heading", "level": 1, "text": "第一条  合同标的"},
                    {"type": "paragraph", "text": "甲方向乙方购买一批办公设备。", "indent": True},
                    {"type": "signature_block", "signer": "甲方（签章）：张三", "entity": "乙方（签章）：李四", "date": "二〇二六年六月十一日"},
                ],
                "output_name": "dispatch_合同",
            },
            "test/dispatch",
        ))
        _check("registry.dispatch compose_contract 成功", r["success"])
    except ImportError:
        print("  [SKIP] tools.registry 不可用")

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print("结果: {}/{} 通过".format(_PASS, total), end="")
    if _FAIL > 0:
        print(", {} 失败".format(_FAIL))
        _sys.exit(1)
    else:
        print(" — 全部通过")
    print("=" * 60)
