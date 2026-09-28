/*
 * 模块描述：React 应用根组件，串联认证状态、聊天布局、工作区、主题和管理路由。
 */

import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { App as CapacitorApp } from '@capacitor/app';
import { SplashScreen } from '@capacitor/splash-screen';
import { ShieldAlert, ExternalLink } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useChat } from './hooks/useChat';
import { useWorkspace } from './hooks/useWorkspace';
import { useStorage } from './hooks/useStorage';
import { apiFetch, sendHeartbeat, verifyAuth, logout as apiLogout, setUnauthorizedHandler, type Role } from './services/api';
import { isNative } from './lib/platform';
import { APP_CONFIG } from './lib/app-config';
import { exitNativeApp, useBackButton } from './hooks/useBackButton';
import { useAppBack, useAppBackUp } from './hooks/useAppBack';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { WorkspacePanel } from './components/WorkspacePanel';
import { InputArea } from './components/InputArea';
import { Login } from './components/Login';
import { BrandMark } from './components/Brand';
import { UpdateGate } from './components/UpdateGate';
import { GuidedTour } from './components/GuidedTour';

const Workbench = React.lazy(() => import('./workbench/Workbench'));
const AdminDashboard = React.lazy(() => import('./components/AdminDashboard').then(module => ({ default: module.AdminDashboard })));
const CourtPage = React.lazy(() => import('./components/CourtPage').then(module => ({ default: module.CourtPage })));
const MessageList = React.lazy(() => import('./components/MessageList').then(module => ({ default: module.MessageList })));
const SettingsPage = React.lazy(() => import('./components/SettingsPage').then(module => ({ default: module.SettingsPage })));
const IntroLayout = React.lazy(() => import('./intro/IntroLayout'));
const IntroHome = React.lazy(() => import('./intro/HomePage'));
const IntroDesign = React.lazy(() => import('./intro/DesignPage'));
const IntroDownload = React.lazy(() => import('./intro/DownloadPage'));

const SECURE_DOMAIN = APP_CONFIG.domain;
const ROUTE_TRANSITION = { duration: 0.26, ease: [0.2, 0, 0, 1] } as const;

