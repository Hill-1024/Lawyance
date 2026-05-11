"""
模块描述：底层 MCP 工具适配层导出模块，为 mcps 提供统一的工具实现入口。
"""

from .deli_client import match_legal_case
from .pkulaw_client import get_article, search_article, get_linked_content
from .word_annotator import word_reader, word_writer
from .PDF_processor import pdf_text_reader, pdf_commit_by_sentence
from .qcc_client import get_company_profile, get_listing_info, get_contact_info, get_shareholder_info, get_company_registration_info, get_key_personnel, get_external_investments
__all__ = ["match_legal_case",
           "get_article",
           "search_article",
           "get_linked_content",
           "word_reader",
           "word_writer",
           "pdf_text_reader",
           "pdf_commit_by_sentence",
           "get_key_personnel",
           "get_company_profile",
           "get_listing_info",
           "get_contact_info",
           "get_shareholder_info",
           "get_company_registration_info",
           "get_external_investments"]
