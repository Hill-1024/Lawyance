/*
 * 模块描述：React 应用根组件，串联认证状态、聊天布局、工作区、主题和管理路由。
 */

import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { App as CapacitorApp } from '@capacitor/app';
import { SplashScreen } from '@capacitor/splash-screen';
import { ShieldAlert, ExternalLink } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useStorage } from './hooks/useStorage';
import { apiFetch, verifyAuth, logout as apiLogout, setUnauthorizedHandler, type Role } from './services/api';
import { isNative } from './lib/platform';
import { APP_CONFIG } from './lib/app-config';
import { exitNativeApp, useBackButton } from './hooks/useBackButton';
import { useAppBackUp } from './hooks/useAppBack';
import { Login } from './components/Login';
import './components/login.css';
import { BrandLockup } from './components/Brand';
import { UpdateGate } from './components/UpdateGate';
import { GuidedTour } from './components/GuidedTour';
import { AnnouncementBanner } from './components/AnnouncementBanner';

const Workbench = React.lazy(() => import('./workbench/Workbench'));
const AdminDashboard = React.lazy(() => import('./components/AdminDashboard').then(module => ({ default: module.AdminDashboard })));
const BusinessConsole = React.lazy(() => import('./business/BusinessConsole'));
const SettingsPage = React.lazy(() => import('./components/SettingsPage').then(module => ({ default: module.SettingsPage })));

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
  const goUp = useAppBackUp();
  const location = useLocation();
  const settingsOpen = location.pathname.startsWith('/settings');
  const backgroundLocation = useRef(location.pathname.startsWith('/settings') ? { ...location, pathname: '/', search: '', hash: '' } : location);
  if (!settingsOpen) backgroundLocation.current = location;
  const surfaceLocation = settingsOpen ? backgroundLocation.current : location;

  const { requestPersistence } = useStorage();

  const isIpAccess = typeof window !== 'undefined' && !isNative() && isIpHostname(window.location.hostname);
  const secureAccessUrl = typeof window !== 'undefined'
    ? `https://${SECURE_DOMAIN}${window.location.pathname}${window.location.search}${window.location.hash}`
    : `https://${SECURE_DOMAIN}`;

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      setIsAuthenticated(false);
      setUserRole('user');
      // 登录页是不做鉴权的唯一入口；其余路径都由守卫送去 /login。
      // 会话过期发生在受守卫路由时才踢人。
      const path = window.location.pathname;
      const isPublicPath = path.startsWith('/login');
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

  // 登录成功：拉到工作台状态后进工作台；深链被守卫拦下时按 state.from 送回原路径。
  const handleLoginSuccess = async (data: { role?: Role }) => {
    setUserRole(data.role || 'user');
    setIsAuthenticated(true);
    const from = (location.state as { from?: string } | null)?.from;
    try {
      const res = await apiFetch('/api/workbench/status');
      const status = res.ok ? await res.json() : null;
      setWorkbenchStatus(status || { enabled: false, username: '' });
    } catch {
      setWorkbenchStatus({ enabled: false, username: '' });
    }
    navigate(from || '/home', { replace: true });
  };

  useEffect(() => { if (isAuthenticated) apiFetch('/api/workbench/status').then(r=>r.ok?r.json():null).then(s=>setWorkbenchStatus(s||{enabled:false,username:''})).catch(()=>setWorkbenchStatus({enabled:false,username:''})); else setWorkbenchStatus(undefined); }, [isAuthenticated]);

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

  useBackButton(useCallback(() => {
    // 退栈优先：深链直接进入子页时退栈会离开应用，此时由 goUp 改用 replace 落到父级。
    if (goUp()) return true;
    exitNativeApp().catch(console.error);
    return true;
  }, [goUp]), isAuthenticated);

  if (isAuthChecking) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-app)] text-[var(--accent)] transition-colors duration-300">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-[var(--accent-quiet)] border-t-[var(--accent)]" />
      </div>
    );
  }

  const secureAccessBanner = isIpAccess ? (
    <div className="lg-notice">
      <div className="lg-notice-body">
        <ShieldAlert size={18} strokeWidth={2} aria-hidden="true" />
        <div>
          <div className="lg-notice-strong">当前正在通过 IP 访问。</div>
          <div>
            建议改用 <span className="lg-notice-strong">https://{SECURE_DOMAIN}</span> 访问，避免证书与登录状态问题。
          </div>
        </div>
      </div>
      <a href={secureAccessUrl} className="lg-notice-action">
        前往安全地址
        <ExternalLink size={15} strokeWidth={2} aria-hidden="true" />
      </a>
    </div>
  ) : null;

  // 介绍页是公开路由；受守卫路由的认证检查内联在各路由元素中。
  const guardState = { from: location.pathname + location.search };
  const requireAuth = (element: React.ReactNode) =>
    isAuthenticated ? element : <Navigate to="/login" state={guardState} replace />;
  const workbenchPath = '/home';
  const loginRoute = (
    <Login onLoginSuccess={handleLoginSuccess} notice={secureAccessBanner} />
  );

  // 工作台状态在登录后异步拉取；未返回前给加载态，避免冷加载被判成「未启用」。
  const workbenchElement =
    isAuthenticated && !workbenchStatus ? (
      <RouteLoadingFallback />
    ) : workbenchStatus?.enabled ? (
      <React.Suspense fallback={<RouteLoadingFallback />}>
        <Workbench key={workbenchStatus.username} username={workbenchStatus.username} />
      </React.Suspense>
    ) : (
      <WorkbenchUnavailable onLogout={handleLogout} />
    );
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
            {/* 介绍页已迁到独立仓库与独立进程（介绍页仓 Lawyance_Intro），
                这里只剩功能页；/ 与未知路径都回工作台，未登录再由守卫送去 /login。 */}
            <Route path="/" element={<Navigate to={workbenchPath} replace />} />
            <Route path="/login" element={isAuthenticated ? <Navigate to={workbenchPath} replace /> : loginRoute} />
            <Route path="/home" element={requireAuth(workbenchElement)} />
            <Route path="/project/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/conversation/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/court/:uuid" element={requireAuth(workbenchElement)} />
            <Route path="/court" element={
              <Navigate replace to={'/court/' + (courtSession || 'new') + (courtProject ? '?project=' + encodeURIComponent(courtProject) : '')} />
            } />
            <Route path="/settings/*" element={requireAuth(<AnimatedRouteSurface><React.Suspense fallback={<RouteLoadingFallback />}><SettingsPage /></React.Suspense></AnimatedRouteSurface>)} />
            {/* Business 母账号的控制台：后端按套餐判权，非 business 账号由页面渲染说明页。 */}
            <Route path="/business" element={requireAuth(<AnimatedRouteSurface><React.Suspense fallback={<RouteLoadingFallback />}><BusinessConsole /></React.Suspense></AnimatedRouteSurface>)} />
            <Route path="/admin" element={requireAuth(<AnimatedRouteSurface>{userRole === 'sudo' || userRole === 'admin' ? <React.Suspense fallback={<RouteLoadingFallback />}><AdminDashboard role={userRole} onLogout={handleLogout} /></React.Suspense> : <div className="flex min-h-[100dvh] w-full items-center justify-center bg-[var(--bg-app)] px-6 text-center text-lg font-medium text-[var(--color-danger-500)]">403 Forbidden: Access Denied</div>}</AnimatedRouteSurface>)} />
            {/* 旧路径（/legacy、迁移走的介绍页路径及任何已经消失的深链）一律回工作台，不留白屏。 */}
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </React.Fragment>
      </AnimatePresence>
      </div>
      <AnimatePresence>{settingsOpen && <React.Suspense key="settings" fallback={<div className="fixed inset-0 z-[var(--z-route-modal)] bg-[var(--bg-overlay)]" role="status" aria-label="正在打开设置" />}><SettingsPage onClose={() => navigate(backgroundLocation.current.pathname + backgroundLocation.current.search, { replace: true })} /></React.Suspense>}</AnimatePresence>
      {/*
       * 指引是首次启动的模态层，只在工作台里有锚点。
       * 等 workbenchStatus 落地再挂载，避免先渲染再整套换掉。
       * 设置页开着时不挂载，否则两个模态互抢焦点，且指引会盖在设置之上。
       */}
      {isAuthenticated && workbenchStatus?.enabled && !settingsOpen && <GuidedTour />}
      {isAuthenticated && <AnnouncementBanner />}
    </UpdateGate>
  );
}

/** 未启用工作台时的落点：服务端没配数据库就进不去，给明确出口而不是白屏。 */
function WorkbenchUnavailable({ onLogout }: { onLogout: () => void }) {
  return (
    <div className="lg-page">
      <section className="lg-sheet" aria-labelledby="wb-unavailable-title">
        <header className="lg-head">
          <BrandLockup />
          <h1 className="lg-title" id="wb-unavailable-title">
            工作台尚未就绪
          </h1>
          <p className="lg-sub">
            服务端还没有配置云端数据库，账号与资料暂时无法读取。请联系管理员完成配置后重试。
          </p>
        </header>
        <div className="lg-form">
          <button type="button" className="lg-submit" onClick={() => window.location.reload()}>
            重试
          </button>
        </div>
        <footer className="lg-foot">
          <span>需要帮助请联系管理员</span>
          <button type="button" className="lg-link" onClick={onLogout}>
            退出登录
          </button>
        </footer>
      </section>
    </div>
  );
}

export default App;
