"""
模块描述：结构化文书模块异常层次结构。
所有异常均携带 code（机器可读）、message（用户友好中文）、details（附加上下文）。
"""

from __future__ import annotations


class LegalDocumentError(Exception):
    """所有文书模块异常的基类。"""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class TemplateNotFoundError(LegalDocumentError):
    """请求的模板不存在。"""

    def __init__(self, template_name: str, available: list[str] | None = None):
        available = available or []
        hint = f"，当前可用模板: {', '.join(available)}" if available else ""
        super().__init__(
            code="TEMPLATE_NOT_FOUND",
            message=f"未找到模板 '{template_name}'{hint}",
            details={"template_name": template_name, "available_templates": available},
        )


class ManifestValidationError(LegalDocumentError):
    """manifest.json 格式或内容不合法。"""

    def __init__(self, template_name: str, reason: str, field_name: str | None = None):
        detail = {"template_name": template_name, "reason": reason}
        if field_name:
            detail["field_name"] = field_name
        super().__init__(
            code="MANIFEST_INVALID",
            message=f"模板 '{template_name}' 的 manifest.json 校验失败: {reason}",
            details=detail,
        )


class TemplateSyntaxError(LegalDocumentError):
    """DOCX 模板中 Jinja2 语法错误。"""

    def __init__(self, template_name: str, reason: str, location: str | None = None):
        detail = {"template_name": template_name, "reason": reason}
        if location:
            detail["location"] = location
        super().__init__(
            code="TEMPLATE_SYNTAX_ERROR",
            message=f"模板 '{template_name}' 存在语法问题: {reason}",
            details=detail,
        )


class FieldValidationError(LegalDocumentError):
    """输入字段校验失败。"""

    def __init__(self, template_name: str, errors: list[str]):
        joined = "; ".join(errors)
        super().__init__(
            code="FIELD_VALIDATION_ERROR",
            message=f"字段校验失败: {joined}",
            details={"template_name": template_name, "errors": errors},
        )


class DocumentGenerationError(LegalDocumentError):
    """文书渲染或保存阶段错误。"""

    def __init__(self, template_name: str, reason: str):
        super().__init__(
            code="GENERATION_ERROR",
            message=f"文书生成失败（模板: {template_name}）: {reason}",
            details={"template_name": template_name, "reason": reason},
        )
