/*
 * 模块描述：聊天状态 Hook，管理会话、消息、发送流程、编辑/撤回和对话级记忆同步。
 */

import { useState, useEffect } from 'react';
import type { BackendHistoryMessage, Conversation, ConversationMemory, Message, ThoughtBlock } from '../types';
import { fileDB } from '../lib/db';
import { chat, deleteWorkspace, MemoryRevisionConflictError, syncConversationMemory } from '../services/api';

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

const GREETING_MESSAGE = `您好，我是 **Lawyance**，由 **工大法智团队** 开发的专业法律AI助手。

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
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string>('');
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(true);
  const [agentMode, setAgentMode] = useState('default');
  const [isOCPEnabled, setIsOCPEnabled] = useState(true);
  const [isInitialized, setIsInitialized] = useState(false);

  const currentConversation = conversations.find(c => c.id === currentId) || { id: '', title: '', messages: [] };
  const messages = currentConversation.messages;
  const nowIso = () => new Date().toISOString();

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
        return { ...conv, messages: updater(conv.messages), updated_at: nowIso() };
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
    memorySnapshot: ConversationMemory
  ) => {
    try {
      return await chat(message, history, convId, stream, agentMode, isOCPEnabled, memorySnapshot);
    } catch (error) {
      if (!(error instanceof MemoryRevisionConflictError)) throw error;
      updateConversationMemory(convId, error.detail?.memory_snapshot as ConversationMemory | undefined);
      return chat(message, history, convId, stream, agentMode, isOCPEnabled, memorySnapshot, 'server_merge');
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
      const response = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          history: [{ role: 'user', content: titleSource.substring(0, 200) }]
        })
      });

      if (response.ok) {
        const data = await response.json();
        let title = String(data.title || '').replace(/["']/g, '').trim();
        if (title.length > 20) title = title.substring(0, 20) + '...';
        applyTitleIfCurrent(title);
      }
    } catch (error) {
      console.error('Failed to summarize:', error);
      const fallbackTitle = titleSource.substring(0, 15) + (titleSource.length > 15 ? '...' : '');
      applyTitleIfCurrent(fallbackTitle);
    }
  };

  const processStream = async (response: Response, agentMessageId: string | null, convId: string, onFileGenerated?: (name: string, path: string) => void) => {
    const reader = response.body?.getReader();
    if (!reader) {
      setIsLoading(false);
      return;
    }

    const decoder = new TextDecoder();
    let thoughtBlocks: ThoughtBlock[] = [];
    let contextMessages: BackendHistoryMessage[] = [];
    let bodyText = '';
    let currentSignature = '';
    let currentDownloadPath = '';
    let streamBuffer = '';
    let thoughtIdCounter = 0;

    const nextThoughtId = () => `${agentMessageId || 'assistant'}-thought-${thoughtIdCounter++}`;

    const handleStreamData = (data: any) => {
      if (data.type === 'content') {
        bodyText += data.content || '';
      } else if (data.type === 'thought') {
        const thoughtType = (['reasoning', 'draft', 'tool', 'ocp', 'memory'].includes(data.thought_type)
          ? data.thought_type
          : 'reasoning') as ThoughtBlock['type'];
        const shouldAppend = data.mode === 'append' || thoughtType === 'reasoning' || thoughtType === 'draft';
        thoughtBlocks = appendThoughtBlock(
          thoughtBlocks,
          data.content || '',
          thoughtType,
          nextThoughtId(),
          shouldAppend
        );
      } else if (data.type === 'thought_signature') {
        currentSignature = data.content;
      } else if (data.type === 'download_path') {
        if (data.content && data.content !== currentDownloadPath) {
          currentDownloadPath = data.content;
          const fileName = currentDownloadPath.split('/').pop() || 'generated_file';
          onFileGenerated?.(fileName, currentDownloadPath);
        }
      } else if (data.type === 'memory_sync') {
        updateConversationMemory(convId, data.content as ConversationMemory);
      } else if (data.type === 'history_trace') {
        const traceMessages = Array.isArray(data.content) ? data.content : [data.content];
        contextMessages = [
          ...contextMessages,
          ...traceMessages
            .map((item: BackendHistoryMessage) => normalizeBackendMessage(item))
            .filter((item: BackendHistoryMessage | null): item is BackendHistoryMessage => Boolean(item))
        ];
      } else if (data.type === 'content_replace') {
        bodyText = data.content || '';
      } else if (data.type === 'error') {
        bodyText += `\n\n**Error:** ${data.content}`;
      }
    };

    const commitAssistantState = () => {
      updateMessages(convId, prev => prev.map(msg =>
        msg.id === agentMessageId ? {
          ...msg,
          content: bodyText,
          thought_blocks: thoughtBlocks,
          context_messages: contextMessages,
          thought_signature: currentSignature || msg.thought_signature,
          download_path: currentDownloadPath || msg.download_path
        } : msg
      ));
    };

    if (!agentMessageId) {
      agentMessageId = (Date.now() + 1).toString();
      const now = nowIso();
      updateMessages(convId, prev => [...prev, { id: agentMessageId!, role: 'assistant', content: '', thought_blocks: [], created_at: now, updated_at: now }]);
    }

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        streamBuffer += decoder.decode(value, { stream: true });
        const lines = streamBuffer.split('\n');
        streamBuffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);
              handleStreamData(data);
            } catch (e) {
              console.warn('Failed to parse stream data:', dataStr);
            }
          }
        }

        if (bodyText || thoughtBlocks.length > 0 || currentSignature || currentDownloadPath) {
          commitAssistantState();
        }
      }

      if (streamBuffer.trim().startsWith('data: ')) {
        try {
          const dataStr = streamBuffer.trim().slice(6);
          if (dataStr && dataStr !== '[DONE]') {
            const data = JSON.parse(dataStr);
            handleStreamData(data);
          }
        } catch (e) {
          console.warn('Failed to parse trailing stream data:', streamBuffer);
        }
      }
      commitAssistantState();
    } catch (err) {
      console.error('Stream read error:', err);
    } finally {
      reader.releaseLock();
      setIsLoading(false);
      onFileGenerated?.('sync', '');
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

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setPendingUploads([]);
    setIsLoading(true);

    // Pre-flight sync: Ensure all files are synced to the server before sending the request
    if (syncFiles) {
      await syncFiles();
    }

    try {
      const response = await sendChatWithMemoryRetry(messageContent, history, convId, isStreaming, memorySnapshot);

      if (isStreaming) {
        await processStream(response, null, convId, onFileGenerated);
      } else {
        const data = await response.json();
        const agentMessageId = (Date.now() + 1).toString();

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
        setIsLoading(false);
        onFileGenerated?.('sync', '');
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
      console.error('Failed to send message:', error);
      setIsLoading(false);
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

    updateMessages(convId, () => retainedMessages);
    updateConversationMemory(convId, memorySnapshot);
    setIsLoading(true);

    // Pre-flight sync: Ensure all files are synced to the server before sending the request
    if (syncFiles) {
      await syncFiles();
    }

    try {
      const now = nowIso();
      const userMessage: Message = { id: Date.now().toString(), role: 'user', content: content, created_at: now, updated_at: now };
      updateMessages(convId, prev => [...prev, userMessage]);

      const response = await sendChatWithMemoryRetry(content, history, convId, isStreaming, memorySnapshot);

      if (isStreaming) {
        await processStream(response, null, convId, onFileGenerated);
      } else {
        const data = await response.json();
        const agentMessageId = (Date.now() + 1).toString();

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
        setIsLoading(false);
        onFileGenerated?.('sync', '');
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
      console.error('Failed to regenerate message:', error);
      setIsLoading(false);
    }
  };

  const handleUndo = async (convId: string, messageId: string, setPendingUploads: (val: any) => void) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgIndex = conv.messages.findIndex(m => m.id === messageId);
    if (msgIndex === -1) return;

    const msg = conv.messages[msgIndex];
    if (msg.role !== 'user') return;

    let textContent = msg.content;
    let filesToRestore: {name: string, path: string}[] = [];

    const fileInfoRegex = new RegExp("\\[用户已上传以下文件，请根据需要进行读取和处理\\]\\n([\\s\\S]*)$");
    const match = msg.content.match(fileInfoRegex);
    if (match) {
      textContent = msg.content.replace(match[0], '').trim();
      filesToRestore = match[1].split('\n').filter(line => line.startsWith('- ')).map(line => {
        const nameMatch = line.match(/^- (.*?) \\(路径: (.*?)\\)/);
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

  return {
    conversations,
    currentId,
    setCurrentId,
    input,
    setInput,
    isLoading,
    isStreaming,
    setIsStreaming,
    agentMode,
    setAgentMode,
    isOCPEnabled,
    setIsOCPEnabled,
    isInitialized,
    currentConversation,
    messages,
    handleNewChat,
    deleteConversation,
    handleSend: async (pendingUploads: {name: string, path: string}[], setPendingUploads: (val: any) => void, onFileGenerated?: (name: string, path: string) => void, syncFiles?: () => Promise<void>, isLowStorage?: boolean) => {
      if (isLowStorage) {
        alert('本地存储空间不足！请点击侧边栏下方的存储指示器进行【导出并清理】，否则无法继续发送消息。');
        return;
      }
      return handleSend(pendingUploads, setPendingUploads, onFileGenerated, syncFiles);
    },
    handleRegenerateMessage,
    handleUndo,
    handleEdit
  };
}
