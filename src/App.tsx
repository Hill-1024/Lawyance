/*
 * 模块描述：React 应用根组件，串联认证状态、聊天布局、工作区、主题和管理路由。
 */

import React, { useCallback, useState, useEffect } from 'react';
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { App as CapacitorApp } from '@capacitor/app';
import { SplashScreen } from '@capacitor/splash-screen';
import { ShieldAlert, ExternalLink } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useChat } from './hooks/useChat';
import { useWorkspace } from './hooks/useWorkspace';
import { useStorage } from './hooks/useStorage';
import { sendHeartbeat, verifyAuth, logout as apiLogout, setUnauthorizedHandler } from './services/api';
import { isNative } from './lib/platform';
import { exitNativeApp, useBackButton } from './hooks/useBackButton';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { WorkspacePanel } from './components/WorkspacePanel';
import { InputArea } from './components/InputArea';
import { MessageList } from './components/MessageList';
import { Login } from './components/Login';
import { AdminDashboard } from './components/AdminDashboard';
import { BrandMark } from './components/Brand';
import { CourtPage } from './components/CourtPage';
import { SettingsPage } from './components/SettingsPage';
import { UpdateGate } from './components/UpdateGate';

const SECURE_DOMAIN = 'law.mutsumi.moe';
const ROUTE_TRANSITION = { duration: 0.26, ease: [0.2, 0, 0, 1] } as const;

const isIpHostname = (hostname: string) => {
  if (!hostname) return false;
  const isIpv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
  const isIpv6 = hostname.includes(':');
  return isIpv4 || isIpv6;
};

