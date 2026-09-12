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
    async def test_close_during_replay_releases_reader_slot(self):
        state = await stream_buffer.create("s1", "alice")
        await stream_buffer.append("s1", {"type": "content", "content": "cached"})
        for _ in range(stream_buffer.MAX_READERS_PER_STREAM + 1):
            reader = stream_buffer.reader("s1", -1)
            try:
                self.assertEqual((await anext(reader))["type"], "content")
            finally:
                await reader.aclose()
            self.assertEqual(state.readers, {})

    async def test_duplicate_id_preserves_original_owner_and_bytes(self):
        state = await stream_buffer.create("s1", "alice")
        await stream_buffer.append("s1", {"type": "content", "content": "cached"})
        before = stream_buffer.stats()
        self.assertIsNone(await stream_buffer.create("s1", "bob"))
        self.assertIs(await stream_buffer.get("s1", "alice"), state)
        self.assertEqual(stream_buffer.stats(), before)

    async def test_append_waiting_on_deleted_state_does_not_leak_bytes(self):
        state = await stream_buffer.create("s1", "alice")
        before = stream_buffer.stats()["global_bytes"]
        async with state.lock:
            pending = asyncio.create_task(stream_buffer.append("s1", {"type": "content", "content": "late"}))
            await asyncio.sleep(0)
            await stream_buffer.delete("s1")
        self.assertEqual(await pending, -1)
        self.assertEqual(stream_buffer.stats()["global_bytes"], before)
        self.assertEqual(state.events, [])

    async def test_finished_stream_rejects_late_events(self):
        state = await stream_buffer.create("s1", "alice")
        await stream_buffer.append("s1", {"type": "done"})
        await stream_buffer.finish("s1")
        before = stream_buffer.stats()
        self.assertEqual(await stream_buffer.append("s1", {"type": "content", "content": "late"}), -1)
        self.assertEqual(state.next_seq, 1)
        self.assertEqual(stream_buffer.stats(), before)

    async def test_ack_waiting_on_deleted_state_preserves_other_stream_bytes(self):
        state = await stream_buffer.create("s1", "alice")
        other = await stream_buffer.create("s2", "alice")
        await stream_buffer.append("s1", {"type": "content", "content": "a"})
        await stream_buffer.append("s2", {"type": "content", "content": "b"})
        async with state.lock:
            pending = asyncio.create_task(stream_buffer.ack("s1", "alice", 0))
            await asyncio.sleep(0)
            await stream_buffer.delete("s1")
        self.assertIsNone(await pending)
        self.assertEqual(stream_buffer.stats()["global_bytes"], other.byte_count)

    async def test_reader_waiting_on_deleted_state_terminates(self):
        state = await stream_buffer.create("s1", "alice")
        async with state.lock:
            pending = asyncio.create_task(collect_reader("s1", -1))
            await asyncio.sleep(0)
            await stream_buffer.delete("s1")
        self.assertEqual(await asyncio.wait_for(pending, timeout=1), [])
        self.assertEqual(state.readers, {})

    async def asyncTearDown(self):
        for stream_id in [
            "s1", "s2", "owned", "ttl", "quota", "bytes", "cancel",
            "slow", "finish-full", "reader-one", "events",
            "slow-bytes",
        ]:
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

    async def test_slow_reader_is_bounded_and_disconnected_with_reason(self):
        original = stream_buffer.MAX_READER_QUEUE_EVENTS
        stream_buffer.MAX_READER_QUEUE_EVENTS = 2
        try:
            await stream_buffer.create("slow", "alice")
            reader = stream_buffer.reader("slow", -1)
            pending = asyncio.create_task(reader.__anext__())
            await asyncio.sleep(0)

            for index in range(3):
                await stream_buffer.append("slow", {"type": "content", "content": str(index)})

            overflow = await asyncio.wait_for(pending, timeout=1)
            self.assertEqual(overflow["type"], "resume_unavailable")
            self.assertEqual(overflow["reason"], "slow_reader")
            state = await stream_buffer.get("slow", "alice")
            self.assertEqual(state.readers, {})
            with self.assertRaises(StopAsyncIteration):
                await reader.__anext__()
        finally:
            stream_buffer.MAX_READER_QUEUE_EVENTS = original

    async def test_slow_reader_queue_is_also_bounded_by_bytes(self):
        original_events = stream_buffer.MAX_READER_QUEUE_EVENTS
        original_bytes = stream_buffer.MAX_READER_QUEUE_BYTES
        stream_buffer.MAX_READER_QUEUE_EVENTS = 100
        stream_buffer.MAX_READER_QUEUE_BYTES = 64
        try:
            await stream_buffer.create("slow-bytes", "alice")
            reader = stream_buffer.reader("slow-bytes", -1)
            pending = asyncio.create_task(reader.__anext__())
            await asyncio.sleep(0)

            await stream_buffer.append("slow-bytes", {"type": "content", "content": "x" * 200})

            overflow = await asyncio.wait_for(pending, timeout=1)
            self.assertEqual(overflow["type"], "resume_unavailable")
            self.assertEqual(overflow["reason"], "slow_reader")
            with self.assertRaises(StopAsyncIteration):
                await reader.__anext__()
        finally:
            stream_buffer.MAX_READER_QUEUE_EVENTS = original_events
            stream_buffer.MAX_READER_QUEUE_BYTES = original_bytes

    async def test_finish_then_delete_never_queue_full_when_reader_data_slots_are_full(self):
        original = stream_buffer.MAX_READER_QUEUE_EVENTS
        stream_buffer.MAX_READER_QUEUE_EVENTS = 2
        try:
            await stream_buffer.create("finish-full", "alice")
            reader = stream_buffer.reader("finish-full", -1)
            first = asyncio.create_task(reader.__anext__())
            await asyncio.sleep(0)

            await stream_buffer.append("finish-full", {"type": "content", "content": "a"})
            await stream_buffer.append("finish-full", {"type": "content", "content": "b"})
            await stream_buffer.finish("finish-full")
            await stream_buffer.delete("finish-full")

            self.assertEqual((await first)["content"], "a")
            remaining = [event async for event in reader]
            self.assertEqual([event["content"] for event in remaining], ["b"])
        finally:
            stream_buffer.MAX_READER_QUEUE_EVENTS = original

    async def test_reader_count_limit_rejects_extra_live_reader(self):
        original = stream_buffer.MAX_READERS_PER_STREAM
        stream_buffer.MAX_READERS_PER_STREAM = 1
        try:
            await stream_buffer.create("reader-one", "alice")
            first_reader = stream_buffer.reader("reader-one", -1)
            first_pending = asyncio.create_task(first_reader.__anext__())
            await asyncio.sleep(0)

            second_reader = stream_buffer.reader("reader-one", -1)
            rejected = await second_reader.__anext__()
            self.assertEqual(rejected["type"], "resume_unavailable")
            self.assertEqual(rejected["reason"], "reader_limit")
            with self.assertRaises(StopAsyncIteration):
                await second_reader.__anext__()

            first_pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first_pending
            await first_reader.aclose()
        finally:
            stream_buffer.MAX_READERS_PER_STREAM = original

    async def test_stored_event_count_is_bounded_even_for_tiny_events(self):
        original = stream_buffer.MAX_EVENTS_PER_STREAM
        stream_buffer.MAX_EVENTS_PER_STREAM = 2
        try:
            await stream_buffer.create("events", "alice")
            for index in range(5):
                await stream_buffer.append("events", {"type": "x", "value": index})
            await stream_buffer.finish("events")

            state = await stream_buffer.get("events", "alice")
            self.assertEqual(len(state.events), 2)
            self.assertTrue(state.truncated)
            replay = await collect_reader("events", -1)
            self.assertEqual(replay[0]["type"], "resume_unavailable")
            self.assertEqual(replay[0]["reason"], "quota")
        finally:
            stream_buffer.MAX_EVENTS_PER_STREAM = original


if __name__ == "__main__":
    unittest.main()
