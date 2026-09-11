/*
 * 模块描述：后台管理面板，按 sudo / admin 权限展示日志、账号层级与在线设备，视觉体系与主界面保持一致。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAppBack } from '../hooks/useAppBack';
import {
  Activity,
  ArrowLeft,
  Clock,
  EyeOff,
  Globe,
  KeyRound,
  Loader2,
  LogOut,
  MonitorSmartphone,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Trash2,
  User,
  Users,
  Wifi,
} from 'lucide-react';
import {
  clearLogs,
  deleteAccount,
  fetchAccounts,
  fetchLogs,
  fetchSessions,
  logout as apiLogout,
  revokeSession,
  setAccount,
  updateAccountLimits,
  verifyAuth,
  type Account,
  type AccountLimits,
  type Role,
  type SessionInfo,
} from '../services/api';
import { AnimatedSwitch } from './AnimatedSwitch';
import { BrandMark } from './Brand';
import { HoverInfo } from './HoverInfo';
import { useAppDialog } from '../contexts/DialogContext';
import {
  Banner,
  EmptyState,
  SettingsField,
  SettingsRow,
  StatusChip,
  fieldInputClass,
} from './settings/SettingsUI';

/* ── 日志解析 ── */

interface ParsedLog {
  time: string;
  ip: string;
  user: string;
  client: string;
  method: string;
  path: string;
  status: string;
  raw: string;
}

function parseLogLine(raw: string): ParsedLog {
  // 格式: "2026-04-22 19:46:30,123 | INFO | 127.0.0.1 | admin | web | POST | /api/chat | 200"
  const parts = raw.split(' | ');
  if (parts.length >= 3) {
    const afterLevel = raw.split(' | INFO | ')[1] || raw.split(' | ')[2] || '';
    const fields = afterLevel.split(' | ');
    const hasClientType = fields.length >= 6;
    return {
      time: (parts[0] || '').trim(),
      ip: (fields[0] || '').trim(),
      user: (fields[1] || '').trim(),
      client: (hasClientType ? fields[2] : 'web').trim(),
      method: (hasClientType ? fields[3] : fields[2] || '').trim(),
      path: (hasClientType ? fields[4] : fields[3] || '').trim(),
      status: (hasClientType ? fields[5] : fields[4] || '').trim(),
      raw,
    };
  }
  return { time: '', ip: '', user: '', client: '', method: '', path: '', status: '', raw };
}

const statusTone = (status: string): 'ok' | 'warn' | 'danger' | 'muted' => {
  const code = Number.parseInt(status, 10);
  if (Number.isNaN(code)) return 'muted';
  if (code >= 200 && code < 300) return 'ok';
  if (code >= 300 && code < 400) return 'warn';
  return 'danger';
};

const METHOD_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'muted' | 'accent'> = {
  GET: 'accent',
  POST: 'ok',
  PUT: 'warn',
  DELETE: 'danger',
};

const LOG_SKELETON_ROWS = 8;

const ROLE_LABEL: Record<Role, string> = {
  sudo: '超级管理员',
  admin: '管理员',
  user: '普通用户',
};

const ROLE_TONE: Record<Role, 'accent' | 'warn' | 'muted'> = {
  sudo: 'accent',
  admin: 'warn',
  user: 'muted',
};

const CLIENT_LABEL: Record<string, string> = {
  web: '浏览器',
  capacitor: '移动端',
};

