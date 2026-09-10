"""
模块描述：工具分发异常隔离测试，锁定单个工具抛错不得中断整轮对话。
"""

import importlib
import os
import sys
import unittest


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"tools", "tools.registry"} or name.startswith("tools."):
            sys.modules.pop(name, None)


class ToolDispatchIsolationTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("LAWVER_RELEASE_SYNC_ON_STARTUP", "0")
        purge_runtime_modules()
        self.registry_module = importlib.import_module("tools.registry")

    def tearDown(self):
        purge_runtime_modules()

    def _registry_with_handler(self, handler):
        registry = self.registry_module.ToolRegistry()
        registry.register(
            name="exploding_tool",
            schema={"type": "function", "function": {"name": "exploding_tool", "parameters": {}}},
            handler=handler,
            exposure=frozenset({"agent"}),
        )
        return registry

    def test_raising_handler_returns_model_readable_error(self):
        def boom(_args, _scope):
            raise KeyError("body")

        registry = self._registry_with_handler(boom)
        result = registry.dispatch("exploding_tool", {}, "u1/c1", capability="agent")

        # 关键行为：异常被转成结构化结果，而不是向上冒泡打断整轮生成。
        self.assertIsInstance(result, dict)
        self.assertFalse(result["ok"])
        self.assertEqual(result["tool"], "exploding_tool")
        self.assertIn("KeyError", result["error"])

    def test_error_result_is_not_mistaken_for_authorization_failure(self):
        def boom(_args, _scope):
            raise IndexError("totalCount")

        registry = self._registry_with_handler(boom)
        result = registry.dispatch("exploding_tool", {}, "u1/c1", capability="agent")
        # 授权失败的 error 值是固定串；工具异常必须与之区分，否则会被误报成"未授权"。
        self.assertNotEqual(result["error"], self.registry_module.AUTHORIZATION_ERROR)

    def test_authorization_failure_still_reported(self):
        calls = []

        def handler(_args, _scope):
            calls.append(1)
            return {"ok": True}

        registry = self._registry_with_handler(handler)
        result = registry.dispatch("exploding_tool", {}, "u1/c1", capability=None)
        self.assertEqual(result["error"], self.registry_module.AUTHORIZATION_ERROR)
        # 未授权时绝不能真的调用处理器。
        self.assertEqual(calls, [])

    def test_unknown_tool_still_reported(self):
        registry = self.registry_module.ToolRegistry()
        result = registry.dispatch("nope", {}, "u1/c1", capability="agent")
        self.assertIn("不存在", str(result))

    def test_successful_handler_passes_through(self):
        registry = self._registry_with_handler(lambda args, scope: {"ok": True, "echo": args})
        result = registry.dispatch("exploding_tool", {"a": 1}, "u1/c1", capability="agent")
        self.assertEqual(result, {"ok": True, "echo": {"a": 1}})


if __name__ == "__main__":
    unittest.main()