const AnimatedRouteSurface: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      className="min-h-[100dvh] bg-[var(--bg-app)]"
      initial={reduceMotion ? false : { opacity: 0, x: 24, scale: 0.995 }}
      animate={reduceMotion ? { opacity: 1 } : { opacity: 1, x: 0, scale: 1 }}
      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 18, scale: 0.995 }}
      transition={reduceMotion ? { duration: 0.01 } : ROUTE_TRANSITION}
      style={{ willChange: reduceMotion ? undefined : 'opacity, transform' }}
    >
      {children}
    </motion.div>
  );
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [userRole, setUserRole] = useState('user');
  const navigate = useNavigate();
  const location = useLocation();

  const {
    conversations,
    currentId,
    setCurrentId,
    input,
    setInput,
    isLoading,
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
    handleSend,
    handleRegenerateMessage,
    handleUndo,
    handleEdit,
    branchConversation
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
  } = useWorkspace(currentId, isAuthenticated && isInitialized);
  const { isLowStorage, requestPersistence } = useStorage();

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [composerOverlayHeight, setComposerOverlayHeight] = useState(0);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1024);
  const isIpAccess = typeof window !== 'undefined' && !isNative() && isIpHostname(window.location.hostname);
  const secureAccessUrl = typeof window !== 'undefined'
    ? `https://${SECURE_DOMAIN}${window.location.pathname}${window.location.search}${window.location.hash}`
    : `https://${SECURE_DOMAIN}`;

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      setIsAuthenticated(false);
      setUserRole('user');
      navigate('/');
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

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
      setUserRole('user');
      navigate('/');
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
        if (isNative()) {
          requestAnimationFrame(() => {
            SplashScreen.hide().catch(console.error);
          });
        }
      }
    };
    checkAuth();
    requestPersistence().catch(console.error);
  }, []);

  useEffect(() => {
    if (!isNative()) return;

    let listener: { remove: () => Promise<void> } | undefined;
    CapacitorApp.addListener('appStateChange', async ({ isActive }) => {
      if (!isActive) return;
      try {
        const data = await verifyAuth();
        setIsAuthenticated(true);
        setUserRole(data.role || 'user');
      } catch {
        setIsAuthenticated(false);
      }
    }).then(handle => {
      listener = handle;
    });

    return () => {
      listener?.remove();
    };
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

  useBackButton(useCallback(() => {
    if (isInputExpanded) {
      setIsInputExpanded(false);
      return true;
    }
    if (isSidebarOpen) {
      setIsSidebarOpen(false);
      return true;
    }
    if (isWorkspaceOpen) {
      setIsWorkspaceOpen(false);
      return true;
    }
    if (location.pathname !== '/') {
      navigate(-1);
      return true;
    }
    exitNativeApp().catch(console.error);
    return true;
  }, [isInputExpanded, isSidebarOpen, isWorkspaceOpen, location.pathname, navigate]), isAuthenticated && isInitialized);

  if (isAuthChecking) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-app)] text-[var(--accent)] transition-colors duration-300">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-[var(--accent-quiet)] border-t-[var(--accent)]" />
      </div>
    );
  }

  const secureAccessBanner = isIpAccess ? (
    <div className="mx-4 mt-4 mb-2 rounded-[var(--radius-lg)] border border-[rgba(184,132,42,0.3)] bg-[rgba(184,132,42,0.1)] px-4 py-3 text-[#5C3F0E] shadow-[var(--shadow-1)] dark:text-[#FBEBC8]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--color-warning-500)]" />
          <div className="text-sm leading-6">
            <div className="font-medium">当前正在通过 IP 访问。</div>
            <div>建议改用 <span className="font-semibold">https://{SECURE_DOMAIN}</span> 进行安全访问，避免证书与登录状态问题。</div>
          </div>
        </div>
        <a
          href={secureAccessUrl}
          className="inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-warning-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#9A6F22]"
        >
          前往安全地址
          <ExternalLink size={16} strokeWidth={2} />
        </a>
      </div>
    </div>
  ) : null;

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-[var(--bg-app)] transition-colors duration-300">
        {secureAccessBanner}
        <Login onLoginSuccess={(data) => {
          setUserRole(data.role || 'user');
          setIsAuthenticated(true);
        }} />
      </div>
    );
  }

  if (!isInitialized) return null;

  const chatLayout = (
    <div className="lawver-chat-shell flex overflow-hidden bg-[var(--bg-app)] font-sans text-[var(--fg-1)] transition-colors duration-300">
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
        onCourtClick={() => navigate('/court')}
        onSettingsClick={() => navigate('/settings')}
        onLogout={handleLogout}
        isDesktopLayout={windowWidth >= 1024}
      />

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {secureAccessBanner}
        <Header
          title={currentConversation.title}
          isSidebarOpen={isSidebarOpen}
          setIsSidebarOpen={setIsSidebarOpen}
          isWorkspaceOpen={isWorkspaceOpen}
          setIsWorkspaceOpen={setIsWorkspaceOpen}
          workspaceFilesCount={workspaceFiles.length}
          onSettingsClick={() => navigate('/settings')}
        />

        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-[var(--bg-app)]">
            {messages.length === 0 ? (
              <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden text-[var(--fg-3)]">
                <div className="pointer-events-none absolute inset-x-0 top-1/4 mx-auto h-72 max-w-xl rounded-full bg-[var(--accent)] opacity-[0.06] blur-3xl" />
                <div className="relative max-w-md px-6 text-center">
                  <BrandMark className="mx-auto mb-6 h-[72px] w-[72px] text-[var(--accent)]" />
                  <h2 className="t-headline-l">Welcome to Lawver</h2>
                  <p className="t-body-l t-muted mt-2 text-[15px]">Start a conversation or upload a document to begin.</p>
                </div>
              </div>
            ) : (
              <MessageList
                conversationId={currentId}
                messages={messages}
                isLoading={isLoading}
                bottomInset={composerOverlayHeight}
                onRegenerate={(id) => handleRegenerateMessage(currentId, id, handleGeneratedFile, syncFiles)}
                onEdit={(id) => handleEdit(currentId, id, setPendingUploads)}
                onUndo={(id) => handleUndo(currentId, id, setPendingUploads)}
                onBranch={(id) => branchConversation(currentId, id)}
              />
            )}

            <InputArea
              input={input}
              setInput={setInput}
              handleSend={() => handleSend(pendingUploads, setPendingUploads, handleGeneratedFile, syncFiles, isLowStorage)}
              isLoading={isLoading}
              composerStatus={composerStatus}
              contextUsage={contextUsage}
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
              onSettingsClearanceChange={setComposerOverlayHeight}
            />
          </div>

          <WorkspacePanel
            isWorkspaceOpen={isWorkspaceOpen}
            setIsWorkspaceOpen={setIsWorkspaceOpen}
            workspaceFiles={workspaceFiles}
            onDeleteFile={deleteFile}
            isDesktopLayout={windowWidth >= 1024}
          />
        </div>
      </div>
    </div>
  );

  return (
    <UpdateGate>
      <AnimatePresence mode="wait" initial={false}>
        <React.Fragment key={location.pathname}>
          <Routes location={location}>
            <Route path="/" element={chatLayout} />
            <Route path="/court" element={<CourtPage onBack={() => navigate('/')} onSettingsClick={() => navigate('/settings')} secureAccessBanner={secureAccessBanner} windowWidth={windowWidth} />} />
            <Route path="/settings" element={<AnimatedRouteSurface><SettingsPage /></AnimatedRouteSurface>} />
            <Route path="/admin" element={<AnimatedRouteSurface>{userRole === 'admin' ? <AdminDashboard /> : <div className="flex min-h-[100dvh] w-full items-center justify-center bg-[var(--bg-app)] px-6 text-center text-lg font-medium text-[var(--color-danger-500)]">403 Forbidden: Access Denied</div>}</AnimatedRouteSurface>} />
          </Routes>
        </React.Fragment>
      </AnimatePresence>
    </UpdateGate>
  );
}

export default App;
