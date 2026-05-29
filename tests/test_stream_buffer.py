"""
模块描述：聊天断线续传缓冲区的核心行为测试。
"""

import asyncio
import time
import unittest

from services import stream_buffer


async def collect_reader(stream_id: str, from_seq: int) -> list[dict]:
    return [event async for event in stream_buffer.reader(stream_id, from_seq)]


class StreamBufferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for stream_id in ["s1", "s2", "owned", "ttl", "quota", "bytes", "cancel"]:
            await stream_buffer.delete(stream_id)

    async def test_reader_replays_events_after_requested_seq_and_ack_trims(self):
        state = await stream_buffer.create("s1", "alice")
        self.assertIsNotNone(state)
        await stream_buffer.append("s1", {"type": "stream_start", "stream_id": "s1", "buffered": True})
        await stream_buffer.append("s1", {"type": "content", "content": "a"})
        await stream_buffer.append("s1", {"type": "content", "content": "b"})
        await stream_buffer.append("s1", {"type": "done"})
        await stream_buffer.finish("s1")

        replay = await collect_reader("s1", 1)
        self.assertEqual([event["content"] for event in replay if event["type"] == "content"], ["b"])
        self.assertEqual(replay[-1]["type"], "done")

        trimmed_to = await stream_buffer.ack("s1", "alice", 3)
        self.assertEqual(trimmed_to, 3)
        self.assertIsNone(await stream_buffer.get("s1", "alice"))

    async def test_owner_isolation_for_get_ack_and_cancel(self):
        await stream_buffer.create("owned", "alice")
        await stream_buffer.append("owned", {"type": "content", "content": "secret"})

        self.assertIsNone(await stream_buffer.get("owned", "bob"))
        self.assertIsNone(await stream_buffer.ack("owned", "bob", 0))
        self.assertFalse(await stream_buffer.cancel("owned", "bob"))
        self.assertIsNotNone(await stream_buffer.get("owned", "alice"))

    async def test_cancel_cancels_producer_and_deletes_state(self):
        await stream_buffer.create("cancel", "alice")
        task = asyncio.create_task(asyncio.sleep(30))
        await stream_buffer.set_task("cancel", task)

        self.assertTrue(await stream_buffer.cancel("cancel", "alice"))
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled() or task.done())
        self.assertIsNone(await stream_buffer.get("cancel", "alice"))

    async def test_ttl_sweep_deletes_expired_streams(self):
        state = await stream_buffer.create("ttl", "alice")
        self.assertIsNotNone(state)
        state.created_at = time.time() - stream_buffer.TTL_SECONDS - 10

        removed = await stream_buffer.sweep_once()
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(await stream_buffer.get("ttl", "alice"))

    async def test_per_user_concurrency_limit_blocks_new_streams(self):
        original = stream_buffer.MAX_STREAMS_PER_USER
        stream_buffer.MAX_STREAMS_PER_USER = 1
        try:
            self.assertIsNotNone(await stream_buffer.create("quota", "alice"))
            self.assertIsNone(await stream_buffer.create("s2", "alice"))
        finally:
            stream_buffer.MAX_STREAMS_PER_USER = original

    async def test_byte_limit_marks_resume_unavailable(self):
        original = stream_buffer.MAX_BYTES_PER_STREAM
        stream_buffer.MAX_BYTES_PER_STREAM = 32
        try:
            await stream_buffer.create("bytes", "alice")
            await stream_buffer.append("bytes", {"type": "content", "content": "x" * 200})
            await stream_buffer.append("bytes", {"type": "done"})
            await stream_buffer.finish("bytes")

            replay = await collect_reader("bytes", -1)
            self.assertEqual(replay[0]["type"], "resume_unavailable")
            self.assertEqual(replay[0]["reason"], "quota")
        finally:
            stream_buffer.MAX_BYTES_PER_STREAM = original


if __name__ == "__main__":
    unittest.main()
