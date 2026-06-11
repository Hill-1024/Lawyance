"""
模块描述：Block-based 法律文书生成模块。
对外暴露文种发现、写作守则查询、文书编排三个 MCP 工具函数。
"""

from .errors import (
    DocumentGenerationError,
    FieldValidationError,
    LegalDocumentError,
    ManifestValidationError,
    TemplateNotFoundError,
    TemplateSyntaxError,
)
from .contract_generator import compose_contract, get_contract_skeleton
from .generator import (
    compose_legal_document,
    get_legal_document_guide,
    list_legal_document_types,
)

__all__ = [
    "list_legal_document_types",
    "get_legal_document_guide",
    "compose_legal_document",
    "get_contract_skeleton",
    "compose_contract",
    "LegalDocumentError",
    "TemplateNotFoundError",
    "ManifestValidationError",
    "TemplateSyntaxError",
    "FieldValidationError",
    "DocumentGenerationError",
]
