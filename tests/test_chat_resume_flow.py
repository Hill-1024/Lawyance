"""
模块描述：断线续传在 HTTP/SSE 层的契约回归——重放范围、done 归属、确认后 410。

前端据此判断"该重连"还是"只能重新生成"：
- 用 from_seq 重连必须只补没收到的事件，并带上 done，客户端才能把这条回答收尾；
- 设备确认接收（ack 到 final_seq）后缓冲随即删除，再续传必须 410（续传窗口已过），
  而不是给出一个空的 200 让客户端以为"续上了"却永远等不到内容。
"""

import asyncio
import itertools
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import chat as chat_routes
from services import stream_buffer
from services.chat_pipeline import PreparedChatTurn
from services.auth_dependencies import get_current_user

_TURN_SEQ = itertools.count(1)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if not payload or payload == "[DONE]":
            continue
        events.append(json.loads(payload))
    return events


class ChatResumeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        # 每次用新的 turn_id：同一个 id 第二次 create 会失败并退回非缓冲直连流，测不到续传。
        self.turn_id = f"turn_resume_flow_{next(_TURN_SEQ)}"
        self.original_prepare = chat_routes.prepare_chat_turn
        self.original_run_agent_stream = stream_buffer.run_agent_stream
        self.original_route_run_agent_stream = chat_routes.run_agent_stream

        async def fake_prepare(request, current_user):
            return PreparedChatTurn(
                content=request.message,
                session_id=request.conversation_id,
                stream=request.stream,
                agent_mode=request.agent_mode,
                workspace_scope=f"{current_user}:{request.conversation_id}",
                turn_id=self.turn_id,
                agent=object(),
            )

        async def fake_run_agent_stream(prepared):
            for index in range(4):
                await asyncio.sleep(0)
                yield {"type": "content", "content": f"chunk-{index}"}

        chat_routes.prepare_chat_turn = fake_prepare
        stream_buffer.run_agent_stream = fake_run_agent_stream
        # 直连（非缓冲）分支也从路由模块取这个名字，一并替换，避免真的驱动模型。
        chat_routes.run_agent_stream = fake_run_agent_stream

        app = FastAPI()
        app.include_router(chat_routes.router)
        app.dependency_overrides[get_current_user] = lambda: "tester"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        chat_routes.prepare_chat_turn = self.original_prepare
        stream_buffer.run_agent_stream = self.original_run_agent_stream
        chat_routes.run_agent_stream = self.original_route_run_agent_stream
        if self.turn_id in stream_buffer._REGISTRY:
            asyncio.run(stream_buffer.delete(self.turn_id))

    def _start_stream(self) -> list[dict]:
        response = self.client.post(
            "/api/chat",
            json={"message": "你好", "conversation_id": "conv_resume", "stream": True, "resume_enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        return _parse_sse(response.text)

    def test_resume_replays_only_missing_events_and_keeps_done(self) -> None:
        events = self._start_stream()
        self.assertEqual(events[0]["type"], "stream_start")
        self.assertEqual(events[0]["stream_id"], self.turn_id)
        self.assertTrue(events[0]["buffered"])
        self.assertEqual([event["seq"] for event in events], list(range(len(events))))
        self.assertEqual(events[-1]["type"], "done")
        final_seq = events[-1]["final_seq"]

        # 客户端在收到 seq=2 之后掉线：重连只该补 seq>2，并把 done 一起带上收尾。
        resumed = _parse_sse(self.client.get(f"/api/chat/resume/{self.turn_id}?from_seq=2").text)
        self.assertEqual([event["seq"] for event in resumed], [3, 4, 5])
        self.assertEqual([event["type"] for event in resumed], ["content", "content", "done"])
        self.assertEqual(resumed[-1]["final_seq"], final_seq)

    def test_resume_with_full_seq_returns_only_done(self) -> None:
        events = self._start_stream()
        final_seq = events[-1]["final_seq"]

        resumed = _parse_sse(self.client.get(f"/api/chat/resume/{self.turn_id}?from_seq={final_seq}").text)
        self.assertEqual([event["seq"] for event in resumed], [])
        self.assertEqual(self.client.get(f"/api/chat/resume/{self.turn_id}?from_seq={final_seq}").status_code, 200)

    def test_acked_stream_is_gone_and_answers_410(self) -> None:
        events = self._start_stream()
        final_seq = events[-1]["final_seq"]

        acked = self.client.post(
            "/api/chat/ack",
            json={"stream_id": self.turn_id, "acked_seq": final_seq},
        )
        self.assertEqual(acked.status_code, 200)
        self.assertIsNone(stream_buffer._REGISTRY.get(self.turn_id), "确认到终态后缓冲应被删除")

        # 前端把 410 当作"续传窗口已过"，而不是可以静默重试的状态。
        self.assertEqual(self.client.get(f"/api/chat/resume/{self.turn_id}?from_seq=-1").status_code, 410)

    def test_resume_of_unknown_stream_is_410(self) -> None:
        self.assertEqual(self.client.get("/api/chat/resume/turn_never_existed?from_seq=-1").status_code, 410)


if __name__ == "__main__":
    unittest.main()
