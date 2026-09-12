"""
模块描述：模拟法庭模式回归测试，覆盖路由、FSM、prompt、scope 和流式事件契约。
"""

import importlib
import json
import os
import sys
import tempfile
import types
import unittest

from fastapi.testclient import TestClient


TEST_SECRET = "c" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class CourtModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")
        purge_runtime_modules()

    async def asyncTearDown(self):
        self.tmp.cleanup()
        purge_runtime_modules()

    async def test_court_route_streams_and_terminates_with_done(self):
        agent = importlib.import_module("agent")
        court_route = importlib.import_module("routes.court")

        prepared = types.SimpleNamespace()
        original_prepare = court_route.prepare_court_turn
        original_run = court_route.run_court_turn_stream

        async def fake_prepare(*_args, **_kwargs):
            return prepared

        async def fake_run(_prepared):
            yield {"type": "content", "content": "开庭", "speaker": "judge"}

        try:
            court_route.prepare_court_turn = fake_prepare
            court_route.run_court_turn_stream = fake_run
            with TestClient(agent.app, base_url="http://localhost") as client:
                login = client.post(
                    "/api/login",
                    json={"username": "admin", "password": "bootstrap-password"},
                    headers={"origin": "http://localhost:5173"},
                )
                self.assertEqual(login.status_code, 200)
                response = client.post(
                    "/api/court/turn",
                    json={"court_session_id": "court-1"},
                    headers={"origin": "http://localhost:5173"},
                )
        finally:
            court_route.prepare_court_turn = original_prepare
            court_route.run_court_turn_stream = original_run

        self.assertEqual(response.status_code, 200)
        self.assertIn('data: {"type": "content", "content": "开庭", "speaker": "judge"}', response.text)
        self.assertTrue(response.text.rstrip().endswith("data: [DONE]"))

    async def test_fsm_ignores_frontend_speaker_and_uses_structured_state(self):
        court_fsm = importlib.import_module("services.court_fsm")

        decision = court_fsm.decide_next_turn(
            {
                "case_type": "civil",
                "phase": "court_debate",
                "speaker": "opponent",
                "phase_turn_counts": {"court_debate": 4},
                "total_turns": 8,
            },
            public_events=[{"speaker": "opponent", "content": "我方无更多意见"}],
        )

        self.assertEqual(decision.phase, "final_statement")
        self.assertNotEqual(decision.speaker, "opponent")
        self.assertEqual(decision.court_state["phase"], "final_statement")

    async def test_fsm_lets_user_speak_in_claim_statement_as_plaintiff(self):
        """民事原告应当在诉辩陈述阶段开口。"""
        court_fsm = importlib.import_module("services.court_fsm")
        decision = court_fsm.decide_next_turn(
            {"case_type": "civil", "user_side": "原告", "phase": "claim_statement"},
            public_events=[{"speaker": "judge", "content": "现在开庭"}],
        )
        self.assertTrue(decision.awaiting_user)
        self.assertIsNone(decision.speaker)

    async def test_fsm_lets_opponent_speak_in_claim_statement_when_user_is_defendant(self):
        """用户是被告时，诉辩陈述阶段应由 opponent 出场作为原告。"""
        court_fsm = importlib.import_module("services.court_fsm")
        decision = court_fsm.decide_next_turn(
            {"case_type": "civil", "user_side": "被告", "phase": "claim_statement"},
            public_events=[{"speaker": "judge", "content": "现在开庭"}],
        )
        self.assertEqual(decision.speaker, "opponent")
        self.assertFalse(decision.awaiting_user)

    async def test_fsm_alternating_phase_flips_between_user_and_opponent(self):
        """法庭辩论是双方轮流，对方刚说完后该用户。"""
        court_fsm = importlib.import_module("services.court_fsm")
        decision = court_fsm.decide_next_turn(
            {
                "case_type": "civil",
                "user_side": "原告",
                "phase": "court_debate",
                "phase_turn_counts": {"court_debate": 1},
            },
            public_events=[{"speaker": "opponent", "content": "对方观点"}],
        )
        self.assertTrue(decision.awaiting_user)
        self.assertIsNone(decision.speaker)

    async def test_fsm_criminal_final_statement_belongs_to_defense(self):
        """刑事最后陈述权属被告——辩护方用户必须开口。"""
        court_fsm = importlib.import_module("services.court_fsm")
        decision = court_fsm.decide_next_turn(
            {"case_type": "criminal", "user_side": "辩护方", "phase": "final_statement"},
            public_events=[],
        )
        self.assertTrue(decision.awaiting_user)

    async def test_fsm_judge_awaits_user_in_inquiry_phase(self):
        """法官在 court_inquiry 询问后必须等用户回应。"""
        court_fsm = importlib.import_module("services.court_fsm")
        decision = court_fsm.decide_next_turn(
            {"case_type": "civil", "user_side": "原告", "phase": "court_inquiry"},
            public_events=[],
        )
        self.assertEqual(decision.speaker, "judge")
        self.assertTrue(decision.court_state["awaiting_user"])

    async def test_court_prompt_avoids_main_identity_and_output_contract(self):
        court_prompts = importlib.import_module("services.court_prompts")

        messages = court_prompts.build_court_messages(
            speaker="judge",
            case_type="civil",
            user_side="plaintiff",
            court_state={"case_type": "civil", "phase": "opening"},
            shared_dossier={"facts": "公开事实"},
            private_brief={"strategy": "内线策略ABC"},
            public_summary="",
            recent_events=[],
            memory_context="",
        )
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertNotIn("你是 Lawver", prompt_text)
        self.assertNotIn("<final_answer>", prompt_text)
        self.assertIn("模拟法庭", prompt_text)
        self.assertNotIn("内线策略ABC", prompt_text)

    async def test_court_prompt_enforces_fact_and_legal_source_boundaries(self):
        court_prompts = importlib.import_module("services.court_prompts")

        judge_messages = court_prompts.build_court_messages(
            speaker="judge",
            case_type="civil",
            user_side="原告",
            court_state={"case_type": "civil", "phase": "opening"},
            shared_dossier={"facts": "公开事实"},
            private_brief={},
            public_summary="",
            recent_events=[],
            memory_context="",
        )
        judge_prompt = "\n".join(message["content"] for message in judge_messages)

        self.assertIn("本轮事实与法源边界", judge_prompt)
        self.assertIn("不得把模型推测写成已发生事实", judge_prompt)
        self.assertIn("不得把新的未公开事实作为发言依据", judge_prompt)
        self.assertIn("本轮未核验", judge_prompt)
        self.assertNotIn("对方律师可以抛出用户方未知但合理的可能事实", judge_prompt)

        opponent_messages = court_prompts.build_court_messages(
            speaker="opponent",
            case_type="civil",
            user_side="原告",
            court_state={"case_type": "civil", "phase": "claim_statement"},
            shared_dossier={"facts": "公开事实"},
            private_brief={},
            public_summary="",
            recent_events=[],
            memory_context="",
        )
        opponent_prompt = "\n".join(message["content"] for message in opponent_messages)

        self.assertIn("对方律师可以抛出用户方未知但合理的可能事实", opponent_prompt)
        self.assertIn("可能事实/攻防假设/待核实事项", opponent_prompt)
        self.assertIn("不得把这类线索说成已经发生", opponent_prompt)
        self.assertIn("具体法条", opponent_prompt)

    async def test_court_executor_routes_memory_scope_separately(self):
        court_pipeline = importlib.import_module("services.court_pipeline")
        calls = []

        def fake_dispatch(name, args, workspace_scope=None, *, capability=None):
            calls.append((name, workspace_scope, capability))
            return "ok"

        original_dispatch = court_pipeline.use_tools
        try:
            court_pipeline.use_tools = fake_dispatch
            executor = court_pipeline.build_court_tool_executor("user/court", "user/court:judge")
            executor("retrieve_conversation_memory", {"query": "争点"})
            executor("pdf_text_reader", {"pdf_path": "TEMP/user/court/a.pdf"})
        finally:
            court_pipeline.use_tools = original_dispatch

        self.assertEqual(calls, [
            ("retrieve_conversation_memory", "user/court:judge", "court"),
            ("pdf_text_reader", "user/court", "court"),
        ])

    async def test_role_scopes_are_derived_from_user_workspace_scope(self):
        court_pipeline = importlib.import_module("services.court_pipeline")
        workspace_service = importlib.import_module("services.workspace_service")

        admin_scope = workspace_service.get_workspace_scope("admin", "same-session")
        other_scope = workspace_service.get_workspace_scope("other", "same-session")

        self.assertNotEqual(
            court_pipeline.role_memory_scope(admin_scope, "judge"),
            court_pipeline.role_memory_scope(other_scope, "judge"),
        )

    async def test_user_agent_takes_over_when_enabled(self):
        """用户开启 user_agent_enabled 后，FSM 决定的 awaiting_user 由 user_agent 接管。"""
        court_pipeline = importlib.import_module("services.court_pipeline")
        captured = {}

        original_sync = court_pipeline.sync_memory_cache
        original_retrieve = court_pipeline.retrieve_memory_context
        original_agent = court_pipeline.ToolLoopAgent

        def fake_sync(*_args, **_kwargs):
            return {}

        def fake_retrieve(scope, _query):
            return f"memory from {scope}", {}

        class FakeAgent:
            def __init__(self, **kwargs):
                captured["memory"] = kwargs["memory"]
                captured["mode"] = kwargs["mode"]

        try:
            court_pipeline.sync_memory_cache = fake_sync
            court_pipeline.retrieve_memory_context = fake_retrieve
            court_pipeline.ToolLoopAgent = FakeAgent
            schemas = importlib.import_module("schemas")
            request = schemas.CourtTurnRequest(
                court_session_id="court-user-agent",
                court_state={
                    "case_type": "civil",
                    "user_side": "原告",
                    "phase": "claim_statement",
                    "phase_turn_counts": {},
                    "user_agent_enabled": True,
                },
                private_brief={"strategy": "突出违约金条款"},
                public_events_recent=[{"speaker": "judge", "phase": "opening", "content": "现在开庭"}],
            )
            prepared = await court_pipeline.prepare_court_turn(request, "admin")
        finally:
            court_pipeline.sync_memory_cache = original_sync
            court_pipeline.retrieve_memory_context = original_retrieve
            court_pipeline.ToolLoopAgent = original_agent

        # FSM 本该返 awaiting_user（原告陈述 + 用户立场=原告），但被 user_agent 接管。
        self.assertEqual(prepared.decision.speaker, "user")
        self.assertTrue(prepared.is_user_agent)
        self.assertFalse(prepared.decision.awaiting_user)
        self.assertEqual(prepared.decision.court_state["phase_turn_counts"]["claim_statement"], 1)
        self.assertEqual(prepared.decision.court_state["total_turns"], 1)
        self.assertTrue(prepared.decision.court_state["user_agent_enabled"])
        # user agent prompt 注入了私有 brief，且不带主聊天 Lawver 主身份。
        prompt_text = "\n".join(message["content"] for message in captured["memory"])
        self.assertIn("user_agent", prompt_text)
        self.assertIn("突出违约金条款", prompt_text)
        self.assertNotIn("你是 Lawver", prompt_text)
        self.assertEqual(captured["mode"], "court_user")

    async def test_user_agent_disabled_keeps_awaiting_user(self):
        """user_agent_enabled=False 时维持原行为——FSM 返 awaiting_user，pipeline 不接管。"""
        court_pipeline = importlib.import_module("services.court_pipeline")
        schemas = importlib.import_module("schemas")
        request = schemas.CourtTurnRequest(
            court_session_id="court-no-agent",
            court_state={
                "case_type": "civil",
                "user_side": "原告",
                "phase": "claim_statement",
                "phase_turn_counts": {},
                # user_agent_enabled 未设
            },
            public_events_recent=[{"speaker": "judge", "phase": "opening", "content": "现在开庭"}],
        )
        prepared = await court_pipeline.prepare_court_turn(request, "admin")
        self.assertIsNone(prepared.decision.speaker)
        self.assertTrue(prepared.decision.awaiting_user)
        self.assertFalse(prepared.decision.court_state["user_agent_enabled"])
        self.assertFalse(prepared.is_user_agent)

    async def test_clear_court_memory_clears_three_role_scopes(self):
        """撤回时调用的 endpoint 必须清三角色 memory scope。"""
        agent = importlib.import_module("agent")
        court_route = importlib.import_module("routes.court")

        cleared_scopes: list[str] = []

        def fake_call_memory_tool(tool_name, args, scope):
            if tool_name == "clear_conversation_memory":
                cleared_scopes.append(scope)
            return {"status": "ok"}

        original = court_route.call_memory_tool
        try:
            court_route.call_memory_tool = fake_call_memory_tool
            with TestClient(agent.app, base_url="http://localhost") as client:
                login = client.post(
                    "/api/login",
                    json={"username": "admin", "password": "bootstrap-password"},
                    headers={"origin": "http://localhost:5173"},
                )
                self.assertEqual(login.status_code, 200)
                response = client.post(
                    "/api/court/memory/clear",
                    json={"court_session_id": "court-rewind-1"},
                    headers={"origin": "http://localhost:5173"},
                )
        finally:
            court_route.call_memory_tool = original

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        # 四个 AI 角色 scope 都被清——judge / opponent / reviewer / user(代理)。
        self.assertEqual(len(cleared_scopes), 4)
        suffixes = sorted(scope.rsplit(":", 1)[-1] for scope in cleared_scopes)
        self.assertEqual(suffixes, ["judge", "opponent", "reviewer", "user"])

    async def test_reviewer_cross_role_memory_is_injected_by_pipeline(self):
        court_pipeline = importlib.import_module("services.court_pipeline")
        captured = {}

        original_sync = court_pipeline.sync_memory_cache
        original_retrieve = court_pipeline.retrieve_memory_context
        original_agent = court_pipeline.ToolLoopAgent

        def fake_sync(*_args, **_kwargs):
            return {}

        def fake_retrieve(scope, query):
            return f"memory from {scope}", {}

        class FakeAgent:
            def __init__(self, **kwargs):
                captured["memory"] = kwargs["memory"]

        try:
            court_pipeline.sync_memory_cache = fake_sync
            court_pipeline.retrieve_memory_context = fake_retrieve
            court_pipeline.ToolLoopAgent = FakeAgent
            request = importlib.import_module("schemas").CourtTurnRequest(
                court_session_id="court-1",
                court_state={
                    "case_type": "civil",
                    "phase": "review",
                    "phase_turn_counts": {},
                    "trial_over": False,
                },
                public_events_recent=[{"speaker": "judge", "phase": "judge_summary", "content": "总结"}],
                agent_states={"judge": {"memory_snapshot": {}}, "opponent": {"memory_snapshot": {}}},
            )
            prepared = await court_pipeline.prepare_court_turn(request, "admin")
        finally:
            court_pipeline.sync_memory_cache = original_sync
            court_pipeline.retrieve_memory_context = original_retrieve
            court_pipeline.ToolLoopAgent = original_agent

        self.assertEqual(prepared.decision.speaker, "reviewer")
        prompt_text = "\n".join(message["content"] for message in captured["memory"])
        self.assertIn("其他角色记忆摘要", prompt_text)
        self.assertIn("admin/court%2D1:judge", prompt_text)


if __name__ == "__main__":
    unittest.main()
