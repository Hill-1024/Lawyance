"""
模块描述：工具结果超阈值摘要压缩的单元测试。
"""

from __future__ import annotations

import asyncio
import importlib
import types
import unittest


class ToolResultCompressionTests(unittest.TestCase):
    def test_below_threshold_returns_original(self):
        service = importlib.import_module("services.tool_result_compression")

        async def run():
            return await service.maybe_compress_tool_result(
                "search_article",
                "短结果",
                threshold_tokens=20_000,
            )

        self.assertEqual(asyncio.run(run()), "短结果")

    def test_skip_control_tools(self):
        service = importlib.import_module("services.tool_result_compression")
        huge = "法条" * 120_000
        should, _ = service.should_compress_tool_result(huge, tool_name="submit_plan")
        self.assertFalse(should)

    def test_over_threshold_summarizes(self):
        service = importlib.import_module("services.tool_result_compression")
        original_call = service.call

        async def fake_call(messages, stream=False, include_tools=True):
            return types.SimpleNamespace(content="保留关键法条第一百条与管辖地新加坡。")

        huge = ("相关法条内容与案件事实。" * 8000)
        self.assertGreater(service.estimate_text_tokens(huge), 1000)

        async def run():
            service.call = fake_call
            try:
                return await service.maybe_compress_tool_result(
                    "get_article",
                    huge,
                    threshold_tokens=1000,
                )
            finally:
                service.call = original_call

        compressed = asyncio.run(run())
        self.assertIn("[工具结果摘要 | tool=get_article", compressed)
        self.assertIn("第一百条", compressed)
        self.assertNotIn(huge[:80], compressed)

    def test_summary_failure_falls_back_to_truncate(self):
        service = importlib.import_module("services.tool_result_compression")
        original_call = service.call

        async def boom(*_args, **_kwargs):
            raise RuntimeError("llm down")

        huge = "证据材料" * 50_000

        async def run():
            service.call = boom
            try:
                return await service.maybe_compress_tool_result(
                    "web_fetch",
                    huge,
                    threshold_tokens=1000,
                )
            finally:
                service.call = original_call

        compressed = asyncio.run(run())
        self.assertIn("mode=truncate", compressed)
        self.assertIn("摘要失败", compressed)
        self.assertLess(len(compressed), len(huge))


if __name__ == "__main__":
    unittest.main()
