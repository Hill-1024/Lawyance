import React, { useState, useEffect } from 'react';
import { Routes, Route, useNavigate } from 'react-router-dom';
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

  if (!isAuthenticated) {
    return <Login onLoginSuccess={async () => {
      try {
        const data = await verifyAuth();
        setUserRole(data.role || 'user');
        setIsAuthenticated(true);
      } catch (e) {
        window.location.reload();
      }
    }} />;
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
