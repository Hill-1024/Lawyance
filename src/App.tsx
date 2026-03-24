import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, Sparkles, Menu, Mic, Info, X, Plus, ChevronUp, ChevronDown, Settings2, Trash2 } from 'lucide-react';
import Markdown from 'react-markdown';
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

const MD3_COLORS = [
  { name: 'Default Black', value: '#1F1F1F' },
  { name: 'Blue', value: '#0B57D0' },
  { name: 'Green', value: '#146C2E' },
  { name: 'Purple', value: '#65558F' },
  { name: 'Orange', value: '#8C5000' },
  { name: 'Red', value: '#B3261E' },
];

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([
    { id: 'default', title: 'New Chat', messages: [] }
  ]);
  const [currentId, setCurrentId] = useState<string>('default');

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [isStreaming, setIsStreaming] = useState(true);
  const [agentMode, setAgentMode] = useState('default');
  const [themeColor, setThemeColor] = useState('#1F1F1F');
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hasInitialized = useRef(false);

  const currentConversation = conversations.find(c => c.id === currentId) || conversations[0] || { id: 'default', title: 'New Chat', messages: [] };
  const messages = currentConversation.messages;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    let failCount = 0;
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/heartbeat', { method: 'POST' });
        if (!res.ok) throw new Error('Backend disconnected');
        failCount = 0; // Reset on success
      } catch (e) {
        failCount++;
        console.error(`Heartbeat failed (${failCount}/3)`, e);
        if (failCount >= 3) {
          document.body.innerHTML = '<div style="display:flex;justify-content:center;align-items:center;height:100vh;background:#1F1F1F;color:#fff;font-family:sans-serif;text-align:center;"><div><h1 style="font-size:24px;margin-bottom:16px;">后端已断开连接</h1><p style="color:#A0A0A0;">前端已自动关闭空转状态，您可以安全地关闭此窗口。</p></div></div>';
          setTimeout(() => window.close(), 1000);
          clearInterval(interval);
        }
      }
    }, 5000);

    return () => clearInterval(interval);
  }, []);

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

      const agentMessageId = Date.now().toString();
      updateMessages(newId, prev => [...prev, { id: agentMessageId, role: 'agent', content: '' }]);
      setIsLoading(false);

      if (isStreaming) {
        await processStream(response, agentMessageId, newId);
      } else {
        const data = await response.json();
        updateMessages(newId, prev => prev.map(msg =>
          msg.id === agentMessageId ? { ...msg, content: data.reply } : msg
        ));
      }
    } catch (error) {
      console.error('Error connecting to Python agent:', error);
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'agent',
        content: '抱歉，连接到 Agent 时发生错误。\n\n在本地运行 `npm install` 和 `npm run dev` 即可正常使用。\n\n请检查 Python 后端服务是否正常启动。'
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

  const processStream = async (response: Response, messageId: string, convId: string) => {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('No reader available');

    const decoder = new TextDecoder();
    let done = false;
    let text = '';

    while (!done) {
      const { value, done: readerDone } = await reader.read();
      done = readerDone;
      if (value) {
        text += decoder.decode(value, { stream: true });
        updateMessages(convId, prev => prev.map(msg =>
          msg.id === messageId ? { ...msg, content: text } : msg
        ));
      }
    }
  };

  useEffect(() => {
    if (hasInitialized.current) return;
    hasInitialized.current = true;

    const initChat = async () => {
      setIsLoading(true);

      try {
        const res = await fetch('/api/conversations');
        if (res.ok) {
          const data = await res.json();
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
                  messages.push({ id: `${id}-${msgIdCounter++}`, role: 'agent', content: m.content });
                }
              }
            }

            loadedConversations.push({ id, title, messages });
          }

          if (loadedConversations.length > 0) {
            loadedConversations.sort((a, b) => b.id.localeCompare(a.id));
            setConversations(loadedConversations);
            setCurrentId(loadedConversations[0].id);
            setIsLoading(false);
            return;
          }
        }
      } catch (e) {
        console.error("Failed to load conversations", e);
      }

      await handleNewChat('default');
    };

    initChat();
  }, []);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim()
    };

    const convId = currentId;
    const isFirstUserMessage = currentConversation.messages.filter(m => m.role === 'user').length === 0;

    updateMessages(convId, prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
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

      if (!response.ok) throw new Error('Network response was not ok');

      const agentMessageId = (Date.now() + 1).toString();
      updateMessages(convId, prev => [...prev, { id: agentMessageId, role: 'agent', content: '' }]);
      setIsLoading(false);

      if (isStreaming) {
        await processStream(response, agentMessageId, convId);
      } else {
        const data = await response.json();
        updateMessages(convId, prev => prev.map(msg =>
          msg.id === agentMessageId ? { ...msg, content: data.reply } : msg
        ));
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

  return (
    <div className="flex flex-col h-screen bg-white text-gray-900 font-sans selection:bg-gray-200 selection:text-black" style={{ '--theme-color': themeColor } as React.CSSProperties}>

      {/* Sidebar Overlay */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-40 transition-opacity"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`fixed top-0 left-0 h-full w-72 bg-white shadow-2xl z-50 transform transition-transform duration-300 ease-in-out ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'} flex flex-col`}>
        <div className="p-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-medium text-lg">Conversations</h2>
          <button onClick={() => setIsSidebarOpen(false)} className="p-2 hover:bg-gray-100 rounded-full transition-colors">
            <X size={20} className="text-gray-600" />
          </button>
        </div>
        <div className="p-3">
          <button
            onClick={() => handleNewChat()}
            className="w-full py-3 px-4 text-white rounded-xl flex items-center gap-2 transition-colors font-medium shadow-sm"
            style={{ backgroundColor: themeColor }}
          >
            <Plus size={18} />
            New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-1">
          {conversations.map(conv => (
            <div
              key={conv.id}
              onClick={() => {
                setCurrentId(conv.id);
                setIsSidebarOpen(false);
              }}
              className={`w-full text-left px-4 py-3 rounded-xl transition-colors flex items-center justify-between group cursor-pointer ${
                conv.id === currentId ? 'font-medium' : 'hover:bg-gray-50 text-gray-700'
              }`}
              style={conv.id === currentId ? { backgroundColor: `${themeColor}15`, color: themeColor } : {}}
            >
              <span className="truncate pr-2">{conv.title}</span>
              <button
                onClick={(e) => deleteConversation(conv.id, e)}
                className={`p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200 ${conv.id === currentId ? 'hover:bg-white/50' : ''}`}
                title="Delete chat"
              >
                <Trash2 size={16} className={conv.id === currentId ? '' : 'text-gray-500'} style={conv.id === currentId ? { color: themeColor } : {}} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Top App Bar */}
      <header className="flex items-center justify-between px-2 py-2 bg-white text-gray-900 shrink-0 z-10 border-b border-gray-100">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setIsSidebarOpen(true)}
            className="p-3 hover:bg-gray-100 rounded-full transition-colors"
          >
            <Menu size={24} className="text-gray-600" />
          </button>
          <h1 className="text-[20px] font-medium tracking-tight ml-1">GDUT-Lawver</h1>
        </div>
        <div className="flex items-center gap-1 relative">
          <button
            onClick={() => setIsColorPickerOpen(!isColorPickerOpen)}
            className="p-3 hover:bg-gray-100 rounded-full transition-colors"
          >
            <Info size={24} className="text-gray-600" />
          </button>

          {isColorPickerOpen && (
            <div className="absolute top-full right-0 mt-2 w-64 bg-white rounded-2xl shadow-xl border border-gray-100 p-4 z-50">
              <h3 className="font-medium text-gray-900 mb-3">Theme Color</h3>
              <div className="grid grid-cols-3 gap-2 mb-4">
                {MD3_COLORS.map(color => (
                  <button
                    key={color.value}
                    onClick={() => setThemeColor(color.value)}
                    className={`h-10 rounded-full border-2 transition-all ${themeColor === color.value ? 'border-gray-900 scale-110' : 'border-transparent'}`}
                    style={{ backgroundColor: color.value }}
                    title={color.name}
                  />
                ))}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-600">Custom:</span>
                <input
                  type="color"
                  value={themeColor}
                  onChange={(e) => setThemeColor(e.target.value)}
                  className="w-full h-8 rounded cursor-pointer border-0 p-0"
                />
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Chat Area */}
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth" onClick={() => setIsColorPickerOpen(false)}>
        <div className="max-w-3xl mx-auto flex flex-col gap-6">
          {messages.map((msg) => (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              key={msg.id}
              className={`flex gap-3 max-w-[85%] sm:max-w-[75%] ${msg.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}
            >
              {/* Agent Avatar */}
              {msg.role === 'agent' && (
                <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-1 shadow-sm text-white" style={{ backgroundColor: themeColor }}>
                  <Sparkles size={16} />
                </div>
              )}

              {/* Message Bubble */}
              <div className={`px-5 py-3.5 text-[15px] leading-relaxed shadow-sm ${
                msg.role === 'user'
                  ? 'text-white rounded-3xl rounded-tr-sm'
                  : 'bg-gray-50 border border-gray-100 text-gray-900 rounded-3xl rounded-tl-sm'
              }`}
              style={msg.role === 'user' ? { backgroundColor: themeColor } : {}}
              >
                {msg.role === 'user' ? (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <div className="prose prose-sm max-w-none prose-p:leading-relaxed prose-headings:text-gray-900 prose-headings:font-medium prose-strong:text-gray-900 prose-strong:font-medium prose-a:text-blue-600 prose-code:text-gray-800 prose-code:bg-gray-200 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-100 prose-pre:text-gray-900 prose-pre:border prose-pre:border-gray-200">
                    <Markdown>{msg.content}</Markdown>
                  </div>
                )}
              </div>
            </motion.div>
          ))}

          {/* Loading Indicator */}
          {isLoading && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3 max-w-[85%] self-start">
              <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-1 shadow-sm text-white" style={{ backgroundColor: themeColor }}>
                <Sparkles size={16} />
              </div>
              <div className="bg-gray-50 border border-gray-100 text-gray-900 rounded-3xl rounded-tl-sm px-5 py-4 flex items-center gap-3 shadow-sm">
                <Loader2 size={18} className="animate-spin text-gray-500" />
                <span className="text-[14px] font-medium text-gray-500">Agent is typing...</span>
              </div>
            </motion.div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Bottom App Bar / Input Area */}
      <footer className="bg-white p-4 shrink-0 pb-6 border-t border-gray-100" onClick={() => setIsColorPickerOpen(false)}>
        <div className="max-w-3xl mx-auto relative flex flex-col gap-2">

          {isInputExpanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="bg-gray-50 rounded-2xl p-4 border border-gray-200 flex flex-col gap-4 overflow-hidden"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Settings2 size={20} className="text-gray-500" />
                  <span className="text-sm font-medium text-gray-700">Enable Streaming Output</span>
                </div>
                <button
                  onClick={() => setIsStreaming(!isStreaming)}
                  className={`w-12 h-6 rounded-full transition-colors relative ${isStreaming ? '' : 'bg-gray-300'}`}
                  style={isStreaming ? { backgroundColor: themeColor } : {}}
                >
                  <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${isStreaming ? 'left-7' : 'left-1'}`} />
                </button>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Sparkles size={20} className="text-gray-500" />
                  <span className="text-sm font-medium text-gray-700">Agent Mode</span>
                </div>
                <select
                  value={agentMode}
                  onChange={(e) => setAgentMode(e.target.value)}
                  className="text-sm border-gray-300 rounded-lg focus:ring-0 cursor-pointer bg-white px-3 py-1.5 outline-none border"
                >
                  <option value="default">Default</option>
                  <option value="plan_and_solve">Plan & Solve</option>
                  <option value="react">ReAct</option>
                </select>
              </div>
            </motion.div>
          )}

          <div className="flex items-end gap-2 bg-gray-50 border border-gray-200 rounded-[28px] p-2 focus-within:bg-white focus-within:border-gray-300 focus-within:shadow-sm transition-all duration-300">
            <button
              onClick={() => setIsInputExpanded(!isInputExpanded)}
              className="p-3 text-gray-500 hover:bg-gray-200 rounded-full shrink-0 transition-colors"
            >
              {isInputExpanded ? <ChevronDown size={24} /> : <ChevronUp size={24} />}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Reply to Agent..."
              className="flex-1 max-h-32 min-h-12 bg-transparent border-none focus:ring-0 resize-none py-3 text-gray-900 placeholder:text-gray-400 text-[15px] leading-relaxed outline-none"
              rows={1}
            />
            {input.trim() ? (
              <button
                onClick={handleSend}
                disabled={isLoading}
                className="p-3 text-white rounded-full shrink-0 hover:opacity-90 transition-opacity disabled:opacity-50 shadow-sm flex items-center justify-center"
                style={{ backgroundColor: themeColor }}
              >
                <Send size={20} />
              </button>
            ) : (
              <button className="p-3 text-gray-500 hover:bg-gray-100 rounded-full shrink-0 transition-colors">
                <Mic size={24} />
              </button>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}

