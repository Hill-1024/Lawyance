"""
模块描述：结构化法律文书生成模块。
提供模板发现、字段查询和文书生成三个 MCP 工具函数。
"""

from .errors import (
    DocumentGenerationError,
    FieldValidationError,
    LegalDocumentError,
    ManifestValidationError,
    TemplateNotFoundError,
    TemplateSyntaxError,
)
from .generator import (
    generate_legal_document,
    get_template_fields,
    list_legal_templates,
)

__all__ = [
    "list_legal_templates",
    "get_template_fields",
    "generate_legal_document",
    "LegalDocumentError",
    "TemplateNotFoundError",
    "ManifestValidationError",
    "TemplateSyntaxError",
    "FieldValidationError",
    "DocumentGenerationError",
]
