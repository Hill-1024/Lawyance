"""
模块描述：结构化法律文书生成器。
核心接口：list_legal_templates、get_template_fields、generate_legal_document。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .cache import template_cache
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
from .validator import validate_input_fields
from workspace import WorkspacePathError, validate_workspace_scope

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


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


def _get_output_path(template_name: str, workspace_scope: str | None) -> str:
    safe_scope = validate_workspace_scope(workspace_scope)
    result_dir = os.path.join("Result", safe_scope)
    os.makedirs(result_dir, exist_ok=True)
    safe_name = template_name.replace("/", "_").replace("\\", "_")
    return os.path.join(result_dir, "{}_lawver.docx".format(safe_name)).replace("\\", "/")


def list_legal_templates(category: str | None = None) -> str:
    """列出所有可用的法律文书模板。"""
    try:
        index = template_cache.get_index()
    except Exception as e:
        return _make_response(False, data={"error": str(e)})

    if category:
        category = category.strip()
        index = [e for e in index if e.category == category]

    templates = [
        {
            "name": e.name, "version": e.version, "category": e.category,
            "description": e.description, "field_count": e.field_count,
            "required_fields": e.field_keys,
        }
        for e in index
    ]
    return _make_response(success=True, data={"templates": templates, "total": len(templates)})


def get_template_fields(template_name: str) -> str:
    """获取指定模板的字段清单。"""
    try:
        cached = template_cache.get(template_name)
    except TemplateNotFoundError as e:
        return _make_error_response(e)

    manifest = cached.manifest
    fields_info = []
    for f in manifest["fields"]:
        fi = {
            "key": f["key"], "label": f["label"], "type": f["type"],
            "required": f.get("required", False), "description": f.get("description", ""),
        }
        if f.get("default") is not None:
            fi["default"] = f["default"]
        if f.get("max_length"):
            fi["max_length"] = f["max_length"]
        if f.get("item_schema"):
            fi["item_schema"] = f["item_schema"]
        fields_info.append(fi)

    return _make_response(success=True, data={
        "template_name": manifest["name"], "version": manifest["version"],
        "category": manifest["category"], "description": manifest["description"],
        "fields": fields_info,
    })


def generate_legal_document(
    template_name: str, fields: dict, workspace_scope: str | None = None,
) -> str:
    """根据模板和字段值生成法律文书。"""
    start_time = time.time()

    try:
        cached = template_cache.get(template_name)
    except TemplateNotFoundError as e:
        return _make_error_response(e)

    manifest = cached.manifest

    try:
        normalized_fields = validate_input_fields(fields, manifest)
    except FieldValidationError as e:
        return _make_error_response(e)

    generation_id = log_generation_start(template_name, len(normalized_fields))

    try:
        from docxtpl import DocxTemplate
        docx_path = str(_TEMPLATES_DIR / template_name / "template.docx")
        render_docx = DocxTemplate(docx_path)
        render_docx.render(normalized_fields)
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError(template_name, "模板渲染失败: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={"generation_id": generation_id, "duration_ms": round(duration_ms, 1)})

    try:
        output_path = _get_output_path(template_name, workspace_scope)
        render_docx.save(output_path)
    except WorkspacePathError as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError(template_name, "工作区作用域非法: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={"generation_id": generation_id, "duration_ms": round(duration_ms, 1)})
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error = DocumentGenerationError(template_name, "文件保存失败: {}".format(e))
        log_generation_error(generation_id, error, duration_ms)
        return _make_error_response(error, meta={"generation_id": generation_id, "duration_ms": round(duration_ms, 1)})

    duration_ms = (time.time() - start_time) * 1000
    log_generation_complete(generation_id, duration_ms, output_path)

    return _make_response(success=True, data={"output_path": output_path}, meta={
        "generation_id": generation_id, "status": "completed",
        "duration_ms": round(duration_ms, 1), "template_name": template_name,
        "fields_provided": len(normalized_fields),
    })


# ---------------------------------------------------------------------------
# 自测试代码：python -m mcp.legal_document.generator
# 以「民事行政起诉状」模板为示例
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

    TEMPLATE = "民事行政起诉状"
    TOTAL_FIELDS = 18
    REQUIRED_FIELDS = 18
    OPTIONAL_FIELDS = 0

    print("=" * 60)
    print("结构化文书生成器 — 自测试")
    print("示例模板: {}".format(TEMPLATE))
    print("=" * 60)

    # [1]
    print("\n[1] list_legal_templates")
    r = json.loads(list_legal_templates())
    _check("返回 success=True", r["success"])
    _check("至少 1 个模板", r["data"]["total"] >= 1)
    if r["data"]["templates"]:
        t0 = r["data"]["templates"][0]
        _check("模板含 name", "name" in t0)
        _check("模板含 category", "category" in t0)
        _check("模板含 field_count", "field_count" in t0)
        _check("模板名称匹配", t0["name"] == TEMPLATE)
    r = json.loads(list_legal_templates(category="民事诉讼"))
    _check("category='民事诉讼' 筛选有效", r["data"]["total"] >= 1)
    r = json.loads(list_legal_templates(category="nonexistent"))
    _check("category 无匹配时返回空", r["data"]["total"] == 0)

    # [2]
    print("\n[2] get_template_fields")
    r = json.loads(get_template_fields(TEMPLATE))
    _check("返回 success=True", r["success"])
    fields = r["data"].get("fields", [])
    required = [f for f in fields if f["required"]]
    optional = [f for f in fields if not f["required"]]
    _check("总字段数 {}".format(TOTAL_FIELDS), len(fields) == TOTAL_FIELDS, "实际: {}".format(len(fields)))
    _check("必填字段 {}".format(REQUIRED_FIELDS), len(required) == REQUIRED_FIELDS, "实际: {}".format(len(required)))
    _check("可选字段 {}".format(OPTIONAL_FIELDS), len(optional) == OPTIONAL_FIELDS, "实际: {}".format(len(optional)))
    _check("每个字段含 key", all("key" in f for f in fields))
    _check("每个字段含 type", all("type" in f for f in fields))
    _check("每个字段含 label", all("label" in f for f in fields))
    r = json.loads(get_template_fields("不存在的模板"))
    _check("不存在的模板返回失败", not r["success"])
    _check("错误码 TEMPLATE_NOT_FOUND", r["error"]["code"] == "TEMPLATE_NOT_FOUND")

    # [3]
    print("\n[3] generate_legal_document — 正常生成")
    test_fields = {
        "document_title": "民事起诉状",
        "plaintiff_name": "王小明", "plaintiff_gender": "男", "plaintiff_birth": "1988年3月15日",
        "plaintiff_id_card": "110108198803150019", "plaintiff_address": "北京市海淀区学院路30号",
        "plaintiff_phone": "13800138001",
        "defendant_name": "李大伟", "defendant_gender": "男", "defendant_birth": "1985年7月20日",
        "defendant_id_card": "110108198507200025", "defendant_address": "北京市朝阳区建国路100号",
        "defendant_phone": "13900139002",
        "claims": "1. 请求判令被告偿还借款本金人民币20万元；\n2. 请求判令被告支付利息；\n3. 请求判令被告承担本案诉讼费用。",
        "facts_and_reasons": "2023年6月1日，被告向原告借款人民币20万元，约定借期一年，年利率6%，并出具借条。借款到期后被告以各种理由推脱，至今未还。\n\n根据《中华人民共和国民法典》相关规定，被告逾期未还款已构成违约。为维护合法权益，特向贵院提起诉讼。",
        "evidence": "1. 借条原件一份；\n2. 银行转账记录一份；\n3. 微信聊天记录截图。",
        "court_name": "北京市海淀区", "date_filed": "二〇二五年五月二十六日",
    }
    r = json.loads(generate_legal_document(TEMPLATE, test_fields, "test/self_test"))
    _check("返回 success=True", r["success"])
    _check("含 output_path", bool(r["data"].get("output_path")))
    output_path = r["data"].get("output_path", "")
    _check("文件已生成", os.path.exists(output_path), output_path)
    if os.path.exists(output_path):
        _check("文件大小 > 10KB", os.path.getsize(output_path) > 10240, "{} bytes".format(os.path.getsize(output_path)))
    _check("含 generation_id", bool(r["meta"].get("generation_id")))
    _check("status 为 completed", r["meta"].get("status") == "completed")
    _check("含 duration_ms", isinstance(r["meta"].get("duration_ms"), (int, float)))
    _check("template_name 正确", r["meta"].get("template_name") == TEMPLATE)
    _check("fields_provided={}".format(TOTAL_FIELDS), r["meta"].get("fields_provided") == TOTAL_FIELDS)

    # [4]
    print("\n[4] generate_legal_document — 错误场景")
    r = json.loads(generate_legal_document(TEMPLATE, {}, "test"))
    _check("缺必填字段 → success=False", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")
    _check("返回 {} 个错误".format(TOTAL_FIELDS),
           len(r["error"]["details"].get("errors", [])) == TOTAL_FIELDS)
    r = json.loads(generate_legal_document("不存在的模板", {}, "test"))
    _check("不存在的模板 → success=False", not r["success"])
    _check("错误码 TEMPLATE_NOT_FOUND", r["error"]["code"] == "TEMPLATE_NOT_FOUND")
    _check("提示可用模板列表", bool(r["error"]["details"].get("available_templates")))
    r = json.loads(generate_legal_document(TEMPLATE, {"unknown_key": "value"}, "test"))
    _check("未知字段被拒绝", not r["success"])
    _check("提示未知字段", "未知字段" in r["error"]["message"])
    r = json.loads(generate_legal_document(TEMPLATE, {"plaintiff_name": 12345}, "test"))
    _check("类型错误被拒绝", not r["success"])
    _check("错误码 FIELD_VALIDATION_ERROR", r["error"]["code"] == "FIELD_VALIDATION_ERROR")

    # [5]
    print("\n[5] MCP registry 集成")
    try:
        from tools.registry import registry as _reg
        agent_tools = _reg.names("agent")
        _check("list_legal_templates 在 agent 中", "list_legal_templates" in agent_tools)
        _check("get_template_fields 在 agent 中", "get_template_fields" in agent_tools)
        _check("generate_legal_document 在 agent 中", "generate_legal_document" in agent_tools)
        r = json.loads(_reg.dispatch("list_legal_templates", {}, None))
        _check("registry.dispatch list 成功", r["success"])
        df = {
            "document_title": "测", "plaintiff_name": "测", "plaintiff_gender": "男",
            "plaintiff_birth": "1", "plaintiff_id_card": "1", "plaintiff_address": "1",
            "plaintiff_phone": "1", "defendant_name": "测", "defendant_gender": "男",
            "defendant_birth": "1", "defendant_id_card": "1", "defendant_address": "1",
            "defendant_phone": "1", "claims": "诉请", "facts_and_reasons": "事实",
            "evidence": "证据", "court_name": "法院", "date_filed": "日",
        }
        r = json.loads(_reg.dispatch("generate_legal_document", {"template_name": TEMPLATE, "fields": df}, "test/dispatch"))
        _check("registry.dispatch generate 成功", r["success"])
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
