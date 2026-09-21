export type ChatStreamStatus = 'streaming' | 'done' | 'error';

/** 终态确认可跳过节流，但不能重复确认已发送的序号。 */
export const shouldAckBufferedStream = (
  last: { seq: number; at: number } | undefined,
  seq: number,
  now: number,
  force = false
) => seq >= 0 && (!last || (seq > last.seq && (force || now - last.at >= 500)));

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

/** 服务端 resume_unavailable 的原因，前端据此区分「重连即可」与「真的没得续」。 */
export type ResumeUnavailableReason = 'quota' | 'reader_limit' | 'slow_reader' | (string & {});

/**
 * 只有 reader_limit / slow_reader 表示"缓冲还在，只是这个读者被踢下线或名额用满"，
 * 重新接上即可继续；quota（缓冲已截断/未建立）与其未知原因才是真的取不回来。
 */
export const isRetryableResumeUnavailable = (reason: ResumeUnavailableReason | null | undefined) => (
  reason === 'slow_reader' || reason === 'reader_limit'
);

/** 一次续传尝试的退避状态：连续失败次数与上次发起时刻。 */
export type ResumeAttemptState = { attempt: number; lastAt: number };

/** 第 n 次失败后的等待：0（尚未尝试）→ 1s → 3s → 8s → 20s → 之后 30s。 */
export const RESUME_RETRY_DELAYS_MS = [0, 1000, 3000, 8000, 20000, 30_000] as const;
export const RESUME_RETRY_MAX_DELAY_MS = 30_000;
/** 连续「可重试」失败（每次都没有新内容）上限，超过则按不可续传收尾，避免无限重连。 */
export const RESUME_RETRY_LIMIT = 6;

export const resumeRetryDelayMs = (attempt: number) => {
  if (attempt <= 0) return 0;
  const index = Math.min(attempt, RESUME_RETRY_DELAYS_MS.length - 1);
  return RESUME_RETRY_DELAYS_MS[index] ?? RESUME_RETRY_MAX_DELAY_MS;
};

export const recordResumeAttempt = (
  previous: ResumeAttemptState | undefined,
  now: number
): ResumeAttemptState => ({ attempt: (previous?.attempt ?? 0) + 1, lastAt: now });

/**
 * 是否允许为某条消息发起续传。
 *
 * 判定顺序即优先级：
 * 1. 本地已有活跃回答（未停滞）时一律不续传——那说明这条"断流"其实是本端正在接收的流，
 *    续传只会把它打断并抢走停止按钮；原生流的 id 与服务端 turn_id 不同名，所以这里按
 *    "本地有没有在跑的流"判断，而不是按流 id 比对。
 * 2. 连续失败后按退避等待，避免每次窗口聚焦/切回前台都重试一遍。
 * 3. 连续失败次数超过上限则放弃（内容确实取不回来），交由调用方按不可续传收尾。
 */
export const shouldStartResumeAttempt = (options: {
  now: number;
  attempt: ResumeAttemptState | undefined;
  hasActiveRun: boolean;
}) => {
  if (options.hasActiveRun) return false;
  const attempt = options.attempt;
  if (!attempt) return true;
  if (attempt.attempt > RESUME_RETRY_LIMIT) return false;
  return options.now - attempt.lastAt >= resumeRetryDelayMs(attempt.attempt);
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
