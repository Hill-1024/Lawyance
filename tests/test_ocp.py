"""
模块描述：OCP 审查流程测试，覆盖流式审查、工具轮次和正文保留行为。
"""

import unittest
import asyncio
from types import SimpleNamespace

import ocp


class _FakeOCPStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class _FakeOCPCompletions:
    def __init__(self, chunks):
        self._chunks = chunks

    async def create(self, **_kwargs):
        return _FakeOCPStream(self._chunks)


def _content_chunk(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                )
            )
        ]
    )


def _fake_client(chunks):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=_FakeOCPCompletions(chunks)
        )
    )


class OCPTests(unittest.TestCase):
    def test_ocp_tool_surface_is_law_source_only(self):
        tool_names = {tool["function"]["name"] for tool in ocp.OCP_TOOLS}

        self.assertEqual(tool_names, ocp.OCP_ALLOWED_TOOL_NAMES)
        self.assertNotIn("retrieve_conversation_memory", tool_names)
        self.assertNotIn("remember_conversation_turn", tool_names)
        self.assertNotIn("pdf_commit_by_sentence", tool_names)
        self.assertNotIn("word_writer", tool_names)

    def test_clean_output_removes_wrappers_without_touching_body(self):
        cleaned = ocp.OCPStatic._clean_output(
            """
            以下是修复后的正文：

            《民法典》第五百七十七条
            > 当事人一方不履行合同义务的，应当承担违约责任。

            以上为修复后的正文
            """
        )

        self.assertIn("《民法典》第五百七十七条", cleaned)
        self.assertIn("应当承担违约责任", cleaned)
        self.assertNotIn("以下是修复后的正文", cleaned)
        self.assertNotIn("以上为修复后的正文", cleaned)

    def test_clean_output_repairs_table_without_separator(self):
        cleaned = ocp.OCPStatic._clean_output(
            "| 项目 | 数值 |\n"
            "| A | 1 |\n"
            "| B | 2 |"
        )

        self.assertIn("| 项目 | 数值 |", cleaned)
        self.assertIn("| --- | --- |", cleaned)
        self.assertIn("| A | 1 |", cleaned)
        self.assertIn("| B | 2 |", cleaned)

    def test_clean_output_expands_collapsed_blockquote_table(self):
        cleaned = ocp.OCPStatic._clean_output(
            "> **关键认定标准：** | 构成要件 | 本案情况 | 是否符合 | "
            "|---------|---------|---------| "
            "| **数额较大** | 本案总金额400元 | 不符合 | "
            "| **多次盗窃** | 二年内三次以上盗窃 | 需核实次数 | "
            "**⚠️ 重要提示：** 应核实具体次数。"
        )

        self.assertIn("> **关键认定标准：**", cleaned)
        self.assertIn("> | 构成要件 | 本案情况 | 是否符合 |", cleaned)
        self.assertIn("> | --- | --- | --- |", cleaned)
        self.assertIn("> | **数额较大** | 本案总金额400元 | 不符合 |", cleaned)
        self.assertIn("> | **多次盗窃** | 二年内三次以上盗窃 | 需核实次数 |", cleaned)
        self.assertIn("> **⚠️ 重要提示：** 应核实具体次数。", cleaned)

    def test_deterministic_repair_normalizes_inconsistent_table_width(self):
        cleaned = ocp.OCPStatic._deterministic_format_repair(
            "| 法条 | 要点 |\n"
            "| 《民法典》 | 违约责任 | 第五百七十七条 |\n"
            "| 《民事诉讼法》 | 起诉条件 |"
        )

        lines = [line for line in cleaned.splitlines() if line.strip().startswith("|")]
        pipe_counts = {line.count("|") for line in lines}

        self.assertEqual(len(pipe_counts), 1)
        self.assertIn("| 法条 | 要点 |  |", cleaned)
        self.assertIn("| --- | --- | --- |", cleaned)
        self.assertIn("| 《民事诉讼法》 | 起诉条件 |  |", cleaned)

    def test_clean_output_removes_ocp_process_lines_from_body(self):
        cleaned = ocp.OCPStatic._clean_output(
            "[OCP] 正在进行格式审查与信源核验...\n"
            "OCP 正在检查正文结构、引用角标和 Markdown 语法\n"
            "《民法典》第五百七十七条\n"
            "> 当事人一方不履行合同义务的，应当承担违约责任。\n"
        )

        self.assertNotIn("[OCP]", cleaned)
        self.assertNotIn("OCP 正在", cleaned)
        self.assertIn("《民法典》第五百七十七条", cleaned)

    def test_clean_output_prefers_final_answer_payload(self):
        cleaned = ocp.OCPStatic._clean_output(
            "需要注意：\n"
            "- 最终回复必须包裹在 <final_answer> 标签中\n"
            "现在让我构建答案。<final_answer>\n"
            "外卖被偷，通常应先区分刑事、治安和民事赔偿路径。\n"
            "</final_answer>"
        )

        self.assertEqual(cleaned, "外卖被偷，通常应先区分刑事、治安和民事赔偿路径。")
        self.assertNotIn("需要注意", cleaned)
        self.assertNotIn("final_answer", cleaned)

    def test_ocp_stream_commits_body_once_after_review_finishes(self):
        checker = ocp.OCPStream(session_id="test")
        checker.client = _fake_client([
            _content_chunk("《民法典》第五百七十七条\n"),
            _content_chunk("> 当事人一方不履行合同义务的，应当承担违约责任。"),
        ])

        async def collect_events():
            return [event async for event in checker.check_stream("原始正文需要格式修复")]

        events = asyncio.run(collect_events())
        replacements = [event for event in events if event.get("type") == "content_replace"]

        self.assertEqual(len(replacements), 1)
        self.assertIn("《民法典》第五百七十七条", replacements[0]["content"])
        self.assertLess(
            events.index(replacements[0]),
            next(i for i, event in enumerate(events) if "审查完成" in event.get("content", "")),
        )

    def test_ocp_stream_fallback_uses_final_answer_payload(self):
        checker = ocp.OCPStream(session_id="test")
        checker.MAX_TOOL_ROUNDS = 0
        raw = (
            "需要注意：最终回复必须包裹在 <final_answer> 中。\n"
            "<final_answer>\n"
            "OK\n"
            "</final_answer>"
        )

        async def collect_events():
            return [event async for event in checker.check_stream(raw)]

        events = asyncio.run(collect_events())
        replacements = [event for event in events if event.get("type") == "content_replace"]

        self.assertEqual(len(replacements), 1)
        self.assertEqual(replacements[0]["content"], "OK")
        self.assertNotIn("需要注意", replacements[0]["content"])

    def test_ocp_stream_preserves_short_answer_when_checker_drifts(self):
        checker = ocp.OCPStream(session_id="test")
        checker.client = _fake_client([
            _content_chunk("好的，收到您的请求。请提供需要我检查并修复格式的文本内容。"),
        ])

        async def collect_events():
            return [event async for event in checker.check_stream("OK")]

        events = asyncio.run(collect_events())
        replacements = [event for event in events if event.get("type") == "content_replace"]

        self.assertEqual(len(replacements), 1)
        self.assertEqual(replacements[0]["content"], "OK")

    def test_ocp_stream_rejects_status_line_as_replacement(self):
        original = (
            "《民法典》第五百七十七条\n"
            "> 当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、"
            "采取补救措施或者赔偿损失等违约责任。"
        )
        checker = ocp.OCPStream(session_id="test")
        checker.client = _fake_client([_content_chunk("审查完成")])

        async def collect_events():
            return [event async for event in checker.check_stream(original)]

        events = asyncio.run(collect_events())
        replacements = [event for event in events if event.get("type") == "content_replace"]

        self.assertEqual(len(replacements), 1)
        self.assertNotEqual(replacements[0]["content"], "审查完成")
        self.assertIn("《民法典》第五百七十七条", replacements[0]["content"])

    def test_ocp_rejects_process_text_as_replacement(self):
        original = "《民法典》第六百二十一条规定，买受人应当及时通知质量异议。"
        candidate = (
            "我来检查文本格式。\n\n"
            "首先检查信源角标，需要调用工具获取《民法典》第六百二十一条的链接。"
        )

        self.assertFalse(ocp.OCPStatic._is_substantive_replacement(original, candidate))

    def test_ocp_stream_falls_back_when_review_rounds_are_exhausted(self):
        checker = ocp.OCPStream(session_id="test")
        checker.MAX_TOOL_ROUNDS = 0
        original = (
            "《民法典》第六百二十一条<sup><a href=\"https://example.com/621\">1</a></sup>\n"
            "| 项目 | 结论 |\n"
            "|---|---|\n"
            "| 质量异议 | 买方应及时通知 |"
        )

        async def collect_events():
            return [event async for event in checker.check_stream(original)]

        events = asyncio.run(collect_events())
        replacements = [event for event in events if event.get("type") == "content_replace"]

        self.assertEqual(len(replacements), 1)
        self.assertIn("第六百二十一条", replacements[0]["content"])
        self.assertTrue(any("最大检查轮次" in event.get("content", "") for event in events))


if __name__ == "__main__":
    unittest.main()
