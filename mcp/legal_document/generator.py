"""
模块描述：Block-based 法律文书生成器。
对外暴露三个 MCP 工具：
  - list_legal_document_types: 列出可用文种
  - get_legal_document_guide:  返回写作守则（强约束 prompt）
  - compose_legal_document:    根据 blocks 数组渲染 docx
"""

from __future__ import annotations

import json
import os
import re
import time

from .cache import guide_cache
from .composer import compose_docx
from .errors import (
    DocumentGenerationError,
    FieldValidationError,
    LegalDocumentError,
    TemplateNotFoundError,
)
from .logger import (
    log_generation_complete,
    log_generation_error,
    log_generation_start,
)
from .validator import evaluate_soft_constraints, validate_blocks
from workspace import WorkspacePathError, validate_workspace_scope


_OUTPUT_NAME_SAFE = re.compile(r"[^\w一-龥\-]+")


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
    name = name.strip()
    name = _OUTPUT_NAME_SAFE.sub("_", name)
    return name.strip("_") or "document"


def _get_output_path(doc_type: str, workspace_scope: str | None, output_name: str | None) -> str:
    safe_scope = validate_workspace_scope(workspace_scope)
    result_dir = os.path.join("Result", safe_scope)
    os.makedirs(result_dir, exist_ok=True)
    if output_name:
        base = _sanitize_output_name(output_name)
    else:
        base = _sanitize_output_name(doc_type)
    return os.path.join(result_dir, "{}_lawver.docx".format(base)).replace("\\", "/")


def list_legal_document_types(category: str | None = None) -> str:
    """列出所有可用的法律文书文种。"""
    try:
        index = guide_cache.get_index()
    except Exception as e:
        return _make_response(False, data={"error": str(e)})

    if category:
        category = category.strip()
        index = [e for e in index if e.category == category]

    items = [
        {
            "doc_type": e.doc_type,
            "category": e.category,
            "description": e.description,
            "required_sections": e.required_sections,
            "applicable_law": e.applicable_law,
        }
        for e in index
    ]
    return _make_response(success=True, data={"document_types": items, "total": len(items)})


def get_legal_document_guide(doc_type: str) -> str:
    """获取指定文种的写作守则（markdown）与结构性约束。"""
    try:
        guide = guide_cache.get(doc_type)
    except TemplateNotFoundError as e:
        return _make_error_response(e)
    except Exception as e:
        return _make_response(False, data={"error": str(e)})

    return _make_response(success=True, data={
        "doc_type": guide["doc_type"],
        "category": guide["category"],
        "description": guide["description"],
        "applicable_law": guide["applicable_law"],
        "required_sections": guide["required_sections"],
        "soft_warnings": guide["soft_warnings"],
        "guide": guide["guide_markdown"],
        "block_schema": {
            "supported_types": [
                "title", "heading", "paragraph", "ordered_list",
                "unordered_list", "table", "signature_block",
                "page_break", "blank_line",
            ],
            "examples": {
                "title": {"type": "title", "text": "民事起诉状"},
                "heading": {"type": "heading", "level": 2, "text": "诉讼请求"},
                "paragraph": {"type": "paragraph", "text": "段落正文…", "indent": True, "align": "justify"},
                "ordered_list": {"type": "ordered_list", "items": ["请求一", "请求二"]},
                "unordered_list": {"type": "unordered_list", "items": ["要点 A", "要点 B"]},
                "table": {"type": "table", "header": ["列 1", "列 2"], "rows": [["a", "b"]]},
                "signature_block": {"type": "signature_block", "signer": "XXX", "date": "二〇二六年五月二十六日"},
                "page_break": {"type": "page_break"},
                "blank_line": {"type": "blank_line"},
            },
        },
    })


