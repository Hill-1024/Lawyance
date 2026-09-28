import assert from 'node:assert/strict';

import {
  ChatStreamResponseError,
  isRetryableResumeUnavailable,
  isSuccessfulChatStream,
  recordResumeAttempt,
  reduceChatStreamOutcome,
  RESUME_RETRY_LIMIT,
  RESUME_RETRY_MAX_DELAY_MS,
  resumeRetryDelayMs,
  SessionRunBarrier,
  shouldAckBufferedStream,
  shouldStartResumeAttempt,
  throwIfChatStreamFailed,
  type ChatStreamOutcome
} from '../frontend/src/lib/stream-run-guards';

const initialOutcome: ChatStreamOutcome = {
  status: 'streaming',
  seenDone: false
};

assert.equal(shouldAckBufferedStream(undefined, -1, 1000, true), false);
assert.equal(shouldAckBufferedStream(undefined, 10, 1000), true);
const lastAck = { seq: 10, at: 1000 };
assert.equal(shouldAckBufferedStream(lastAck, 10, 2000, true), false, '终态重渲染不能重复确认相同序号');
assert.equal(shouldAckBufferedStream(lastAck, 9, 2000, true), false);
assert.equal(shouldAckBufferedStream(lastAck, 11, 1100), false);
assert.equal(shouldAckBufferedStream(lastAck, 11, 1100, true), true, '新的终态序号应立即确认');
assert.equal(shouldAckBufferedStream(lastAck, 11, 1500), true);

const failedOutcome = reduceChatStreamOutcome(initialOutcome, {
  type: 'error',
  message: '上游模型失败'
});
const failedThenDone = reduceChatStreamOutcome(failedOutcome, { type: 'done' });
assert.equal(failedThenDone.status, 'error');
assert.equal(failedThenDone.seenDone, true);
assert.equal(failedThenDone.errorMessage, '上游模型失败');
assert.equal(isSuccessfulChatStream(failedThenDone), false);
assert.throws(
  () => throwIfChatStreamFailed(failedThenDone),
  (error: unknown) => error instanceof ChatStreamResponseError && error.message === '上游模型失败'
);

const successfulOutcome = reduceChatStreamOutcome(initialOutcome, { type: 'done' });
assert.equal(successfulOutcome.status, 'done');
assert.equal(isSuccessfulChatStream(successfulOutcome), true);

const barrier = new SessionRunBarrier();
let finishSessionA!: () => void;
const sessionACompletion = new Promise<void>(resolve => {
  finishSessionA = resolve;
});
barrier.beginClosing('session-a', sessionACompletion);

const waitingForA = barrier.waitFor('session-a');
assert.ok(waitingForA);
assert.equal(barrier.waitFor('session-b'), null, 'session A 的收尾不应阻塞 session B');

let sessionAReleased = false;
void waitingForA.then(() => {
  sessionAReleased = true;
});
await Promise.resolve();
assert.equal(sessionAReleased, false);

finishSessionA();
await waitingForA;
assert.equal(sessionAReleased, true);
await Promise.resolve();
assert.equal(barrier.waitFor('session-a'), null);

// resume_unavailable 分级：慢读/读者名额用满只是本读者被踢下线，缓冲仍在，可以重连；
// quota（缓冲被截断）与其未知原因才是真的取不回来，只能按不可续传收尾。
assert.equal(isRetryableResumeUnavailable('slow_reader'), true);
assert.equal(isRetryableResumeUnavailable('reader_limit'), true);
assert.equal(isRetryableResumeUnavailable('quota'), false);
assert.equal(isRetryableResumeUnavailable('unknown'), false);
assert.equal(isRetryableResumeUnavailable(undefined), false);
assert.equal(isRetryableResumeUnavailable(null), false);

// 本端已有活跃回答时任何续传都要让路：那条"断流"其实是我们自己正在接收的流。
assert.equal(
  shouldStartResumeAttempt({ now: 1000, attempt: undefined, hasActiveRun: true }),
  false,
  '本地有活跃流时不得续传'
);
assert.equal(
  shouldStartResumeAttempt({ now: 1000, attempt: undefined, hasActiveRun: false }),
  true,
  '本地空闲时首次续传立即发起'
);

// 失败后按退避等待，避免每次窗口聚焦/切回前台都重连一遍。
const firstAttempt = recordResumeAttempt(undefined, 1000);
assert.deepEqual(firstAttempt, { attempt: 1, lastAt: 1000 });
assert.equal(resumeRetryDelayMs(0), 0, '尚未尝试过时无需等待');
assert.equal(shouldStartResumeAttempt({ now: 1500, attempt: firstAttempt, hasActiveRun: false }), false);
assert.equal(shouldStartResumeAttempt({ now: 2000, attempt: firstAttempt, hasActiveRun: false }), true);

const secondAttempt = recordResumeAttempt(firstAttempt, 2000);
assert.equal(resumeRetryDelayMs(secondAttempt.attempt), 3000, '第二次失败后退避拉长');
assert.equal(shouldStartResumeAttempt({ now: 3000, attempt: secondAttempt, hasActiveRun: false }), false);
assert.equal(shouldStartResumeAttempt({ now: 5000, attempt: secondAttempt, hasActiveRun: false }), true);
assert.equal(resumeRetryDelayMs(RESUME_RETRY_LIMIT + 5), RESUME_RETRY_MAX_DELAY_MS, '退避有上限，不会退到无穷大');

// 预算耗尽后不再自动重连（调用方按不可续传收尾），否则每次切回前台都会重试一遍。
const exhausted = { attempt: RESUME_RETRY_LIMIT + 1, lastAt: 0 };
assert.equal(shouldStartResumeAttempt({ now: 10 ** 9, attempt: exhausted, hasActiveRun: false }), false);
assert.equal(
  shouldStartResumeAttempt({ now: 10 ** 9, attempt: { attempt: RESUME_RETRY_LIMIT, lastAt: 0 }, hasActiveRun: false }),
  true,
  '还剩预算时仍允许最后一次尝试'
);

console.log('stream/run guards: terminal error monotonicity, per-session closing isolation, resume policy passed');
