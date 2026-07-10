"""
模块描述：Plan-and-Solve 控制面工具测试。
"""

import unittest

from tools import registry


class ControlPlaneToolTests(unittest.TestCase):
    def test_ask_user_normalizes_options_and_free_text(self):
        result = registry.dispatch(
            "ask_user",
            {
                "question": "下一步按哪个方向处理？",
                "options": [
                    {"label": "先检索", "description": "优先找法条和案例"},
                    "直接起草",
                    {"value": "补充事实"},
                    {"label": ""},
                ],
            },
            "tester/conv",
            capability="agent",
        )

        self.assertEqual(result["question"], "下一步按哪个方向处理？")
        self.assertTrue(result["allow_free_text"])
        self.assertTrue(result["allow_ignore"])
        self.assertEqual(result["ignore_label"], "忽略此问题")
        self.assertEqual(result["ignore_value"], "忽略此问题，请根据现有信息自行判断并继续。")
        self.assertEqual(
            result["options"],
            [
                {"id": "option_1", "label": "先检索", "value": "先检索", "description": "优先找法条和案例"},
                {"id": "option_2", "label": "直接起草", "value": "直接起草"},
                {"id": "option_3", "label": "补充事实", "value": "补充事实"},
            ],
        )

    def test_submit_plan_returns_acknowledged_steps(self):
        result = registry.dispatch(
            "submit_plan",
            {"steps": [" 检索法律依据 ", "", "整理结论"]},
            "tester/conv",
            capability="plan_and_solve",
        )

        self.assertEqual(result, {"acknowledged": True, "steps": ["检索法律依据", "整理结论"]})

    def test_submit_final_answer_returns_acknowledged(self):
        result = registry.dispatch(
            "submit_final_answer",
            {"answer": "最终正文"},
            "tester/conv",
            capability="plan_and_solve",
        )

        self.assertEqual(result, {"acknowledged": True})


if __name__ == "__main__":
    unittest.main()
