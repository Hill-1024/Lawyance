"""
模块描述：Plan-and-Solve 控制面工具测试。
"""

import unittest

from tools import registry


class ControlPlaneToolTests(unittest.TestCase):
    def test_submit_plan_returns_acknowledged_steps(self):
        result = registry.dispatch(
            "submit_plan",
            {"steps": [" 检索法律依据 ", "", "整理结论"]},
            "tester/conv",
        )

        self.assertEqual(result, {"acknowledged": True, "steps": ["检索法律依据", "整理结论"]})

    def test_submit_final_answer_returns_acknowledged(self):
        result = registry.dispatch(
            "submit_final_answer",
            {"answer": "最终正文"},
            "tester/conv",
        )

        self.assertEqual(result, {"acknowledged": True})


if __name__ == "__main__":
    unittest.main()
