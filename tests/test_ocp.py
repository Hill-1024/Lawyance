import unittest

import ocp


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


if __name__ == "__main__":
    unittest.main()
