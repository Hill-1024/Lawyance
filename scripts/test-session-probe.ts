import assert from 'node:assert/strict';

/*
 * 回归用例（T1）：/api/session 的登录态探测不得把瞬态失败判成「未登录」。
 * 429/5xx/网络抛错必须退避重试一次；仍不可用就抛 SessionProbeUnavailableError，
 * 让调用方保持当前登录态——只有 401（和 200 响应体里的 authenticated:false）
 * 才允许得到 authenticated:false 的结论。
 */

import { fetchSession, SessionProbeUnavailableError, type SessionProbe } from '../frontend/src/services/api';

type FetchStub = (input: string, init?: RequestInit) => Promise<{
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}>;

const stubFetch = (impl: FetchStub) => {
  (globalThis as { fetch: unknown }).fetch = async (input: string, init?: RequestInit) =>
    impl(String(input), init);
};

const respond = (status: number, body?: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

// ── 200：以响应体为准 ────────────────────────────────────────────────
{
  let calls = 0;
  stubFetch(() => {
    calls += 1;
    return Promise.resolve(respond(200, { authenticated: true, username: 'uitest', role: 'user' }));
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, true);
  assert.equal(probe.username, 'uitest');
  assert.equal(calls, 1, '「仍登录」结论直接可信，不应复核');
}
{
  let calls = 0;
  stubFetch(() => {
    calls += 1;
    return Promise.resolve(respond(200, { authenticated: false }));
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, false, '服务端连续两次说未登录才是未登录');
  assert.equal(calls, 2, '「未登录」结论必须复核一次');
}
{
  // 单次误报（200:false 后紧接 200:true，如代理/多节点抖动）：以较新结论为准，不得假登出。
  const bodies = [{ authenticated: false }, { authenticated: true, username: 'uitest', role: 'user' }];
  stubFetch(() => Promise.resolve(respond(200, bodies.shift() ?? { authenticated: true })));
  const probe = await fetchSession();
  assert.equal(probe.authenticated, true, '单次 authenticated:false 被复核翻案时应保持登录态');
}

// ── 401：确定未登录，不再重试，但要复核一次 ──────────────────────────
{
  let calls = 0;
  stubFetch(() => {
    calls += 1;
    return Promise.resolve(respond(401, { detail: 'Not authenticated' }));
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, false);
  assert.equal(calls, 2, '401 是确定结论，不退避重试，但需复核一次');
}
{
  // 单次 401 误报后恢复：保持登录态。
  let first = true;
  stubFetch(() => {
    if (first) {
      first = false;
      return Promise.resolve(respond(401, { detail: 'Not authenticated' }));
    }
    return Promise.resolve(respond(200, { authenticated: true, username: 'uitest', role: 'user' }));
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, true, '单次 401 误报被复核翻案时应保持登录态');
}

// ── 429：瞬态，退避重试一次后恢复 ────────────────────────────────────
{
  const statuses = [429, 200];
  const seen: number[] = [];
  stubFetch(() => {
    const status = statuses[seen.length] ?? 200;
    seen.push(status);
    return Promise.resolve(
      status === 429
        ? respond(429, 'Rate limit exceeded')
        : respond(200, { authenticated: true, username: 'uitest', role: 'user' }),
    );
  });
  const probe: SessionProbe = await fetchSession();
  assert.deepEqual(seen, [429, 200], '429 后应恰好重试一次');
  assert.equal(probe.authenticated, true, '限流窗口里的刷新不得假登出');
}

// ── 5xx / 网络抛错：同样按瞬态处理 ──────────────────────────────────
{
  const statuses = [503, 200];
  stubFetch(() => {
    const status = statuses.shift() ?? 200;
    return Promise.resolve(
      status === 503
        ? respond(503, 'upstream error')
        : respond(200, { authenticated: true, username: 'uitest', role: 'user' }),
    );
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, true);
}
{
  const attempts: string[] = [];
  stubFetch((input) => {
    attempts.push(input);
    if (attempts.length === 1) throw new TypeError('Failed to fetch');
    return Promise.resolve(respond(200, { authenticated: true, username: 'uitest', role: 'user' }));
  });
  const probe = await fetchSession();
  assert.equal(probe.authenticated, true, '网络瞬断后恢复的探测应生效');
  assert.equal(attempts.length, 2);
}

// ── 持续瞬态失败：抛专用错误（调用方保持登录态），而不是 authenticated:false ──
{
  let calls = 0;
  stubFetch(() => {
    calls += 1;
    return Promise.resolve(respond(429, 'Rate limit exceeded'));
  });
  await assert.rejects(
    fetchSession(),
    (error: unknown) => error instanceof SessionProbeUnavailableError,
    '持续 429 不得返回 authenticated:false',
  );
  assert.equal(calls, 2, '重试恰好一次后放弃');
}

console.log('test-session-probe: all assertions passed');
