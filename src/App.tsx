import React, { useState, useRef, useEffect } from 'react';
import { fileDB } from './lib/db';
import { Send, Loader2, Sparkles, Menu, Info, X, Plus, ChevronUp, ChevronDown, Settings2, Trash2, Sun, Moon, Monitor, Paperclip, Download, Undo2, Pencil, RefreshCw } from 'lucide-react';
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

export default function App() {
  // Migration and Initialization
  const { initialConvs, initialId } = (() => {
    const savedConvs = localStorage.getItem('lawver_conversations');
    const savedId = localStorage.getItem('lawver_current_id');

    let convs: Conversation[] = [];
    if (savedConvs) {
      try {
        convs = JSON.parse(savedConvs);
        let migrated = false;
        convs = convs.map(c => {
          if (c.id === 'default') {
            migrated = true;
            return { ...c, id: generateUUID() };
          }
          return c;
        });
        if (migrated) localStorage.setItem('lawver_conversations', JSON.stringify(convs));
      } catch (e) {
        console.error('Failed to parse conversations', e);
      }
    }

    if (convs.length === 0) {
      const newId = generateUUID();
      convs = [{ id: newId, title: 'New Chat', messages: [] }];
    }

    let finalId = savedId;
    if (!finalId || finalId === 'default' || !convs.some(c => c.id === finalId)) {
      finalId = convs[0].id;
    }

    return { initialConvs: convs, initialId: finalId };
  })();

  const [conversations, setConversations] = useState<Conversation[]>(initialConvs);
  const [currentId, setCurrentId] = useState<string>(initialId);

  useEffect(() => {
    console.log('[UUID 验证] 当前会话 ID:', currentId);
  }, [currentId]);

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialized, setIsInitialized] = useState(true);

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (windowWidth >= 1024) {
      setIsSidebarOpen(true);
    } else {
      setIsSidebarOpen(false);
    }
  }, [windowWidth < 1024]); // Only trigger when crossing the 1024px threshold
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [isStreaming, setIsStreaming] = useState(true);
  const [agentMode, setAgentMode] = useState('default');

  const [themeMode, setThemeMode] = useState<'light' | 'system' | 'dark'>('system');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadedFiles, setUploadedFiles] = useState<{name: string, path: string}[]>([]);
  const [isDragging, setIsDragging] = useState(false);

  // Save to localStorage
  useEffect(() => {
    localStorage.setItem('lawver_conversations', JSON.stringify(conversations));
  }, [conversations]);

  useEffect(() => {
    localStorage.setItem('lawver_current_id', currentId);
  }, [currentId]);

  // Load and Sync uploaded files from IndexedDB when conversation changes
  useEffect(() => {
    const syncFiles = async () => {
      try {
        const files = await fileDB.getFilesByConvId(currentId);
        setUploadedFiles(files.map(f => ({ name: f.fileName, path: f.path })));

        // Re-upload to backend to ensure TEMP path exists (in case of backend cleanup)
        for (const file of files) {
          const formData = new FormData();
          formData.append('file', file.blob, file.fileName);
          formData.append('conversation_id', currentId);
          fetch('/api/upload', { method: 'POST', body: formData }).catch(console.error);
        }
      } catch (err) {
        console.error('Failed to sync files from IndexedDB:', err);
      }
    };
    syncFiles();
  }, [currentId]);

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
        // Save to IndexedDB for persistence
        await fileDB.saveFile(currentId, file.name, file, filePath);
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
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    try {
      const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: formatHistoryForBackend(conv.messages) })
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

  const formatHistoryForBackend = (msgs: Message[]) => {
    return msgs.map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content
    }));
  };

  const handleNewChat = async (forceId?: string) => {
    const newId = forceId || generateUUID();

    setConversations(prev => {
      if (prev.some(c => c.id === newId)) return prev;
      return [{ id: newId, title: 'New Chat', messages: [] }, ...prev];
    });
    setCurrentId(newId);
    if (window.innerWidth < 1024) {
      setIsSidebarOpen(false);
    }

    setIsLoading(true);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '介绍自己',
          history: [],
          conversation_id: newId,
          stream: isStreaming,
          agent_mode: agentMode
        })
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
        content: '抱歉，连接到 Agent 时发生错误。'
      };
      updateMessages(newId, prev => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const deleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const filtered = conversations.filter(c => c.id !== convId);

    // Cleanup IndexedDB
    await fileDB.deleteFilesByConvId(convId);

    if (filtered.length === 0) {
      setConversations([]);
      await handleNewChat();
    } else {
      setConversations(filtered);
      if (currentId === convId) {
        setCurrentId(filtered[0].id);
      }
    }
  };

  const processStream = async (response: Response, existingMessageId: string | null, convId: string) => {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('No reader available');

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

          if (!messageId) {
            messageId = generateUUID();
            updateMessages(convId, prev => [...prev, { id: messageId!, role: 'agent', content: '' }]);
            setIsLoading(false);
          }

          text += chunk;
          updateMessages(convId, prev => prev.map(msg =>
            msg.id === messageId ? { ...msg, content: text } : msg
          ));
        }
      }
    } catch (err) {
      console.error('读取流时发生错误:', err);
      setIsLoading(false);
    } finally {
      reader.releaseLock();
    }
  };

  const handleSend = async () => {
    if ((!input.trim() && uploadedFiles.length === 0) || isLoading || !isInitialized) {
      return;
    }

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

    let convId = currentId;
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const isFirstUserMessage = conv.messages.filter(m => m.role === 'user').length === 0;
    const history = formatHistoryForBackend(conv.messages);

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setUploadedFiles([]);
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage.content,
          history: history,
          conversation_id: convId,
          stream: isStreaming,
          agent_mode: agentMode
        })
      });

      if (!response.ok) throw new Error('Network response was not ok');

      if (isStreaming) {
        await processStream(response, null, convId);
      } else {
        const data = await response.json();
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

  const handleRecallMessage = async (convId: string, messageId: string) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;
    const msgIndex = conv.messages.findIndex(m => m.id === messageId);
    if (msgIndex === -1) return;
    updateMessages(convId, prev => prev.slice(0, msgIndex));
  };

  const handleEditMessage = async (convId: string, messageId: string) => {
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;

    const msgIndex = conv.messages.findIndex(m => m.id === messageId);
    if (msgIndex === -1) return;

    const msg = conv.messages[msgIndex];
    if (msg.role !== 'user') return;

    const fileInfoRegex = /\[用户已上传以下文件，请根据需要进行读取和处理]\n([\s\S]*)$/;
    const match = msg.content.match(fileInfoRegex);
    let textContent = msg.content;
    let filesToRestore: {name: string, path: string}[] = [];

    if (match) {
      textContent = msg.content.replace(match[0], '').trim();
      const fileLines = match[1].split('\n').filter(line => line.startsWith('- '));
      filesToRestore = fileLines.map(line => {
        const nameMatch = line.match(/^- (.*?) \(路径: (.*?)\)$/);
        if (nameMatch) return { name: nameMatch[1], path: nameMatch[2] };
        return null;
      }).filter(Boolean) as {name: string, path: string}[];
    }

    setInput(textContent);
    setUploadedFiles(filesToRestore);
    updateMessages(convId, prev => prev.slice(0, msgIndex));
  };

  const handleRegenerateMessage = async (convId: string, messageId: string) => {
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

    try {
      const userMessage: Message = { id: Date.now().toString(), role: 'user', content: content };
      updateMessages(convId, prev => [...prev, userMessage]);

      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: content,
          history: history,
          conversation_id: convId,
          stream: isStreaming,
          agent_mode: agentMode
        })
      });

      if (!response.ok) throw new Error('Network response was not ok');

      if (isStreaming) {
        await processStream(response, null, convId);
      } else {
        const data = await response.json();
        const agentMessageId = (Date.now() + 1).toString();
        updateMessages(convId, prev => [...prev, { id: agentMessageId, role: 'agent', content: data.reply }]);
        setIsLoading(false);
      }

      if (isFirstUserMessage) {
        await summarizeConversation(convId);
      }
    } catch (error) {
      console.error('Failed to regenerate message:', error);
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMac = /Mac|iPhone|iPod|iPad/i.test(navigator.userAgent);
    const isSendTriggered = isMac ? (e.metaKey && e.key === 'Enter') : (e.ctrlKey && e.key === 'Enter');

    if (isSendTriggered) {
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
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 font-sans selection:bg-blue-200 dark:selection:bg-blue-900 selection:text-blue-900 dark:selection:text-blue-100 overflow-hidden">

      {/* Sidebar Overlay */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40 transition-opacity backdrop-blur-sm lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`fixed lg:relative top-0 left-0 h-full w-[85vw] max-w-[320px] lg:max-w-none bg-gray-50 dark:bg-gray-900 shadow-2xl lg:shadow-none z-50 transform transition-all duration-300 ease-in-out ${isSidebarOpen ? 'translate-x-0 lg:w-80' : '-translate-x-full lg:translate-x-0 lg:w-0'} flex flex-col lg:rounded-none rounded-r-3xl border-r border-gray-200 dark:border-gray-800 shrink-0 overflow-hidden`}>
        <div className="p-6 pb-4 flex items-center justify-between min-w-62.5">
          <h2 className="font-medium text-xl text-gray-900 dark:text-gray-100 whitespace-nowrap">Conversations</h2>
          <button onClick={() => setIsSidebarOpen(false)} className="p-2 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400 lg:hidden">
            <X size={24} />
          </button>
        </div>
        <div className="px-4 pb-4 min-w-62.5">
          <button
            onClick={() => handleNewChat()}
            className="w-full py-4 px-6 bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white rounded-full flex items-center justify-center gap-2 transition-all font-medium shadow-md hover:shadow-lg active:scale-[0.98] whitespace-nowrap"
          >
            <Plus size={20} />
            New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-4 flex flex-col gap-1 custom-scrollbar min-w-62.5">
          {conversations.map(conv => (
            <div
              key={conv.id}
              onClick={() => {
                setCurrentId(conv.id);
                if (window.innerWidth < 1024) setIsSidebarOpen(false);
              }}
              className={`w-full text-left px-4 py-3.5 rounded-full transition-colors flex items-center justify-between group cursor-pointer ${
                conv.id === currentId ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium' : 'hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400'
              }`}
            >
              <span className="truncate pr-2 text-[15px]">{conv.title}</span>
              <button
                onClick={(e) => deleteConversation(conv.id, e)}
                className={`p-2 rounded-full lg:opacity-0 lg:group-hover:opacity-100 transition-opacity hover:bg-gray-300 dark:hover:bg-gray-700 ${conv.id === currentId ? 'hover:bg-blue-200 dark:hover:bg-blue-800' : ''}`}
                title="Delete chat"
              >
                <Trash2 size={18} className={conv.id === currentId ? 'text-blue-700 dark:text-blue-300' : 'text-gray-600 dark:text-gray-400'} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Top App Bar */}
        <header className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 shrink-0 z-10 sticky top-0 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="p-3 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400"
            >
              <Menu size={24} />
            </button>
            <h1 className="text-lg sm:text-[22px] font-medium tracking-tight ml-1 truncate max-w-30 sm:max-w-none">
              {currentConversation.title || 'GDUT-Lawver'}
            </h1>
          </div>
          <div className="flex items-center gap-1 relative">
            <div className="flex items-center bg-gray-200 dark:bg-gray-800 rounded-full p-1 relative">
              <motion.div
                className="absolute top-1 bottom-1 w-8 sm:w-9 bg-white dark:bg-gray-600 rounded-full shadow-sm"
                initial={false}
                animate={{
                  x: themeMode === 'light' ? 0 : themeMode === 'system' ? (windowWidth < 640 ? 32 : 36) : (windowWidth < 640 ? 64 : 72)
                }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
              />
              <button
                onClick={() => setThemeMode('light')}
                className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'light' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
                title="Light Mode"
              >
                <Sun size={16} className="sm:size-4.5" />
              </button>
              <button
                onClick={() => setThemeMode('system')}
                className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'system' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
                title="System Mode"
              >
                <Monitor size={16} className="sm:size-4.5" />
              </button>
              <button
                onClick={() => setThemeMode('dark')}
                className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'dark' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
                title="Dark Mode"
              >
                <Moon size={16} className="sm:size-4.5" />
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
          className={`flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth transition-colors custom-scrollbar ${isDragging ? 'bg-blue-50/50 dark:bg-blue-900/20 border-2 border-dashed border-blue-400 dark:border-blue-600' : ''}`}
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
                } else if (thinkDepth > 0 && content.startsWith("<final_answer>", i)) {
                  // 前端双保险：如果遇到 <final_answer> 但 <think> 尚未闭合，强制闭合思考过程
                  thinkDepth = 0;
                  thinks.push(currentThink);
                  currentThink = "";
                  mainContent += "<final_answer>";
                  i += 14;
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
              }

              if (thinkDepth > 0 || (mainContent === "" && msg.id === messages[messages.length - 1].id && isLoading)) {
                isThinking = true;
              }
            } else {
              mainContent = msg.content;
            }

            // Strip XML tags used for Constrained Decoding
            mainContent = mainContent.replace(/<\/?response>/g, '').replace(/<\/?final_answer>/g, '').trim();

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
                className={`flex gap-3 sm:gap-4 max-w-[92%] sm:max-w-[85%] md:max-w-[75%] ${msg.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}
              >
                {/* Agent Avatar */}
                {msg.role === 'agent' && (
                  <div className="shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full flex items-center justify-center mt-1 shadow-sm text-white bg-blue-600 dark:bg-blue-500">
                    <Sparkles size={16} className="sm:size-5" />
                  </div>
                )}

                <div className={`flex flex-col gap-2 min-w-0 w-full ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
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
                    <div className={`px-4 py-3 sm:px-6 sm:py-4 text-[15px] sm:text-[16px] leading-relaxed shadow-sm w-fit ${
                      msg.role === 'user'
                        ? 'bg-blue-600 dark:bg-blue-500 text-white rounded-[20px] sm:rounded-[28px] rounded-tr-sm sm:rounded-tr-lg'
                        : 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[20px] sm:rounded-[28px] rounded-tl-sm sm:rounded-tl-lg border border-gray-200 dark:border-gray-800'
                    }`}
                    >
                      {msg.role === 'user' ? (
                        <div className="flex flex-col gap-2">
                          {(() => {
                            const fileInfoRegex = /\[用户已上传以下文件，请根据需要进行读取和处理]\n([\s\S]*)$/;
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
                                          <span className="truncate max-w-50">{file}</span>
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
                          {(() => {
                            const downloadMatch = (msg.content || "").match(/(Result\/[a-zA-Z0-9_-]+\/[^\s"'`)\]<>*。，！？,?]+)/);
                            const downloadPath = downloadMatch ? downloadMatch[1] : null;
                            if (downloadPath) {
                              return (
                                <div className="mt-1 pt-3 border-t border-gray-200 dark:border-gray-700">
                                  <a
                                    href={`/api/download?file_path=${encodeURIComponent(downloadPath)}`}
                                    download
                                    className="inline-flex items-center gap-2 px-4 py-2 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-full text-sm font-medium hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                                  >
                                    <Download size={16} />
                                    下载文件
                                  </a>
                                </div>
                              );
                            }
                            return null;
                          })()}
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
                  {msg.role === 'user' && !isLoading && (
                    <div className="flex gap-2 self-end mt-1">
                      <button
                        onClick={() => handleRegenerateMessage(currentId, msg.id)}
                        className="text-xs text-gray-500 hover:text-green-500 transition-colors flex items-center gap-1 px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
                        title="重新生成"
                      >
                        <RefreshCw size={12} />
                        重新生成
                      </button>
                      <button
                        onClick={() => handleEditMessage(currentId, msg.id)}
                        className="text-xs text-gray-500 hover:text-blue-500 transition-colors flex items-center gap-1 px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
                        title="编辑消息"
                      >
                        <Pencil size={12} />
                        编辑
                      </button>
                      <button
                        onClick={() => handleRecallMessage(currentId, msg.id)}
                        className="text-xs text-gray-500 hover:text-red-500 transition-colors flex items-center gap-1 px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
                        title="撤回消息"
                      >
                        <Undo2 size={12} />
                        撤回
                      </button>
                    </div>
                  )}
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
              <div className="bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[28px] rounded-tl-lg px-6 py-4 flex items-center gap-3 shadow-sm border border-gray-200 dark:border-gray-700">
                <Loader2 size={20} className="animate-spin text-gray-500 dark:text-gray-400" />
                <span className="text-[15px] font-medium text-gray-500 dark:text-gray-400">Agent is typing...</span>
              </div>
            </motion.div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Bottom App Bar / Input Area */}
      <footer className="bg-gray-50 dark:bg-gray-900 p-2 sm:p-4 shrink-0 pb-6 sm:pb-8 border-t border-gray-200 dark:border-gray-800">
        <div className="max-w-3xl mx-auto relative flex flex-col gap-3">

          {isInputExpanded && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="absolute bottom-full mb-3 left-0 right-0 bg-white dark:bg-gray-800 rounded-3xl p-4 sm:p-5 flex flex-col gap-4 sm:gap-5 border border-gray-200 dark:border-gray-700 shadow-lg z-10"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Settings2 size={20} className="text-gray-600 dark:text-gray-400 sm:size-6" />
                  <span className="text-sm sm:text-[15px] font-medium text-gray-900 dark:text-gray-100">Enable Streaming Output</span>
                </div>
                <button
                  onClick={() => setIsStreaming(!isStreaming)}
                  className={`w-12 h-7 sm:w-14 sm:h-8 rounded-full transition-colors relative flex items-center px-1 ${isStreaming ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-200 dark:bg-gray-700'}`}
                >
                  <motion.div
                    className="w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-white shadow-sm"
                    initial={false}
                    animate={{ x: isStreaming ? (windowWidth < 640 ? 20 : 24) : 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Sparkles size={20} className="text-gray-600 dark:text-gray-400 sm:size-6" />
                  <span className="text-sm sm:text-[15px] font-medium text-gray-900 dark:text-gray-100">Agent Mode</span>
                </div>
                <select
                  value={agentMode}
                  onChange={(e) => setAgentMode(e.target.value)}
                  className="text-sm sm:text-[15px] border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 cursor-pointer px-3 py-1.5 sm:px-4 sm:py-2 outline-none font-medium"
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
                  className="flex items-center gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full px-3 py-1 sm:px-4 sm:py-1.5 shadow-sm"
                >
                  <Paperclip size={12} className="text-blue-600 dark:text-blue-400 sm:size-3.5" />
                  <span className="text-xs sm:text-sm text-gray-700 dark:text-gray-300 max-w-30 sm:max-w-50 truncate">{file.name}</span>
                  <button
                    onClick={() => removeUploadedFile(index)}
                    className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full text-gray-500 hover:text-red-500 transition-colors"
                  >
                    <X size={12} className="sm:size-3.5" />
                  </button>
                </motion.div>
              ))}
            </div>
          )}

          <div className="flex items-end gap-1 sm:gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-800 rounded-3xl sm:rounded-4xl p-1.5 sm:p-2 focus-within:border-blue-500 dark:focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-500 dark:focus-within:ring-blue-400 transition-all duration-300 shadow-sm">
            <button
              onClick={() => setIsInputExpanded(!isInputExpanded)}
              className="p-2 sm:p-3.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full shrink-0 transition-colors"
            >
              {isInputExpanded ? <ChevronDown size={20} className="sm:size-6" /> : <ChevronUp size={20} className="sm:size-6" />}
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
              className="p-2 sm:p-3.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full shrink-0 transition-colors"
              title="上传文件"
            >
              <Paperclip size={20} className="sm:size-6" />
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={windowWidth < 640 ? "Message..." : `Reply to Agent... (${/Mac|iPhone|iPod|iPad/i.test(navigator.userAgent) ? 'Cmd' : 'Ctrl'} + Enter to send)`}
              className="flex-1 max-h-32 min-h-11 sm:min-h-14 bg-transparent border-none focus:ring-0 resize-none py-3 sm:py-4 text-gray-900 dark:text-gray-100 placeholder:text-gray-500 dark:placeholder:text-gray-400 text-sm sm:text-[16px] leading-relaxed outline-none"
              rows={1}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || (!input.trim() && uploadedFiles.length === 0)}
              className={`p-3 sm:p-4 rounded-full shrink-0 transition-colors shadow-sm flex items-center justify-center ${
                input.trim() || uploadedFiles.length > 0
                  ? 'text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600'
                  : 'text-gray-400 bg-gray-100 dark:bg-gray-800 dark:text-gray-600 cursor-not-allowed'
              }`}
            >
              <Send size={20} className="sm:size-6" />
            </button>
          </div>
        </div>
      </footer>
    </div>
  </div>
);
}

