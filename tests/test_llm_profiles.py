"""
模块描述：模型配置档案测试，锁定多套端点的保存、切换、热生效与凭据隔离。
"""

import importlib
import json
import os
import sys
import tempfile
import unittest


TEST_SECRET = "y" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "function_calling"} or name.startswith("routes.") or name.startswith("services."):
            sys.modules.pop(name, None)


class LlmProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ["API_KEY"] = "env-api-key"
        os.environ["BASE_URL"] = "https://env.example.com/v1"
        os.environ["LLM_MODEL"] = "env-model"
        purge_runtime_modules()
        self.settings = importlib.import_module("services.settings_service")

    def tearDown(self):
        self.tmp.cleanup()
        purge_runtime_modules()

    def _ids_by_name(self, state: dict) -> dict:
        return {profile["name"]: profile["id"] for profile in state["profiles"]}

    def test_first_listing_seeds_a_profile_from_current_config(self):
        state = self.settings.list_llm_profiles()
        self.assertEqual(len(state["profiles"]), 1)
        self.assertTrue(state["profiles"][0]["active"])
        # 播种的档案应继承环境变量里的端点，用户无需重新填写。
        self.assertEqual(state["profiles"][0]["base_url"], "https://env.example.com/v1")
        self.assertEqual(state["profiles"][0]["model"], "env-model")
        self.assertTrue(state["profiles"][0]["has_api_key"])

    def test_save_and_activate_switches_runtime_config(self):
        self.settings.list_llm_profiles()
        state = self.settings.save_llm_profile({
            "name": "备用端点",
            "base_url": "https://backup.example.com/v1",
            "model": "backup-model",
            "api_key": "sk-backup",
            "activate": True,
        })
        ids = self._ids_by_name(state)
        self.assertTrue(next(p for p in state["profiles"] if p["id"] == ids["备用端点"])["active"])

        runtime = self.settings.resolve_active_llm_config()
        self.assertEqual(runtime["base_url"], "https://backup.example.com/v1")
        self.assertEqual(runtime["model"], "backup-model")
        self.assertEqual(runtime["api_key"], "sk-backup")
        # providers.llm 必须同步，保证既有读取路径也拿到新值。
        self.assertEqual(
            self.settings.get_provider_runtime_config("llm")["model"],
            "backup-model",
        )

    def test_save_without_activate_keeps_previous_runtime(self):
        self.settings.list_llm_profiles()
        self.settings.save_llm_profile({
            "name": "不激活",
            "base_url": "https://other.example.com/v1",
            "model": "other-model",
        })
        runtime = self.settings.resolve_active_llm_config()
        self.assertEqual(runtime["model"], "env-model")

    def test_delete_removes_profile_and_its_secret(self):
        state = self.settings.list_llm_profiles()
        state = self.settings.save_llm_profile({
            "name": "待删除",
            "base_url": "https://temp.example.com/v1",
            "model": "temp-model",
            "api_key": "sk-temp-secret",
        })
        target = self._ids_by_name(state)["待删除"]

        with open(self.settings.SECRETS_FILE, encoding="utf-8") as handle:
            self.assertIn("sk-temp-secret", handle.read())

        self.settings.delete_llm_profile(target)

        with open(self.settings.SECRETS_FILE, encoding="utf-8") as handle:
            self.assertNotIn("sk-temp-secret", handle.read())
        self.assertNotIn("待删除", self._ids_by_name(self.settings.list_llm_profiles()))

    def test_deleting_active_profile_falls_back_to_remaining(self):
        state = self.settings.list_llm_profiles()
        state = self.settings.save_llm_profile({
            "name": "第二档",
            "base_url": "https://second.example.com/v1",
            "model": "second-model",
            "activate": True,
        })
        second = self._ids_by_name(state)["第二档"]
        first = self._ids_by_name(state)["当前配置"]

        self.settings.delete_llm_profile(second)
        runtime = self.settings.resolve_active_llm_config()
        self.assertEqual(runtime["profile_id"], first)
        self.assertEqual(runtime["model"], "env-model")

    def test_profile_listing_never_exposes_api_key(self):
        self.settings.list_llm_profiles()
        self.settings.save_llm_profile({
            "name": "带密钥",
            "base_url": "https://secret.example.com/v1",
            "model": "secret-model",
            "api_key": "sk-must-not-leak",
            "activate": True,
        })
        payload = json.dumps(self.settings.list_llm_profiles(), ensure_ascii=False)
        self.assertNotIn("sk-must-not-leak", payload)
        # get_settings 同样不能泄漏。
        self.assertNotIn("sk-must-not-leak", json.dumps(self.settings.get_settings(), ensure_ascii=False))

    def test_validation_rejects_bad_input(self):
        self.settings.list_llm_profiles()
        for payload, label in [
            ({"name": "", "base_url": "https://x.com/v1", "model": "m"}, "空名称"),
            ({"name": "n", "base_url": "ftp://x.com", "model": "m"}, "非 http(s) 协议"),
            ({"name": "n", "base_url": "https://x.com/v1", "model": ""}, "空模型"),
            ({"name": "n", "base_url": "", "model": "m"}, "空 URL"),
        ]:
            with self.assertRaises(ValueError, msg=f"{label} 应被拒绝"):
                self.settings.save_llm_profile(payload)

    def test_activate_unknown_profile_raises(self):
        self.settings.list_llm_profiles()
        with self.assertRaises(ValueError):
            self.settings.activate_llm_profile("doesnotexist")

    def test_direct_provider_edit_mirrors_into_active_profile(self):
        state = self.settings.list_llm_profiles()
        active = state["active"]
        self.settings.update_settings({
            "providers": {"llm": {"base_url": "https://edited.example.com/v1", "model": "edited-model"}},
        })
        profiles = self.settings.list_llm_profiles()["profiles"]
        active_profile = next(p for p in profiles if p["id"] == active)
        # 直接编辑 providers.llm 后，活动档案不能与运行时配置分叉。
        self.assertEqual(active_profile["base_url"], "https://edited.example.com/v1")
        self.assertEqual(active_profile["model"], "edited-model")

    def test_profile_cap_enforced(self):
        self.settings.list_llm_profiles()
        for index in range(self.settings.MAX_LLM_PROFILES - 1):
            self.settings.save_llm_profile({
                "name": f"批量{index}",
                "base_url": "https://bulk.example.com/v1",
                "model": f"bulk-{index}",
            })
        with self.assertRaises(ValueError):
            self.settings.save_llm_profile({
                "name": "超限",
                "base_url": "https://overflow.example.com/v1",
                "model": "overflow",
            })

    # ── 回归：档案字段不完整时绝不能把关卡与模型拆到两个来源 ──

    def test_incomplete_profile_does_not_shadow_env_endpoint(self):
        """档案只有占位 base_url、没有 model 时，必须整体回退到 env。

        旧实现按字段回退，会把档案的 base_url 与环境变量的 model 拼在一起，
        出现「deepseek 的模型名发到 api.openai.com」这种错配，模型直接拒绝请求。
        """
        state = self.settings.list_llm_profiles()
        # 模拟线上坏状态：活动档案写着占位端点但没有模型
        with open(self.settings.SETTINGS_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        saved["llm_profiles"] = [{
            "id": state["active"],
            "name": "当前配置",
            "base_url": "https://api.openai.com/v1",
            "model": "",
            "enabled": True,
        }]
        saved.pop("providers", None)
        with open(self.settings.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(saved, handle, ensure_ascii=False)

        runtime = self.settings.resolve_active_llm_config()
        self.assertEqual(runtime["base_url"], "https://env.example.com/v1", "端点必须来自 env，而不是档案里的占位值")
        self.assertEqual(runtime["model"], "env-model")
        self.assertEqual(runtime["api_key"], "env-api-key")

    def test_incomplete_profile_is_not_reported_as_active_source(self):
        state = self.settings.list_llm_profiles()
        with open(self.settings.SETTINGS_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        saved["llm_profiles"] = [{
            "id": state["active"], "name": "当前配置",
            "base_url": "https://api.openai.com/v1", "model": "", "enabled": True,
        }]
        with open(self.settings.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(saved, handle, ensure_ascii=False)

        listing = self.settings.list_llm_profiles()
        self.assertFalse(listing["profiles"][0].get("active"), "信息不完整的档案不应显示为使用中")
        self.assertIn("环境变量", listing["effective"]["source"])

    def test_seed_skips_placeholder_endpoint_when_nothing_configured(self):
        """没有任何真实配置时不应凭空造出 api.openai.com 档案。"""
        os.environ.pop("BASE_URL", None)
        os.environ.pop("LLM_MODEL", None)
        os.environ.pop("API_KEY", None)
        purge_runtime_modules()
        self.settings = importlib.import_module("services.settings_service")

        state = self.settings.list_llm_profiles()
        self.assertEqual(state["profiles"], [], "无配置时不应播种占位档案")
        self.assertEqual(state["active"], "")

    def test_seed_captures_env_endpoint_and_model_together(self):
        state = self.settings.list_llm_profiles()
        seed = state["profiles"][0]
        # 播种的端点与模型必须来自同一来源，不能一个用默认值一个用 env
        self.assertEqual(seed["base_url"], "https://env.example.com/v1")
        self.assertEqual(seed["model"], "env-model")

    def test_saving_incomplete_profile_is_rejected(self):
        self.settings.list_llm_profiles()
        with self.assertRaises(ValueError):
            self.settings.save_llm_profile({
                "name": "半截配置", "base_url": "https://api.openai.com/v1", "model": "",
            })


if __name__ == "__main__":
    unittest.main()
