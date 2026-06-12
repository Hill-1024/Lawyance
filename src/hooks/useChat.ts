/*
 * 模块描述：聊天状态 Hook，管理会话、消息、发送流程、编辑/撤回和对话级记忆同步。
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import type { BackendHistoryMessage, ContextUsage, Conversation, ConversationMemory, Message, ThoughtBlock, UserChoiceRequest } from '../types';
import { fileDB } from '../lib/db';
import { getAuthToken } from '../lib/auth-storage';
import { isNative, isNativeAndroid } from '../lib/platform';
import { NativeStream, requestNativeStreamNotificationPermission, type NativeStreamEvent } from '../lib/native-stream';
import { getResumeEnabled, notifyResumeEnabledChanged, setResumeEnabled, subscribeResumeEnabled } from '../lib/resume-prefs';
import {
  ackStream,
  apiUrl,
  buildChatRequestBody,
  cancelStream,
  chat,
  deleteWorkspace,
  MemoryRevisionConflictError,
  resumeStream,
  StreamExpiredError,
  summarizeTitle,
  syncConversationMemory
} from '../services/api';
import { addLocalStorageDataChangeListener } from '../services/storageEvents';
import { useAppDialog } from '../contexts/DialogContext';

const generateUUID = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
};

const GREETING_MESSAGE = `您好，我是 **Lawver**，由 **工大法智团队** 开发的专业法律AI助手。

## 我的核心能力：
- 法律检索：精准查询法律法规条文、司法解释及经典判例
- 案例分析：基于事实进行多维度法律分析（民事、行政、刑事）
- 合同审查：支持PDF与Word文档的批注、修改及风险识别
- 专业咨询：为律师及法律从业者提供客观、严谨的法律分析意见

## 我的工作原则：
- 客观中立 — 不讨好顺从，基于事实与法条进行专业判断
- 细节导向 — 不遗漏任何可能影响案件走向的关键细节
- 多维分析 — 综合考虑程序与实体、攻防双方的立场
- 信源可溯 — 所有法条与案例均提供权威出处
请问有什么法律问题需要我协助分析？`;

const CONTEXT_COMPRESSION_THRESHOLD_TOKENS = 500000;
const HISTORY_COMPRESSION_STATUS = '正在整理较早上下文';
const CJK_CHAR_PATTERN = /[\u3400-\u9fff\uf900-\ufaff]/g;
const STREAM_COMMIT_THROTTLE_MS = 48;
const NATIVE_DRAIN_BATCH_SIZE = 128;
const NATIVE_STREAM_SESSIONS_KEY = 'lawver:native-stream-sessions';
const NATIVE_STREAM_SESSION_TTL_MS = 60 * 60 * 1000;

type NativeStreamSessionRecord = {
  streamId: string;
  convId: string;
  messageId: string;
  createdAt: string;
};

const isAbortError = (error: unknown) => (
  typeof error === 'object' &&
  error !== null &&
  'name' in error &&
  (error as { name?: string }).name === 'AbortError'
);

const readNativeStreamSessions = (): NativeStreamSessionRecord[] => {
  try {
    const raw = localStorage.getItem(NATIVE_STREAM_SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const now = Date.now();
    return parsed.filter((item): item is NativeStreamSessionRecord => {
      if (!item || typeof item !== 'object') return false;
      const record = item as NativeStreamSessionRecord;
      if (!record.streamId || !record.convId || !record.messageId || !record.createdAt) return false;
      const createdAt = Date.parse(record.createdAt);
      return Number.isFinite(createdAt) && now - createdAt <= NATIVE_STREAM_SESSION_TTL_MS;
    });
  } catch {
    return [];
  }
};

const writeNativeStreamSessions = (records: NativeStreamSessionRecord[]) => {
  try {
    localStorage.setItem(NATIVE_STREAM_SESSIONS_KEY, JSON.stringify(records));
  } catch (error) {
    console.warn('Failed to persist native stream sessions:', error);
  }
};

const rememberNativeStreamSession = (record: NativeStreamSessionRecord) => {
  const records = readNativeStreamSessions().filter(item =>
    item.streamId !== record.streamId && item.messageId !== record.messageId
  );
  records.push(record);
  writeNativeStreamSessions(records);
};

const forgetNativeStreamSession = (streamId: string) => {
  const records = readNativeStreamSessions().filter(item => item.streamId !== streamId);
  writeNativeStreamSessions(records);
};

const normalizeBackendMessage = (msg: Partial<Message> | BackendHistoryMessage): BackendHistoryMessage | null => {
  const rawRole = (msg.role as string) || '';
  const role = rawRole === 'agent' ? 'assistant' : rawRole;
  if (!['user', 'assistant', 'tool', 'system'].includes(role)) return null;

  const normalized: BackendHistoryMessage = {
    role: role as BackendHistoryMessage['role'],
    content: typeof msg.content === 'string' ? msg.content : ''
  };

  if ('tool_calls' in msg && msg.tool_calls) {
    normalized.tool_calls = msg.tool_calls;
  }
  if ('tool_call_id' in msg && msg.tool_call_id) {
    normalized.tool_call_id = msg.tool_call_id;
  }
  if ('name' in msg && msg.name) {
    normalized.name = msg.name;
  }
  if (normalized.role === 'tool' && !normalized.tool_call_id) {
    return null;
  }
  return normalized;
};

const formatHistoryForBackend = (messages: Message[]) => {
  return messages.flatMap(msg => {
    const formatted: BackendHistoryMessage[] = [];
    for (const contextMessage of msg.context_messages || []) {
      const normalized = normalizeBackendMessage(contextMessage);
      if (normalized) formatted.push(normalized);
    }

    const normalized = normalizeBackendMessage(msg);
    if (normalized) formatted.push(normalized);
    return formatted;
  });
};

const estimateTextTokens = (value: unknown): number => {
  const text = typeof value === 'string' ? value : String(value ?? '');
  if (!text) return 0;
  const cjkMatches = text.match(CJK_CHAR_PATTERN);
  const cjkCount = cjkMatches?.length ?? 0;
  const nonCjk = text.replace(CJK_CHAR_PATTERN, '').replace(/\s+/g, ' ');
  return cjkCount + Math.ceil(nonCjk.length / 4);
};

const estimateBackendMessageTokens = (message: BackendHistoryMessage): number => {
  let total = 4 + estimateTextTokens(message.role) + estimateTextTokens(message.content);
  if (message.name) total += estimateTextTokens(message.name);
  if (message.tool_call_id) total += estimateTextTokens(message.tool_call_id);
  if (message.tool_calls) total += estimateTextTokens(JSON.stringify(message.tool_calls));
  return total;
};

const estimateRequestContextTokens = (history: BackendHistoryMessage[], messageContent: string): number => (
  3 + history.reduce((total, message) => total + estimateBackendMessageTokens(message), 0) + estimateTextTokens(messageContent)
);

const appendThoughtBlock = (
  blocks: ThoughtBlock[],
  content: string,
  blockType: ThoughtBlock['type'],
  blockId: string,
  shouldAppend: boolean
) => {
  if (!content) return blocks;

  const lastBlock = blocks[blocks.length - 1];
  if (shouldAppend && lastBlock && lastBlock.type === blockType) {
    return [
      ...blocks.slice(0, -1),
      { ...lastBlock, content: `${lastBlock.content}${content}` }
    ];
  }

  return [
    ...blocks,
    {
      id: blockId,
      type: blockType,
      content
    }
  ];
};

const normalizeUserChoiceRequest = (raw: any): UserChoiceRequest | null => {
  const source = raw && typeof raw === 'object' && 'content' in raw ? raw.content : raw;
  if (!source || typeof source !== 'object') return null;

  const question = String(source.question || '').trim();
  if (!question) return null;

  const rawOptions = Array.isArray(source.options) ? source.options : [];
  const options = rawOptions.flatMap((option: any, index: number) => {
    if (option && typeof option === 'object') {
      const label = String(option.label || option.value || '').trim();
      if (!label) return [];
      return [{
        id: String(option.id || `option_${index + 1}`),
        label,
        value: String(option.value || label),
        ...(option.description ? { description: String(option.description) } : {})
      }];
    }
    const label = String(option || '').trim();
    if (!label) return [];
    return [{ id: `option_${index + 1}`, label, value: label }];
  });

  return {
    id: String(source.id || `choice_${Date.now()}`),
    question,
    options,
    allow_free_text: source.allow_free_text !== false,
    allow_ignore: source.allow_ignore !== false,
    free_text_label: String(source.free_text_label || '自定义'),
    ignore_label: String(source.ignore_label || '忽略此问题'),
    ignore_value: String(source.ignore_value || '忽略此问题，请根据现有信息自行判断并继续。'),
  };
};

const createEmptyConversationMemory = (conversationId: string): ConversationMemory => {
  const now = new Date().toISOString();
    return {
      version: 1,
      revision: 0,
      scope: {
      type: 'conversation',
      future_user_scope: null
    },
    conversation_id: conversationId,
    events: [],
    facts: [],
    focus: [],
    updated_at: now,
    last_synced_at: now
  };
};

/** 把原生服务回传的 "HTTP <status>: <body>" 错误解析成结构化错误，使记忆冲突能与 Web 路径一致地重试。 */
const parseHttpStreamError = (raw: string): Error => {
  const match = /^HTTP (\d+):\s*([\s\S]*)$/.exec(raw || '');
  if (match) {
    const status = Number(match[1]);
    let parsed: any = null;
    try { parsed = JSON.parse(match[2]); } catch { /* 非 JSON 错误体 */ }
    const detail = parsed?.detail ?? parsed;
    if (status === 409 && detail?.error === 'memory_revision_conflict') {
      return new MemoryRevisionConflictError(detail);
    }
    const message = (typeof detail === 'string' ? detail : detail?.detail || detail?.error) || raw;
    return new Error(message);
  }
  return new Error(raw || '原生流式请求失败');
};

