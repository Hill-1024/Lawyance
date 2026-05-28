"""
模块描述：TXT/Markdown 工具测试，覆盖工作区读写与可执行内容过滤。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("DELI_APPID", "test-deli-app")
os.environ.setdefault("DELI_SECRET", "test-deli-secret")
os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

import mcps


class TextFileToolTests(unittest.TestCase):
    def test_txt_md_reader_filters_executable_markdown_content(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                os.makedirs("TEMP/user/conv", exist_ok=True)
                file_path = "TEMP/user/conv/note.md"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(
                        "# 标题\n"
                        "<script>alert('x')</script>\n"
                        '<a onclick="steal()" href="javascript:alert(1)">链接</a>\n'
                        "[坏链接](javascript:alert)\n"
                        "正文保留"
                    )

                result = json.loads(mcps.use_tools("txt_md_reader", {"file_path": file_path}, conv_id="user/conv"))
            finally:
                os.chdir(old_cwd)

        self.assertTrue(result["success"])
        self.assertIn("正文保留", result["text"])
        self.assertIn("#lawver-filtered-url", result["text"])
        self.assertNotIn("<script", result["text"].lower())
        self.assertNotIn("onclick", result["text"].lower())
        self.assertNotIn("javascript:", result["text"].lower())
        self.assertTrue(result["removed_executable_content"])
        self.assertIn("已过滤", result["warning"])

    def test_txt_md_writer_writes_to_result_and_sanitizes_content(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                result = json.loads(mcps.use_tools(
                    "txt_md_writer",
                    {
                        "output_name": "draft.md",
                        "content": "# 草稿\n<script>window.evil()</script>\n[跳转](javascript:evil)\n",
                    },
                    conv_id="user/conv",
                ))
                output_path = result["output_path"]
                with open(output_path, encoding="utf-8") as f:
                    written = f.read()
            finally:
                os.chdir(old_cwd)

        self.assertTrue(result["success"])
        self.assertEqual(output_path, "Result/user/conv/draft.md")
        self.assertIn("# 草稿", written)
        self.assertIn("#lawver-filtered-url", written)
        self.assertNotIn("<script", written.lower())
        self.assertNotIn("window.evil", written)
        self.assertTrue(result["removed_executable_content"])

    def test_txt_md_writer_is_limited_to_result_workspace(self):
        result = mcps.use_tools(
            "txt_md_writer",
            {"file_path": "TEMP/user/conv/unsafe.md", "content": "x"},
            conv_id="user/conv",
        )

        self.assertIn("错误", result)
        self.assertIn("当前工作区", result)

    def test_txt_md_reader_rejects_unsupported_extensions(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                os.makedirs("TEMP/user/conv", exist_ok=True)
                file_path = "TEMP/user/conv/data.csv"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("a,b")

                result = json.loads(mcps.use_tools("txt_md_reader", {"file_path": file_path}, conv_id="user/conv"))
            finally:
                os.chdir(old_cwd)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UNSUPPORTED_FILE_TYPE")


if __name__ == "__main__":
    unittest.main()
