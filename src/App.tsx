import React, { useState, useEffect } from 'react';
import { Routes, Route, useNavigate } from 'react-router-dom';
import { ShieldAlert, ExternalLink } from 'lucide-react';
import { useTheme } from './hooks/useTheme';
import { useChat } from './hooks/useChat';
import { useWorkspace } from './hooks/useWorkspace';
import { useStorage } from './hooks/useStorage';
import { sendHeartbeat, verifyAuth, logout as apiLogout } from './services/api';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { WorkspacePanel } from './components/WorkspacePanel';
import { InputArea } from './components/InputArea';
import { MessageList } from './components/MessageList';
import { Login } from './components/Login';
import { AdminDashboard } from './components/AdminDashboard';

const SECURE_DOMAIN = 'law.mutsumi.moe';

const isIpHostname = (hostname: string) => {
  if (!hostname) return false;
  const isIpv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
  const isIpv6 = hostname.includes(':');
  return isIpv4 || isIpv6;
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [userRole, setUserRole] = useState('user');
  const navigate = useNavigate();

  const { themeMode, setThemeMode } = useTheme();
  const {
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
  } = useChat();

  const {
    isWorkspaceOpen,
    setIsWorkspaceOpen,
    workspaceFiles,
    pendingUploads,
    setPendingUploads,
    handleFileUpload,
    handleGeneratedFile,
    removeUploadedFile,
    deleteFile,
    syncFiles
  } = useWorkspace(currentId);
  const { isLowStorage, requestPersistence } = useStorage();

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1024);
  const isIpAccess = typeof window !== 'undefined' && isIpHostname(window.location.hostname);
  const secureAccessUrl = typeof window !== 'undefined'
    ? `https://${SECURE_DOMAIN}${window.location.pathname}${window.location.search}${window.location.hash}`
    : `https://${SECURE_DOMAIN}`;

  const handleLogout = async () => {
    try {
      await apiLogout();
      setIsAuthenticated(false);
      setUserRole('user');
      navigate('/');
    } catch (e) {
      console.error("Logout failed:", e);
      // Fallback: clear auth state anyway
      setIsAuthenticated(false);
      window.location.reload();
    }
  };

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const data = await verifyAuth();
        setIsAuthenticated(true);
        setUserRole(data.role || 'user');
      } catch (e) {
        setIsAuthenticated(false);
      } finally {
        setIsAuthChecking(false);
      }
    };
    checkAuth();
    requestPersistence().catch(console.error);
  }, []);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (!currentId || !isAuthenticated || !isInitialized) return;

    const initialSync = async () => {
      try {
        await sendHeartbeat(currentId);
        await syncFiles();
      } catch (e) {
        console.error("Initial heartbeat/sync failed:", e);
      }
    };
    initialSync();

    const interval = setInterval(() => {
      sendHeartbeat(currentId).catch(console.error);
    }, 5 * 60 * 1000);

    const handleFocus = async () => {
      console.log("[Reconnect] Window focused, syncing files and sending heartbeat...");
      try {
        await sendHeartbeat(currentId);
        await syncFiles();
      } catch (e) {
        console.error("Focus sync failed:", e);
      }
    };

    window.addEventListener('focus', handleFocus);
    window.addEventListener('online', handleFocus);

    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('online', handleFocus);
    };
  }, [currentId, isAuthenticated, isInitialized, syncFiles]);

  if (isAuthChecking) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 dark:bg-gray-900 transition-colors duration-300">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  const secureAccessBanner = isIpAccess ? (
    <div className="mx-4 mt-4 mb-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-300" />
          <div className="text-sm leading-6">
            <div className="font-medium">当前正在通过 IP 访问。</div>
            <div>建议改用 <span className="font-semibold">https://{SECURE_DOMAIN}</span> 进行安全访问，避免证书与登录状态问题。</div>
          </div>
        </div>
        <a
          href={secureAccessUrl}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-700 dark:bg-amber-500 dark:hover:bg-amber-400"
        >
          前往安全地址
          <ExternalLink size={16} />
        </a>
      </div>
    </div>
  ) : null;

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors duration-300">
        {secureAccessBanner}
        <Login onLoginSuccess={async () => {
          try {
            const data = await verifyAuth();
            setUserRole(data.role || 'user');
            setIsAuthenticated(true);
          } catch (e) {
            window.location.reload();
          }
        }} />
      </div>
    );
  }

  if (!isInitialized) return null;

  const chatLayout = (
    <div className="flex h-screen bg-white dark:bg-gray-900 font-sans overflow-hidden transition-colors duration-300">
      <Sidebar
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        conversations={conversations}
        currentId={currentId}
        setCurrentId={setCurrentId}
        handleNewChat={handleNewChat}
        deleteConversation={deleteConversation}
        userRole={userRole}
        onAdminClick={() => navigate('/admin')}
        onLogout={handleLogout}
      />

      <div className="flex-1 flex flex-col min-w-0 relative">
        {secureAccessBanner}
        <Header
          title={currentConversation.title}
          isSidebarOpen={isSidebarOpen}
          setIsSidebarOpen={setIsSidebarOpen}
          isWorkspaceOpen={isWorkspaceOpen}
          setIsWorkspaceOpen={setIsWorkspaceOpen}
          workspaceFilesCount={workspaceFiles.length}
          themeMode={themeMode}
          setThemeMode={setThemeMode}
          windowWidth={windowWidth}
        />

        <div className="flex-1 flex overflow-hidden relative">
          <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-gray-900">
            {messages.length === 0 ? (
              <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400">
                <div className="text-center">
                  <h2 className="text-2xl font-medium mb-2 text-gray-900 dark:text-gray-100">Welcome to Lawver</h2>
                  <p>Start a conversation or upload a document to begin.</p>
                </div>
              </div>
            ) : (
              <MessageList
                messages={messages}
                isLoading={isLoading}
                onRegenerate={(id) => handleRegenerateMessage(currentId, id, handleGeneratedFile, syncFiles)}
                onEdit={(id) => handleEdit(currentId, id, setPendingUploads)}
                onUndo={(id) => handleUndo(currentId, id, setPendingUploads)}
              />
            )}

            <InputArea
              input={input}
              setInput={setInput}
              handleSend={() => handleSend(pendingUploads, setPendingUploads, handleGeneratedFile, syncFiles, isLowStorage)}
              isLoading={isLoading}
              pendingUploads={pendingUploads}
              removeUploadedFile={removeUploadedFile}
              handleFileUpload={handleFileUpload}
              isInputExpanded={isInputExpanded}
              setIsInputExpanded={setIsInputExpanded}
              isStreaming={isStreaming}
              setIsStreaming={setIsStreaming}
              agentMode={agentMode}
              setAgentMode={setAgentMode}
              isOCPEnabled={isOCPEnabled}
              setIsOCPEnabled={setIsOCPEnabled}
            />
          </div>

          <WorkspacePanel
            isWorkspaceOpen={isWorkspaceOpen}
            setIsWorkspaceOpen={setIsWorkspaceOpen}
            workspaceFiles={workspaceFiles}
            onDeleteFile={deleteFile}
          />
        </div>
      </div>
    </div>
  );

  return (
    <Routes>
      <Route path="/" element={chatLayout} />
      <Route path="/admin" element={userRole === 'admin' ? <AdminDashboard /> : <div className="flex h-screen w-full items-center justify-center text-red-500 font-medium text-lg dark:bg-gray-900">403 Forbidden: Access Denied</div>} />
    </Routes>
  );
}

export default App;
