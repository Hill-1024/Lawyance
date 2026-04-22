import { useState, useEffect, useRef } from 'react';
import { Conversation, Message } from '../types';
import { fileDB } from '../lib/db';
import { chat, getWorkspaceFiles, restoreFile, deleteWorkspace } from '../services/api';

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

const formatHistoryForBackend = (messages: Message[]) => {
  return messages.map(msg => ({
    role: (msg.role === 'assistant' || (msg.role as string) === 'agent') ? 'assistant' : msg.role,
    content: msg.content
  }));
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

  useEffect(() => {
    const saved = localStorage.getItem('conversations');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed.length > 0) {
          setConversations(parsed);
          setCurrentId(parsed[0].id);
        } else {
          handleNewChat();
        }
      } catch (e) {
        handleNewChat();
      }
    } else {
      handleNewChat();
    }
    setIsInitialized(true);
  }, []);

  useEffect(() => {
    if (isInitialized) {
      localStorage.setItem('conversations', JSON.stringify(conversations));
    }
  }, [conversations, isInitialized]);

  const handleNewChat = () => {
    const newId = generateUUID();
    setConversations(prev => [{
      id: newId,
      title: 'New Conversation',
      messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE }]
    }, ...prev]);
    setCurrentId(newId);
  };

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setConversations(prev => {
      const filtered = prev.filter(c => c.id !== id);
      if (filtered.length === 0) {
        const newId = generateUUID();
        setCurrentId(newId);
        return [{ id: newId, title: 'New Conversation', messages: [{ id: generateUUID(), role: 'assistant', content: GREETING_MESSAGE }] }];
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
        return { ...conv, messages: updater(conv.messages) };
      }
      return conv;
    }));
  };

  const summarizeConversation = async (convId: string, messagesToSummarize?: Message[]) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgs = messagesToSummarize || conv.messages;
    const userMessages = msgs.filter(m => m.role === 'user');
    if (userMessages.length === 0) return;

    const firstUserMessage = userMessages[0].content;
    const cleanMessage = firstUserMessage.replace(/\[用户已上传以下文件.*?\]/g, '').trim();
    const titleSource = cleanMessage.length > 0 ? cleanMessage : "File Analysis";

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `Please summarize this message into a short title (max 15 chars, no quotes, no punctuation, just the title text): "${titleSource.substring(0, 200)}"`,
          history: [],
          conversation_id: 'summary_' + Date.now(),
          stream: false,
          agent_mode: 'default'
        })
      });

      if (response.ok) {
        const data = await response.json();
        let title = data.reply.replace(/["']/g, '').trim();
        if (title.length > 20) title = title.substring(0, 20) + '...';

        setConversations(prev => prev.map(c => {
          if (c.id === convId) {
            return { ...c, title };
          }
          return c;
        }));
      }
    } catch (error) {
      console.error('Failed to summarize:', error);
      const fallbackTitle = titleSource.substring(0, 15) + (titleSource.length > 15 ? '...' : '');
      setConversations(prev => prev.map(c => {
        if (c.id === convId) {
          return { ...c, title: fallbackTitle };
        }
        return c;
      }));
    }
  };

  const processStream = async (response: Response, agentMessageId: string | null, convId: string, onFileGenerated?: (name: string, path: string) => void) => {
    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let currentText = '';
    let currentSignature = '';
    let currentDownloadPath = '';
    let isInThought = false;

    if (!agentMessageId) {
      agentMessageId = (Date.now() + 1).toString();
      updateMessages(convId, prev => [...prev, { id: agentMessageId!, role: 'assistant', content: '' }]);
    }

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);
              if (data.type === 'content') {
                // Only close thought block if there's actual non-whitespace content
                if (isInThought && data.content.trim()) {
                  currentText += '</think>\n\n';
                  isInThought = false;
                }
                currentText += data.content;
              } else if (data.type === 'thought') {
                if (!isInThought) {
                  currentText += '<think>\n';
                  isInThought = true;
                }
                currentText += data.content;
              } else if (data.type === 'thought_signature') {
                currentSignature = data.content;
              } else if (data.type === 'download_path') {
                if (data.content && data.content !== currentDownloadPath) {
                  currentDownloadPath = data.content;
                  const fileName = currentDownloadPath.split('/').pop() || 'generated_file';
                  onFileGenerated?.(fileName, currentDownloadPath);
                }
              } else if (data.type === 'content_replace') {
                // OCP-Stream: 用修正后的内容替换已有正文，保留所有思考块
                if (isInThought) {
                  currentText += '\n</think>\n\n';
                  isInThought = false;
                }
                // 提取所有 <think>...</think> 块
                const thinkBlocks: string[] = [];
                const thinkRegex = /<think>[\s\S]*?<\/think>/g;
                let thinkMatch;
                while ((thinkMatch = thinkRegex.exec(currentText)) !== null) {
                  thinkBlocks.push(thinkMatch[0]);
                }
                // 用思考块 + 修正后的正文重构
                currentText = (thinkBlocks.length > 0 ? thinkBlocks.join('\n\n') + '\n\n' : '') + data.content;
              } else if (data.type === 'error') {
                currentText += `\n\n**Error:** ${data.content}`;
              }
            } catch (e) {
              console.warn('Failed to parse stream data:', dataStr);
            }
          }
        }

        if (currentText || currentSignature || currentDownloadPath) {
          let displayUpdateText = currentText;
          if (currentSignature) {
            displayUpdateText = `[Thought Process: ${currentSignature}]\n${displayUpdateText}`;
          }

          updateMessages(convId, prev => prev.map(msg =>
            msg.id === agentMessageId ? {
              ...msg,
              content: displayUpdateText,
              thought_signature: currentSignature || msg.thought_signature,
              download_path: currentDownloadPath || msg.download_path
            } : msg
          ));
        }
      }

      if (isInThought) {
        currentText += '\n</think>';
        isInThought = false;

        // Final update to ensure the closed tag is reflected
        updateMessages(convId, prev => prev.map(msg =>
          msg.id === agentMessageId ? { ...msg, content: currentText } : msg
        ));
      }
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
      content: messageContent
    };

    let convId = currentId;
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const isFirstUserMessage = conv.messages.filter(m => m.role === 'user').length === 0;
    const history = formatHistoryForBackend(conv.messages);

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setPendingUploads([]);
    setIsLoading(true);

    // Pre-flight sync: Ensure all files are synced to the server before sending the request
    if (syncFiles) {
      await syncFiles();
    }

    try {
      const response = await chat(messageContent, history, convId, isStreaming, agentMode, isOCPEnabled);

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
          download_path: data.download_path
        }]);
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
    const history = formatHistoryForBackend(conv.messages.slice(0, msgIndex));

    updateMessages(convId, prev => prev.slice(0, msgIndex));
    setIsLoading(true);

    // Pre-flight sync: Ensure all files are synced to the server before sending the request
    if (syncFiles) {
      await syncFiles();
    }

    try {
      const userMessage: Message = { id: Date.now().toString(), role: 'user', content: content };
      updateMessages(convId, prev => [...prev, userMessage]);

      const response = await chat(content, history, convId, isStreaming, agentMode, isOCPEnabled);

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
          download_path: data.download_path
        }]);
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
    updateMessages(convId, prev => prev.slice(0, msgIndex));
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
    handleSend,
    handleRegenerateMessage,
    handleUndo,
    handleEdit
  };
}
