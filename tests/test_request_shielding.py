"""
模块描述：请求防护回归测试，覆盖布隆过滤器、共享限流与 Redis 降级路径。

重点验证两条不能被破坏的性质：
1. 布隆过滤器绝不允许假阴性——未就绪、键被淘汰、Redis 报错时都必须放行；
2. Redis 只能加速和共享状态，不可用时限流必须继续生效，只是退回进程内计数。
"""

import importlib
import os
import shutil
import sys
import tempfile
import time
import unittest

from starlette.requests import Request
from starlette.responses import Response

try:
    import fakeredis
except ImportError:  # pragma: no cover - 测试环境未安装 fakeredis 时跳过 Redis 分支
    fakeredis = None


TEST_SECRET = "y" * 32


def purge_runtime_modules():
    # services 包本身也要清掉：只删子模块时，包对象上残留的旧属性会让
    # `from services import x` 拿到上一次的模块对象，测试里的 patch 就会打空。
    for name in list(sys.modules):
        if (
            name in {"agent", "app_factory", "auth", "services", "infra"}
            or name.startswith("routes.")
            or name.startswith("services.") or name.startswith("infra.")
        ):
            sys.modules.pop(name, None)


class ShieldTestBase(unittest.TestCase):
    """每个用例都在临时 data 目录和干净的模块状态下运行。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "SECRET_KEY",
                "INITIAL_ADMIN_PASSWORD",
                "LAWVER_DATA_DIR",
                "LAWVER_REDIS_URL",
                "REDIS_URL",
                "LAWVER_RATE_LIMIT_ENABLED",
                "LAWVER_API_RATE_LIMIT",
                "LAWVER_LOGIN_RATE_LIMIT",
                "LAWVER_BLOOM_ENABLED",
                "LAWVER_BLOOM_SESSION_CAPACITY",
                "LAWVER_BLOOM_ERROR_RATE",
            )
        }
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        for key in ("LAWVER_REDIS_URL", "REDIS_URL"):
            os.environ.pop(key, None)
        purge_runtime_modules()

    def tearDown(self):
        # 先归还共享状态再清模块引用，避免残留的客户端/计数影响后续用例。
        rate_limit = sys.modules.get("services.rate_limit")
        if rate_limit is not None:
            rate_limit.reset()
        redis_backend = sys.modules.get("infra.redis_backend")
        if redis_backend is not None:
            redis_backend.reset()
        purge_runtime_modules()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)


class LocalBloomFilterTests(ShieldTestBase):
    def test_no_false_negatives_for_inserted_items(self):
        bloom = importlib.import_module("infra.bloom")
        filter_ = bloom.LocalBloomFilter(capacity=5_000, error_rate=0.01)
        items = [f"sid-{index}" for index in range(5_000)]
        filter_.warm(items)

        for item in items:
            self.assertTrue(filter_.maybe_contains(item), item)

    def test_unwarmed_filter_fails_open(self):
        bloom = importlib.import_module("infra.bloom")
        filter_ = bloom.LocalBloomFilter(capacity=100, error_rate=0.01)

        self.assertTrue(filter_.needs_warm())
        # 预热前没有资格判定「不存在」，否则会误杀全部有效会话。
        self.assertTrue(filter_.maybe_contains("anything"))
        filter_.warm(["known"])
        self.assertFalse(filter_.needs_warm())

    def test_unknown_items_are_rejected_within_configured_error_rate(self):
        bloom = importlib.import_module("infra.bloom")
        filter_ = bloom.LocalBloomFilter(capacity=2_000, error_rate=0.01)
        filter_.warm([f"member-{index}" for index in range(2_000)])

        probed = [f"absent-{index}" for index in range(2_000)]
        rejected = sum(1 for item in probed if not filter_.maybe_contains(item))
        false_positive_rate = 1 - rejected / len(probed)
        # 配置值 1%，统计波动下给 5% 的宽松上界，只用来挡住实现退化。
        self.assertLess(false_positive_rate, 0.05)

    def test_disabled_switch_returns_null_filter(self):
        os.environ["LAWVER_BLOOM_ENABLED"] = "0"
        bloom = importlib.import_module("infra.bloom")
        filter_ = bloom.create("session", capacity=100, error_rate=0.01)

        self.assertEqual(filter_.backend, "disabled")
        self.assertTrue(filter_.maybe_contains("nope"))
        self.assertEqual(filter_.add("nope"), False)


@unittest.skipIf(fakeredis is None, "fakeredis not installed")
class RedisBloomFilterTests(ShieldTestBase):
    def _filter(self):
        bloom = importlib.import_module("infra.bloom")
        self.fake = fakeredis.FakeStrictRedis(decode_responses=True)
        return bloom.create("session", capacity=1_000, error_rate=0.01, client=self.fake)

    def test_membership_after_warm(self):
        filter_ = self._filter()
        self.assertEqual(filter_.backend, "redis")
        self.assertEqual(filter_.warm(["sid-1", "sid-2"]), 2)

        self.assertTrue(filter_.maybe_contains("sid-1"))
        self.assertFalse(filter_.maybe_contains("sid-absent"))
        self.assertFalse(filter_.needs_warm())

    def test_fails_open_before_warm(self):
        filter_ = self._filter()
        # 未就绪时位图与就绪标记都不存在，任何判断都必须交给权威存储。
        self.assertTrue(filter_.maybe_contains("sid-absent"))

    def test_fails_open_when_bitset_is_evicted(self):
        filter_ = self._filter()
        filter_.warm(["sid-1"])
        self.fake.delete("lawver:bloom:session")

        self.assertTrue(filter_.maybe_contains("sid-1"))
        self.assertTrue(filter_.needs_warm())

    def test_fails_open_when_ready_marker_is_evicted(self):
        filter_ = self._filter()
        filter_.warm(["sid-1"])
        self.fake.delete("lawver:bloom:session:ready")

        # 位图可能只写了一半，此时不能信任「不存在」。
        self.assertTrue(filter_.maybe_contains("sid-1"))
        self.assertTrue(filter_.needs_warm())

    def test_add_persists_new_members(self):
        filter_ = self._filter()
        filter_.warm(["sid-1"])
        self.assertTrue(filter_.add("sid-2"))

        self.assertTrue(filter_.maybe_contains("sid-2"))

    def test_fails_open_when_redis_errors(self):
        bloom = importlib.import_module("infra.bloom")

        class BrokenRedis:
            def pipeline(self, transaction=False):
                raise RuntimeError("redis down")

        filter_ = bloom.RedisBloomFilter("session", BrokenRedis(), 1_000, 0.01)
        self.assertTrue(filter_.maybe_contains("sid-1"))
        self.assertFalse(filter_.add("sid-1"))


class RateLimitTests(ShieldTestBase):
    def test_local_window_enforces_limit_and_resets(self):
        rate_limit = importlib.import_module("services.rate_limit")
        now = 1_000.0

        self.assertTrue(rate_limit.hit("api", "ip", limit=2, window_seconds=60, now=now).allowed)
        self.assertTrue(rate_limit.hit("api", "ip", limit=2, window_seconds=60, now=now).allowed)
        blocked = rate_limit.hit("api", "ip", limit=2, window_seconds=60, now=now)
        self.assertFalse(blocked.allowed)
        self.assertGreaterEqual(blocked.retry_after, 1)

        # 窗口结束后重新放行，且不同 IP 互不影响。
        self.assertTrue(rate_limit.hit("api", "ip", limit=2, window_seconds=60, now=now + 61).allowed)
        self.assertTrue(rate_limit.hit("api", "other", limit=2, window_seconds=60, now=now).allowed)

    def test_limit_zero_and_disabled_switch_allow_everything(self):
        rate_limit = importlib.import_module("services.rate_limit")

        for _ in range(5):
            self.assertTrue(rate_limit.hit("api", "ip", limit=0, window_seconds=60).allowed)

        os.environ["LAWVER_RATE_LIMIT_ENABLED"] = "0"
        for _ in range(5):
            self.assertTrue(rate_limit.hit("api", "ip", limit=1, window_seconds=60).allowed)

    def test_falls_back_to_local_when_redis_errors(self):
        rate_limit = importlib.import_module("services.rate_limit")
        calls = {"pipeline": 0}

        class BrokenRedis:
            def pipeline(self, transaction=False):
                calls["pipeline"] += 1
                raise RuntimeError("redis down")

        provider = rate_limit.redis_backend
        original = provider.get_client
        provider.get_client = lambda: BrokenRedis()
        try:
            rate_limit.reset()
            self.assertTrue(rate_limit.hit("api", "ip", limit=1, window_seconds=60).allowed)
            self.assertFalse(rate_limit.hit("api", "ip", limit=1, window_seconds=60).allowed)
        finally:
            provider.get_client = original

        # 先确认 Redis 路径确实被尝试过，再确认降级后限流仍然生效。
        self.assertGreaterEqual(calls["pipeline"], 1)


@unittest.skipIf(fakeredis is None, "fakeredis not installed")
class RedisRateLimitTests(ShieldTestBase):
    def test_redis_counter_sets_ttl_and_enforces_limit(self):
        rate_limit = importlib.import_module("services.rate_limit")
        fake = fakeredis.FakeStrictRedis(decode_responses=True)

        provider = rate_limit.redis_backend
        original = provider.get_client
        provider.get_client = lambda: fake
        try:
            self.assertTrue(rate_limit.hit("api", "1.2.3.4", limit=2, window_seconds=60).allowed)
            self.assertTrue(rate_limit.hit("api", "1.2.3.4", limit=2, window_seconds=60).allowed)
            self.assertFalse(rate_limit.hit("api", "1.2.3.4", limit=2, window_seconds=60).allowed)

            key = f"{provider.prefix()}:rl:api:1.2.3.4"
            self.assertGreater(fake.ttl(key), 0)
            self.assertEqual(int(fake.get(key)), 3)

            # 不同 IP 使用独立计数键。
            self.assertTrue(rate_limit.hit("api", "5.6.7.8", limit=2, window_seconds=60).allowed)
        finally:
            provider.get_client = original


class RedisBackendTests(ShieldTestBase):
    def test_unconfigured_returns_no_client(self):
        redis_backend = importlib.import_module("infra.redis_backend")

        self.assertFalse(redis_backend.is_configured())
        self.assertIsNone(redis_backend.get_client())
        self.assertFalse(redis_backend.status()["available"])

    def test_malformed_url_degrades_without_raising(self):
        redis_backend = importlib.import_module("infra.redis_backend")
        os.environ["LAWVER_REDIS_URL"] = "http://not-a-redis-url"

        self.assertIsNone(redis_backend.get_client())
        self.assertFalse(redis_backend.status()["available"])

    def test_unreachable_server_degrades_quickly(self):
        redis_backend = importlib.import_module("infra.redis_backend")
        os.environ["LAWVER_REDIS_URL"] = "redis://127.0.0.1:6399/0"

        started = time.time()
        self.assertIsNone(redis_backend.get_client())
        self.assertLess(time.time() - started, 5)
        # 冷却窗口内不再重试连接。
        self.assertIsNone(redis_backend.get_client())


class MiddlewareShieldTests(ShieldTestBase, unittest.IsolatedAsyncioTestCase):
    def _request(self, path, method="POST", client="198.51.100.30", read_body=True):
        async def receive():
            if not read_body:
                raise AssertionError("rate-limited requests must not read the body")
            return {"type": "http.request", "body": b"", "more_body": False}

        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"origin", b"http://localhost:5173"),
                ],
                "client": (client, 1234),
                "server": ("localhost", 80),
            },
            receive,
        )

    async def _call(self, app_security, request):
        async def call_next(_request):
            return Response("ok")

        return await app_security.security_and_logging_middleware(request, call_next)

    async def test_general_bucket_returns_429_with_retry_after(self):
        app_security = importlib.import_module("services.app_security")
        rate_limit = importlib.import_module("services.rate_limit")
        rate_limit.reset()
        app_security.RATE_LIMIT = 2

        self.assertEqual((await self._call(app_security, self._request("/api/chat"))).status_code, 200)
        self.assertEqual((await self._call(app_security, self._request("/api/chat"))).status_code, 200)
        # 被限流的请求在读取请求体之前就该返回。
        blocked = await self._call(
            app_security, self._request("/api/chat", read_body=False)
        )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.body, b"Rate limit exceeded")
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)

    async def test_login_bucket_is_stricter_than_general_bucket(self):
        app_security = importlib.import_module("services.app_security")
        rate_limit = importlib.import_module("services.rate_limit")
        rate_limit.reset()
        app_security.RATE_LIMIT = 100
        app_security.LOGIN_RATE_LIMIT = 1

        self.assertEqual((await self._call(app_security, self._request("/api/login"))).status_code, 200)
        blocked = await self._call(app_security, self._request("/api/login", read_body=False))
        self.assertEqual(blocked.status_code, 429)

        # 登录桶被限流不影响同 IP 访问其他接口。
        self.assertEqual((await self._call(app_security, self._request("/api/chat"))).status_code, 200)

    async def test_options_and_non_api_paths_are_not_counted(self):
        app_security = importlib.import_module("services.app_security")
        rate_limit = importlib.import_module("services.rate_limit")
        rate_limit.reset()
        app_security.RATE_LIMIT = 1

        for _ in range(3):
            response = await self._call(app_security, self._request("/assets/app.js", method="GET"))
            self.assertEqual(response.status_code, 200)
            response = await self._call(app_security, self._request("/api/chat", method="OPTIONS"))
            self.assertEqual(response.status_code, 200)


class VerifyTokenBloomTests(ShieldTestBase):
    def setUp(self):
        super().setUp()
        self.auth = importlib.import_module("auth")
        self.auth_store = importlib.import_module("infra.auth_store")
        # auth 必须绑定到同一个 store 对象，否则下面的 patch 会打空、断言失去意义。
        self.assertIs(self.auth.auth_store, self.auth_store)

    def test_unknown_sid_is_rejected_without_touching_storage(self):
        ok, _, sid, _ = self.auth.create_session("admin", client="web")
        self.assertTrue(ok)
        self.auth.warm_session_bloom()
        token = self.auth.create_token("admin", sid)
        self.assertEqual(self.auth.verify_token(token), "admin")

        calls = {"get_session": 0}
        original = self.auth_store.get_session

        def spy(session_id):
            calls["get_session"] += 1
            return original(session_id)

        self.auth_store.get_session = spy
        try:
            bogus = self.auth.create_token("admin", "not-a-real-sid")
            self.assertIsNone(self.auth.verify_token(bogus))
        finally:
            self.auth_store.get_session = original

        self.assertEqual(calls["get_session"], 0)

    def test_logout_of_unknown_sid_skips_the_write_transaction(self):
        self.auth.warm_session_bloom()
        touched = {"revoke": 0}
        original = self.auth_store.revoke_session

        def spy(session_id):
            touched["revoke"] += 1
            return original(session_id)

        self.auth_store.revoke_session = spy
        try:
            bogus = self.auth.create_token("admin", "ghost-sid")
            self.assertFalse(self.auth.revoke_token_session(bogus))
        finally:
            self.auth_store.revoke_session = original

        self.assertEqual(touched["revoke"], 0)

    def test_revoked_session_is_still_rejected_after_warm(self):
        ok, _, sid, _ = self.auth.create_session("admin", client="web")
        self.assertTrue(ok)
        self.auth.warm_session_bloom()
        token = self.auth.create_token("admin", sid)
        self.assertEqual(self.auth.verify_token(token), "admin")

        self.auth.revoke_token_session(token)
        # 位图只增不删，撤销后的 sid 仍可能在位图里，必须由数据库最终裁决。
        self.assertIsNone(self.auth.verify_token(token))

    def test_warm_rebuild_covers_sessions_created_before_the_filter(self):
        ok, _, sid, _ = self.auth.create_session("admin", client="web")
        self.assertTrue(ok)
        # 模拟进程重启：丢掉内存过滤器，只用数据库里的有效会话重建。
        self.auth._session_bloom = None
        self.auth.warm_session_bloom()

        token = self.auth.create_token("admin", sid)
        self.assertEqual(self.auth.verify_token(token), "admin")
        self.assertTrue(self.auth.bloom_status()["ready"])

    def test_disabled_bloom_keeps_authentication_working(self):
        os.environ["LAWVER_BLOOM_ENABLED"] = "0"
        self.auth._session_bloom = None

        ok, _, sid, _ = self.auth.create_session("admin", client="web")
        self.assertTrue(ok)
        self.assertEqual(self.auth.bloom_status()["backend"], "disabled")

        token = self.auth.create_token("admin", sid)
        self.assertEqual(self.auth.verify_token(token), "admin")
        self.assertIsNone(self.auth.verify_token(self.auth.create_token("admin", "nope")))


@unittest.skipIf(fakeredis is None, "fakeredis not installed")
class AuthSharedBloomTests(ShieldTestBase):
    def test_verify_token_uses_the_shared_bitmap(self):
        auth = importlib.import_module("auth")
        provider = importlib.import_module("infra.redis_backend")
        fake = fakeredis.FakeStrictRedis(decode_responses=True)

        original = provider.get_client
        provider.get_client = lambda: fake
        try:
            auth._session_bloom = None
            self.assertEqual(auth.bloom_status()["backend"], "redis")

            # add 会先建出位图但没写就绪标记：这种半成品绝不能用来判定「不存在」。
            ok, _, sid, _ = auth.create_session("admin", client="web")
            self.assertTrue(ok)
            self.assertTrue(fake.exists("lawver:bloom:session"))
            self.assertFalse(fake.exists("lawver:bloom:session:ready"))
            self.assertEqual(auth.verify_token(auth.create_token("admin", sid)), "admin")

            auth.warm_session_bloom()
            self.assertTrue(fake.exists("lawver:bloom:session:ready"))
            self.assertEqual(auth.verify_token(auth.create_token("admin", sid)), "admin")
            self.assertIsNone(auth.verify_token(auth.create_token("admin", "ghost-sid")))
        finally:
            provider.get_client = original
            auth._session_bloom = None


class StartupShieldingTests(ShieldTestBase):
    def test_prepare_request_shielding_warms_bloom_when_redis_is_down(self):
        app_factory = importlib.import_module("app_factory")
        auth = importlib.import_module("auth")
        redis_backend = importlib.import_module("infra.redis_backend")
        self.assertIs(app_factory.auth_service, auth)

        os.environ["LAWVER_REDIS_URL"] = "redis://127.0.0.1:6399/0"
        redis_backend.reset()

        calls = []
        original = auth.warm_session_bloom
        auth.warm_session_bloom = lambda: (calls.append(1), 0)[1]
        try:
            # Redis 连不上时启动流程也必须跑完，只是退回进程内过滤器。
            app_factory._prepare_request_shielding()
        finally:
            auth.warm_session_bloom = original

        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