const formatTime = (value?: number | null) => {
  if (!value) return '—';
  return new Date(value * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

type Tab = 'logs' | 'accounts' | 'sessions';
type ModalMode = 'add' | 'reset';

interface AdminDashboardProps {
  role: Role;
}

/* ── 组件 ── */

export const AdminDashboard: React.FC<AdminDashboardProps> = ({ role }) => {
  // 后台返回聊天必须退栈，否则再按返回又会前进回后台。
  const goBack = useAppBack();
  const { showConfirm } = useAppDialog();
  const [activeTab, setActiveTab] = useState<Tab>(role === 'sudo' ? 'logs' : 'accounts');

  const [logs, setLogs] = useState<string[]>([]);
  const [ipFilter, setIpFilter] = useState('');
  const [ignoreHeartbeat, setIgnoreHeartbeat] = useState(true);
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [isClearingLogs, setIsClearingLogs] = useState(false);
  const [isClearLogsDialogOpen, setIsClearLogsDialogOpen] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [myQuota, setMyQuota] = useState<{ max_users?: number | null; user_max_online?: number | null }>({});
  const [isAccountsLoading, setIsAccountsLoading] = useState(false);
  const [accountsError, setAccountsError] = useState('');

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isSessionsLoading, setIsSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState('');

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>('add');
  const [editUsername, setEditUsername] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [editRole, setEditRole] = useState<Role>('user');
  const [newMaxOnline, setNewMaxOnline] = useState('');
  const [newMaxUsers, setNewMaxUsers] = useState('');
  const [newUserMaxOnline, setNewUserMaxOnline] = useState('');
  const [modalError, setModalError] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const [limitsTarget, setLimitsTarget] = useState<Account | null>(null);
  const [limitMaxOnline, setLimitMaxOnline] = useState('');
  const [limitMaxUsers, setLimitMaxUsers] = useState('');
  const [limitUserMaxOnline, setLimitUserMaxOnline] = useState('');
  const [limitsError, setLimitsError] = useState('');
  const [isSavingLimits, setIsSavingLimits] = useState(false);

  const logsRequestIdRef = useRef(0);
  const accountsRequestIdRef = useRef(0);
  const sessionsRequestIdRef = useRef(0);
  const modalGenerationRef = useRef(0);
  const logsQueryRef = useRef({ ipFilter: '', ignoreHeartbeat: true });

  useEffect(() => {
    logsQueryRef.current = { ipFilter, ignoreHeartbeat };
  }, [ignoreHeartbeat, ipFilter]);

  const loadLogs = useCallback(async () => {
    const requestId = ++logsRequestIdRef.current;
    const query = logsQueryRef.current;
    setIsLogsLoading(true);
    setLogsError('');
    try {
      const data = await fetchLogs(query.ipFilter, query.ignoreHeartbeat);
      if (requestId !== logsRequestIdRef.current) return;
      setLogs(data.logs || []);
    } catch (error: any) {
      if (requestId !== logsRequestIdRef.current) return;
      setLogsError(error.message);
    } finally {
      if (requestId === logsRequestIdRef.current) setIsLogsLoading(false);
    }
  }, []);

  const loadAccounts = useCallback(async () => {
    const requestId = ++accountsRequestIdRef.current;
    setIsAccountsLoading(true);
    setAccountsError('');
    try {
      const data = await fetchAccounts();
      if (requestId !== accountsRequestIdRef.current) return;
      setAccounts(data.accounts || []);
    } catch (error: any) {
      if (requestId !== accountsRequestIdRef.current) return;
      setAccountsError(error.message);
    } finally {
      if (requestId === accountsRequestIdRef.current) setIsAccountsLoading(false);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    const requestId = ++sessionsRequestIdRef.current;
    setIsSessionsLoading(true);
    setSessionsError('');
    try {
      const data = await fetchSessions();
      if (requestId !== sessionsRequestIdRef.current) return;
      setSessions(data.sessions || []);
    } catch (error: any) {
      if (requestId !== sessionsRequestIdRef.current) return;
      setSessionsError(error.message);
    } finally {
      if (requestId === sessionsRequestIdRef.current) setIsSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (role === 'admin') {
      verifyAuth()
        .then(info => setMyQuota({ max_users: info.max_users, user_max_online: info.user_max_online }))
        .catch(() => {});
    }
  }, [role]);

  useEffect(() => {
    if (activeTab === 'logs') {
      void loadLogs();
      return () => { logsRequestIdRef.current += 1; };
    }
    if (activeTab === 'accounts') {
      void loadAccounts();
      return () => { accountsRequestIdRef.current += 1; };
    }
    void loadSessions();
    return () => { sessionsRequestIdRef.current += 1; };
  }, [activeTab, loadAccounts, loadLogs, loadSessions]);

  useEffect(() => {
    if (!isClearLogsDialogOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isClearingLogs) setIsClearLogsDialogOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isClearLogsDialogOpen, isClearingLogs]);

  const confirmClearLogs = async () => {
    logsRequestIdRef.current += 1;
    setIsLogsLoading(false);
    setIsClearingLogs(true);
    setLogsError('');
    try {
      await clearLogs();
      setLogs([]);
      setIsClearLogsDialogOpen(false);
    } catch (e: any) {
      setLogsError(e.message);
    } finally {
      setIsClearingLogs(false);
    }
  };

  const buildLimits = (): AccountLimits => {
    if (role !== 'sudo' || modalMode !== 'add' || editRole === 'sudo') return {};
    const limits: AccountLimits = {
      max_online: newMaxOnline.trim() === '' ? 0 : Number(newMaxOnline),
    };
    if (editRole === 'admin') {
      limits.max_users = newMaxUsers.trim() === '' ? -1 : Number(newMaxUsers);
      limits.user_max_online = newUserMaxOnline.trim() === '' ? 0 : Number(newUserMaxOnline);
    }
    return limits;
  };

  const handleSaveAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    const generation = modalGenerationRef.current;
    setModalError('');
    const limits = buildLimits();
    if (Object.values(limits).some(value => Number.isNaN(value))) {
      setModalError('配额必须是数字，留空表示不限制。');
      return;
    }
    setIsSaving(true);
    try {
      await setAccount(editUsername, editPassword, editRole, limits);
      void loadAccounts();
      if (generation !== modalGenerationRef.current) return;
      setIsSaving(false);
      setIsModalOpen(false);
      modalGenerationRef.current += 1;
    } catch (error: any) {
      if (generation !== modalGenerationRef.current) return;
      setModalError(error.message);
    } finally {
      if (generation === modalGenerationRef.current) setIsSaving(false);
    }
  };

  const handleDeleteAccount = async (username: string) => {
    if (username === 'admin') return;
    const confirmed = await showConfirm({
      title: '删除账号？',
      message: `确定要删除账号「${username}」吗？其在线设备会立即下线，此操作不可撤销。`,
      tone: 'danger',
      confirmLabel: '删除',
    });
    if (!confirmed) return;
    try {
      await deleteAccount(username);
      void loadAccounts();
    } catch (e: any) {
      setAccountsError(e.message);
    }
  };

  const openLimitsModal = (account: Account) => {
    setLimitsTarget(account);
    setLimitMaxOnline(account.max_online == null ? '' : String(account.max_online));
    setLimitMaxUsers(account.max_users == null ? '' : String(account.max_users));
    setLimitUserMaxOnline(account.user_max_online == null ? '' : String(account.user_max_online));
    setLimitsError('');
    setIsSavingLimits(false);
  };

  const handleSaveLimits = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!limitsTarget) return;
    setLimitsError('');
    const limits: AccountLimits =
      limitsTarget.role === 'admin'
        ? {
            max_users: limitMaxUsers.trim() === '' ? -1 : Number(limitMaxUsers),
            user_max_online: limitUserMaxOnline.trim() === '' ? 0 : Number(limitUserMaxOnline),
          }
        : { max_online: limitMaxOnline.trim() === '' ? 0 : Number(limitMaxOnline) };
    if (Object.values(limits).some(value => Number.isNaN(value))) {
      setLimitsError('配额必须是数字，留空表示不限制。');
      return;
    }
    setIsSavingLimits(true);
    try {
      await updateAccountLimits(limitsTarget.username, limits);
      void loadAccounts();
      setLimitsTarget(null);
    } catch (error: any) {
      setLimitsError(error.message);
    } finally {
      setIsSavingLimits(false);
    }
  };

  const handleKickSession = async (session: SessionInfo) => {
    const confirmed = await showConfirm({
      title: '下线该设备？',
      message: `将强制账号「${session.username}」的这台设备退出登录。`,
      tone: 'danger',
      confirmLabel: '下线',
    });
    if (!confirmed) return;
    try {
      await revokeSession(session.sid);
      void loadSessions();
    } catch (e: any) {
      setSessionsError(e.message);
    }
  };

  const closeAccountModal = useCallback(() => {
    modalGenerationRef.current += 1;
    setIsModalOpen(false);
    setIsSaving(false);
  }, []);

  const openAddModal = () => {
    modalGenerationRef.current += 1;
    setModalMode('add');
    setEditUsername('');
    setEditPassword('');
    setEditRole('user');
    setNewMaxOnline('');
    setNewMaxUsers('');
    setNewUserMaxOnline('');
    setModalError('');
    setIsSaving(false);
    setIsModalOpen(true);
  };

  const openResetModal = (account: Account) => {
    modalGenerationRef.current += 1;
    setModalMode('reset');
    setEditUsername(account.username);
    setEditPassword('');
    setEditRole(account.role);
    setModalError('');
    setIsSaving(false);
    setIsModalOpen(true);
  };

  const handleLogout = async () => { try { await apiLogout(); } finally { window.location.href = '/'; } };

  const parsedLogs = useMemo(() => logs.map(parseLogLine), [logs]);

  const logStats = useMemo(() => {
    const entries = parsedLogs.filter(log => log.ip);
    const errors = entries.filter(log => Number.parseInt(log.status, 10) >= 400).length;
    const ips = new Set(entries.map(log => log.ip));
    const users = new Set(entries.map(log => log.user).filter(Boolean));
    return { total: entries.length, errors, ips: ips.size, users: users.size };
  }, [parsedLogs]);

  const staffCount = accounts.filter(a => a.role === 'sudo' || a.role === 'admin').length;
  const onlineDeviceCount = sessions.filter(s => s.online).length;
  const quotaReached = role === 'admin' && myQuota.max_users != null && accounts.length >= myQuota.max_users;

  return (
    <div className="flex h-[100dvh] w-full max-w-full flex-col overflow-x-hidden bg-[var(--bg-app)] text-[var(--fg-1)] transition-colors duration-500">
      <header className="lawver-topbar sticky top-0 z-30 flex w-full max-w-full shrink-0 items-center justify-between gap-3 overflow-hidden border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-3 pb-2 pt-[calc(0.625rem+var(--safe-top))] sm:px-5 sm:pb-3 sm:pt-[calc(0.75rem+var(--safe-top))]">
        <div className="flex min-w-0 items-center gap-2">
          <HoverInfo label="返回聊天" placement="bottom">
            <button
              onClick={() => goBack('/')}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              aria-label="返回聊天"
            >
              <ArrowLeft size={20} strokeWidth={2} />
            </button>
          </HoverInfo>
          <span className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)] sm:flex">
            <BrandMark className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <h1 className="t-title-l truncate">{role === 'sudo' ? '系统管理' : '用户管理'}</h1>
            <p className="truncate text-[12px] text-[var(--fg-3)]">
              {role === 'sudo' ? '访问审计与账号层级管理' : '管理自己创建的用户'}
            </p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="md3-btn-text lawver-pressable shrink-0 !text-[var(--color-danger-500)] text-sm"
        >
          <LogOut size={16} strokeWidth={2} /> 退出
        </button>
      </header>

      <div className="shrink-0 px-3 pt-4 sm:px-5">
        <div className="inline-flex flex-wrap rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-1)]">
          {role === 'sudo' && (
            <button
              onClick={() => setActiveTab('logs')}
              className={`md3-seg-btn ${activeTab === 'logs' ? 'active' : ''}`}
              aria-pressed={activeTab === 'logs'}
            >
              <Activity size={16} strokeWidth={2} /> 使用日志
            </button>
          )}
          <button
            onClick={() => setActiveTab('accounts')}
            className={`md3-seg-btn ${activeTab === 'accounts' ? 'active' : ''}`}
            aria-pressed={activeTab === 'accounts'}
          >
            <Users size={16} strokeWidth={2} /> {role === 'sudo' ? '全部账号' : '我的用户'}
          </button>
          <button
            onClick={() => setActiveTab('sessions')}
            className={`md3-seg-btn ${activeTab === 'sessions' ? 'active' : ''}`}
            aria-pressed={activeTab === 'sessions'}
          >
            <MonitorSmartphone size={16} strokeWidth={2} /> 在线设备
          </button>
        </div>
      </div>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden px-3 pb-5 pt-4 sm:px-5">
        {activeTab === 'logs' && role === 'sudo' ? (
          <div className="flex h-full min-w-0 flex-col gap-3">
            {/* 概览 */}
            <div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { label: '本次读取', value: logStats.total, hint: '条记录' },
                { label: '异常响应', value: logStats.errors, hint: '4xx / 5xx', danger: logStats.errors > 0 },
                { label: '来源 IP', value: logStats.ips, hint: '去重后' },
                { label: '活跃用户', value: logStats.users, hint: '去重后' },
              ].map(stat => (
                <div
                  key={stat.label}
                  className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2.5 shadow-[var(--shadow-1)]"
                >
                  <p className="text-[11px] font-medium text-[var(--fg-3)]">{stat.label}</p>
                  <p className={`mt-0.5 text-[19px] font-semibold tabular-nums leading-6 ${
                    stat.danger ? 'text-[var(--color-danger-500)]' : 'text-[var(--fg-1)]'
                  }`}>
                    {stat.value}
                  </p>
                  <p className="text-[11px] text-[var(--fg-4)]">{stat.hint}</p>
                </div>
              ))}
            </div>

            {/* 工具条 */}
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="relative min-w-0 w-full flex-1 sm:min-w-[200px] sm:max-w-sm">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--fg-4)]" strokeWidth={2} />
                <input
                  type="text"
                  placeholder="按 IP 地址过滤…"
                  value={ipFilter}
                  onChange={e => {
                    const value = e.target.value;
                    logsQueryRef.current = { ...logsQueryRef.current, ipFilter: value };
                    setIpFilter(value);
                  }}
                  onKeyDown={e => e.key === 'Enter' && loadLogs()}
                  className="md3-input min-h-11 !rounded-full !py-2.5 !pl-10"
                  aria-label="按 IP 地址过滤日志"
                />
              </div>
              <AnimatedSwitch
                checked={ignoreHeartbeat}
                onCheckedChange={checked => {
                  logsQueryRef.current = { ...logsQueryRef.current, ignoreHeartbeat: checked };
                  setIgnoreHeartbeat(checked);
                }}
                label="隐藏心跳"
                size="sm"
              />
              <button onClick={loadLogs} disabled={isLogsLoading} className="md3-btn-tonal lawver-pressable disabled:opacity-50">
                {isLogsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" strokeWidth={2} />} 刷新
              </button>
              <button
                onClick={() => setIsClearLogsDialogOpen(true)}
                disabled={isLogsLoading || isClearingLogs}
                className="md3-btn-tonal lawver-pressable !text-[var(--color-danger-500)] disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" strokeWidth={2} /> 清理日志
              </button>
            </div>

            {logsError && <Banner tone="danger">{logsError}</Banner>}

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
              {isLogsLoading && parsedLogs.length === 0 ? (
                <div className="flex-1 space-y-3 p-4" aria-busy="true">
                  {Array.from({ length: LOG_SKELETON_ROWS }).map((_, index) => (
                    <div key={index} className="flex items-center gap-3">
                      <span className="h-3 w-24 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                      <span className="h-3 w-20 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                      <span className="h-3 flex-1 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                      <span className="h-3 w-10 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                    </div>
                  ))}
                </div>
              ) : parsedLogs.length === 0 ? (
                <EmptyState
                  icon={<EyeOff size={22} strokeWidth={2} />}
                  title="暂无日志记录"
                  description="产生 API 访问后，这里会显示时间、来源 IP、用户、方法与响应状态。"
                />
              ) : (
                <div className="md3-scroll min-h-0 flex-1 overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10">
                      <tr className="bg-[var(--bg-surface-2)] shadow-[inset_0_-1px_0_var(--border-subtle)]">
                        <th className="t-label-s t-muted px-3 py-2.5 text-left sm:px-4">时间</th>
                        <th className="t-label-s t-muted px-3 py-2.5 text-left sm:px-4">IP</th>
                        <th className="t-label-s t-muted hidden px-3 py-2.5 text-left sm:table-cell sm:px-4">用户</th>
                        <th className="t-label-s t-muted hidden px-3 py-2.5 text-left lg:table-cell lg:px-4">客户端</th>
                        <th className="t-label-s t-muted px-3 py-2.5 text-left sm:px-4">方法</th>
                        <th className="t-label-s t-muted hidden px-3 py-2.5 text-left lg:table-cell lg:px-4">路径</th>
                        <th className="t-label-s t-muted px-3 py-2.5 text-right sm:px-4">状态</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {parsedLogs.map((log, i) => (
                        log.ip ? (
                          <React.Fragment key={i}>
                            <tr
                              onClick={() => setExpandedLog(expandedLog === log.raw ? null : log.raw)}
                              className={`cursor-pointer transition-colors hover:bg-[rgba(59,98,184,0.05)] ${expandedLog === log.raw ? 'bg-[var(--accent-quiet)]' : ''}`}
                            >
                              <td className="whitespace-nowrap px-2 py-2.5 text-[var(--fg-3)] sm:px-4">
                                <span className="flex items-center gap-1.5 tabular-nums">
                                  <Clock className="hidden h-3.5 w-3.5 shrink-0 opacity-50 sm:block" strokeWidth={2} />
                                  {/* 手机上只留时刻，完整日期在 sm 以上显示，避免表格横向溢出 */}
                                  <span className="sm:hidden">{(log.time.split(' ')[1] || log.time).split(',')[0]}</span>
                                  <span className="hidden sm:inline">{log.time.split(',')[0]}</span>
                                </span>
                              </td>
                              <td className="whitespace-nowrap px-2 py-2.5 font-mono text-xs text-[var(--fg-2)] sm:px-4">
                                <span className="flex items-center gap-1.5">
                                  <Globe className="hidden h-3.5 w-3.5 shrink-0 opacity-40 sm:block" strokeWidth={2} />
                                  {log.ip}
                                </span>
                              </td>
                              <td className="hidden whitespace-nowrap px-3 py-2.5 sm:table-cell sm:px-4">
                                <span className="flex items-center gap-1.5">
                                  <User className="hidden h-3.5 w-3.5 shrink-0 opacity-40 sm:block" strokeWidth={2} />
                                  <span className="text-[var(--fg-1)]">{log.user}</span>
                                </span>
                              </td>
                              <td className="hidden whitespace-nowrap px-3 py-2.5 text-xs text-[var(--fg-3)] lg:table-cell lg:px-4">
                                <span className="flex items-center gap-1.5">
                                  <MonitorSmartphone className="h-3.5 w-3.5 shrink-0 opacity-40" strokeWidth={2} />
                                  {log.client}
                                </span>
                              </td>
                              <td className="whitespace-nowrap px-2 py-2.5 sm:px-4">
                                <StatusChip tone={METHOD_TONE[log.method] || 'muted'}>{log.method}</StatusChip>
                              </td>
                              <td className="hidden max-w-[220px] truncate px-3 py-2.5 font-mono text-xs text-[var(--fg-2)] lg:table-cell lg:max-w-[180px] lg:px-4 xl:max-w-[320px]" title={log.path}>
                                {log.path}
                              </td>
                              <td className="whitespace-nowrap px-2 py-2.5 text-right sm:px-4">
                                <StatusChip tone={statusTone(log.status)} className="tabular-nums">{log.status}</StatusChip>
                              </td>
                            </tr>
                            {expandedLog === log.raw && (
                              <tr className="bg-[var(--bg-inset)]">
                                <td colSpan={7} className="px-3 py-3 sm:px-4">
                                  <p className="mb-1 text-[11px] font-medium text-[var(--fg-3)]">原始日志行</p>
                                  <code className="block break-all font-mono text-[11px] leading-5 text-[var(--fg-2)]">{log.raw}</code>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        ) : (
                          <tr key={i}>
                            <td colSpan={7} className="break-all px-3 py-2 text-xs text-[var(--fg-3)] sm:px-4">{log.raw}</td>
                          </tr>
                        )
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : activeTab === 'accounts' ? (
          <div className="md3-scroll flex h-full min-w-0 flex-col gap-3 overflow-auto pb-6">
            {accountsError && <Banner tone="danger">{accountsError}</Banner>}

            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <p className="text-[12px] text-[var(--fg-3)]">
                {role === 'sudo'
                  ? `共 ${accounts.length} 个账号，其中管理类账号 ${staffCount} 个`
                  : `已创建 ${accounts.length} 个用户${myQuota.max_users != null ? ` / 上限 ${myQuota.max_users} 个` : '（不限数量）'}`}
              </p>
              <button
                onClick={openAddModal}
                disabled={quotaReached}
                className="md3-btn-filled lawver-pressable text-sm disabled:opacity-50"
              >
                <Plus size={16} strokeWidth={2.4} /> 新增{role === 'sudo' ? '账号' : '用户'}
              </button>
            </div>

            {quotaReached && (
              <Banner tone="warning">
                已达可创建用户上限（{myQuota.max_users} 个）。如确需更多账号，请联系超级管理员调整配额。
              </Banner>
            )}

            {isAccountsLoading && accounts.length === 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={index} className="flex items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
                    <span className="h-11 w-11 shrink-0 animate-pulse rounded-[var(--radius-md)] bg-[var(--bg-inset)]" />
                    <span className="min-w-0 flex-1">
                      <span className="block h-3.5 w-1/2 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                      <span className="mt-2 block h-3 w-1/3 animate-pulse rounded-full bg-[var(--bg-inset)]" />
                    </span>
                  </div>
                ))}
              </div>
            ) : accounts.length === 0 ? (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
                <EmptyState
                  icon={<Users size={22} strokeWidth={2} />}
                  title={role === 'sudo' ? '还没有账号' : '还没有创建用户'}
                  description={role === 'sudo' ? '新增账号后，成员即可登录使用 Lawver。' : '创建用户后，他们即可登录使用 Lawver。'}
                  action={(
                    <button onClick={openAddModal} className="md3-btn-tonal lawver-pressable text-sm" disabled={quotaReached}>
                      <Plus size={16} strokeWidth={2.4} /> 新增{role === 'sudo' ? '账号' : '用户'}
                    </button>
                  )}
                />
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {accounts.map(acc => (
                  <div
                    key={acc.username}
                    className="group flex min-w-0 flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] transition-colors hover:border-[var(--border-default)]"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[15px] font-semibold ${
                        acc.role === 'user'
                          ? 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]'
                          : 'bg-[var(--accent)] text-[var(--accent-on)]'
                      }`}>
                        {acc.username.charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[14px] font-medium text-[var(--fg-1)]">{acc.username}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          <StatusChip tone={ROLE_TONE[acc.role]}>{ROLE_LABEL[acc.role]}</StatusChip>
                          {(acc.online_count ?? 0) > 0 && (
                            <StatusChip tone="ok"><Wifi size={11} strokeWidth={2.4} className="mr-1" />{acc.online_count} 台在线</StatusChip>
                          )}
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-0.5">
                        {role === 'sudo' && (
                          <HoverInfo label="调整配额" placement="top">
                            <button
                              onClick={() => openLimitsModal(acc)}
                              className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)]"
                              aria-label={`调整 ${acc.username} 的配额`}
                            >
                              <SlidersHorizontal className="h-4 w-4" strokeWidth={2} />
                            </button>
                          </HoverInfo>
                        )}
                        <HoverInfo label="重置密码" placement="top">
                          <button
                            onClick={() => openResetModal(acc)}
                            className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)]"
                            aria-label={`重置 ${acc.username} 的密码`}
                          >
                            <KeyRound className="h-4 w-4" strokeWidth={2} />
                          </button>
                        </HoverInfo>
                        {acc.username === 'admin' ? (
                          <HoverInfo label="系统管理员不可删除" placement="top">
                            <button
                              className="inline-flex h-11 w-11 cursor-not-allowed items-center justify-center rounded-full text-[var(--fg-4)] opacity-40"
                              aria-label="系统管理员不可删除"
                              disabled
                            >
                              <Trash2 className="h-4 w-4" strokeWidth={2} />
                            </button>
                          </HoverInfo>
                        ) : (
                          <HoverInfo label="删除账号" placement="top">
                            <button
                              onClick={() => handleDeleteAccount(acc.username)}
                              className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
                              aria-label={`删除账号 ${acc.username}`}
                            >
                              <Trash2 className="h-4 w-4" strokeWidth={2} />
                            </button>
                          </HoverInfo>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--fg-3)]">
                      {acc.owner && <span>归属：{acc.owner}</span>}
                      {acc.role === 'admin' && (
                        <span>
                          可建用户：{acc.owned_count ?? 0}
                          {acc.max_users == null ? '（不限）' : ` / ${acc.max_users}`}
                        </span>
                      )}
                      {acc.role !== 'sudo' && (
                        <span>最大在线：{acc.role === 'admin' ? (acc.user_max_online == null ? '不限' : acc.user_max_online) : (acc.max_online == null ? '不限' : acc.max_online)} 台</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <SettingsRow
                dense
                icon={<ShieldAlert size={17} strokeWidth={2} />}
                title="账号安全提示"
                description={
                  role === 'sudo'
                    ? '删除或重置密码会立即作废该账号已签发的令牌；系统管理员账号不可删除。'
                    : '重置密码会让该用户的所有设备立即重新登录；你只能管理自己创建的用户。'
                }
              />
            </div>
          </div>
        ) : (
          <div className="md3-scroll flex h-full min-w-0 flex-col gap-3 overflow-auto pb-6">
            {sessionsError && <Banner tone="danger">{sessionsError}</Banner>}

            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <p className="text-[12px] text-[var(--fg-3)]">
                共 {sessions.length} 台已登录设备，其中 {onlineDeviceCount} 台近期活跃
              </p>
              <button onClick={loadSessions} disabled={isSessionsLoading} className="md3-btn-tonal lawver-pressable disabled:opacity-50">
                {isSessionsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" strokeWidth={2} />} 刷新
              </button>
            </div>

            {isSessionsLoading && sessions.length === 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={index} className="h-24 animate-pulse rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)]" />
                ))}
              </div>
            ) : sessions.length === 0 ? (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
                <EmptyState
                  icon={<MonitorSmartphone size={22} strokeWidth={2} />}
                  title="暂无在线设备"
                  description={role === 'sudo' ? '所有账号的登录设备会显示在这里，可直接踢下线。' : '你的用户登录后，其设备会显示在这里。'}
                />
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {sessions.map(session => (
                  <div
                    key={session.sid}
                    className="flex min-w-0 items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)]"
                  >
                    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] ${
                      session.online ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
                    }`}>
                      <MonitorSmartphone className="h-5 w-5" strokeWidth={2} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-medium text-[var(--fg-1)]">{session.username}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <StatusChip tone={session.online ? 'ok' : 'muted'}>
                          {session.online ? '在线' : '离线'}
                        </StatusChip>
                        <span className="text-[11px] text-[var(--fg-3)]">
                          {CLIENT_LABEL[session.client || ''] || session.client || '未知客户端'}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-[var(--fg-4)]">
                        最近活跃：{formatTime(session.last_seen_at)}
                      </p>
                    </div>
                    <HoverInfo label="下线该设备" placement="top">
                      <button
                        onClick={() => handleKickSession(session)}
                        className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
                        aria-label={`下线 ${session.username} 的设备`}
                      >
                        <LogOut className="h-4 w-4" strokeWidth={2} />
                      </button>
                    </HoverInfo>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>

      {isClearLogsDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-[var(--bg-overlay)]"
            onClick={() => !isClearingLogs && setIsClearLogsDialogOpen(false)}
            aria-hidden="true"
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="clear-logs-title"
            aria-describedby="clear-logs-description"
            className="relative w-full max-w-md rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6 text-[var(--fg-1)] shadow-[var(--shadow-5)]"
            style={{ animation: 'lawverPopoverIn 0.2s ease-out' }}
          >
            <div className="mb-5 flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[rgba(176,70,62,0.12)] text-[var(--color-danger-500)]">
                <Trash2 className="h-5 w-5" strokeWidth={2} />
              </div>
              <div className="min-w-0">
                <h3 id="clear-logs-title" className="t-title-l">清理全部日志？</h3>
                <p id="clear-logs-description" className="mt-2 text-sm leading-6 text-[var(--fg-3)]">
                  此操作会清空当前使用日志和已轮转的日志文件，清理后无法撤销。
                </p>
                <p className="mt-3 rounded-[var(--radius-md)] bg-[var(--bg-inset)] px-3 py-2 text-xs tabular-nums text-[var(--fg-3)]">
                  当前列表显示 {logs.length} 条记录；筛选隐藏的日志也会被一并清理。
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="md3-btn-text lawver-pressable"
                onClick={() => setIsClearLogsDialogOpen(false)}
                disabled={isClearingLogs}
                autoFocus
              >
                取消
              </button>
              <button
                type="button"
                className="md3-btn-tonal lawver-pressable !text-[var(--color-danger-500)]"
                onClick={confirmClearLogs}
                disabled={isClearingLogs}
              >
                {isClearingLogs ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" strokeWidth={2} />}
                {isClearingLogs ? '清理中…' : '确认清理'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-[var(--bg-overlay)]" onClick={closeAccountModal} aria-hidden="true" />
          <div
            className="relative max-h-[90dvh] w-full max-w-md overflow-auto rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-5)]"
            style={{ animation: 'lawverPopoverIn 0.2s ease-out' }}
          >
            <form onSubmit={handleSaveAccount}>
              <div className="flex items-start gap-3 border-b border-[var(--border-subtle)] p-5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
                  {modalMode === 'add' ? <Plus size={18} strokeWidth={2.4} /> : <KeyRound size={17} strokeWidth={2} />}
                </span>
                <div className="min-w-0">
                  <h3 className="t-title-l">
                    {modalMode === 'add' ? `新增${role === 'sudo' ? '账号' : '用户'}` : '重置密码'}
                  </h3>
                  <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
                    {modalMode === 'add'
                      ? (role === 'sudo' ? '创建账号并设置其权限与配额' : '创建一个归属于你的普通用户')
                      : `为 ${editUsername} 设置新的登录密码`}
                  </p>
                </div>
              </div>

              <div className="flex min-w-0 flex-col gap-4 p-5">
                {modalError && <Banner tone="danger">{modalError}</Banner>}

                <SettingsField label="用户名">
                  <input
                    type="text"
                    required
                    disabled={modalMode === 'reset'}
                    value={editUsername}
                    onChange={e => setEditUsername(e.target.value)}
                    className={fieldInputClass}
                    placeholder="输入用户名"
                    autoComplete="off"
                  />
                </SettingsField>

                <SettingsField label="密码" hint="至少 6 位字符">
                  <input
                    type="password"
                    required
                    minLength={6}
                    value={editPassword}
                    onChange={e => setEditPassword(e.target.value)}
                    className={fieldInputClass}
                    placeholder="最少 6 位字符"
                    autoComplete="new-password"
                  />
                </SettingsField>

                {modalMode === 'add' && role === 'sudo' && (
                  <>
                    <SettingsField label="角色">
                      <div className="grid grid-cols-3 gap-2">
                        {(['user', 'admin', 'sudo'] as Role[]).map(option => (
                          <button
                            key={option}
                            type="button"
                            onClick={() => setEditRole(option)}
                            aria-pressed={editRole === option}
                            className={`lawver-pressable h-11 rounded-[var(--radius-md)] border text-[13px] font-medium transition-colors ${
                              editRole === option
                                ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--accent)]'
                                : 'border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--fg-2)] hover:bg-[var(--bg-surface-2)]'
                            }`}
                          >
                            {ROLE_LABEL[option]}
                          </button>
                        ))}
                      </div>
                    </SettingsField>

                    {editRole !== 'sudo' && (
                      <SettingsField label="最大在线设备数" hint="留空表示不限制">
                        <input
                          type="number"
                          min={1}
                          max={1000}
                          value={newMaxOnline}
                          onChange={e => setNewMaxOnline(e.target.value)}
                          className={fieldInputClass}
                          placeholder="不限制"
                        />
                      </SettingsField>
                    )}

                    {editRole === 'admin' && (
                      <>
                        <SettingsField label="可创建用户上限 n" hint="留空表示不限制">
                          <input
                            type="number"
                            min={0}
                            max={10000}
                            value={newMaxUsers}
                            onChange={e => setNewMaxUsers(e.target.value)}
                            className={fieldInputClass}
                            placeholder="不限制"
                          />
                        </SettingsField>
                        <SettingsField label="其用户默认最大在线数 m" hint="留空表示不限制">
                          <input
                            type="number"
                            min={1}
                            max={1000}
                            value={newUserMaxOnline}
                            onChange={e => setNewUserMaxOnline(e.target.value)}
                            className={fieldInputClass}
                            placeholder="不限制"
                          />
                        </SettingsField>
                      </>
                    )}
                  </>
                )}

                {modalMode === 'add' && role === 'admin' && (
                  <Banner tone="info">
                    该用户的最大在线设备数由超级管理员通过你的配额 m 决定，创建后不可自行修改。
                  </Banner>
                )}
              </div>

              <div className="flex justify-end gap-2 border-t border-[var(--border-subtle)] px-5 py-4">
                <button type="button" onClick={closeAccountModal} className="md3-btn-text lawver-pressable">取消</button>
                <button type="submit" disabled={isSaving} className="md3-btn-filled lawver-pressable disabled:opacity-50">
                  {isSaving ? <Loader2 size={15} className="animate-spin" /> : null}
                  {isSaving ? '保存中…' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {limitsTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-[var(--bg-overlay)]" onClick={() => setLimitsTarget(null)} aria-hidden="true" />
          <div
            className="relative w-full max-w-md overflow-hidden rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-5)]"
            style={{ animation: 'lawverPopoverIn 0.2s ease-out' }}
          >
            <form onSubmit={handleSaveLimits}>
              <div className="flex items-start gap-3 border-b border-[var(--border-subtle)] p-5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
                  <SlidersHorizontal size={17} strokeWidth={2} />
                </span>
                <div className="min-w-0">
                  <h3 className="t-title-l">调整配额</h3>
                  <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
                    {limitsTarget.username}（{ROLE_LABEL[limitsTarget.role]}）
                  </p>
                </div>
              </div>

              <div className="flex min-w-0 flex-col gap-4 p-5">
                {limitsError && <Banner tone="danger">{limitsError}</Banner>}

                {limitsTarget.role === 'admin' ? (
                  <>
                    <SettingsField label="可创建用户上限 n" hint="留空表示不限制">
                      <input
                        type="number"
                        min={0}
                        max={10000}
                        value={limitMaxUsers}
                        onChange={e => setLimitMaxUsers(e.target.value)}
                        className={fieldInputClass}
                        placeholder="不限制"
                      />
                    </SettingsField>
                    <SettingsField label="其用户默认最大在线数 m" hint="留空表示不限制">
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        value={limitUserMaxOnline}
                        onChange={e => setLimitUserMaxOnline(e.target.value)}
                        className={fieldInputClass}
                        placeholder="不限制"
                      />
                    </SettingsField>
                  </>
                ) : (
                  <SettingsField label="最大在线设备数" hint="留空表示不限制">
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      value={limitMaxOnline}
                      onChange={e => setLimitMaxOnline(e.target.value)}
                      className={fieldInputClass}
                      placeholder="不限制"
                    />
                  </SettingsField>
                )}

                <Banner tone="info">
                  n 决定该管理员能创建多少用户；m 决定其用户默认的在线设备上限，管理员本人无法修改。
                </Banner>
              </div>

              <div className="flex justify-end gap-2 border-t border-[var(--border-subtle)] px-5 py-4">
                <button type="button" onClick={() => setLimitsTarget(null)} className="md3-btn-text lawver-pressable">取消</button>
                <button type="submit" disabled={isSavingLimits} className="md3-btn-filled lawver-pressable disabled:opacity-50">
                  {isSavingLimits ? <Loader2 size={15} className="animate-spin" /> : null}
                  {isSavingLimits ? '保存中…' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
