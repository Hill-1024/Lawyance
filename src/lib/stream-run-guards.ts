export type ChatStreamStatus = 'streaming' | 'done' | 'error';

export type ChatStreamOutcome = {
  status: ChatStreamStatus;
  seenDone: boolean;
  errorMessage?: string;
};

export type ChatStreamTerminalEvent =
  | { type: 'error'; message?: string }
  | { type: 'done' };

/**
 * SSE 的传输结束不等于业务成功。error 是单调终态：后续 done 只表示
 * 服务端已关闭流，不能把先前的业务错误覆盖成成功。
 */
export const reduceChatStreamOutcome = (
  current: ChatStreamOutcome,
  event: ChatStreamTerminalEvent
): ChatStreamOutcome => {
  if (event.type === 'error') {
    return {
      ...current,
      status: 'error',
      errorMessage: event.message?.trim() || current.errorMessage || '服务端处理失败。'
    };
  }

  return {
    ...current,
    seenDone: true,
    status: current.status === 'error' || current.errorMessage ? 'error' : 'done'
  };
};

export const isSuccessfulChatStream = (outcome: ChatStreamOutcome) => (
  outcome.seenDone && outcome.status === 'done' && !outcome.errorMessage
);

export class ChatStreamResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatStreamResponseError';
  }
}

export const throwIfChatStreamFailed = (outcome: ChatStreamOutcome) => {
  if (outcome.errorMessage) {
    throw new ChatStreamResponseError(outcome.errorMessage);
  }
};

/**
 * 按 session 隔离异步收尾。等待同一 session 的旧任务完成，但不会阻塞
 * 其他 session 启动；若同一 session 出现多个收尾任务，则等待全部完成。
 */
export class SessionRunBarrier {
  private readonly closingRuns = new Map<string, Promise<void>>();

  beginClosing(sessionId: string, completion: Promise<void>) {
    const previous = this.closingRuns.get(sessionId);
    const barrier = previous
      ? Promise.all([previous, completion]).then(() => undefined)
      : completion;

    this.closingRuns.set(sessionId, barrier);
    void barrier.then(() => {
      if (this.closingRuns.get(sessionId) === barrier) {
        this.closingRuns.delete(sessionId);
      }
    });
  }

  waitFor(sessionId: string): Promise<void> | null {
    return this.closingRuns.get(sessionId) || null;
  }
}
