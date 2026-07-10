"""
模块描述：SSE 心跳包装的背压与取消回归测试。
"""

import asyncio
import unittest

from routes.chat import HEARTBEAT_QUEUE_MAX_CHUNKS, _with_heartbeat


class ChatHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_consumer_backpressures_source_instead_of_buffering_all_chunks(self):
        produced = 0
        source_closed = asyncio.Event()

        async def source():
            nonlocal produced
            try:
                for index in range(1000):
                    produced += 1
                    yield str(index)
            finally:
                source_closed.set()

        wrapped = _with_heartbeat(source())
        self.assertEqual(await wrapped.__anext__(), "0")
        await asyncio.sleep(0.05)

        self.assertLessEqual(produced, HEARTBEAT_QUEUE_MAX_CHUNKS + 2)
        await wrapped.aclose()
        await asyncio.wait_for(source_closed.wait(), timeout=1)


if __name__ == "__main__":
    unittest.main()