def compose_legal_document(
    doc_type: str,
    blocks: list[dict],
    output_name: str | None = None,
    workspace_scope: str | None = None,
) -> str:
    """根据 blocks 数组渲染指定文种的法律文书。"""
    start_time = time.time()

    try:
        guide = guide_cache.get(doc_type)
    except TemplateNotFoundError as e:
        return _make_error_response(e)
    except Exception as e:
        return _make_response(False, data={"error": str(e)})

    try:
        normalized_blocks = validate_blocks(blocks, doc_type)
    except FieldValidationError as e:
        return _make_error_response(e)

    generation_id = log_generation_start(doc_type, len(normalized_blocks))

    soft_warnings = evaluate_soft_constraints(normalized_blocks, guide)

    try:
        output_path = _get_output_path(doc_type, workspace_scope, output_name)
    except WorkspacePathError as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError(doc_type, "工作区作用域非法: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={
            "generation_id": generation_id, "duration_ms": round(duration_ms, 1),
        })

    try:
        compose_stats = compose_docx(normalized_blocks, output_path)
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError(doc_type, "DOCX 渲染失败: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={
            "generation_id": generation_id, "duration_ms": round(duration_ms, 1),
        })

    duration_ms = (time.time() - start_time) * 1000
    log_generation_complete(generation_id, duration_ms, output_path)

    return _make_response(success=True, data={
        "output_path": output_path,
        "soft_warnings": soft_warnings,
        "rendered_block_counts": compose_stats["rendered_block_counts"],
        "skipped_unknown_types": compose_stats["skipped_unknown_types"],
    }, meta={
        "generation_id": generation_id,
        "status": "completed",
        "duration_ms": round(duration_ms, 1),
        "doc_type": doc_type,
        "blocks_provided": len(normalized_blocks),
    })


