import assert from 'node:assert/strict';

import {
  ChatStreamResponseError,
  isSuccessfulChatStream,
  reduceChatStreamOutcome,
  SessionRunBarrier,
  throwIfChatStreamFailed,
  type ChatStreamOutcome
} from '../src/lib/stream-run-guards';

const initialOutcome: ChatStreamOutcome = {
  status: 'streaming',
  seenDone: false
};

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

console.log('stream/run guards: terminal error monotonicity and per-session closing isolation passed');