/**
 * 在渲染任何内容之前判定原生流的 HTTP 层结果：
 * 一旦有 SSE 事件到达即视为正常流（drain 为非消费式，processStream 仍可从头重放）；
 * 若在没有任何事件的情况下就 done，则视为 HTTP 层失败（如 409 记忆冲突），交上层识别并重试。
 */
const waitForNativeStreamHead = async (
  streamId: string,
  signal?: AbortSignal
): Promise<{ kind: 'ok' } | { kind: 'http_error'; error: string }> => {
  if (signal?.aborted) return { kind: 'ok' };
  let settle: (value: { kind: 'ok' } | { kind: 'http_error'; error: string }) => void = () => {};
  const outcome = new Promise<{ kind: 'ok' } | { kind: 'http_error'; error: string }>(resolve => { settle = resolve; });
  let settled = false;
  const finish = (value: { kind: 'ok' } | { kind: 'http_error'; error: string }) => {
    if (settled) return;
    settled = true;
    settle(value);
  };
  const evaluate = async () => {
    if (signal?.aborted) { finish({ kind: 'ok' }); return; }
    try {
      const result = await NativeStream.drain({ streamId, fromIndex: 0, maxEvents: 1 });
      if (result.events.length > 0) finish({ kind: 'ok' });
      else if (result.done) finish({ kind: 'http_error', error: result.error || '原生流在收到数据前已结束' });
    } catch (error) {
      finish({ kind: 'http_error', error: (error as Error)?.message || String(error) });
    }
  };
  const eventHandle = await NativeStream.addListener('streamEvent', event => { if (event.streamId === streamId) evaluate(); });
  const doneHandle = await NativeStream.addListener('streamDone', event => { if (event.streamId === streamId) evaluate(); });
  await evaluate();
  try {
    return await outcome;
  } finally {
    await eventHandle.remove();
    await doneHandle.remove();
  }
};