const RouteLoadingFallback = () => (
  <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-app)] text-[var(--accent)]">
    <div className="h-10 w-10 animate-spin rounded-full border-2 border-[var(--accent-quiet)] border-t-[var(--accent)]" />
  </div>
);

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
      className="min-h-[100dvh] w-full max-w-full overflow-x-hidden bg-[var(--bg-app)]"
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
  const [workbenchStatus, setWorkbenchStatus] = useState<{enabled:boolean;username:string}>();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [userRole, setUserRole] = useState<Role>('user');
  const navigate = useNavigate();
  // 返回上级一律退栈；深链进入时改用 replace，避免压栈造成"返回又前进"。
  const goBack = useAppBack();
  const goUp = useAppBackUp();
  const location = useLocation();
  const settingsOpen = location.pathname.startsWith('/settings');
  const backgroundLocation = useRef(location.pathname.startsWith('/settings') ? { ...location, pathname: '/', search: '', hash: '' } : location);
  if (!settingsOpen) backgroundLocation.current = location;
  const surfaceLocation = settingsOpen ? backgroundLocation.current : location;

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
    activeAssistantMessageId,
    handleNewChat,
    deleteConversation,
    handleSend,
    handleRegenerateMessage,
    handleUserChoice,
    stopActiveGeneration,
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
    restorePendingUploads,
    isUploadingFiles,
    handleFileUpload,
    handleGeneratedFile,
    removeUploadedFile,
    deleteFile,
    syncFiles
  } = useWorkspace(currentId, isAuthenticated && isInitialized && (workbenchStatus?.enabled === false || location.pathname === '/legacy'));
  const { isLowStorage, requestPersistence } = useStorage();

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputExpanded, setIsInputExpanded] = useState(false);
  const [composerOverlayHeight, setComposerOverlayHeight] = useState(0);
  const [composerHeight, setComposerHeight] = useState(0);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1024);
  const isIpAccess = typeof window !== 'undefined' && !isNative() && isIpHostname(window.location.hostname);
  const secureAccessUrl = typeof window !== 'undefined'
    ? `https://${SECURE_DOMAIN}${window.location.pathname}${window.location.search}${window.location.hash}`
    : `https://${SECURE_DOMAIN}`;

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      setIsAuthenticated(false);
      setUserRole('user');
      // 公开路由（介绍页/登录）上不踢人：未登录时后台 hooks 的请求会吃 401，
      // 访客浏览介绍页不应被打断；会话过期发生在受守卫路由时才送去登录。
      const path = window.location.pathname;
      const isPublicPath = path === '/' || path === '/design' || path === '/download' || path.startsWith('/login');
      if (!isPublicPath) navigate('/login');
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  const handleLogout = async () => {
    try {
      await apiLogout();
      setIsAuthenticated(false);
      setUserRole('user');
      navigate('/login');
    } catch (e) {
      console.error("Logout failed:", e);
      // Fallback: clear auth state anyway
      setIsAuthenticated(false);
      setUserRole('user');
      navigate('/login');
    }
  };

  // 登录成功：拉工作台灰度状态决定落点（workbench → /home，旧版 → /legacy），
  // 深链被守卫拦下时按 state.from 送回原路径。
  const handleLoginSuccess = async (data: { role?: Role }) => {
    setUserRole(data.role || 'user');
    setIsAuthenticated(true);
    const from = (location.state as { from?: string } | null)?.from;
    try {
      const res = await apiFetch('/api/v2/status');
      const status = res.ok ? await res.json() : null;
      setWorkbenchStatus(status || { enabled: false, username: '' });
      navigate(from || (status?.enabled ? '/home' : '/legacy'), { replace: true });
    } catch {
      setWorkbenchStatus({ enabled: false, username: '' });
      navigate(from || '/legacy', { replace: true });
    }
  };

  useEffect(() => { if (isAuthenticated) apiFetch('/api/v2/status').then(r=>r.ok?r.json():null).then(s=>setWorkbenchStatus(s||{enabled:false,username:''})).catch(()=>setWorkbenchStatus({enabled:false,username:''})); else setWorkbenchStatus(undefined); }, [isAuthenticated]);

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
    if (!isNative()) {
      requestPersistence().catch(console.error);
    }
  }, []);

  useEffect(() => {
    if (!isNative()) return;

    let listener: { remove: () => Promise<void> } | undefined;
    // 卸载可能早于 addListener 的 Promise 落地；用 disposed 标记补摘，
    // 否则监听器会永久留在原生层。
    let disposed = false;
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
      if (disposed) {
        void handle.remove();
        return;
      }
      listener = handle;
    });

    return () => {
      disposed = true;
      listener?.remove();
    };
  }, []);

  useEffect(() => {
    // resize 事件在一次拖拽中会连发上百次，而 windowWidth 只用于 1024 断点判定；
    // 用 rAF 合并到每帧一次，避免整个 App 每像素重渲染一次。
    let frame = 0;
    const handleResize = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setWindowWidth(window.innerWidth);
      });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  useEffect(() => {
    if (!currentId || !isAuthenticated || !isInitialized || (location.pathname !== '/legacy' && workbenchStatus?.enabled !== false)) return;

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
  }, [currentId, isAuthenticated, isInitialized, syncFiles, workbenchStatus?.enabled, location.pathname]);

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
    // 退栈优先：深链直接进入子页时退栈会离开应用，此时由 goUp 改用 replace 落到父级。
    if (goUp()) return true;
    exitNativeApp().catch(console.error);
    return true;
  }, [isInputExpanded, isSidebarOpen, isWorkspaceOpen, goUp]), isAuthenticated && isInitialized);

  const activeChoicePrompt = React.useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === 'assistant' && message.pending_choice && !message.pending_choice.answered) {
        return {
          messageId: message.id,
          choice: message.pending_choice
        };
      }
    }
    return null;
  }, [messages]);

  // 消息列表的操作回调用 ref 持有最新实现、外层暴露稳定引用：否则输入框每敲一个键
  // 都会让 App 重渲染并连带整列消息重新渲染（每条消息都要重跑 Markdown 解析）。
  const messageActionsRef = React.useRef({
    currentId,
    handleRegenerateMessage,
    handleUserChoice,
    handleEdit,
    handleUndo,
    branchConversation,
    handleGeneratedFile,
    syncFiles,
    setPendingUploads,
    restorePendingUploads,
  });
  // 在 effect 里刷新而不是渲染期赋值：并发渲染下渲染可能被丢弃或重放，渲染期写 ref 不纯。
  useEffect(() => {
    messageActionsRef.current = {
      currentId,
      handleRegenerateMessage,
      handleUserChoice,
      handleEdit,
      handleUndo,
      branchConversation,
      handleGeneratedFile,
      syncFiles,
      setPendingUploads,
      restorePendingUploads,
    };
  });

  const onRegenerateMessage = useCallback((id: string) => {
    const actions = messageActionsRef.current;
    return actions.handleRegenerateMessage(actions.currentId, id, actions.handleGeneratedFile, actions.syncFiles);
  }, []);
  const onAnswerMessageChoice = useCallback((id: string, value: string) => {
    const actions = messageActionsRef.current;
    return actions.handleUserChoice(id, value, actions.handleGeneratedFile, actions.syncFiles);
  }, []);
  const onEditMessage = useCallback((id: string) => {
    const actions = messageActionsRef.current;
    return actions.handleEdit(actions.currentId, id, actions.restorePendingUploads);
  }, []);
  const onUndoMessage = useCallback((id: string) => {
    const actions = messageActionsRef.current;
    return actions.handleUndo(actions.currentId, id, actions.restorePendingUploads);
  }, []);
  const onBranchMessage = useCallback((id: string) => {
    const actions = messageActionsRef.current;
    return actions.branchConversation(actions.currentId, id);
  }, []);

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
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-warning-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#9A6F22]"
        >
          前往安全地址
          <ExternalLink size={16} strokeWidth={2} />
        </a>
      </div>
    </div>
  ) : null;

  // 介绍页是公开路由；受守卫路由的认证检查内联在各路由元素中。
  const guardState = { from: location.pathname + location.search };
  const requireAuth = (element: React.ReactNode) =>
    isAuthenticated ? element : <Navigate to="/login" state={guardState} replace />;
  const workbenchPath = workbenchStatus?.enabled ? '/home' : '/legacy';
  const loginRoute = (
    <div className="min-h-screen bg-[var(--bg-app)] transition-colors duration-300">
      {secureAccessBanner}
      <Login onLoginSuccess={handleLoginSuccess} />
    </div>
  );

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
              <React.Suspense fallback={<div className="min-h-0 flex-1" aria-hidden="true" />}>
                <MessageList
                  conversationId={currentId}
                  messages={messages}
                  isLoading={isLoading}
                  activeAssistantMessageId={activeAssistantMessageId}
                  bottomInset={composerOverlayHeight}
                  composerHeight={composerHeight}
                  onRegenerate={onRegenerateMessage}
                  onAnswerChoice={onAnswerMessageChoice}
                  onEdit={onEditMessage}
                  onUndo={onUndoMessage}
                  onBranch={onBranchMessage}
                />
              </React.Suspense>
            )}

            <InputArea
              input={input}
              setInput={setInput}
              handleSend={() => {
                if (isUploadingFiles) return;
                handleSend(pendingUploads, setPendingUploads, handleGeneratedFile, syncFiles, isLowStorage);
              }}
              handleStop={stopActiveGeneration}
              activeChoicePrompt={activeChoicePrompt}
              onAnswerChoice={onAnswerMessageChoice}
              isLoading={isLoading}
              composerStatus={composerStatus}
              contextUsage={contextUsage}
              pendingUploads={pendingUploads}
              isUploadingFiles={isUploadingFiles}
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
              onComposerHeightChange={setComposerHeight}
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

  // 工作台灰度状态在登录后异步拉取；未返回前不判定「未启用」，避免冷加载被误重定向到 /legacy。
  const workbenchElement =
    isAuthenticated && !workbenchStatus ? (
      <RouteLoadingFallback />
    ) : workbenchStatus?.enabled ? (
      <React.Suspense fallback={<RouteLoadingFallback />}>
        <Workbench key={workbenchStatus.username} username={workbenchStatus.username} />
      </React.Suspense>
    ) : (
      <Navigate to="/legacy" replace />
    );
  const legacyChat = isInitialized ? chatLayout : <RouteLoadingFallback />;
  const courtRedirectParams = new URLSearchParams(surfaceLocation.search);
  const courtProject = courtRedirectParams.get('project');
  const courtSession = courtRedirectParams.get('session');
  // 工作台四条路径共用一个过渡 key：路径化切换（/home ↔ /project ↔ /conversation ↔ /court）
  // 不重挂 Workbench，内存态与轮询得以延续；其余路由仍按整路径过渡。
  const firstSegment = surfaceLocation.pathname.split('/').filter(Boolean)[0] || '';
  const surfaceKey = ['home', 'project', 'conversation', 'court'].includes(firstSegment)
    ? 'workbench'
    : surfaceLocation.pathname;

  return (
    <UpdateGate>
      <div data-settings-background="" inert={settingsOpen}>
      <AnimatePresence mode="wait" initial={false}>
        <React.Fragment key={surfaceKey}>
          <Routes location={surfaceLocation}>
            <Route path="/" element={<IntroHomeRoute isAuthenticated={isAuthenticated} workbenchEnabled={!!workbenchStatus?.enabled} />} />
            <Route path="/design" element={
              <React.Suspense fallback={<RouteLoadingFallback />}>
                <IntroLayout activePage="design" isAuthenticated={isAuthenticated} workbenchEnabled={!!workbenchStatus?.enabled}>
                  <IntroDesign />
                </IntroLayout>
              </React.Suspense>
            } />
            <Route path="/download" element={
              <React.Suspense fallback={<RouteLoadingFallback />}>
                <IntroLayout activePage="download" isAuthenticated={isAuthenticated} workbenchEnabled={!!workbenchStatus?.enabled}>
                  <IntroDownload />
                </IntroLayout>
              </React.Suspense>
            } />
            <Route path="/login" element={isAuthenticated ? <Navigate to={workbenchPath} replace /> : loginRoute} />
            <Route path="/home" element={requireAuth(workbenchElement)} />
            <Route path="/project/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/conversation/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/court/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/legacy" element={requireAuth(legacyChat)} />
            <Route path="/court" element={
              workbenchStatus?.enabled
                ? <Navigate replace to={'/court/' + (courtSession || 'new') + (courtProject ? '?project=' + encodeURIComponent(courtProject) : '')} />
                : <React.Suspense fallback={<RouteLoadingFallback />}><CourtPage onBack={() => goBack('/')} onSettingsClick={() => navigate('/settings')} secureAccessBanner={secureAccessBanner} windowWidth={windowWidth} /></React.Suspense>
            } />
            <Route path="/settings/*" element={requireAuth(<AnimatedRouteSurface><React.Suspense fallback={<RouteLoadingFallback />}><SettingsPage /></React.Suspense></AnimatedRouteSurface>)} />
            <Route path="/admin" element={requireAuth(<AnimatedRouteSurface>{userRole === 'sudo' || userRole === 'admin' ? <React.Suspense fallback={<RouteLoadingFallback />}><AdminDashboard role={userRole} onLogout={handleLogout} /></React.Suspense> : <div className="flex min-h-[100dvh] w-full items-center justify-center bg-[var(--bg-app)] px-6 text-center text-lg font-medium text-[var(--color-danger-500)]">403 Forbidden: Access Denied</div>}</AnimatedRouteSurface>)} />
          </Routes>
        </React.Fragment>
      </AnimatePresence>
      </div>
      <AnimatePresence>{settingsOpen && <React.Suspense key="settings" fallback={<div className="fixed inset-0 z-[var(--z-route-modal)] bg-[var(--bg-overlay)]" role="status" aria-label="正在打开设置" />}><SettingsPage onClose={() => navigate(backgroundLocation.current.pathname + backgroundLocation.current.search, { replace: true })} /></React.Suspense>}</AnimatePresence>
      {/*
       * 指引是首次启动的模态层，工作台和旧版聊天都要有：锚点与文案按落点分两套。
       * 等 workbenchStatus 落地再挂载，否则会先按旧版那套渲染、拿到状态后又整套换掉。
       * 设置页开着时不挂载，否则两个模态互抢焦点，且指引会盖在设置之上。
       */}
      {isAuthenticated && workbenchStatus && !settingsOpen && (
        <GuidedTour
          variant={workbenchStatus.enabled ? 'workbench' : 'chat'}
          isSidebarOpen={isSidebarOpen}
          setIsSidebarOpen={setIsSidebarOpen}
        />
      )}
    </UpdateGate>
  );
}

/** 介绍页首页路由：携带旧版 query 深链（/?project|conversation|court=…）时先重定向到新路径。 */
function IntroHomeRoute({ isAuthenticated, workbenchEnabled }: { isAuthenticated: boolean; workbenchEnabled: boolean }) {
  const [params] = useSearchParams();
  const project = params.get('project');
  const conversation = params.get('conversation');
  const court = params.get('court');
  if (conversation) return <Navigate replace to={'/conversation/' + conversation} />;
  if (court) {
    return <Navigate replace to={'/court/' + court + (project ? '?project=' + encodeURIComponent(project) : '')} />;
  }
  if (project) return <Navigate replace to={'/project/' + project} />;
  return (
    <React.Suspense fallback={<RouteLoadingFallback />}>
      <IntroLayout activePage="home" isAuthenticated={isAuthenticated} workbenchEnabled={workbenchEnabled}>
        <IntroHome isAuthenticated={isAuthenticated} workbenchPath={workbenchEnabled ? '/home' : '/legacy'} />
      </IntroLayout>
    </React.Suspense>
  );
}

export default App;
