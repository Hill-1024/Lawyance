"""Focused regressions for backend edge-service hardening."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc-token")
os.environ.setdefault("QCC_ENDPOINT", "https://agent.qcc.com/mcp/company/stream")

from mcp import qcc_client
from mcp.legal_document import generator
from mcp.legal_document.errors import FieldValidationError
from mcp.legal_document.validator import MAX_BLOCKS, validate_blocks


class QCCClientHardeningTests(unittest.TestCase):
    def test_public_tool_error_does_not_expose_internal_exception(self):
        with patch.object(
            qcc_client.QichachaSimpleClient,
            "call_tool",
            side_effect=RuntimeError("/private/secret/token=abc"),
        ):
            result = qcc_client.run_tool("get_company_profile", "示例公司")

        self.assertEqual(result, {"error": "企业信息服务调用失败，请稍后重试。"})
        self.assertNotIn("secret", json.dumps(result))

    def test_oversized_remote_response_is_rejected_and_closed(self):
        response = MagicMock()
        response.status_code = 200
        response.iter_content.return_value = [b"x" * (qcc_client._MAX_RESPONSE_BYTES + 1)]
        with patch("mcp.qcc_client.requests.post", return_value=response):
            with self.assertRaises(qcc_client.QCCClientError):
                qcc_client.QichachaSimpleClient().call_tool("get_company_profile", "示例公司")

        response.close.assert_called_once()

    def test_invalid_company_name_is_rejected_before_network(self):
        with patch("mcp.qcc_client.requests.post") as remote_post:
            with self.assertRaises(qcc_client.QCCClientError):
                qcc_client.QichachaSimpleClient().call_tool("get_company_profile", "x" * 257)
        remote_post.assert_not_called()


class LegalDocumentHardeningTests(unittest.TestCase):
    def test_template_backend_exception_is_not_returned(self):
        with patch.object(generator.guide_cache, "get_index", side_effect=RuntimeError("/private/template.json")):
            result = generator.list_legal_document_types()

        self.assertFalse(json.loads(result)["success"])
        self.assertNotIn("/private/template.json", result)

    def test_render_exception_is_not_returned(self):
        with patch.object(generator, "_get_output_path", return_value="unused.docx"), patch.object(
            generator,
            "compose_docx",
            side_effect=RuntimeError("/private/output/path"),
        ):
            result = generator.compose_legal_document(
                "民事起诉状",
                [{"type": "title", "text": "民事起诉状"}],
                workspace_scope="user/session",
            )

        payload = json.loads(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "GENERATION_ERROR")
        self.assertNotIn("/private/output/path", result)

    def test_block_count_has_a_hard_limit(self):
        with self.assertRaises(FieldValidationError):
            validate_blocks(
                [{"type": "blank_line"} for _ in range(MAX_BLOCKS + 1)],
                "测试文书",
            )


if __name__ == "__main__":
    unittest.main()