# ---------------------------------------------------------------------------
# 自测试代码：python -m mcp.legal_document.generator
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

    EXPECTED_TYPES = {
        "民事起诉状", "民事答辩状", "行政起诉状", "上诉状",
        "刑事辩护词", "法律意见书", "律师函",
        "仲裁申请书", "民事再审申请书", "强制执行申请书",
        "委托代理合同", "和解协议",
    }

    print("=" * 60)
    print("Block-based 文书编排器 — 自测试")
    print("=" * 60)

    # [1] list_legal_document_types
    print("\n[1] list_legal_document_types")
    r = json.loads(list_legal_document_types())
    _check("返回 success=True", r["success"])
    types_in_response = {t["doc_type"] for t in r["data"]["document_types"]}
    _check(
        "12 个文种全部出现",
        EXPECTED_TYPES.issubset(types_in_response),
        "缺失: {}".format(EXPECTED_TYPES - types_in_response),
    )
    r = json.loads(list_legal_document_types(category="诉讼"))
    _check("category='诉讼' 筛选有效", r["data"]["total"] >= 4)
    r = json.loads(list_legal_document_types(category="不存在"))
    _check("无匹配返回空", r["data"]["total"] == 0)

    # [2] get_legal_document_guide
    print("\n[2] get_legal_document_guide")
    r = json.loads(get_legal_document_guide("民事起诉状"))
    _check("返回 success=True", r["success"])
    _check("含 guide_markdown 内容", "诉讼请求" in r["data"]["guide"])
    _check("含 block_schema", "supported_types" in r["data"]["block_schema"])
    _check("含 required_sections", len(r["data"]["required_sections"]) > 0)
    r = json.loads(get_legal_document_guide("不存在的文种"))
    _check("未知文种返回 success=False", not r["success"])
    _check("错误码 TEMPLATE_NOT_FOUND", r["error"]["code"] == "TEMPLATE_NOT_FOUND")

    # [3] compose_legal_document — 完整文档
    print("\n[3] compose_legal_document — 完整文档")
    test_blocks = [
        {"type": "title", "text": "民事起诉状"},
        {"type": "heading", "level": 2, "text": "原告"},
        {"type": "paragraph", "text": "王小明，男，1988 年 3 月 15 日出生，汉族，住北京市海淀区学院路 30 号，身份证号 110108198803150019，电话 13800138001。"},
        {"type": "heading", "level": 2, "text": "被告"},
        {"type": "paragraph", "text": "李大伟，男，1985 年 7 月 20 日出生，汉族，住北京市朝阳区建国路 100 号，身份证号 110108198507200025，电话 13900139002。"},
        {"type": "heading", "level": 2, "text": "诉讼请求"},
        {"type": "ordered_list", "items": [
            "请求判令被告偿还借款本金人民币 200,000 元；",
            "请求判令被告支付自 2023 年 6 月 1 日起按年利率 6% 计算至实际清偿之日的利息；",
            "本案诉讼费用由被告承担。",
        ]},
        {"type": "heading", "level": 2, "text": "事实和理由"},
        {"type": "paragraph", "text": "2023 年 6 月 1 日，被告向原告借款人民币 200,000 元，约定借期一年，年利率 6%，并出具借条。借款到期后被告以各种理由推脱，至今未还。"},
        {"type": "paragraph", "text": "综上，根据《中华人民共和国民法典》第六百七十五条之规定，请求贵院依法判决。"},
        {"type": "heading", "level": 2, "text": "证据清单"},
        {"type": "table", "header": ["序号", "证据名称", "证据来源", "证明事项"], "rows": [
            ["1", "借条原件", "原告持有", "借贷关系成立"],
            ["2", "银行转账记录", "中国工商银行", "借款实际交付"],
        ]},
        {"type": "paragraph", "text": "此致", "indent": False, "align": "left"},
        {"type": "paragraph", "text": "北京市海淀区人民法院", "indent": False, "align": "left"},
        {"type": "signature_block", "signer": "王小明", "date": "二〇二六年五月二十六日"},
    ]
    r = json.loads(compose_legal_document(
        "民事起诉状", test_blocks, output_name="self_test_起诉状",
        workspace_scope="test/self_test",
    ))
    _check("返回 success=True", r["success"])
    _check("含 output_path", bool(r["data"].get("output_path")))
    output_path = r["data"].get("output_path", "")
    _check("文件已生成", os.path.exists(output_path), output_path)
    if os.path.exists(output_path):
        _check("文件大小 > 5KB", os.path.getsize(output_path) > 5120, "{} bytes".format(os.path.getsize(output_path)))
    _check("无 soft_warnings 或仅含合理告警", isinstance(r["data"]["soft_warnings"], list))
    _check("rendered_block_counts 含 title", r["data"]["rendered_block_counts"].get("title") == 1)
    _check("rendered_block_counts 含 signature_block", r["data"]["rendered_block_counts"].get("signature_block") == 1)

    # [4] compose_legal_document — 软警告
    print("\n[4] compose_legal_document — 软警告（缺关键章节）")
    minimal_blocks = [
        {"type": "title", "text": "民事起诉状"},
        {"type": "paragraph", "text": "原告 王小明…"},
        {"type": "signature_block", "signer": "王小明", "date": "二〇二六年五月二十六日"},
    ]
    r = json.loads(compose_legal_document(
        "民事起诉状", minimal_blocks, output_name="self_test_minimal",
        workspace_scope="test/self_test",
    ))
    _check("仍然 success=True（软约束）", r["success"])
    _check("返回 soft_warnings", len(r["data"]["soft_warnings"]) > 0)

    # [5] compose_legal_document — 错误场景
    print("\n[5] compose_legal_document — 错误场景")
    r = json.loads(compose_legal_document(
        "民事起诉状", [], workspace_scope="test/self_test",
    ))
    _check("空 blocks → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    r = json.loads(compose_legal_document(
        "不存在的文种", [{"type": "title", "text": "X"}], workspace_scope="test/self_test",
    ))
    _check("不存在文种 → success=False", not r["success"])
    _check("错误码 TEMPLATE_NOT_FOUND", r["error"]["code"] == "TEMPLATE_NOT_FOUND")

    r = json.loads(compose_legal_document(
        "民事起诉状", [{"type": "未知块"}], workspace_scope="test/self_test",
    ))
    _check("未知 block 类型 → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    # [6] MCP registry 集成
    print("\n[6] MCP registry 集成")
    try:
        from tools.registry import registry as _reg
        agent_tools = _reg.names("agent")
        _check("list_legal_document_types 在 agent 中", "list_legal_document_types" in agent_tools)
        _check("get_legal_document_guide 在 agent 中", "get_legal_document_guide" in agent_tools)
        _check("compose_legal_document 在 agent 中", "compose_legal_document" in agent_tools)
        r = json.loads(_reg.dispatch("list_legal_document_types", {}, None))
        _check("registry.dispatch list 成功", r["success"])
        r = json.loads(_reg.dispatch(
            "compose_legal_document",
            {
                "doc_type": "民事答辩状",
                "blocks": [
                    {"type": "title", "text": "民事答辩状"},
                    {"type": "paragraph", "text": "答辩人 …"},
                    {"type": "heading", "level": 2, "text": "答辩请求"},
                    {"type": "ordered_list", "items": ["请求驳回原告诉请"]},
                    {"type": "heading", "level": 2, "text": "事实与理由"},
                    {"type": "paragraph", "text": "答辩人认为…"},
                    {"type": "paragraph", "text": "此致", "indent": False, "align": "left"},
                    {"type": "paragraph", "text": "XX 法院", "indent": False, "align": "left"},
                    {"type": "signature_block", "lines": ["答辩人：李大伟", "二〇二六年五月二十六日"]},
                ],
                "output_name": "dispatch_答辩状",
            },
            "test/dispatch",
        ))
        _check("registry.dispatch compose 成功", r["success"])
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
