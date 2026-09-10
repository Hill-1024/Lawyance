/*
 * 模块描述：管理员后台，展示访问日志与账号管理，视觉体系与主界面保持一致。
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
  Trash2,
  User,
  Users,
} from 'lucide-react';
import {
  clearLogs,
  deleteAccount,
  fetchAccounts,
  fetchLogs,
  logout as apiLogout,
  setAccount,
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

/* ── 组件 ── */

export const AdminDashboard: React.FC = () => {
  // 后台返回聊天必须退栈，否则再按返回又会前进回后台。
  const goBack = useAppBack();
  const { showConfirm } = useAppDialog();
  const [activeTab, setActiveTab] = useState<'logs' | 'accounts'>('logs');

  const [logs, setLogs] = useState<string[]>([]);
  const [ipFilter, setIpFilter] = useState('');
  const [ignoreHeartbeat, setIgnoreHeartbeat] = useState(true);
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [isClearingLogs, setIsClearingLogs] = useState(false);
  const [isClearLogsDialogOpen, setIsClearLogsDialogOpen] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  const [accounts, setAccounts] = useState<{ username: string; role: string }[]>([]);
  const [isAccountsLoading, setIsAccountsLoading] = useState(false);
  const [accountsError, setAccountsError] = useState('');

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'add' | 'reset'>('add');
  const [editUsername, setEditUsername] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [editRole, setEditRole] = useState('user');
  const [modalError, setModalError] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const logsRequestIdRef = useRef(0);
  const accountsRequestIdRef = useRef(0);
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

  useEffect(() => {
    if (activeTab === 'logs') {
      void loadLogs();
      return () => { logsRequestIdRef.current += 1; };
    }
    void loadAccounts();
    return () => { accountsRequestIdRef.current += 1; };
  }, [activeTab, loadAccounts, loadLogs]);

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

  const handleSaveAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    const generation = modalGenerationRef.current;
    setModalError('');
    setIsSaving(true);
    try {
      await setAccount(editUsername, editPassword, editRole);
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
      message: `确定要删除账号「${username}」吗？此操作不可撤销。`,
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
    setModalError('');
    setIsSaving(false);
    setIsModalOpen(true);
  };

  const openResetModal = (u: string, r: string) => {
    modalGenerationRef.current += 1;
    setModalMode('reset');
    setEditUsername(u);
    setEditPassword('');
    setEditRole(r);
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

  const adminCount = accounts.filter(a => a.role === 'admin').length;

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
            <h1 className="t-title-l truncate">管理后台</h1>
            <p className="truncate text-[12px] text-[var(--fg-3)]">访问审计与账号管理</p>
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
        <div className="inline-flex rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-1)]">
          <button
            onClick={() => setActiveTab('logs')}
            className={`md3-seg-btn ${activeTab === 'logs' ? 'active' : ''}`}
            aria-pressed={activeTab === 'logs'}
          >
            <Activity size={16} strokeWidth={2} /> 使用日志
          </button>
          <button
            onClick={() => setActiveTab('accounts')}
            className={`md3-seg-btn ${activeTab === 'accounts' ? 'active' : ''}`}
            aria-pressed={activeTab === 'accounts'}
          >
            <Users size={16} strokeWidth={2} /> 用户管理
          </button>
        </div>
      </div>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden px-3 pb-5 pt-4 sm:px-5">
        {activeTab === 'logs' ? (
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
        ) : (
          <div className="md3-scroll flex h-full min-w-0 flex-col gap-3 overflow-auto pb-6">
            {accountsError && <Banner tone="danger">{accountsError}</Banner>}

            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <p className="text-[12px] text-[var(--fg-3)]">
                共 {accounts.length} 个账号，其中管理员 {adminCount} 个
              </p>
              <button onClick={openAddModal} className="md3-btn-filled lawver-pressable text-sm">
                <Plus size={16} strokeWidth={2.4} /> 新增账号
              </button>
            </div>

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
                  title="还没有账号"
                  description="新增账号后，成员即可登录使用 Lawver。"
                  action={(
                    <button onClick={openAddModal} className="md3-btn-tonal lawver-pressable text-sm">
                      <Plus size={16} strokeWidth={2.4} /> 新增账号
                    </button>
                  )}
                />
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {accounts.map(acc => (
                  <div
                    key={acc.username}
                    className="group flex min-w-0 items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] transition-colors hover:border-[var(--border-default)]"
                  >
                    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[15px] font-semibold ${
                      acc.role === 'admin'
                        ? 'bg-[var(--accent)] text-[var(--accent-on)]'
                        : 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]'
                    }`}>
                      {acc.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-medium text-[var(--fg-1)]">{acc.username}</p>
                      <StatusChip tone={acc.role === 'admin' ? 'accent' : 'muted'} className="mt-1">
                        {acc.role === 'admin' ? '管理员' : '普通用户'}
                      </StatusChip>
                    </div>
                    <div className="flex shrink-0 gap-0.5">
                      <HoverInfo label="重置密码" placement="top">
                        <button
                          onClick={() => openResetModal(acc.username, acc.role)}
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
                ))}
              </div>
            )}

            <div className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <SettingsRow
                dense
                icon={<ShieldAlert size={17} strokeWidth={2} />}
                title="账号安全提示"
                description="删除或重置密码会立即作废该账号已签发的令牌；系统管理员账号不可删除。"
              />
            </div>
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
            className="relative w-full max-w-md overflow-hidden rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-5)]"
            style={{ animation: 'lawverPopoverIn 0.2s ease-out' }}
          >
            <form onSubmit={handleSaveAccount}>
              <div className="flex items-start gap-3 border-b border-[var(--border-subtle)] p-5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
                  {modalMode === 'add' ? <Plus size={18} strokeWidth={2.4} /> : <KeyRound size={17} strokeWidth={2} />}
                </span>
                <div className="min-w-0">
                  <h3 className="t-title-l">{modalMode === 'add' ? '新增账号' : '重置密码'}</h3>
                  <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
                    {modalMode === 'add' ? '创建一个新的系统账号' : `为 ${editUsername} 设置新的登录密码`}
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

                {modalMode === 'add' && (
                  <SettingsField label="角色">
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { value: 'user', label: '普通用户' },
                        { value: 'admin', label: '管理员' },
                      ].map(option => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setEditRole(option.value)}
                          aria-pressed={editRole === option.value}
                          className={`lawver-pressable h-11 rounded-[var(--radius-md)] border text-[13px] font-medium transition-colors ${
                            editRole === option.value
                              ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--accent)]'
                              : 'border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--fg-2)] hover:bg-[var(--bg-surface-2)]'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </SettingsField>
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
    </div>
  );
};
