/*
 * 模块描述：聊天状态 Hook，管理会话、消息、发送流程、编辑/撤回和对话级记忆同步。
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import type { BackendHistoryMessage, ContextUsage, Conversation, ConversationMemory, Message, ThoughtBlock } from '../types';
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

const isAbortError = (error: unknown) => (
  typeof error === 'object' &&
  error !== null &&
  'name' in error &&
  (error as { name?: string }).name === 'AbortError'
);

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
    await Promise.all([
      serverStreamId ? cancelStream(serverStreamId).catch(console.error) : Promise.resolve(),
      nativeStreamId ? NativeStream.stop({ streamId: nativeStreamId }).catch(console.error) : Promise.resolve(),
    ]);
  }, [abortActiveRequest]);

  useEffect(() => () => abortActiveRequest(false), [abortActiveRequest]);

  useEffect(() => {
    if (!isNative()) return;

    let listener: { remove: () => Promise<void> } | undefined;
    CapacitorApp.addListener('appStateChange', ({ isActive }) => {
      if (isActive) {
        drainNativeStreamRef.current?.().catch(console.error);
      }
      if (!isActive && !isNativeAndroid()) abortActiveRequest();
    }).then(handle => {
      listener = handle;
    });

    return () => {
      listener?.remove();
    };
  }, [abortActiveRequest]);

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

  useEffect(() => {
    if (isInitialized) {
      fileDB.saveConversations(conversations).catch(e => {
        console.error('Failed to save conversations to IndexedDB:', e);
      });
    }
  }, [conversations, isInitialized]);

  const handleNewChat = () => {
    const newId = generateUUID();
    const now = nowIso();
    setConversations(prev => [{
      id: newId,
      title: 'New Conversation',
      messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE, created_at: now, updated_at: now }],
      memory: createEmptyConversationMemory(newId),
      created_at: now,
      updated_at: now
    }, ...prev]);
    setCurrentId(newId);
  };

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setConversations(prev => {
      const filtered = prev.filter(c => c.id !== id);
      if (filtered.length === 0) {
        const newId = generateUUID();
        const now = nowIso();
        setCurrentId(newId);
        return [{
          id: newId,
          title: 'New Conversation',
          messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE, created_at: now, updated_at: now }],
          memory: createEmptyConversationMemory(newId),
          created_at: now,
          updated_at: now
        }];
      }
      if (currentId === id) {
        setCurrentId(filtered[0].id);
      }
      return filtered;
    });
    await fileDB.deleteFilesByConvId(id);
    try {
      await deleteWorkspace(id);
    } catch (err) {
      console.error("Failed to delete workspace on server:", err);
    }
  };

  const updateMessages = (convId: string, updater: (prev: Message[]) => Message[]) => {
    setConversations(prev => prev.map(conv => {
      if (conv.id === convId) {
        const nextMessages = updater(conv.messages);
        if (nextMessages === conv.messages) return conv;
        return { ...conv, messages: nextMessages, updated_at: nowIso() };
      }
      return conv;
    }));
  };

  const updateConversationMemory = (convId: string, memory?: ConversationMemory | null) => {
    if (!memory) return;
    setConversations(prev => prev.map(conv => {
      if (conv.id !== convId) return conv;
      return {
        ...conv,
        memory: {
          ...memory,
          conversation_id: convId
        }
      };
    }));
  };

  const updateConversationContextUsage = (convId: string, usage?: ContextUsage | null) => {
    if (!usage || typeof usage.prompt_tokens !== 'number') return;
    setConversations(prev => prev.map(conv => (
      conv.id === convId
        ? { ...conv, context_usage: usage, updated_at: nowIso() }
        : conv
    )));
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
      title: '回答已中断',
      tone: 'warning',
      message: '本次回答因离开页面或网络中断而停止。是否开启断线续传？开启后，今后的回答会在中断时自动恢复；为此服务器会在内存中临时缓存回答内容，最多 45 分钟，或在你的设备确认接收后立即删除。本次回答可重新生成。',
      confirmLabel: '开启续传',
      secondaryLabel: '仅重新生成本次',
      cancelLabel: '不了',
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
    signal?: AbortSignal
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
    const isStreamActive = () => !signal?.aborted;

    const commitAssistantState = (forceAck = false) => {
      if (!agentMessageId || !isStreamActive()) return;
      setConversations(prev => {
        let changed = false;
        const next = prev.map(conv => {
          if (conv.id !== convId) return conv;
          const nextMessages = conv.messages.map(msg => {
            if (msg.id !== agentMessageId) return msg;
            changed = true;
            return {
              ...msg,
              content: streamState.bodyText,
              thought_blocks: streamState.thoughtBlocks,
              context_messages: streamState.contextMessages,
              thought_signature: streamState.currentSignature || msg.thought_signature,
              download_path: streamState.currentDownloadPath || msg.download_path,
              stream_id: streamState.streamId || msg.stream_id,
              stream_buffered: streamState.buffered,
              stream_status: streamState.status,
              last_committed_seq: streamState.lastSeq,
              updated_at: nowIso()
            };
          });
          return changed ? { ...conv, messages: nextMessages, updated_at: nowIso() } : conv;
        });
        if (changed) {
          fileDB.saveConversations(next).then(() => {
            if (streamState.buffered && streamState.streamId) {
              ackBufferedStream(streamState.streamId, streamState.lastSeq, forceAck || streamState.status === 'done');
            }
          }).catch(error => {
            console.error('Failed to persist stream progress:', error);
          });
        }
        return next;
      });
    };

    const handleLine = (line: string) => {
      if (!isStreamActive() || !line.startsWith('data: ')) return;
      const dataStr = line.slice(6).trim();
      if (!dataStr) return;
      if (dataStr === '[DONE]') return;
      try {
        const data = JSON.parse(dataStr);
        const changed = processStreamPayload(data, streamState, onFileGenerated);
        if (changed) commitAssistantState(data.type === 'done');
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
      commitAssistantState(streamState.seenDone);
      if (!streamState.seenDone && !streamState.buffered && agentMessageId) {
        await showDisconnectPrompt(convId, agentMessageId, onFileGenerated);
      }
      return isStreamActive() && streamState.seenDone;
    } catch (err) {
      if (isAbortError(err) || !isStreamActive()) return false;
      console.error('Stream read error:', err);
      commitAssistantState(false);
      if (!streamState.buffered && agentMessageId) {
        await showDisconnectPrompt(convId, agentMessageId, onFileGenerated);
      }
      return false;
    } finally {
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
    signal?: AbortSignal
  ): Promise<boolean> => {
    const token = await getAuthToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Lawver-Client': 'capacitor',
      'Origin': 'capacitor://localhost',
      'Referer': 'capacitor://localhost/',
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    await requestNativeStreamNotificationPermission().catch(() => false);

    const encoder = new TextEncoder();
    let nativeStreamId = '';
    let eventHandle: { remove: () => Promise<void> } | null = null;
    let doneHandle: { remove: () => Promise<void> } | null = null;

    const response = new Response(new ReadableStream<Uint8Array>({
      async start(controller) {
        const enqueuePayload = (payload: string) => {
          if (signal?.aborted) return;
          controller.enqueue(encoder.encode(`data: ${payload}\n\n`));
        };
        const drain = async () => {
          const active = activeNativeStreamRef.current;
          if (!active) return;
          const result = await NativeStream.drain({ streamId: active.streamId, fromIndex: active.nextIndex });
          result.events.forEach(payload => enqueuePayload(payload));
          active.nextIndex = result.nextIndex;
          if (result.done) {
            if (result.error) {
              enqueuePayload(JSON.stringify({ type: 'error', content: result.error }));
            }
            enqueuePayload('[DONE]');
            controller.close();
          }
        };

        eventHandle = await NativeStream.addListener('streamEvent', (event: NativeStreamEvent) => {
          if (event.streamId !== nativeStreamId) return;
          const active = activeNativeStreamRef.current;
          if (!active || event.index < active.nextIndex) return;
          enqueuePayload(event.payload);
          active.nextIndex = event.index + 1;
        });
        doneHandle = await NativeStream.addListener('streamDone', event => {
          if (event.streamId !== nativeStreamId) return;
          drain().catch(error => {
            controller.error(error);
          });
        });

        try {
          const started = await NativeStream.startStream({
            url: apiUrl('/api/chat'),
            headers,
            body,
          });
          nativeStreamId = started.streamId;
          activeNativeStreamRef.current = { streamId: nativeStreamId, nextIndex: 0 };
          drainNativeStreamRef.current = drain;
          await drain();
        } catch (error) {
          controller.error(error);
        }
      },
      cancel() {
        if (nativeStreamId) {
          NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
        }
      }
    }));

    try {
      const completed = await processStream(response, agentMessageId, convId, onFileGenerated, signal);
      if (nativeStreamId) {
        await NativeStream.stop({ streamId: nativeStreamId }).catch(console.error);
      }
      return completed;
    } finally {
      await eventHandle?.remove();
      await doneHandle?.remove();
      activeNativeStreamRef.current = null;
      drainNativeStreamRef.current = null;
    }
  };

  useEffect(() => {
    if (!isInitialized) return;
    const handleResume = () => {
      if (activeNativeStreamRef.current) {
        drainNativeStreamRef.current?.().catch(console.error);
        return;
      }
      resumePendingStreams().catch(console.error);
    };
    window.addEventListener('focus', handleResume);
    window.addEventListener('online', handleResume);

    let listener: { remove: () => Promise<void> } | undefined;
    if (isNative()) {
      CapacitorApp.addListener('appStateChange', ({ isActive }) => {
        if (isActive) handleResume();
      }).then(handle => {
        listener = handle;
      });
    }

    return () => {
      window.removeEventListener('focus', handleResume);
      window.removeEventListener('online', handleResume);
      listener?.remove();
    };
  }, [isInitialized, resumePendingStreams]);

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
        const body = JSON.stringify(buildChatRequestBody(
          messageContent,
          history,
          convId,
          true,
          agentMode,
          isOCPEnabled,
          memorySnapshot,
          'merge',
          undefined,
          lastContextTokens,
          resumeEnabled
        ));
        setComposerStatus(null);
        const completed = await processNativeChatStream(body, null, convId, onFileGenerated, abortController.signal);
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

          if (data.download_path) {
            const fileName = data.download_path.split('/').pop() || 'generated_file';
            onFileGenerated?.(fileName, data.download_path);
          }

          updateMessages(convId, prev => [...prev, {
            id: agentMessageId,
            role: 'assistant',
            content: data.reply,
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
        const body = JSON.stringify(buildChatRequestBody(
          content,
          history,
          convId,
          true,
          agentMode,
          isOCPEnabled,
          memorySnapshot,
          'rebuild',
          undefined,
          lastContextTokens,
          resumeEnabled
        ));
        setComposerStatus(null);
        const completed = await processNativeChatStream(body, null, convId, onFileGenerated, abortController.signal);
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

          if (data.download_path) {
            const fileName = data.download_path.split('/').pop() || 'generated_file';
            onFileGenerated?.(fileName, data.download_path);
          }

          updateMessages(convId, prev => [...prev, {
            id: agentMessageId,
            role: 'assistant',
            content: data.reply,
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
    stopActiveGeneration,
    handleUndo,
    handleEdit,
    branchConversation
  };
}
