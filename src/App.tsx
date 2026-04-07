import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, Sparkles, Menu, Mic, Info, X, Plus, ChevronUp, ChevronDown, Settings2, Trash2, Sun, Moon, Monitor, Paperclip } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Mermaid } from './components/Mermaid';
import { motion } from 'motion/react';

type Message = {
  id: string;
  role: 'user' | 'agent';
  content: string;
};

type Conversation = {
  id: string;
  title: string;
  messages: Message[];
};

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([
    { id: 'default', title: 'New Chat', messages: [] }
  ]);
  const [currentId, setCurrentId] = useState<string>('default');

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [isStreaming, setIsStreaming] = useState(true);
  const [agentMode, setAgentMode] = useState('default');

  const [themeMode, setThemeMode] = useState<'light' | 'system' | 'dark'>('system');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadedFiles, setUploadedFiles] = useState<{name: string, path: string}[]>([]);
  const [isDragging, setIsDragging] = useState(false);

  const handleFileUpload = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('conversation_id', currentId);

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        const filePath = data.file_path;
        setUploadedFiles(prev => [...prev, { name: file.name, path: filePath }]);
      } else {
        console.error('Upload failed');
      }
    } catch (err) {
      console.error('Upload error', err);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileUpload(file);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeUploadedFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      handleFileUpload(file);
    }
  };

  useEffect(() => {
    const root = window.document.documentElement;
    const applyTheme = () => {
      if (themeMode === 'dark' || (themeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
    };

    applyTheme();

    if (themeMode === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const listener = () => applyTheme();
      mediaQuery.addEventListener('change', listener);
      return () => mediaQuery.removeEventListener('change', listener);
    }
  }, [themeMode]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const hasInitialized = useRef(false);

  useEffect(() => {
    const sendHeartbeat = async () => {
      try {
        await fetch('/api/heartbeat', { method: 'POST' });
      } catch (e) {
        console.error('Heartbeat failed', e);
      }
    };
    const interval = setInterval(sendHeartbeat, 10000); // 每 10 秒发送一次心跳
    sendHeartbeat();
    return () => clearInterval(interval);
  }, []);

  const currentConversation = conversations.find(c => c.id === currentId) || conversations[0] || { id: 'default', title: 'New Chat', messages: [] };
  const messages = currentConversation.messages;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleScroll = (e: React.UIEvent<HTMLElement>) => {
    const target = e.currentTarget;
    const isBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
    setIsAtBottom(isBottom);
  };

  useEffect(() => {
    if (isAtBottom) {
      scrollToBottom();
    }
  }, [messages]);

  const updateMessages = (convId: string, updater: (prev: Message[]) => Message[]) => {
    setConversations(prev => prev.map(c =>
      c.id === convId ? { ...c, messages: updater(c.messages) } : c
    ));
  };

  const summarizeConversation = async (convId: string) => {
    try {
      const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: convId })
      });
      if (res.ok) {
        const data = await res.json();
        setConversations(prev => prev.map(c =>
          c.id === convId ? { ...c, title: data.title } : c
        ));
      }
    } catch (e) {
      console.error('Failed to summarize', e);
    }
  };

  const handleNewChat = async (forceId?: string) => {
    const newId = forceId || Date.now().toString();

    setConversations(prev => {
      if (prev.some(c => c.id === newId)) return prev;
      return [{ id: newId, title: 'New Chat', messages: [] }, ...prev];
    });
    setCurrentId(newId);
    setIsSidebarOpen(false);

    setIsLoading(true);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '介绍自己', conversation_id: newId, stream: isStreaming, agent_mode: agentMode })
      });

      if (!response.ok) throw new Error('Network response was not ok');

      if (isStreaming) {
        await processStream(response, null, newId);
      } else {
        const data = await response.json();
        const agentMessageId = Date.now().toString();
        updateMessages(newId, prev => [...prev, { id: agentMessageId, role: 'agent', content: data.reply }]);
        setIsLoading(false);
      }
    } catch (error) {
      console.error('Error connecting to Python agent:', error);
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'agent',
        content: '抱歉，连接到 Agent 时发生错误。\n\n**如果你在 AI Studio 云端预览**：云端环境不支持运行 Python 后端。请点击右上角的“Export”下载代码，然后在本地运行 `npm install` 和 `npm run dev` 即可正常使用。\n\n**如果你在本地运行**：请检查 Python 后端服务是否正常启动。'
      };
      updateMessages(newId, prev => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const deleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch('/api/delete_conversation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: convId })
      });
      if (res.ok) {
        const filtered = conversations.filter(c => c.id !== convId);
        if (filtered.length === 0) {
          setConversations([]);
          await handleNewChat();
        } else {
          setConversations(filtered);
          if (currentId === convId) {
            setCurrentId(filtered[0].id);
          }
        }
      }
    } catch (e) {
      console.error('Failed to delete conversation', e);
    }
  };

  const processStream = async (response: Response, existingMessageId: string | null, convId: string) => {
    console.log(`开始处理流式响应... 会话ID: ${convId}, 消息ID: ${existingMessageId}`);
    const reader = response.body?.getReader();
    if (!reader) {
      console.error('无法获取响应流 reader');
      throw new Error('No reader available');
    }

    const decoder = new TextDecoder();
    let done = false;
    let text = '';
    let messageId = existingMessageId;

    try {
      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          console.log(`收到数据块 (长度: ${chunk.length}):`, chunk.substring(0, 20) + (chunk.length > 20 ? '...' : ''));

          if (!messageId) {
            messageId = Date.now().toString();
            console.log(`创建新的助手消息气泡, ID: ${messageId}`);
            updateMessages(convId, prev => [...prev, { id: messageId!, role: 'agent', content: '' }]);
            setIsLoading(false);
          }

          text += chunk;
          updateMessages(convId, prev => prev.map(msg =>
            msg.id === messageId ? { ...msg, content: text } : msg
          ));
        }
      }
      console.log('流式响应处理完成，总长度:', text.length);
    } catch (err) {
      console.error('读取流时发生错误:', err);
      setIsLoading(false);
    } finally {
      reader.releaseLock();
    }
  };

  useEffect(() => {
    if (hasInitialized.current) return;
    hasInitialized.current = true;

    const initChat = async () => {
      console.log('初始化会话...');
      setIsLoading(true);

      try {
        const res = await fetch('/api/conversations');
        if (res.ok) {
          const data = await res.json();
          console.log('从后端加载的原始数据:', data);
          const loadedConversations: Conversation[] = [];

          for (const [id, sessionData] of Object.entries(data)) {
            const { title, messages: mem } = sessionData as any;
            const messages: Message[] = [];

            let msgIdCounter = 0;
            let isFirstUserMessage = true;
            for (const m of mem) {
              if (m.role === 'system') continue;
              if (m.role === 'tool') continue;

              if (m.role === 'user') {
                if (isFirstUserMessage && m.content === '介绍自己') {
                  isFirstUserMessage = false;
                  continue;
                }
                isFirstUserMessage = false;
                messages.push({ id: `${id}-${msgIdCounter++}`, role: 'user', content: m.content || '' });
              } else if (m.role === 'assistant') {
                if (m.content) {
                  const lastMsg = messages[messages.length - 1];
                  if (lastMsg && lastMsg.role === 'agent') {
                    lastMsg.content += '\n' + m.content;
                  } else {
                    messages.push({ id: `${id}-${msgIdCounter++}`, role: 'agent', content: m.content });
                  }
                }
              }
            }

            loadedConversations.push({ id, title, messages });
          }

          if (loadedConversations.length > 0) {
            console.log('成功解析的会话列表:', loadedConversations);
            loadedConversations.sort((a, b) => b.id.localeCompare(a.id));
            setConversations(loadedConversations);
            setCurrentId(loadedConversations[0].id);
            setIsLoading(false);
            setIsInitialized(true);
            return;
          } else {
            console.log('未发现有效会话，准备创建新会话');
          }
        } else {
          console.error('获取会话失败，状态码:', res.status);
        }
      } catch (e) {
        console.error("加载会话时发生异常:", e);
      }

      console.log('执行 handleNewChat 创建初始会话');
      await handleNewChat('default');
      setIsInitialized(true);
    };

    initChat();
  }, []);

  const handleSend = async () => {
    if ((!input.trim() && uploadedFiles.length === 0) || isLoading || !isInitialized) {
      console.log('handleSend 被拦截:', { hasInput: !!input.trim(), hasFiles: uploadedFiles.length > 0, isLoading, isInitialized });
      return;
    }

    // Force scroll to bottom when user sends a message
    setIsAtBottom(true);

    let messageContent = input.trim();
    if (uploadedFiles.length > 0) {
      const fileInfo = uploadedFiles.map(f => `- ${f.name} (路径: ${f.path})`).join('\n');
      messageContent += messageContent ? `\n\n[用户已上传以下文件，请根据需要进行读取和处理]\n${fileInfo}` : `[用户已上传以下文件，请根据需要进行读取和处理]\n${fileInfo}`;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageContent
    };

    console.log('准备发送消息:', userMessage);

    // 确保有有效的会话 ID
    let convId = currentId;
    if (!convId || !conversations.find(c => c.id === convId)) {
      convId = conversations[0]?.id || 'default';
      console.log(`修正会话 ID: ${currentId} -> ${convId}`);
      setCurrentId(convId);
    }

    const isFirstUserMessage = (conversations.find(c => c.id === convId)?.messages.filter(m => m.role === 'user').length || 0) === 0;

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setUploadedFiles([]);
    setIsLoading(true);

    try {
      console.log(`请求后端 /api/chat, 会话: ${convId}, 模式: ${agentMode}`);
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage.content,
          conversation_id: convId,
          stream: isStreaming,
          agent_mode: agentMode
        })
      });

      if (!response.ok) {
        console.error('后端响应错误:', response.status, response.statusText);
        throw new Error('Network response was not ok');
      }

      if (isStreaming) {
        await processStream(response, null, convId);
      } else {
        const data = await response.json();
        console.log('收到非流式响应:', data);
        const agentMessageId = (Date.now() + 1).toString();
        updateMessages(convId, prev => [...prev, { id: agentMessageId, role: 'agent', content: data.reply }]);
        setIsLoading(false);
      }

      if (isFirstUserMessage) {
        await summarizeConversation(convId);
      }

    } catch (error) {
      console.error('Error connecting to Python agent:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'agent',
        content: '抱歉，连接到 Agent 时发生错误。'
      };
      updateMessages(convId, prev => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const markdownComponents: any = {
    a(props: any) {
      const { node, ...rest } = props;
      return <a target="_blank" rel="noopener noreferrer" {...rest} />;
    },
    pre(props: any) {
      const { children, ...rest } = props;
      const childrenArray = React.Children.toArray(children);
      const child = childrenArray[0] as any;

      if (child && child.type === 'code' && typeof child.props?.className === 'string' && child.props.className.includes('language-mermaid')) {
        return <>{children}</>;
      }
      return <pre {...rest}>{children}</pre>;
    },
    code(props: any) {
      const {children, className, node, ...rest} = props;
      const match = /language-(\w+)/.exec(className || '');
      if (match && match[1] === 'mermaid') {
        return <Mermaid chart={String(children).replace(/\n$/, '')} />;
      }
      return <code {...rest} className={className}>{children}</code>;
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 font-sans selection:bg-blue-200 dark:selection:bg-blue-900 selection:text-blue-900 dark:selection:text-blue-100">

      {/* Sidebar Overlay */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40 transition-opacity backdrop-blur-sm"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`fixed top-0 left-0 h-full w-80 bg-gray-50 dark:bg-gray-900 shadow-2xl z-50 transform transition-transform duration-300 ease-in-out ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'} flex flex-col rounded-r-3xl border-r border-gray-200 dark:border-gray-800`}>
        <div className="p-6 pb-4 flex items-center justify-between">
          <h2 className="font-medium text-xl text-gray-900 dark:text-gray-100">Conversations</h2>
          <button onClick={() => setIsSidebarOpen(false)} className="p-2 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400">
            <X size={24} />
          </button>
        </div>
        <div className="px-4 pb-4">
          <button
            onClick={() => handleNewChat()}
            className="w-full py-4 px-6 bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white rounded-full flex items-center justify-center gap-2 transition-all font-medium shadow-md hover:shadow-lg active:scale-[0.98]"
          >
            <Plus size={20} />
            New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-4 flex flex-col gap-1">
          {conversations.map(conv => (
            <div
              key={conv.id}
              onClick={() => {
                setCurrentId(conv.id);
                setIsSidebarOpen(false);
              }}
              className={`w-full text-left px-4 py-3.5 rounded-full transition-colors flex items-center justify-between group cursor-pointer ${
                conv.id === currentId ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium' : 'hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400'
              }`}
            >
              <span className="truncate pr-2 text-[15px]">{conv.title}</span>
              <button
                onClick={(e) => deleteConversation(conv.id, e)}
                className={`p-2 rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-300 dark:hover:bg-gray-700 ${conv.id === currentId ? 'hover:bg-blue-200 dark:hover:bg-blue-800' : ''}`}
                title="Delete chat"
              >
                <Trash2 size={18} className={conv.id === currentId ? 'text-blue-700 dark:text-blue-300' : 'text-gray-600 dark:text-gray-400'} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Top App Bar */}
      <header className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 shrink-0 z-10 sticky top-0 border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsSidebarOpen(true)}
            className="p-3 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400"
          >
            <Menu size={24} />
          </button>
          <h1 className="text-[22px] font-medium tracking-tight ml-1">GDUT-Lawver</h1>
        </div>
        <div className="flex items-center gap-1 relative">
          <div className="flex items-center bg-gray-200 dark:bg-gray-800 rounded-full p-1 relative">
            <motion.div
              className="absolute top-1 bottom-1 w-9 bg-white dark:bg-gray-600 rounded-full shadow-sm"
              initial={false}
              animate={{
                x: themeMode === 'light' ? 0 : themeMode === 'system' ? 36 : 72
              }}
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
            />
            <button
              onClick={() => setThemeMode('light')}
              className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'light' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
              title="Light Mode"
            >
              <Sun size={18} />
            </button>
            <button
              onClick={() => setThemeMode('system')}
              className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'system' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
              title="System Mode"
            >
              <Monitor size={18} />
            </button>
            <button
              onClick={() => setThemeMode('dark')}
              className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'dark' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
              title="Dark Mode"
            >
              <Moon size={18} />
            </button>
          </div>
        </div>
      </header>

      {/* Chat Area */}
      <main
        ref={scrollContainerRef as any}
        onScroll={handleScroll}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth transition-colors ${isDragging ? 'bg-blue-50/50 dark:bg-blue-900/20 border-2 border-dashed border-blue-400 dark:border-blue-600' : ''}`}
      >
        <div className="max-w-3xl mx-auto flex flex-col gap-6">
          {messages.map((msg) => {
            let thinks: string[] = [];
            let mainContent = "";
            let isThinking = false;

            if (msg.role === 'agent') {
              let thinkDepth = 0;
              let currentThink = "";
              let hasFoundFirstThink = false;
              let i = 0;
              const content = msg.content || "";

              while (i < content.length) {
                if (content.startsWith("<think>", i)) {
                  hasFoundFirstThink = true;
                  thinkDepth++;
                  i += 7;
                  if (thinkDepth === 1) {
                    currentThink = "";
                  }
                } else if (content.startsWith("</think>", i)) {
                  if (thinkDepth > 0) {
                    thinkDepth--;
                    i += 8;
                    if (thinkDepth === 0) {
                      thinks.push(currentThink);
                      currentThink = "";
                    }
                  } else {
                    i += 8; // Ignore stray </think>
                  }
                } else {
                  if (thinkDepth > 0) {
                    currentThink += content[i];
                  } else {
                    // Collect content outside of think tags.
                    // We trim leading whitespace only if mainContent is empty.
                    if (mainContent.length > 0 || !content[i].match(/\s/)) {
                      mainContent += content[i];
                    }
                  }
                  i++;
                }
              }

              mainContent = mainContent.trim();

              if (thinkDepth > 0) {
                thinks.push(currentThink);
                isThinking = true;
              }
            } else {
              mainContent = msg.content;
            }

            let sourceContent = "";
            if (msg.role === 'agent') {
              const sourceRegex = /(?:---\s*\n)?\s*\*\*参考信源[：:]\*\*\s*\n([\s\S]*)$/;
              const sourceMatch = mainContent.match(sourceRegex);
              if (sourceMatch) {
                sourceContent = sourceMatch[1];
                mainContent = mainContent.replace(sourceMatch[0], "").trim();
              }
            }

            // Hide empty agent messages (e.g., tool calls with only whitespace content)
            if (msg.role === 'agent' && thinks.length === 0 && mainContent.trim() === '' && !sourceContent) {
              return null;
            }

            return (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                key={msg.id}
                className={`flex gap-4 max-w-[85%] sm:max-w-[75%] ${msg.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}
              >
                {/* Agent Avatar */}
                {msg.role === 'agent' && (
                  <div className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center mt-1 shadow-sm text-white bg-blue-600 dark:bg-blue-500">
                    <Sparkles size={20} />
                  </div>
                )}

                <div className="flex flex-col gap-2 min-w-0 w-full">
                  {/* Thinking Process */}
                  {msg.role === 'agent' && thinks.length > 0 && (
                    <details className="group mb-1">
                      <summary className="flex items-center gap-2 cursor-pointer text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors list-none [&::-webkit-details-marker]:hidden select-none w-fit bg-gray-200/50 dark:bg-gray-800/50 px-4 py-2 rounded-full border border-gray-200 dark:border-gray-700">
                        <ChevronDown size={16} className="transform group-open:-rotate-180 transition-transform duration-200" />
                        {isThinking ? (
                          <span className="flex items-center gap-2">
                            Thinking
                            <span className="flex gap-1">
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.2 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.4 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                            </span>
                          </span>
                        ) : "Thought Process"}
                      </summary>
                      <div className="mt-3 mb-2 px-5 py-4 text-[15px] text-gray-600 dark:text-gray-300 border-l-4 border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-800/50 whitespace-pre-wrap prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-200 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none rounded-r-2xl">
                        {thinks.map((think, i) => (
                          <div key={i} className={i > 0 ? "mt-4 pt-4 border-t border-gray-200 dark:border-gray-700" : ""}>
                            <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{think}</Markdown>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Message Bubble */}
                  {mainContent.trim() || msg.role === 'user' || sourceContent ? (
                    <div className={`px-6 py-4 text-[16px] leading-relaxed shadow-sm w-fit ${
                      msg.role === 'user'
                        ? 'bg-blue-600 dark:bg-blue-500 text-white rounded-[28px] rounded-tr-[8px]'
                        : 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[28px] rounded-tl-[8px] border border-gray-200 dark:border-gray-700'
                    }`}
                    >
                      {msg.role === 'user' ? (
                        <div className="flex flex-col gap-2">
                          {(() => {
                            const fileInfoRegex = /\[用户已上传以下文件，请根据需要进行读取和处理\]\n([\s\S]*)$/;
                            const match = msg.content.match(fileInfoRegex);
                            if (match) {
                              const textContent = msg.content.replace(match[0], '').trim();
                              const files = match[1].split('\n').filter(line => line.startsWith('- ')).map(line => {
                                const nameMatch = line.match(/^- (.*?) \(路径:/);
                                return nameMatch ? nameMatch[1] : line;
                              });
                              return (
                                <>
                                  {textContent && <p className="whitespace-pre-wrap">{textContent}</p>}
                                  {files.length > 0 && (
                                    <div className="flex flex-wrap gap-2 mt-1">
                                      {files.map((file, i) => (
                                        <div key={i} className="flex items-center gap-1.5 bg-blue-700/50 dark:bg-blue-600/50 rounded-full px-3 py-1 text-sm">
                                          <Paperclip size={14} />
                                          <span className="truncate max-w-[200px]">{file}</span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </>
                              );
                            }
                            return <p className="whitespace-pre-wrap">{msg.content}</p>;
                          })()}
                        </div>
                      ) : (
                        <div className="flex flex-col gap-4">
                          {mainContent.trim() && (
                            <div className="prose prose-base dark:prose-invert max-w-none prose-p:leading-relaxed prose-headings:text-gray-900 dark:prose-headings:text-gray-100 prose-headings:font-medium prose-strong:text-gray-900 dark:prose-strong:text-gray-100 prose-strong:font-medium prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-100 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-100 dark:prose-pre:bg-gray-900 prose-pre:text-gray-900 dark:prose-pre:text-gray-100 prose-pre:border prose-pre:border-gray-200 dark:prose-pre:border-gray-700 prose-pre:rounded-2xl">
                              <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{mainContent}</Markdown>
                            </div>
                          )}
                          {sourceContent && (
                            <div className="source-list-container text-[14px] text-gray-600 dark:text-gray-400">
                              <div className="font-medium mb-2 text-gray-900 dark:text-gray-100 flex items-center gap-2 uppercase tracking-wider text-[13px]">
                                <Info size={16} />
                                Sources
                              </div>
                              <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-li:my-1 prose-ol:pl-4 prose-ul:pl-4">
                                <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{sourceContent}</Markdown>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              </motion.div>
            );
          })}

          {/* Loading Indicator */}
          {isLoading && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-4 max-w-[85%] self-start">
              <div className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center mt-1 shadow-sm text-white bg-blue-600 dark:bg-blue-500">
                <Sparkles size={20} />
              </div>
              <div className="bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[28px] rounded-tl-[8px] px-6 py-4 flex items-center gap-3 shadow-sm border border-gray-200 dark:border-gray-700">
                <Loader2 size={20} className="animate-spin text-gray-500 dark:text-gray-400" />
                <span className="text-[15px] font-medium text-gray-500 dark:text-gray-400">Agent is typing...</span>
              </div>
            </motion.div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Bottom App Bar / Input Area */}
      <footer className="bg-gray-50 dark:bg-gray-900 p-4 shrink-0 pb-8 border-t border-gray-200 dark:border-gray-800">
        <div className="max-w-3xl mx-auto relative flex flex-col gap-3">

          {isInputExpanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="bg-white dark:bg-gray-800 rounded-3xl p-5 flex flex-col gap-5 overflow-hidden border border-gray-200 dark:border-gray-700 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Settings2 size={24} className="text-gray-600 dark:text-gray-400" />
                  <span className="text-[15px] font-medium text-gray-900 dark:text-gray-100">Enable Streaming Output</span>
                </div>
                <button
                  onClick={() => setIsStreaming(!isStreaming)}
                  className={`w-14 h-8 rounded-full transition-colors relative flex items-center px-1 ${isStreaming ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-200 dark:bg-gray-700'}`}
                >
                  <motion.div
                    className="w-6 h-6 rounded-full bg-white shadow-sm"
                    initial={false}
                    animate={{ x: isStreaming ? 24 : 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Sparkles size={24} className="text-gray-600 dark:text-gray-400" />
                  <span className="text-[15px] font-medium text-gray-900 dark:text-gray-100">Agent Mode</span>
                </div>
                <select
                  value={agentMode}
                  onChange={(e) => setAgentMode(e.target.value)}
                  className="text-[15px] border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 cursor-pointer px-4 py-2 outline-none font-medium"
                >
                  <option value="default">Default</option>
                  <option value="plan_and_solve">Plan & Solve</option>
                  <option value="react">ReAct</option>
                </select>
              </div>
            </motion.div>
          )}

          {uploadedFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 px-2 pb-1">
              {uploadedFiles.map((file, index) => (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  key={index}
                  className="flex items-center gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full px-4 py-1.5 shadow-sm"
                >
                  <Paperclip size={14} className="text-blue-600 dark:text-blue-400" />
                  <span className="text-sm text-gray-700 dark:text-gray-300 max-w-[200px] truncate">{file.name}</span>
                  <button
                    onClick={() => removeUploadedFile(index)}
                    className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full text-gray-500 hover:text-red-500 transition-colors"
                  >
                    <X size={14} />
                  </button>
                </motion.div>
              ))}
            </div>
          )}

          <div className="flex items-end gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-[32px] p-2 focus-within:border-blue-500 dark:focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-500 dark:focus-within:ring-blue-400 transition-all duration-300 shadow-sm">
            <button
              onClick={() => setIsInputExpanded(!isInputExpanded)}
              className="p-3.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full shrink-0 transition-colors"
            >
              {isInputExpanded ? <ChevronDown size={24} /> : <ChevronUp size={24} />}
            </button>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileInputChange}
              className="hidden"
              accept=".pdf,.doc,.docx"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="p-3.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full shrink-0 transition-colors"
              title="上传文件"
            >
              <Paperclip size={24} />
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Reply to Agent..."
              className="flex-1 max-h-32 min-h-[56px] bg-transparent border-none focus:ring-0 resize-none py-4 text-gray-900 dark:text-gray-100 placeholder:text-gray-500 dark:placeholder:text-gray-400 text-[16px] leading-relaxed outline-none"
              rows={1}
            />
            {input.trim() || uploadedFiles.length > 0 ? (
              <button
                onClick={handleSend}
                disabled={isLoading}
                className="p-4 text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 rounded-full shrink-0 transition-colors disabled:opacity-50 shadow-sm flex items-center justify-center"
              >
                <Send size={24} />
              </button>
            ) : (
              <button className="p-3.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full shrink-0 transition-colors">
                <Mic size={24} />
              </button>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}

