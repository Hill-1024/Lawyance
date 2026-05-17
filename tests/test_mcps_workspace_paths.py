"""
模块描述：mcps 工作区路径边界测试，验证文件读写被限制在当前用户会话工作区内。
"""

import os
import tempfile
import unittest

os.environ.setdefault("DELI_APPID", "test-deli-app")
os.environ.setdefault("DELI_SECRET", "test-deli-secret")
os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

import mcps


class McpsWorkspacePathTests(unittest.TestCase):
    def test_resolves_relative_file_inside_current_workspace(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                os.makedirs("TEMP/user_a/conv_a", exist_ok=True)
                file_path = "TEMP/user_a/conv_a/doc.pdf"
                with open(file_path, "wb") as f:
                    f.write(b"%PDF-test")

                resolved = mcps.resolve_workspace_file(file_path, "user_a/conv_a")
                result_path = mcps.get_result_path(file_path, "user_a/conv_a")
            finally:
                os.chdir(old_cwd)

        self.assertTrue(resolved.endswith(os.path.join("TEMP", "user_a", "conv_a", "doc.pdf")))
        self.assertEqual(result_path, "Result/user_a/conv_a/doc_lawyance.pdf")

    def test_rejects_absolute_and_cross_workspace_paths(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                os.makedirs("TEMP/user_a/conv_a", exist_ok=True)
                file_path = "TEMP/user_a/conv_a/doc.pdf"
                with open(file_path, "wb") as f:
                    f.write(b"%PDF-test")

                with self.assertRaises(mcps.WorkspacePathError):
                    mcps.resolve_workspace_file(os.path.abspath(file_path), "user_a/conv_a")
                with self.assertRaises(mcps.WorkspacePathError):
                    mcps.resolve_workspace_file("TEMP/user_a/conv_a/../../../outside.pdf", "user_a/conv_a")
                with self.assertRaises(mcps.WorkspacePathError):
                    mcps.resolve_workspace_file(file_path, "user_b/conv_b")
            finally:
                os.chdir(old_cwd)

    def test_file_tools_return_error_for_unsafe_paths(self):
        result = mcps.use_tools("pdf_text_reader", {"pdf_path": "TEMP/user/conv/../../../secret.pdf"}, conv_id="user/conv")

        self.assertIn("错误", result)
        self.assertIn("当前工作区", result)

    def test_text_arguments_are_coerced_for_company_tools(self):
        args = mcps._coerce_arguments("get_company_profile", "示例公司")

        self.assertEqual(args, {"company": "示例公司"})


if __name__ == "__main__":
    unittest.main()
