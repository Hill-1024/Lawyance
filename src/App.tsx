import React, { useState, useEffect } from 'react';
import { useTheme } from './hooks/useTheme';
import { useChat } from './hooks/useChat';
import { useWorkspace } from './hooks/useWorkspace';
import { sendHeartbeat, verifyAuth } from './services/api';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { WorkspacePanel } from './components/WorkspacePanel';
import { InputArea } from './components/InputArea';
import { MessageList } from './components/MessageList';
import { Login } from './components/Login';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);

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

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1024);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        await verifyAuth();
        setIsAuthenticated(true);
      } catch (e) {
        setIsAuthenticated(false);
      } finally {
        setIsAuthChecking(false);
      }
    };
    checkAuth();
  }, []);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (!currentId || !isAuthenticated || !isInitialized) return;

    // 当切换到某个对话时，立即发送一次心跳记录其进入连接状态，并同步文件
    const initialSync = async () => {
      try {
        await sendHeartbeat(currentId);
        await syncFiles();
      } catch (e) {
        console.error("Initial heartbeat/sync failed:", e);
      }
    };
    initialSync();

    // 仅为当前处于前台的对话（currentId）每 5 分钟发送一次心跳
    const interval = setInterval(() => {
      sendHeartbeat(currentId).catch(console.error);
    }, 5 * 60 * 1000);

    // 用户重新连接（重新聚焦页面）时，立即同步状态
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
    return <Login onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  if (!isInitialized) return null;

  return (
    <div className="flex h-screen bg-white dark:bg-gray-900 font-sans overflow-hidden transition-colors duration-300">
      <Sidebar
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        conversations={conversations}
        currentId={currentId}
        setCurrentId={setCurrentId}
        handleNewChat={handleNewChat}
        deleteConversation={deleteConversation}
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
                onRegenerate={(id) => handleRegenerateMessage(currentId, id, handleGeneratedFile)}
                onEdit={(id) => handleEdit(currentId, id, setPendingUploads)}
                onUndo={(id) => handleUndo(currentId, id, setPendingUploads)}
              />
            )}

            <InputArea
              input={input}
              setInput={setInput}
              handleSend={() => handleSend(pendingUploads, setPendingUploads, handleGeneratedFile)}
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
}

export default App;
