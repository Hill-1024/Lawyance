"""
模块描述：多模态提示词契约测试，锁定"直附图片已可见、文档才需工具读取"的表述。
"""

import importlib
import os
import sys
import unittest


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"prompt_loader", "services", "services.context_compiler"} or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class MultimodalPromptTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("LAWVER_RELEASE_SYNC_ON_STARTUP", "0")
        purge_runtime_modules()
        self.prompt_loader = importlib.import_module("prompt_loader")

    def tearDown(self):
        purge_runtime_modules()

    def test_core_prompt_routes_images_through_image_reader(self):
        prompt = self.prompt_loader.build_system_prompt()
        self.assertIn("<multimodal_input>", prompt, "缺少多模态输入片段")
        self.assertIn("image_reader", prompt, "未声明图片读取工具")
        self.assertIn("平台不会自动把图片塞给你", prompt, "未声明图片需自行读取")
        self.assertIn("不要声称", prompt, "未约束模型不得否认图像能力")

    def test_multimodal_section_precedes_file_processing_rules(self):
        prompt = self.prompt_loader.build_system_prompt()
        # 先声明图片可见，再讲文档读取；顺序反了模型就会把图片当文档处理
        self.assertLess(
            prompt.index("<multimodal_input>"),
            prompt.index("<file_processing>"),
            "多模态片段必须排在文件处理规范之前",
        )

    def test_document_readers_must_not_be_used_for_images(self):
        prompt = self.prompt_loader.build_system_prompt()
        self.assertIn("本条只约束文档", prompt, "文件读取规则未限定为文档")
        self.assertIn("它们读不了图片", prompt, "未禁止用文档读取工具读图片")

    def test_constraint_recap_requires_image_reader_before_answering(self):
        prompt = self.prompt_loader.build_system_prompt()
        self.assertIn("图片必须先用 `image_reader` 读取", prompt, "尾部约束未要求先用工具读图")
        self.assertIn("禁止声称自己不具备图像能力", prompt, "尾部约束未禁止否认图像能力")

    def test_prompt_contains_no_affirmative_capability_denial(self):
        """提示词里只能出现"禁止否认能力"的约束，不能出现自我否定的能力声明。"""
        prompt = self.prompt_loader.build_system_prompt()
        for denial in ("你无法查看图片", "你不能识别图片", "你不具备多模态能力", "无法识别图片内容"):
            self.assertNotIn(denial, prompt, f"提示词出现自我否定的能力声明: {denial}")

    def test_context_compiler_requires_reading_files_and_images(self):
        """缺口提示必须要求先读取，并指明图片走 image_reader。"""
        compiler = importlib.import_module("services.context_compiler")
        lines = compiler._context_lines(
            content="看看这张借条照片",
            intent={"task_type": "file_review", "focus": []},
            memory_lines=[],
            policy={"requires_file_read": True},
        )
        joined = "\n".join(lines)
        self.assertIn("必须先列出并读取工作区文件", joined)
        self.assertIn("image_reader", joined, "缺口提示未指明图片读取工具")


    def test_court_prompt_routes_materials_through_readers(self):
        """庭审各角色必须知道材料在工作区、需自行读取。

        法庭请求只带公开事件文本，模型没有别的途径知道工作区里有什么文件；
        缺少这段指引时，庭审里上传的材料（含图片）对模型完全不可见。
        """
        court_prompts = importlib.import_module("services.court_prompts")
        for speaker in ("judge", "opponent", "reviewer", "user_agent"):
            messages = court_prompts.build_court_messages(
                speaker=speaker,
                case_type="civil",
                user_side="原告",
                court_state={"phase": "opening", "phase_turn_counts": {}, "total_turns": 0, "speaker_last_positions": {}},
                shared_dossier={},
                private_brief={},
                public_summary="",
                recent_events=[],
                memory_context="",
            )
            text = "\n".join(str(m.get("content") or "") for m in messages)
            self.assertIn("工作区", text, f"{speaker} 未告知材料位于工作区")
            self.assertIn("image_reader", text, f"{speaker} 未告知用 image_reader 读图")
            self.assertIn("list_workspace_files", text, f"{speaker} 未告知可先列出文件")
            self.assertIn("平台不会自动把材料内容给你", text, f"{speaker} 未说明材料需自行读取")

    def test_court_agents_can_call_image_reader(self):
        tools_module = importlib.import_module("tools")
        self.assertIn("image_reader", tools_module.registry.names("court"), "庭审角色无法调用读图工具")


if __name__ == "__main__":
    unittest.main()