export function useChat() {
  const { showAlert, showChoice } = useAppDialog();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string>('');
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [activeAssistantMessageId, setActiveAssistantMessageId] = useState<string | null>(null);
  const [composerStatus, setComposerStatus] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(true);
  const [agentMode, setAgentMode] = useState('default');
  const [isOCPEnabled, setIsOCPEnabled] = useState(true);
  const [isInitialized, setIsInitialized] = useState(false);
  const activeAbortRef = useRef<AbortController | null>(null);
  const activeServerStreamRef = useRef<string | null>(null);
  const activeNativeStreamRef = useRef<{ streamId: string; nextIndex: number } | null>(null);
  const drainNativeStreamRef = useRef<(() => Promise<void>) | null>(null);
  const conversationsRef = useRef<Conversation[]>([]);
  const resumeEnabledRef = useRef(false);
  const ackStateRef = useRef<Record<string, { seq: number; at: number }>>({});
  const resumingStreamsRef = useRef<Set<string>>(new Set());
  const promptedDisconnectsRef = useRef<Set<string>>(new Set());
  const regenerateMessageRef = useRef<((convId: string, messageId: string, onFileGenerated?: (name: string, path: string) => void, syncFiles?: () => Promise<void>) => Promise<void>) | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistConversationsRef = useRef<(snapshot: Conversation[]) => Promise<void>>(async () => {});

  const currentConversation = conversations.find(c => c.id === currentId) || { id: '', title: '', messages: [] };
  const messages = currentConversation.messages;
  const contextUsage = currentConversation.context_usage || null;
  const nowIso = () => new Date().toISOString();

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    getResumeEnabled().then(enabled => {
      resumeEnabledRef.current = enabled;
    }).catch(() => {
      resumeEnabledRef.current = false;
    });
    return subscribeResumeEnabled(enabled => {
      resumeEnabledRef.current = enabled;
    });
  }, []);

  const abortActiveRequest = useCallback((resetUi = true) => {
    activeAbortRef.current?.abort();
    activeAbortRef.current = null;
    if (resetUi) {
      setIsLoading(false);
      setActiveAssistantMessageId(null);
      setComposerStatus(null);
    }
  }, []);

  const stopActiveGeneration = useCallback(async () => {
    const serverStreamId = activeServerStreamRef.current;
    const nativeStreamId = activeNativeStreamRef.current?.streamId;
    abortActiveRequest();
    setActiveAssistantMessageId(null);
    activeServerStreamRef.current = null;
    activeNativeStreamRef.current = null;
    drainNativeStreamRef.current = null;
    if (nativeStreamId) forgetNativeStreamSession(nativeStreamId);
    await Promise.all([
      serverStreamId ? cancelStream(serverStreamId).catch(console.error) : Promise.resolve(),
      nativeStreamId ? NativeStream.stop({ streamId: nativeStreamId }).catch(console.error) : Promise.resolve(),
    ]);
  }, [abortActiveRequest]);

  useEffect(() => () => abortActiveRequest(false), [abortActiveRequest]);

  // 回前台 / 网络恢复时的续传与 drain 收敛在下方单一 effect（resumePendingStreams 之后）处理，
  // 不再在此重复监听 appStateChange；原生（含 Android）后台不再 abort，交由前台服务/服务端续传兜底。

  const shouldShowHistoryCompressionStatus = (
    usage: ContextUsage | null | undefined,
    history: BackendHistoryMessage[],
    messageContent: string
  ) => {
    const threshold = usage?.threshold_tokens || CONTEXT_COMPRESSION_THRESHOLD_TOKENS;
    return Boolean(
      (usage?.prompt_tokens && usage.prompt_tokens > threshold) ||
      estimateRequestContextTokens(history, messageContent) > threshold
    );
  };

  useEffect(() => {
    const initData = async () => {
      // 1. Try to load from IndexedDB
      let savedConvs = await fileDB.getConversations();
      
      // 2. Migration: If empty in IndexedDB, check localStorage
      if (savedConvs.length === 0) {
        const legacy = localStorage.getItem('conversations');
        if (legacy) {
          try {
            savedConvs = JSON.parse(legacy);
            // Save to IndexedDB immediately for migration
            await fileDB.saveConversations(savedConvs);
            // Optional: clear legacy localStorage later
          } catch (e) {
            console.error('Failed to parse legacy conversations:', e);
          }
        }
      }

      if (savedConvs.length > 0) {
        conversationsRef.current = savedConvs;
        setConversations(savedConvs);
        setCurrentId(savedConvs[0].id);
      } else {
        handleNewChat();
      }
      setIsInitialized(true);
    };
    
    initData();
  }, []);

  useEffect(() => {
    if (!isInitialized) return;

    return addLocalStorageDataChangeListener(async detail => {
      const savedConvs = await fileDB.getConversations();
      if (savedConvs.length === 0) return;

      const preferredId = detail.conversationIds?.find(id =>
        savedConvs.some(conversation => conversation.id === id)
      );
      setConversations(savedConvs);
      setCurrentId(current =>
        preferredId || (savedConvs.some(conversation => conversation.id === current) ? current : savedConvs[0].id)
      );
    });
  }, [isInitialized]);

  // 防抖持久化：流式期间每个事件都改 conversations，若每次都全量写 IndexedDB（序列化所有会话+消息），
  // 答案越长写得越大、原生回前台积压一次性灌入时尤甚 → 长时间卡顿。改为合并写盘（默认 400ms），
  // 并在切后台/页面隐藏时立即 flush，避免丢数据。落盘成功后才 ACK，保证服务端裁剪不超前于设备持久化。
  const SAVE_DEBOUNCE_MS = 400;

  // persistConversationsRef 每次渲染重新指向最新闭包；effect 在 commit 后才调用 .current，
  // 故可安全引用稍后定义的 ackBufferedStream（与原实现同样的 TDZ-safe 模式）。
  persistConversationsRef.current = async (snapshot: Conversation[]) => {
    try {
      await fileDB.saveConversations(snapshot);
    } catch (e) {
      console.error('Failed to save conversations to IndexedDB:', e);
      return;
    }
    for (const conv of snapshot) {
      for (const message of conv.messages) {
        if (
          message.role === 'assistant' &&
          message.stream_buffered &&
          message.stream_id &&
          typeof message.last_committed_seq === 'number' &&
          message.last_committed_seq >= 0 &&
          (message.stream_status === 'streaming' || message.stream_status === 'done')
        ) {
          ackBufferedStream(message.stream_id, message.last_committed_seq, message.stream_status === 'done');
        }
      }
    }
  };

  const flushConversationSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    void persistConversationsRef.current(conversationsRef.current);
  }, []);

  useEffect(() => {
    if (!isInitialized) return;
    const snapshot = conversations;
    if (saveTimerRef.current !== null) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      void persistConversationsRef.current(snapshot);
    }, SAVE_DEBOUNCE_MS);
    return () => {
      if (saveTimerRef.current !== null) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [conversations, isInitialized]);

  // 切后台/页面隐藏立即 flush，弥补防抖窗口内的潜在丢失（此刻最可能被系统回收）。
  useEffect(() => {
    if (!isInitialized) return;
    const onHide = () => {
      if (document.visibilityState === 'hidden') flushConversationSave();
    };
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', flushConversationSave);
    let listener: { remove: () => Promise<void> } | undefined;
    if (isNative()) {
      CapacitorApp.addListener('appStateChange', ({ isActive }) => {
        if (!isActive) flushConversationSave();
      }).then(handle => { listener = handle; });
    }
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', flushConversationSave);
      listener?.remove();
    };
  }, [isInitialized, flushConversationSave]);

  const handleNewChat = () => {
    const newId = generateUUID();
    const now = nowIso();
    const newConversation: Conversation = {
      id: newId,
      title: 'New Conversation',
      messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE, created_at: now, updated_at: now }],
      memory: createEmptyConversationMemory(newId),
      created_at: now,
      updated_at: now
    };
    const nextConversations = [newConversation, ...conversationsRef.current];
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    setCurrentId(newId);
  };

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const filtered = conversationsRef.current.filter(c => c.id !== id);
    let nextConversations = filtered;
    if (filtered.length === 0) {
      const newId = generateUUID();
      const now = nowIso();
      setCurrentId(newId);
      nextConversations = [{
        id: newId,
        title: 'New Conversation',
        messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE, created_at: now, updated_at: now }],
        memory: createEmptyConversationMemory(newId),
        created_at: now,
        updated_at: now
      }];
    } else if (currentId === id) {
      setCurrentId(filtered[0].id);
    }
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await fileDB.deleteFilesByConvId(id);
    try {
      await deleteWorkspace(id);
    } catch (err) {
      console.error("Failed to delete workspace on server:", err);
    }
  };

  const updateMessages = (convId: string, updater: (prev: Message[]) => Message[]) => {
    const nextConversations = conversationsRef.current.map(conv => {
      if (conv.id === convId) {
        const nextMessages = updater(conv.messages);
        if (nextMessages === conv.messages) return conv;
        return { ...conv, messages: nextMessages, updated_at: nowIso() };
      }
      return conv;
    });
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
  };

  const ensureNativeAssistantMessage = (convId: string, messageId: string, nativeStreamId: string) => {
    const now = nowIso();
    const placeholderMessage: Message = {
      id: messageId,
      role: 'assistant',
      content: '',
      thought_blocks: [],
      stream_buffered: false,
      stream_status: 'streaming',
      last_committed_seq: -1,
      native_stream_id: nativeStreamId,
      created_at: now,
      updated_at: now
    };
    let changed = false;
    const nextConversations = conversationsRef.current.map(conv => {
      if (conv.id !== convId) return conv;
      const existing = conv.messages.find(message => message.id === messageId);
      if (existing) {
        if (existing.native_stream_id === nativeStreamId && existing.stream_status === 'streaming') return conv;
        changed = true;
        return {
          ...conv,
          messages: conv.messages.map(message =>
            message.id === messageId
              ? {
                ...message,
                native_stream_id: nativeStreamId,
                stream_status: (message.stream_status === 'done' ? 'done' : 'streaming') as Message['stream_status'],
                updated_at: now
              }
              : message
          ),
          updated_at: now
        };
      }
      changed = true;
      return {
        ...conv,
        messages: [
          ...conv.messages,
          placeholderMessage
        ],
        updated_at: now
      };
    });
    if (!changed) return;
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    void persistConversationsRef.current(nextConversations);
  };

  const removeEmptyNativeAssistantMessage = (convId: string, messageId: string, nativeStreamId: string) => {
    const nextConversations = conversationsRef.current.map(conv => {
      if (conv.id !== convId) return conv;
      const nextMessages = conv.messages.filter(message => !(
        message.id === messageId &&
        message.role === 'assistant' &&
        message.native_stream_id === nativeStreamId &&
        !message.stream_id &&
        !message.content &&
        (!message.thought_blocks || message.thought_blocks.length === 0)
      ));
      if (nextMessages.length === conv.messages.length) return conv;
      return { ...conv, messages: nextMessages, updated_at: nowIso() };
    });
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    void persistConversationsRef.current(nextConversations);
  };

  const updateConversationMemory = (convId: string, memory?: ConversationMemory | null) => {
    if (!memory) return;
    const nextConversations = conversationsRef.current.map(conv => {
      if (conv.id !== convId) return conv;
      return {
        ...conv,
        memory: {
          ...memory,
          conversation_id: convId
        }
      };
    });
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
  };

  const updateConversationContextUsage = (convId: string, usage?: ContextUsage | null) => {
    if (!usage || typeof usage.prompt_tokens !== 'number') return;
    const nextConversations = conversationsRef.current.map(conv => (
      conv.id === convId
        ? { ...conv, context_usage: usage, updated_at: nowIso() }
        : conv
    ));
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
  };

  const syncMemoryFromMessages = async (convId: string, messages: Message[]) => {
    const emptyMemory = createEmptyConversationMemory(convId);
    updateConversationMemory(convId, emptyMemory);
    try {
      let data;
      try {
        data = await syncConversationMemory(convId, emptyMemory, formatHistoryForBackend(messages), 'rebuild');
      } catch (error) {
        if (!(error instanceof MemoryRevisionConflictError)) throw error;
        updateConversationMemory(convId, error.detail?.memory_snapshot as ConversationMemory | undefined);
        data = await syncConversationMemory(convId, emptyMemory, formatHistoryForBackend(messages), 'rebuild', 'server_merge');
      }
      updateConversationMemory(convId, data.memory as ConversationMemory | undefined);
    } catch (error) {
      console.error('Failed to sync conversation memory:', error);
    }
  };

  const sendChatWithMemoryRetry = async (
    message: string,
    history: BackendHistoryMessage[],
    convId: string,
    stream: boolean,
    memorySnapshot: ConversationMemory,
    memorySyncMode: 'merge' | 'rebuild' = 'merge',
    lastContextTokens?: number | null,
    resumeEnabled = false,
    signal?: AbortSignal
  ) => {
    try {
      return await chat(message, history, convId, stream, agentMode, isOCPEnabled, memorySnapshot, memorySyncMode, undefined, lastContextTokens, resumeEnabled, signal);
    } catch (error) {
      if (!(error instanceof MemoryRevisionConflictError)) throw error;
      updateConversationMemory(convId, error.detail?.memory_snapshot as ConversationMemory | undefined);
      return chat(message, history, convId, stream, agentMode, isOCPEnabled, memorySnapshot, memorySyncMode, 'server_merge', lastContextTokens, resumeEnabled, signal);
    }
  };

  const summarizeConversation = async (
    convId: string,
    messagesToSummarize?: Message[],
    expectedFirstUser?: Pick<Message, 'id' | 'content'>
  ) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgs = messagesToSummarize || conv.messages;
    const userMessages = msgs.filter(m => m.role === 'user');
    if (userMessages.length === 0) return;

    const firstUserMessage = userMessages[0];
    const titleGuard = expectedFirstUser || {
      id: firstUserMessage.id,
      content: firstUserMessage.content
    };
    const cleanMessage = firstUserMessage.content.replace(/\[用户已上传以下文件.*?\]/g, '').trim();
    const titleSource = cleanMessage.length > 0 ? cleanMessage : "File Analysis";
    const applyTitleIfCurrent = (title: string) => {
      setConversations(prev => prev.map(c => {
        if (c.id !== convId) return c;
        const liveFirstUser = c.messages.find(m => m.role === 'user');
        if (!liveFirstUser ||
            liveFirstUser.id !== titleGuard.id ||
            liveFirstUser.content !== titleGuard.content) {
          return c;
        }
        return { ...c, title };
      }));
    };

    try {
      const data = await summarizeTitle(titleSource);
      let title = String(data.title || '').replace(/["']/g, '').trim();
      if (title.length > 20) title = title.substring(0, 20) + '...';
      applyTitleIfCurrent(title);
    } catch (error) {
      console.error('Failed to summarize:', error);
      const fallbackTitle = titleSource.substring(0, 15) + (titleSource.length > 15 ? '...' : '');
      applyTitleIfCurrent(fallbackTitle);
    }
  };

  const ackBufferedStream = useCallback((streamId: string, seq: number, force = false) => {
    if (seq < 0) return;
    const last = ackStateRef.current[streamId];
    const now = Date.now();
    if (!force && last && (seq <= last.seq || now - last.at < 500)) return;
    ackStateRef.current[streamId] = { seq, at: now };
    ackStream(streamId, seq).catch(error => {
      console.warn('Stream ACK failed:', error);
    });
  }, []);

  const processStreamPayload = (
    data: any,
    state: {
      agentMessageId: string;
      convId: string;
      bodyText: string;
      thoughtBlocks: ThoughtBlock[];
      contextMessages: BackendHistoryMessage[];
      currentSignature: string;
      currentDownloadPath: string;
      pendingChoice: UserChoiceRequest | null;
      thoughtIdCounter: number;
      lastSeq: number;
      streamId?: string;
      buffered: boolean;
      seenDone: boolean;
      finalSeq?: number;
      status: Message['stream_status'];
    },
    onFileGenerated?: (name: string, path: string) => void
  ) => {
    const incomingSeq = Number.isInteger(data.seq) ? Number(data.seq) : state.lastSeq + 1;
    if (incomingSeq <= state.lastSeq) return false;
    state.lastSeq = incomingSeq;

    const nextThoughtId = () => `${state.agentMessageId}-thought-${state.thoughtIdCounter++}`;
    if (data.type === 'stream_start') {
      state.streamId = data.stream_id || state.streamId;
      state.buffered = Boolean(data.buffered);
      state.status = 'streaming';
      if (state.buffered && state.streamId) activeServerStreamRef.current = state.streamId;
    } else if (data.type === 'content') {
      state.bodyText += data.content || '';
    } else if (data.type === 'thought') {
      const thoughtType = (['reasoning', 'draft', 'tool', 'ocp', 'memory'].includes(data.thought_type)
        ? data.thought_type
        : 'reasoning') as ThoughtBlock['type'];
      const shouldAppend = data.mode === 'append' || thoughtType === 'reasoning' || thoughtType === 'draft';
      state.thoughtBlocks = appendThoughtBlock(
        state.thoughtBlocks,
        data.content || '',
        thoughtType,
        nextThoughtId(),
        shouldAppend
      );
    } else if (data.type === 'thought_signature') {
      state.currentSignature = data.content;
    } else if (data.type === 'download_path') {
      if (data.content && data.content !== state.currentDownloadPath) {
        state.currentDownloadPath = data.content;
        const fileName = state.currentDownloadPath.split('/').pop() || 'generated_file';
        onFileGenerated?.(fileName, state.currentDownloadPath);
      }
    } else if (data.type === 'user_choice_request') {
      const choiceRequest = normalizeUserChoiceRequest(data.content);
      if (choiceRequest) {
        state.pendingChoice = choiceRequest;
        state.bodyText = choiceRequest.question;
        state.status = 'done';
      }
    } else if (data.type === 'memory_sync') {
      updateConversationMemory(state.convId, data.content as ConversationMemory);
    } else if (data.type === 'context_usage') {
      updateConversationContextUsage(state.convId, data.content as ContextUsage);
    } else if (data.type === 'history_trace') {
      const traceMessages = Array.isArray(data.content) ? data.content : [data.content];
      state.contextMessages = [
        ...state.contextMessages,
        ...traceMessages
          .map((item: BackendHistoryMessage) => normalizeBackendMessage(item))
          .filter((item: BackendHistoryMessage | null): item is BackendHistoryMessage => Boolean(item))
      ];
    } else if (data.type === 'content_replace') {
      state.bodyText = data.content || '';
    } else if (data.type === 'resume_unavailable') {
      state.status = 'error';
      state.bodyText += '\n\n**续传不可用：** 本次回答的临时缓存已不可用，请重新生成。';
    } else if (data.type === 'error') {
      state.status = 'error';
      state.bodyText += `\n\n**Error:** ${data.content}`;
    } else if (data.type === 'done') {
      state.seenDone = true;
      state.status = 'done';
      state.finalSeq = Number.isInteger(data.final_seq) ? Number(data.final_seq) : incomingSeq;
    }
    return true;
  };

  const showDisconnectPrompt = async (
    convId: string,
    agentMessageId: string,
    onFileGenerated?: (name: string, path: string) => void
  ) => {
    const key = `${convId}:${agentMessageId}`;
    if (promptedDisconnectsRef.current.has(key) || resumeEnabledRef.current) return;
    promptedDisconnectsRef.current.add(key);
    const choice = await showChoice({
      title: '使用服务器续传？',
      tone: 'warning',
      message: '本次回答因离开页面、网络切换或连接中断而停止。\n\n开启后，后续回答中断时会自动恢复。服务器仅在内存中临时缓存回答内容，最多 45 分钟；设备确认接收后会立即删除。\n\n本次回答也可以直接重新生成。',
      confirmLabel: '开启续传',
      secondaryLabel: '重新生成',
      cancelLabel: '暂不开启',
    });
    if (choice === 'confirm') {
      resumeEnabledRef.current = true;
      await setResumeEnabled(true);
      notifyResumeEnabledChanged(true);
    } else if (choice === 'secondary') {
      const conv = conversationsRef.current.find(item => item.id === convId);
      const messageIndex = conv?.messages.findIndex(item => item.id === agentMessageId) ?? -1;
      const previousUser = messageIndex > 0
        ? conv?.messages.slice(0, messageIndex).reverse().find(item => item.role === 'user')
        : undefined;
      if (previousUser) {
        regenerateMessageRef.current?.(convId, previousUser.id, onFileGenerated).catch(console.error);
      }
    }
  };

  const processStream = async (
    response: Response,
    agentMessageId: string | null,
    convId: string,
    onFileGenerated?: (name: string, path: string) => void,
    signal?: AbortSignal,
    nativeStreamId?: string
  ): Promise<boolean> => {
    const reader = response.body?.getReader();
    if (!reader) {
      if (!signal?.aborted) setIsLoading(false);
      return false;
    }

    if (!agentMessageId) {
      if (signal?.aborted) return false;
      agentMessageId = generateUUID();
      const now = nowIso();
      updateMessages(convId, prev => [...prev, {
        id: agentMessageId!,
        role: 'assistant',
        content: '',
        thought_blocks: [],
        stream_buffered: false,
        stream_status: 'streaming',
        last_committed_seq: -1,
        // 持久化原生流 id：WebView 被系统重建后，resumeNativeStreams 据此重新接上仍在跑的前台服务流。
        native_stream_id: nativeStreamId,
        created_at: now,
        updated_at: now
      }]);
    }
    setActiveAssistantMessageId(agentMessageId);

    const existing = conversationsRef.current
      .find(conv => conv.id === convId)
      ?.messages.find(msg => msg.id === agentMessageId);
    const streamState = {
      agentMessageId,
      convId,
      bodyText: existing?.content || '',
      thoughtBlocks: existing?.thought_blocks ? [...existing.thought_blocks] : [],
      contextMessages: existing?.context_messages ? [...existing.context_messages] : [],
      currentSignature: existing?.thought_signature || '',
      currentDownloadPath: existing?.download_path || '',
      pendingChoice: existing?.pending_choice || null,
      thoughtIdCounter: existing?.thought_blocks?.length || 0,
      lastSeq: existing?.last_committed_seq ?? -1,
      streamId: existing?.stream_id,
      buffered: existing?.stream_buffered === true,
      seenDone: false,
      finalSeq: undefined as number | undefined,
      status: (existing?.stream_status || 'streaming') as Message['stream_status'],
    };
    const decoder = new TextDecoder();
    let streamBuffer = '';
    let commitTimer: ReturnType<typeof setTimeout> | null = null;
    let lastCommitAt = 0;
    const isStreamActive = () => !signal?.aborted;

    // 纯更新函数：只更新 React 状态。落盘与 ACK 交由 conversations 持久化 effect 处理，
    // 避免在 setState updater 内执行副作用（StrictMode 双调用会导致双写 / 双 ACK / 顺序错乱）。
    const commitAssistantState = () => {
      if (!agentMessageId || !isStreamActive()) return;
      let changed = false;
      const next = conversationsRef.current.map(conv => {
          if (conv.id !== convId) return conv;
          const nextMessages = conv.messages.map(msg => {
            if (msg.id !== agentMessageId) return msg;
            if ((msg.last_committed_seq ?? -1) > streamState.lastSeq) return msg;
            changed = true;
            return {
              ...msg,
              content: streamState.bodyText,
              thought_blocks: streamState.thoughtBlocks,
              context_messages: streamState.contextMessages,
              thought_signature: streamState.currentSignature || msg.thought_signature,
              pending_choice: streamState.pendingChoice || msg.pending_choice,
              download_path: streamState.currentDownloadPath || msg.download_path,
              stream_id: streamState.streamId || msg.stream_id,
              stream_buffered: streamState.buffered,
              stream_status: streamState.status,
              last_committed_seq: streamState.lastSeq,
              native_stream_id: nativeStreamId || msg.native_stream_id,
              updated_at: nowIso()
            };
          });
          return changed ? { ...conv, messages: nextMessages, updated_at: nowIso() } : conv;
        });
      if (!changed) return;
      lastCommitAt = Date.now();
      conversationsRef.current = next;
      setConversations(next);
    };

    const scheduleAssistantStateCommit = (force = false) => {
      if (force) {
        if (commitTimer !== null) {
          clearTimeout(commitTimer);
          commitTimer = null;
        }
        commitAssistantState();
        return;
      }
      const waitMs = STREAM_COMMIT_THROTTLE_MS - (Date.now() - lastCommitAt);
      if (waitMs <= 0) {
        commitAssistantState();
        return;
      }
      if (commitTimer !== null) return;
      commitTimer = setTimeout(() => {
        commitTimer = null;
        commitAssistantState();
      }, waitMs);
    };

    const handleLine = (line: string) => {
      if (!isStreamActive() || !line.startsWith('data: ')) return;
      const dataStr = line.slice(6).trim();
      if (!dataStr) return;
      if (dataStr === '[DONE]') return;
      try {
        const data = JSON.parse(dataStr);
        const changed = processStreamPayload(data, streamState, onFileGenerated);
        if (changed) scheduleAssistantStateCommit();
      } catch {
        console.warn('Failed to parse stream data:', dataStr);
      }
    };

    try {
      while (true) {
        if (!isStreamActive()) return false;
        const { done, value } = await reader.read();
        if (done) break;
        if (!isStreamActive()) return false;

        streamBuffer += decoder.decode(value, { stream: true });
        const lines = streamBuffer.split('\n');
        streamBuffer = lines.pop() || '';
        lines.forEach(handleLine);
      }

      if (streamBuffer.trim().startsWith('data: ')) {
        handleLine(streamBuffer.trim());
      }
      scheduleAssistantStateCommit(true);
      if (!streamState.seenDone && !streamState.buffered && agentMessageId) {
        await showDisconnectPrompt(convId, agentMessageId, onFileGenerated);
      } else if (!streamState.seenDone && streamState.buffered && streamState.streamId) {
        setTimeout(() => {
          resumePendingStreams().catch(console.error);
        }, 0);
      }
      return isStreamActive() && streamState.seenDone;
    } catch (err) {
      if (isAbortError(err) || !isStreamActive()) return false;
      console.error('Stream read error:', err);
      scheduleAssistantStateCommit(true);
      if (!streamState.buffered && agentMessageId) {
        await showDisconnectPrompt(convId, agentMessageId, onFileGenerated);
      } else if (streamState.buffered && streamState.streamId) {
        setTimeout(() => {
          resumePendingStreams().catch(console.error);
        }, 0);
      }
      return false;
    } finally {
      if (commitTimer !== null) {
        clearTimeout(commitTimer);
        commitTimer = null;
      }
      reader.releaseLock();
      if (isStreamActive()) {
        setIsLoading(false);
        setActiveAssistantMessageId(current => current === agentMessageId ? null : current);
        setComposerStatus(null);
        if (streamState.status === 'done') {
          activeServerStreamRef.current = null;
        }
        onFileGenerated?.('sync', '');
      }
    }
  };

  const resumePendingStreams = useCallback(async () => {
    const pending: Array<{ convId: string; message: Message }> = [];
    conversationsRef.current.forEach(conv => {
      conv.messages.forEach(message => {
        if (
          message.role === 'assistant' &&
          message.stream_status === 'streaming' &&
          message.stream_id &&
          message.stream_buffered === true
        ) {
          pending.push({ convId: conv.id, message });
        }
      });
    });

    for (const item of pending) {
      const streamId = item.message.stream_id;
      if (!streamId || resumingStreamsRef.current.has(streamId)) continue;
      resumingStreamsRef.current.add(streamId);
      const controller = new AbortController();
      try {
        setIsLoading(true);
        setActiveAssistantMessageId(item.message.id);
        setComposerStatus('正在恢复中断的回答');
        const response = await resumeStream(streamId, item.message.last_committed_seq ?? -1, controller.signal);
        await processStream(response, item.message.id, item.convId, undefined, controller.signal);
      } catch (error) {
        if (error instanceof StreamExpiredError) {
          updateMessages(item.convId, prev => prev.map(message =>
            message.id === item.message.id
              ? {
                ...message,
                stream_status: 'error',
                content: `${message.content}\n\n**续传窗口已过：** 请重新生成本次回答。`,
                updated_at: nowIso()
              }
              : message
          ));
        } else if (!isAbortError(error)) {
          console.error('Failed to resume stream:', error);
        }
      } finally {
        resumingStreamsRef.current.delete(streamId);
        setIsLoading(false);
        setActiveAssistantMessageId(null);
        setComposerStatus(null);
      }
    }
  }, []);

  useEffect(() => {
    if (!isInitialized) return;
    resumePendingStreams().catch(console.error);
  }, [isInitialized, resumePendingStreams]);

  const processNativeChatStream = async (
    body: string,
    agentMessageId: string | null,
    convId: string,
    onFileGenerated?: (name: string, path: string) => void,
    signal?: AbortSignal,
    existingStreamId?: string
  ): Promise<boolean> => {
    let nativeStreamId: string;
    let createdPlaceholderId: string | null = null;
    if (existingStreamId) {
      // Attach 模式：WebView 重建后重新接上仍存活的前台服务流，不重发请求、不做 head 判定
      // （流早已在进行，事件从原生 buffer index 0 全量重放，processStream 用 seq 去重）。
      nativeStreamId = existingStreamId;
      if (agentMessageId) {
        ensureNativeAssistantMessage(convId, agentMessageId, nativeStreamId);
      }
      activeNativeStreamRef.current = { streamId: nativeStreamId, nextIndex: 0 };
    } else {
      const token = await getAuthToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Lawver-Client': 'capacitor',
        'Origin': 'capacitor://localhost',
        'Referer': 'capacitor://localhost/',
      };
      if (token) headers.Authorization = `Bearer ${token}`;
      await requestNativeStreamNotificationPermission().catch(() => false);

      const started = await NativeStream.startStream({ url: apiUrl('/api/chat'), headers, body });
      nativeStreamId = started.streamId;
      activeNativeStreamRef.current = { streamId: nativeStreamId, nextIndex: 0 };
      if (!agentMessageId) {
        agentMessageId = generateUUID();
        createdPlaceholderId = agentMessageId;
      }
      rememberNativeStreamSession({
        streamId: nativeStreamId,
        convId,
        messageId: agentMessageId,
        createdAt: nowIso()
      });
      ensureNativeAssistantMessage(convId, agentMessageId, nativeStreamId);

      // 渲染前先判定 HTTP 层结果：非 2xx（如 409 记忆冲突）会以"无事件即 done"出现，
      // 此时抛出结构化错误交由上层重试，避免把 "HTTP 409:..." 当作回答正文渲染。
      let head: { kind: 'ok' } | { kind: 'http_error'; error: string };
      try {
        head = await waitForNativeStreamHead(nativeStreamId, signal);
      } catch (error) {
        await NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
        forgetNativeStreamSession(nativeStreamId);
        if (createdPlaceholderId) removeEmptyNativeAssistantMessage(convId, createdPlaceholderId, nativeStreamId);
        activeNativeStreamRef.current = null;
        throw error;
      }
      if (head.kind === 'http_error') {
        await NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
        forgetNativeStreamSession(nativeStreamId);
        if (createdPlaceholderId) removeEmptyNativeAssistantMessage(convId, createdPlaceholderId, nativeStreamId);
        activeNativeStreamRef.current = null;
        throw parseHttpStreamError(head.error);
      }
    }

    const encoder = new TextEncoder();
    let nextIndex = 0;
    let closed = false;
    let eventHandle: { remove: () => Promise<void> } | null = null;
    let doneHandle: { remove: () => Promise<void> } | null = null;

    const response = new Response(new ReadableStream<Uint8Array>({
      async start(controller) {
        let pumping = false;
        let pumpAgain = false;

        const safeEnqueue = (payload: string) => {
          if (closed || signal?.aborted) return;
          try {
            controller.enqueue(encoder.encode(`data: ${payload}\n\n`));
          } catch {
            // controller 已关闭，忽略。
          }
        };
        const safeClose = () => {
          if (closed) return;
          closed = true;
          try {
            controller.close();
          } catch {
            // controller 已关闭，忽略。
          }
        };

        // 单一出口：所有事件都经由 pump 按 index 顺序从原生 buffer 拉出，
        // 串行执行（pumping/pumpAgain 互斥），杜绝监听器与 drain 并发导致的乱序 / 双重 close。
        const pump = async () => {
          if (closed) return;
          if (pumping) {
            pumpAgain = true;
            return;
          }
          pumping = true;
          try {
            do {
              pumpAgain = false;
              const result = await NativeStream.drain({
                streamId: nativeStreamId,
                fromIndex: nextIndex,
                maxEvents: NATIVE_DRAIN_BATCH_SIZE
              });
              for (const payload of result.events) safeEnqueue(payload);
              nextIndex = result.nextIndex;
              if (activeNativeStreamRef.current?.streamId === nativeStreamId) {
                activeNativeStreamRef.current.nextIndex = nextIndex;
              }
              if (result.done) {
                if (result.error) {
                  // 传输层中断（连接超时 / 截断 / 网络切换），区别于服务端 {type:'error'} 事件。
                  // 不注入合成 error 事件——那会把状态钉成 'error' 而剥夺缓冲流的自动续传资格。
                  // 直接关闭：processStream 因未见 {type:'done'} 走断线分支（缓冲流→续传，非缓冲→断线弹窗）。
                  console.warn('Native stream transport ended without completion:', result.error);
                } else {
                  safeEnqueue('[DONE]');
                }
                safeClose();
                return;
              }
              if (result.hasMore) {
                pumpAgain = true;
                await new Promise(resolve => setTimeout(resolve, 0));
              }
            } while (pumpAgain && !closed);
          } catch (error) {
            safeEnqueue(JSON.stringify({ type: 'error', content: (error as Error)?.message || String(error) }));
            safeClose();
          } finally {
            pumping = false;
          }
        };

        eventHandle = await NativeStream.addListener('streamEvent', (event: NativeStreamEvent) => {
          if (event.streamId !== nativeStreamId) return;
          pump().catch(console.error);
        });
        doneHandle = await NativeStream.addListener('streamDone', event => {
          if (event.streamId !== nativeStreamId) return;
          pump().catch(console.error);
        });

        drainNativeStreamRef.current = pump;
        await pump();
      },
      cancel() {
        closed = true;
        NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
      }
    }));

    try {
      const completed = await processStream(response, agentMessageId, convId, onFileGenerated, signal, nativeStreamId);
      await NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
      forgetNativeStreamSession(nativeStreamId);
      if (!completed && !signal?.aborted) {
        setTimeout(() => {
          resumePendingStreams().catch(console.error);
        }, 0);
      }
      return completed;
    } finally {
      await eventHandle?.remove();
      await doneHandle?.remove();
      activeNativeStreamRef.current = null;
      drainNativeStreamRef.current = null;
    }
  };

  // WebView 被系统重建后，前台服务里的原生流仍在跑，但 JS 侧的 activeNativeStreamRef 已丢失。
  // 据持久化的 native_stream_id + listActive 找回仍存活的流并重新接上（attach 模式）。
  // 注意：服务端缓冲流（stream_buffered）由 resumePendingStreams 负责，这里只管原生前台服务流。
  const resumeNativeStreamsRef = useRef<() => void>(() => {});
  resumeNativeStreamsRef.current = () => {
    if (!isNativeAndroid() || !NativeStream.listActive) return;
    void (async () => {
      let liveIds: Set<string>;
      try {
        const active = await NativeStream.listActive!();
        liveIds = new Set(active?.streamIds || []);
      } catch (error) {
        console.error('Failed to list active native streams:', error);
        return;
      }
      const records = readNativeStreamSessions();
      const recordByStreamId = new Map(records.map(record => [record.streamId, record]));
      const retainedRecords = records.filter(record => liveIds.has(record.streamId));
      if (retainedRecords.length !== records.length) {
        writeNativeStreamSessions(retainedRecords);
      }
      if (liveIds.size === 0) return;
      for (const conv of conversationsRef.current) {
        for (const msg of conv.messages) {
          if (msg.role !== 'assistant' || !msg.native_stream_id) continue;
          if (!recordByStreamId.has(msg.native_stream_id)) {
            recordByStreamId.set(msg.native_stream_id, {
              streamId: msg.native_stream_id,
              convId: conv.id,
              messageId: msg.id,
              createdAt: msg.created_at || nowIso()
            });
          }
        }
      }
      for (const conv of conversationsRef.current) {
        for (const msg of conv.messages) {
          if (msg.role !== 'assistant' || msg.stream_status !== 'streaming') continue;
          const nid = msg.native_stream_id;
          if (!nid || !liveIds.has(nid)) continue;
          if (resumingStreamsRef.current.has(nid)) continue;
          if (activeNativeStreamRef.current?.streamId === nid) continue; // 已有活跃 pump 在 drain
          resumingStreamsRef.current.add(nid);
          const controller = new AbortController();
          setIsLoading(true);
          setActiveAssistantMessageId(msg.id);
          processNativeChatStream('', msg.id, conv.id, undefined, controller.signal, nid)
            .catch(err => { if (!isAbortError(err)) console.error('Failed to resume native stream:', err); })
            .finally(() => { resumingStreamsRef.current.delete(nid); });
        }
      }
      for (const nid of liveIds) {
        const record = recordByStreamId.get(nid);
        if (!record) continue;
        const conv = conversationsRef.current.find(item => item.id === record.convId);
        const msg = conv?.messages.find(item => item.id === record.messageId);
        if (msg?.role === 'assistant' && msg.stream_status === 'streaming') continue;
        ensureNativeAssistantMessage(record.convId, record.messageId, nid);
        if (resumingStreamsRef.current.has(nid)) continue;
        if (activeNativeStreamRef.current?.streamId === nid) continue;
        resumingStreamsRef.current.add(nid);
        const controller = new AbortController();
        setIsLoading(true);
        setActiveAssistantMessageId(record.messageId);
        processNativeChatStream('', record.messageId, record.convId, undefined, controller.signal, nid)
          .catch(err => { if (!isAbortError(err)) console.error('Failed to resume native stream from record:', err); })
          .finally(() => { resumingStreamsRef.current.delete(nid); });
      }
    })();
  };

  // 原生路径的记忆版本冲突重试，行为对齐 Web 的 sendChatWithMemoryRetry：
  // 首发遇到 409 memory_revision_conflict 时，更新本地记忆快照并以 server_merge 重试一次。
  const sendNativeChatWithMemoryRetry = async (
    message: string,
    history: BackendHistoryMessage[],
    convId: string,
    memorySnapshot: ConversationMemory,
    memorySyncMode: 'merge' | 'rebuild',
    lastContextTokens: number | null | undefined,
    resumeEnabled: boolean,
    onFileGenerated?: (name: string, path: string) => void,
    signal?: AbortSignal
  ): Promise<boolean> => {
    const buildBody = (strategy?: 'server_merge') => JSON.stringify(buildChatRequestBody(
      message, history, convId, true, agentMode, isOCPEnabled, memorySnapshot, memorySyncMode, strategy, lastContextTokens ?? null, resumeEnabled
    ));
    try {
      return await processNativeChatStream(buildBody(undefined), null, convId, onFileGenerated, signal);
    } catch (error) {
      if (!(error instanceof MemoryRevisionConflictError)) throw error;
      updateConversationMemory(convId, error.detail?.memory_snapshot as ConversationMemory | undefined);
      return processNativeChatStream(buildBody('server_merge'), null, convId, onFileGenerated, signal);
    }
  };

  useEffect(() => {
    if (!isInitialized) return;
    const resumeTimers = new Set<ReturnType<typeof setTimeout>>();
    const runResumePass = () => {
      if (document.visibilityState === 'hidden') return;
      const hadActiveNative = Boolean(activeNativeStreamRef.current);
      if (activeNativeStreamRef.current) {
        // WebView 仍在、流仍活：直接补 drain 后台积压的事件。
        drainNativeStreamRef.current?.().catch(console.error);
      } else {
        // WebView 可能被重建：找回仍存活的原生流。
        resumeNativeStreamsRef.current();
      }
      const timer = setTimeout(() => {
        resumeTimers.delete(timer);
        resumePendingStreams().catch(console.error);
      }, hadActiveNative ? 600 : 0);
      resumeTimers.add(timer);
    };
    const scheduleResumePasses = () => {
      [0, 250, 1000, 2500].forEach(delay => {
        const timer = setTimeout(() => {
          resumeTimers.delete(timer);
          runResumePass();
        }, delay);
        resumeTimers.add(timer);
      });
    };
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') scheduleResumePasses();
    };
    window.addEventListener('focus', scheduleResumePasses);
    window.addEventListener('online', scheduleResumePasses);
    window.addEventListener('pageshow', scheduleResumePasses);
    document.addEventListener('visibilitychange', handleVisibility);

    let listener: { remove: () => Promise<void> } | undefined;
    if (isNative()) {
      CapacitorApp.addListener('appStateChange', ({ isActive }) => {
        if (isActive) scheduleResumePasses();
      }).then(handle => {
        listener = handle;
      });
    }
    scheduleResumePasses();

    return () => {
      resumeTimers.forEach(timer => clearTimeout(timer));
      resumeTimers.clear();
      window.removeEventListener('focus', scheduleResumePasses);
      window.removeEventListener('online', scheduleResumePasses);
      window.removeEventListener('pageshow', scheduleResumePasses);
      document.removeEventListener('visibilitychange', handleVisibility);
      listener?.remove();
    };
  }, [isInitialized, resumePendingStreams]);

  const handleUserChoice = async (
    messageId: string,
    value: string,
    onFileGenerated?: (name: string, path: string) => void,
    syncFiles?: () => Promise<void>
  ) => {
    const selectedValue = value.trim();
    if (!selectedValue || isLoading || !isInitialized) return;

    const convId = currentId;
    const conv = conversationsRef.current.find(c => c.id === convId);
    if (!conv) return;

    const choiceMessage = conv.messages.find(message => message.id === messageId);
    if (!choiceMessage?.pending_choice || choiceMessage.pending_choice.answered) return;

    const history = formatHistoryForBackend(conv.messages);
    const memorySnapshot = conv.memory || createEmptyConversationMemory(convId);
    const lastContextTokens = conv.context_usage?.prompt_tokens ?? null;
    const shouldShowCompressionStatus = shouldShowHistoryCompressionStatus(conv.context_usage, history, selectedValue);
    const now = nowIso();
    const userMessage: Message = {
      id: generateUUID(),
      role: 'user',
      content: selectedValue,
      created_at: now,
      updated_at: now
    };

    updateMessages(convId, prev => [
      ...prev.map(message =>
        message.id === messageId && message.pending_choice
          ? {
            ...message,
            pending_choice: {
              ...message.pending_choice,
              answered: true,
              selected_value: selectedValue,
            },
            updated_at: now
          }
          : message
      ),
      userMessage
    ]);
    setIsLoading(true);
    setComposerStatus(shouldShowCompressionStatus ? HISTORY_COMPRESSION_STATUS : null);

    const abortController = new AbortController();
    activeAbortRef.current?.abort();
    activeAbortRef.current = abortController;

    try {
      if (syncFiles) {
        await syncFiles();
      }

      const resumeEnabled = await getResumeEnabled();
      resumeEnabledRef.current = resumeEnabled;
      if (isStreaming && isNativeAndroid()) {
        setComposerStatus(null);
        const completed = await sendNativeChatWithMemoryRetry(selectedValue, history, convId, memorySnapshot, 'merge', lastContextTokens, resumeEnabled, onFileGenerated, abortController.signal);
        if (!completed) return;
      } else {
        const response = await sendChatWithMemoryRetry(selectedValue, history, convId, isStreaming, memorySnapshot, 'merge', lastContextTokens, resumeEnabled, abortController.signal);

        if (abortController.signal.aborted) return;
        if (isStreaming) {
          setComposerStatus(null);
          const completed = await processStream(response, null, convId, onFileGenerated, abortController.signal);
          if (!completed) return;
        } else {
          const data = await response.json();
          if (abortController.signal.aborted) return;
          const agentMessageId = generateUUID();
          const pendingChoice = normalizeUserChoiceRequest(data.user_choice_request);

          updateMessages(convId, prev => [...prev, {
            id: agentMessageId,
            role: 'assistant',
            content: pendingChoice?.question || data.reply,
            pending_choice: pendingChoice || undefined,
            download_path: data.download_path,
            context_messages: data.context_messages || [],
            created_at: nowIso(),
            updated_at: nowIso()
          }]);
          updateConversationMemory(convId, data.memory_snapshot as ConversationMemory | undefined);
          updateConversationContextUsage(convId, data.context_usage as ContextUsage | undefined);
          setIsLoading(false);
          setComposerStatus(null);
          onFileGenerated?.('sync', '');
        }
      }
    } catch (error) {
      if (!isAbortError(error) && !abortController.signal.aborted) {
        console.error('Failed to send user choice:', error);
      }
      if (!abortController.signal.aborted) setIsLoading(false);
    } finally {
      if (activeAbortRef.current === abortController) {
        activeAbortRef.current = null;
        setComposerStatus(null);
      }
    }
  };

  const handleSend = async (pendingUploads: {name: string, path: string}[], setPendingUploads: (val: any) => void, onFileGenerated?: (name: string, path: string) => void, syncFiles?: () => Promise<void>) => {
    if ((!input.trim() && pendingUploads.length === 0) || isLoading || !isInitialized) {
      return;
    }

    let messageContent = input.trim();
    if (pendingUploads.length > 0) {
      const fileInfo = pendingUploads.map(f => `- ${f.name} (路径: ${f.path})`).join('\n');
      messageContent += messageContent ? `\n\n[用户已上传以下文件，请根据需要进行读取和处理]\n${fileInfo}` : `[用户已上传以下文件，请根据需要进行读取和处理]\n${fileInfo}`;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageContent,
      created_at: nowIso(),
      updated_at: nowIso()
    };

    let convId = currentId;
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const isFirstUserMessage = conv.messages.filter(m => m.role === 'user').length === 0;
    const history = formatHistoryForBackend(conv.messages);
    const memorySnapshot = conv.memory || createEmptyConversationMemory(convId);
    const lastContextTokens = conv.context_usage?.prompt_tokens ?? null;
    const shouldShowCompressionStatus = shouldShowHistoryCompressionStatus(conv.context_usage, history, messageContent);

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setPendingUploads([]);
    setIsLoading(true);
    setComposerStatus(shouldShowCompressionStatus ? HISTORY_COMPRESSION_STATUS : null);

    const abortController = new AbortController();
    activeAbortRef.current?.abort();
    activeAbortRef.current = abortController;

    try {
      // Pre-flight sync: Ensure all files are synced to the server before sending the request
      if (syncFiles) {
        await syncFiles();
      }

      const resumeEnabled = await getResumeEnabled();
      resumeEnabledRef.current = resumeEnabled;
      if (isStreaming && isNativeAndroid()) {
        setComposerStatus(null);
        const completed = await sendNativeChatWithMemoryRetry(messageContent, history, convId, memorySnapshot, 'merge', lastContextTokens, resumeEnabled, onFileGenerated, abortController.signal);
        if (!completed) return;
      } else {
        const response = await sendChatWithMemoryRetry(messageContent, history, convId, isStreaming, memorySnapshot, 'merge', lastContextTokens, resumeEnabled, abortController.signal);

        if (abortController.signal.aborted) return;
        if (isStreaming) {
          setComposerStatus(null);
          const completed = await processStream(response, null, convId, onFileGenerated, abortController.signal);
          if (!completed) return;
        } else {
          const data = await response.json();
          if (abortController.signal.aborted) return;
          const agentMessageId = generateUUID();
          const pendingChoice = normalizeUserChoiceRequest(data.user_choice_request);

          if (data.download_path) {
            const fileName = data.download_path.split('/').pop() || 'generated_file';
            onFileGenerated?.(fileName, data.download_path);
          }

          updateMessages(convId, prev => [...prev, {
            id: agentMessageId,
            role: 'assistant',
            content: pendingChoice?.question || data.reply,
            pending_choice: pendingChoice || undefined,
            download_path: data.download_path,
            context_messages: data.context_messages || [],
            created_at: nowIso(),
            updated_at: nowIso()
          }]);
          updateConversationMemory(convId, data.memory_snapshot as ConversationMemory | undefined);
          updateConversationContextUsage(convId, data.context_usage as ContextUsage | undefined);
          setIsLoading(false);
          setComposerStatus(null);
          onFileGenerated?.('sync', '');
        }
      }

      if (isFirstUserMessage) {
        setTimeout(() => {
          setConversations(currentConvs => {
            const currentConv = currentConvs.find(c => c.id === convId);
            if (currentConv && currentConv.messages.length > 0) {
              const lastMsg = currentConv.messages[currentConv.messages.length - 1];
              const isStillThinking = lastMsg.content.includes('正在调用工具') ||
                                    lastMsg.content.includes('执行:') ||
                                    (lastMsg.content.includes('<think>') && !lastMsg.content.includes('</think>'));

              if (!isStillThinking) {
                summarizeConversation(convId, currentConv.messages);
              } else {
                setTimeout(() => summarizeConversation(convId), 5000);
              }
            }
            return currentConvs;
          });
        }, 5000);
      }
    } catch (error) {
      if (!isAbortError(error) && !abortController.signal.aborted) {
        console.error('Failed to send message:', error);
      }
      if (!abortController.signal.aborted) setIsLoading(false);
    } finally {
      if (activeAbortRef.current === abortController) {
        activeAbortRef.current = null;
        setComposerStatus(null);
      }
    }
  };

  const handleRegenerateMessage = async (convId: string, messageId: string, onFileGenerated?: (name: string, path: string) => void, syncFiles?: () => Promise<void>) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgIndex = conv.messages.findIndex(m => m.id === messageId);
    if (msgIndex === -1) return;

    const msg = conv.messages[msgIndex];
    if (msg.role !== 'user') return;

    const content = msg.content;
    const isFirstUserMessage = conv.messages.slice(0, msgIndex).filter(m => m.role === 'user').length === 0;
    const retainedMessages = conv.messages.slice(0, msgIndex);
    const history = formatHistoryForBackend(retainedMessages);
    const memorySnapshot = createEmptyConversationMemory(convId);
    const lastContextTokens = conv.context_usage?.prompt_tokens ?? null;
    const shouldShowCompressionStatus = shouldShowHistoryCompressionStatus(conv.context_usage, history, content);

    updateMessages(convId, () => retainedMessages);
    updateConversationMemory(convId, memorySnapshot);
    setIsLoading(true);
    setComposerStatus(shouldShowCompressionStatus ? HISTORY_COMPRESSION_STATUS : null);

    const abortController = new AbortController();
    activeAbortRef.current?.abort();
    activeAbortRef.current = abortController;

    try {
      // Pre-flight sync: Ensure all files are synced to the server before sending the request
      if (syncFiles) {
        await syncFiles();
      }

      const now = nowIso();
      const userMessage: Message = { id: Date.now().toString(), role: 'user', content: content, created_at: now, updated_at: now };
      updateMessages(convId, prev => [...prev, userMessage]);

      const resumeEnabled = await getResumeEnabled();
      resumeEnabledRef.current = resumeEnabled;
      if (isStreaming && isNativeAndroid()) {
        setComposerStatus(null);
        const completed = await sendNativeChatWithMemoryRetry(content, history, convId, memorySnapshot, 'rebuild', lastContextTokens, resumeEnabled, onFileGenerated, abortController.signal);
        if (!completed) return;
      } else {
        const response = await sendChatWithMemoryRetry(content, history, convId, isStreaming, memorySnapshot, 'rebuild', lastContextTokens, resumeEnabled, abortController.signal);

        if (abortController.signal.aborted) return;
        if (isStreaming) {
          setComposerStatus(null);
          const completed = await processStream(response, null, convId, onFileGenerated, abortController.signal);
          if (!completed) return;
        } else {
          const data = await response.json();
          if (abortController.signal.aborted) return;
          const agentMessageId = generateUUID();
          const pendingChoice = normalizeUserChoiceRequest(data.user_choice_request);

          if (data.download_path) {
            const fileName = data.download_path.split('/').pop() || 'generated_file';
            onFileGenerated?.(fileName, data.download_path);
          }

          updateMessages(convId, prev => [...prev, {
            id: agentMessageId,
            role: 'assistant',
            content: pendingChoice?.question || data.reply,
            pending_choice: pendingChoice || undefined,
            download_path: data.download_path,
            context_messages: data.context_messages || [],
            created_at: nowIso(),
            updated_at: nowIso()
          }]);
          updateConversationMemory(convId, data.memory_snapshot as ConversationMemory | undefined);
          updateConversationContextUsage(convId, data.context_usage as ContextUsage | undefined);
          setIsLoading(false);
          setComposerStatus(null);
          onFileGenerated?.('sync', '');
        }
      }

      if (isFirstUserMessage) {
        setTimeout(() => {
          setConversations(currentConvs => {
            const currentConv = currentConvs.find(c => c.id === convId);
            if (currentConv && currentConv.messages.length > 0) {
              const lastMsg = currentConv.messages[currentConv.messages.length - 1];
              const isStillThinking = lastMsg.content.includes('正在调用工具') ||
                                    lastMsg.content.includes('执行:') ||
                                    (lastMsg.content.includes('<think>') && !lastMsg.content.includes('</think>'));

              if (!isStillThinking) {
                summarizeConversation(convId, currentConv.messages);
              } else {
                setTimeout(() => summarizeConversation(convId), 5000);
              }
            }
            return currentConvs;
          });
        }, 5000);
      }
    } catch (error) {
      if (!isAbortError(error) && !abortController.signal.aborted) {
        console.error('Failed to regenerate message:', error);
      }
      if (!abortController.signal.aborted) setIsLoading(false);
    } finally {
      if (activeAbortRef.current === abortController) {
        activeAbortRef.current = null;
        setComposerStatus(null);
      }
    }
  };

  regenerateMessageRef.current = handleRegenerateMessage;

  const handleUndo = async (convId: string, messageId: string, setPendingUploads: (val: any) => void) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgIndex = conv.messages.findIndex(m => m.id === messageId);
    if (msgIndex === -1) return;

    const msg = conv.messages[msgIndex];
    if (msg.role !== 'user') return;

    abortActiveRequest();

    let textContent = msg.content;
    let filesToRestore: {name: string, path: string}[] = [];

    const fileInfoRegex = new RegExp("\\[用户已上传以下文件，请根据需要进行读取和处理\\]\\n([\\s\\S]*)$");
    const match = msg.content.match(fileInfoRegex);
    if (match) {
      textContent = msg.content.replace(match[0], '').trim();
      filesToRestore = match[1].split('\n').filter(line => line.startsWith('- ')).map(line => {
        const nameMatch = line.match(/^- (.*?) \(路径: (.*?)\)/);
        if (nameMatch) {
          return { name: nameMatch[1], path: nameMatch[2] };
        }
        return { name: line.replace('- ', ''), path: '' };
      });
    }

    setInput(textContent);
    setPendingUploads(filesToRestore);
    const retainedMessages = conv.messages.slice(0, msgIndex);
    updateMessages(convId, () => retainedMessages);
    if (!retainedMessages.some(m => m.role === 'user')) {
      setConversations(prev => prev.map(c =>
        c.id === convId ? { ...c, title: 'New Conversation' } : c
      ));
    }
    await syncMemoryFromMessages(convId, retainedMessages);
  };

  const handleEdit = (convId: string, messageId: string, setPendingUploads: (val: any) => void) => {
    handleUndo(convId, messageId, setPendingUploads);
  };

  /**
   * 从指定消息（含）截取本会话，复制为一个新会话。memory scope 派生自 conversation_id，
   * 新 UUID 天然得到干净的服务端记忆，无需额外清理调用。
   */
  const branchConversation = (convId: string, messageId: string): string | null => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return null;
    const idx = conv.messages.findIndex(m => m.id === messageId);
    if (idx < 0) return null;

    const truncated = conv.messages.slice(0, idx + 1).map(msg => ({ ...msg }));
    const newId = generateUUID();
    const now = nowIso();
    const baseTitle = (() => {
      const original = conv.title || 'New Chat';
      return /（分支）$|（分支 \d+）$/.test(original) ? original : `${original}（分支）`;
    })();

    const newConv: Conversation = {
      id: newId,
      title: baseTitle,
      messages: truncated,
      memory: createEmptyConversationMemory(newId),
      parent_id: convId,
      branch_point_message_id: messageId,
      created_at: now,
      updated_at: now
    };

    setConversations(prev => [newConv, ...prev]);
    setCurrentId(newId);
    return newId;
  };

  return {
    conversations,
    currentId,
    setCurrentId,
    input,
    setInput,
    isLoading,
    activeAssistantMessageId,
    composerStatus,
    isStreaming,
    setIsStreaming,
    agentMode,
    setAgentMode,
    isOCPEnabled,
    setIsOCPEnabled,
    isInitialized,
    currentConversation,
    contextUsage,
    messages,
    handleNewChat,
    deleteConversation,
    handleSend: async (pendingUploads: {name: string, path: string}[], setPendingUploads: (val: any) => void, onFileGenerated?: (name: string, path: string) => void, syncFiles?: () => Promise<void>, isLowStorage?: boolean) => {
      if (isLowStorage) {
        await showAlert({
          title: '本地存储空间不足',
          message: '请点击侧边栏下方的存储指示器进行导出并清理，否则无法继续发送消息。',
          tone: 'warning',
        });
        return;
      }
      return handleSend(pendingUploads, setPendingUploads, onFileGenerated, syncFiles);
    },
    handleRegenerateMessage,
    handleUserChoice,
    stopActiveGeneration,
    handleUndo,
    handleEdit,
    branchConversation
  };
}
