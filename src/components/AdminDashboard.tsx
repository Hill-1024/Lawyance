import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchLogs, fetchAccounts, setAccount, logout as apiLogout, deleteAccount } from '../services/api';
import { Search, ShieldAlert, Users, Activity, EyeOff, RefreshCw, ArrowLeft, LogOut, Plus, KeyRound, Globe, Clock, User, Trash2 } from 'lucide-react';
import { BrandMark } from './Brand';

/* ── helpers ── */
interface ParsedLog {
  time: string;
  ip: string;
  user: string;
  method: string;
  path: string;
  status: string;
  raw: string;
}

function parseLogLine(raw: string): ParsedLog {
  // Format: "2026-04-22 19:46:30,123 | INFO | 127.0.0.1 | admin | POST | /api/chat | 200"
  const parts = raw.split(' | ');
  if (parts.length >= 3) {
    // Try to parse the structured part after INFO
    const afterLevel = raw.split(' | INFO | ')[1] || raw.split(' | ')[2] || '';
    const fields = afterLevel.split(' | ');
    return {
      time: (parts[0] || '').trim(),
      ip: (fields[0] || '').trim(),
      user: (fields[1] || '').trim(),
      method: (fields[2] || '').trim(),
      path: (fields[3] || '').trim(),
      status: (fields[4] || '').trim(),
      raw,
    };
  }
  return { time: '', ip: '', user: '', method: '', path: '', status: '', raw };
}

function statusColor(s: string) {
  const code = parseInt(s);
  if (code >= 200 && code < 300) return 'text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]';
  if (code >= 300 && code < 400) return 'text-[var(--color-warning-500)]';
  return 'text-[var(--color-danger-500)]';
}

function methodBadge(m: string) {
  const colors: Record<string, string> = {
    GET: 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]',
    POST: 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]',
    DELETE: 'bg-[var(--color-danger-100)] text-[var(--color-danger-500)]',
    PUT: 'bg-[var(--color-warning-100)] text-[var(--color-warning-500)]',
  };
  return colors[m] || 'bg-[var(--bg-inset)] text-[var(--fg-2)]';
}

/* ── component ── */
export const AdminDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'logs' | 'accounts'>('logs');

  const [logs, setLogs] = useState<string[]>([]);
  const [ipFilter, setIpFilter] = useState('');
  const [ignoreHeartbeat, setIgnoreHeartbeat] = useState(true);
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState('');

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

  useEffect(() => {
    if (activeTab === 'logs') loadLogs();
    else loadAccounts();
  }, [activeTab]);

  const loadLogs = async () => {
    setIsLogsLoading(true); setLogsError('');
    try { const d = await fetchLogs(ipFilter, ignoreHeartbeat); setLogs(d.logs || []); }
    catch (e: any) { setLogsError(e.message); }
    finally { setIsLogsLoading(false); }
  };

  const loadAccounts = async () => {
    setIsAccountsLoading(true); setAccountsError('');
    try { const d = await fetchAccounts(); setAccounts(d.accounts || []); }
    catch (e: any) { setAccountsError(e.message); }
    finally { setIsAccountsLoading(false); }
  };

  const handleSaveAccount = async (e: React.FormEvent) => {
    e.preventDefault(); setModalError(''); setIsSaving(true);
    try { await setAccount(editUsername, editPassword, editRole); setIsModalOpen(false); loadAccounts(); }
    catch (e: any) { setModalError(e.message); }
    finally { setIsSaving(false); }
  };

  const handleDeleteAccount = async (username: string) => {
    if (username === 'admin') return;
    if (!window.confirm(`确定要删除账号 "${username}" 吗？此操作不可撤销。`)) return;

    try {
      await deleteAccount(username);
      loadAccounts();
    } catch (e: any) {
      setAccountsError(e.message);
    }
  };

  const openAddModal = () => { setModalMode('add'); setEditUsername(''); setEditPassword(''); setEditRole('user'); setModalError(''); setIsModalOpen(true); };
  const openResetModal = (u: string, r: string) => { setModalMode('reset'); setEditUsername(u); setEditPassword(''); setEditRole(r); setModalError(''); setIsModalOpen(true); };
  const handleLogout = async () => { try { await apiLogout(); } finally { window.location.href = '/'; } };

  const parsedLogs = useMemo(() => logs.map(parseLogLine), [logs]);

  return (
    <div className="flex h-screen flex-col bg-[var(--bg-app)] text-[var(--fg-1)] transition-colors duration-500">

      {/* ── Top Bar (Liquid Glass) ── */}
      <header className="liquid-glass z-20 flex shrink-0 items-center justify-between px-5 py-3" style={{ borderRadius: 0, borderTop: 'none', borderLeft: 'none', borderRight: 'none' }}>
        <div className="relative z-[1] flex items-center gap-2">
          <button onClick={() => navigate('/')} className="md3-btn-text !p-2 !rounded-full" title="返回聊天">
            <ArrowLeft className="h-5 w-5" strokeWidth={2} />
          </button>
          <div className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)]">
            <BrandMark className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold leading-tight text-[var(--fg-1)]">管理后台</h1>
            <p className="text-xs leading-tight text-[var(--fg-3)]">Lawyance Admin Console</p>
          </div>
        </div>
        <button onClick={handleLogout} className="md3-btn-text relative z-[1] !gap-1.5 !text-[var(--color-danger-500)] text-sm">
          <LogOut className="h-4 w-4" strokeWidth={2} /> 退出
        </button>
      </header>

      {/* ── Navigation (MD3 Segmented Buttons) ── */}
      <div className="px-5 pt-4 pb-2 shrink-0">
        <div className="inline-flex rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-1)]">
          <button onClick={() => setActiveTab('logs')} className={`md3-seg-btn ${activeTab === 'logs' ? 'active' : ''}`}>
            <Activity className="h-4 w-4" strokeWidth={2} /> 使用日志
          </button>
          <button onClick={() => setActiveTab('accounts')} className={`md3-seg-btn ${activeTab === 'accounts' ? 'active' : ''}`}>
            <Users className="h-4 w-4" strokeWidth={2} /> 用户管理
          </button>
        </div>
      </div>

      {/* ── Content ── */}
      <main className="flex-1 overflow-hidden flex flex-col px-5 pb-5 pt-2">

        {/* == Logs Tab == */}
        {activeTab === 'logs' && (
          <div className="flex flex-col h-full gap-3">
            {/* Toolbar */}
            <div className="flex flex-wrap gap-3 items-center">
              <div className="relative flex-1 min-w-[200px] max-w-sm">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--fg-4)]" strokeWidth={2} />
                <input
                  type="text" placeholder="按 IP 地址过滤…" value={ipFilter}
                  onChange={e => setIpFilter(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && loadLogs()}
                  className="md3-input !pl-10 !rounded-full !py-2.5"
                />
              </div>
              <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-[var(--fg-2)]">
                <div className="relative">
                  <input type="checkbox" checked={ignoreHeartbeat} onChange={e => setIgnoreHeartbeat(e.target.checked)}
                    className="peer sr-only" />
                  <div className="h-5 w-9 rounded-full bg-[rgba(20,23,31,0.12)] transition-colors peer-checked:bg-[var(--accent)] dark:bg-white/[0.1]" />
                  <div className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform peer-checked:translate-x-4" />
                </div>
                隐藏心跳
              </label>
              <button onClick={loadLogs} disabled={isLogsLoading} className="md3-btn-tonal">
                <RefreshCw className={`h-4 w-4 ${isLogsLoading ? 'animate-spin' : ''}`} strokeWidth={2} /> 刷新
              </button>
            </div>

            {logsError && (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] px-4 py-3 text-sm text-[var(--color-danger-500)]">
                <ShieldAlert className="h-4 w-4 shrink-0" strokeWidth={2} /> {logsError}
              </div>
            )}

            {/* Log Table Card */}
            <div className="md3-surface-card flex-1 overflow-hidden flex flex-col">
              {parsedLogs.length === 0 ? (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[var(--fg-4)]">
                  <EyeOff className="h-14 w-14 opacity-40" strokeWidth={2} />
                  <p className="text-sm">暂无日志记录</p>
                </div>
              ) : (
                <div className="flex-1 overflow-auto md3-scroll">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10">
                      <tr className="bg-[var(--bg-surface-2)] text-[11px] uppercase tracking-[0.08em] text-[var(--fg-3)]">
                        <th className="text-left px-4 py-3 font-medium">时间</th>
                        <th className="text-left px-4 py-3 font-medium">IP</th>
                        <th className="text-left px-4 py-3 font-medium">用户</th>
                        <th className="text-left px-4 py-3 font-medium">方法</th>
                        <th className="text-left px-4 py-3 font-medium">路径</th>
                        <th className="text-right px-4 py-3 font-medium">状态</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {parsedLogs.map((log, i) => (
                        log.ip ? (
                          <tr key={i} className="log-row transition-colors hover:bg-[rgba(59,98,184,0.05)]" style={{ animationDelay: `${Math.min(i * 15, 300)}ms` }}>
                            <td className="whitespace-nowrap px-4 py-2.5 text-[var(--fg-3)]">
                              <span className="flex items-center gap-1.5"><Clock className="h-3.5 w-3.5 opacity-50" strokeWidth={2} />{log.time.split(',')[0]}</span>
                            </td>
                            <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-[var(--fg-2)]">
                              <span className="flex items-center gap-1.5"><Globe className="h-3.5 w-3.5 opacity-40" strokeWidth={2} />{log.ip}</span>
                            </td>
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <span className="flex items-center gap-1.5"><User className="h-3.5 w-3.5 opacity-40" strokeWidth={2} /><span className="text-[var(--fg-1)]">{log.user}</span></span>
                            </td>
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <span className={`md3-chip text-[11px] ${methodBadge(log.method)}`}>{log.method}</span>
                            </td>
                            <td className="max-w-[300px] truncate px-4 py-2.5 font-mono text-xs text-[var(--fg-2)]">{log.path}</td>
                            <td className={`px-4 py-2.5 text-right font-semibold tabular-nums ${statusColor(log.status)}`}>{log.status}</td>
                          </tr>
                        ) : (
                          <tr key={i} className="log-row"><td colSpan={6} className="break-all px-4 py-2 text-xs text-[var(--fg-3)]">{log.raw}</td></tr>
                        )
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* == Accounts Tab == */}
        {activeTab === 'accounts' && (
          <div className="flex flex-col h-full gap-4">
            {accountsError && (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] px-4 py-3 text-sm text-[var(--color-danger-500)]">
                <ShieldAlert className="h-4 w-4 shrink-0" strokeWidth={2} /> {accountsError}
              </div>
            )}

            {isAccountsLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="h-10 w-10 animate-spin rounded-full border-[3px] border-[var(--accent-quiet)] border-t-[var(--accent)]" />
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 overflow-auto md3-scroll flex-1 content-start pb-20">
                {accounts.map((acc, i) => (
                  <div key={i} className="md3-surface-card p-4 flex items-center gap-4 hover:shadow-md transition-shadow group cursor-default">
                    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold shadow-[var(--shadow-1)] ${acc.role === 'admin'
                        ? 'bg-[var(--accent)] text-[var(--accent-on)]'
                        : 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
                      }`}>
                      {acc.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm font-medium text-[var(--fg-1)]">{acc.username}</p>
                      <span className={`md3-chip mt-1 ${acc.role === 'admin' ? 'md3-chip-primary' : 'md3-chip-tertiary'}`}>
                        {acc.role === 'admin' ? '管理员' : '普通用户'}
                      </span>
                    </div>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button onClick={() => openResetModal(acc.username, acc.role)}
                        className="md3-btn-text !p-2 !rounded-full" title="重置密码">
                          <KeyRound className="h-4 w-4" strokeWidth={2} />
                      </button>
                      {acc.username === 'admin' ? (
                        <button className="md3-btn-text !p-2 !rounded-full opacity-30 cursor-not-allowed" title="系统管理员不可删除">
                          <Trash2 className="h-4 w-4" strokeWidth={2} />
                        </button>
                      ) : (
                        <button onClick={() => handleDeleteAccount(acc.username)}
                          className="md3-btn-text !p-2 !rounded-full !text-[var(--color-danger-500)]" title="删除账号">
                          <Trash2 className="h-4 w-4" strokeWidth={2} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* FAB */}
            <button onClick={openAddModal} className="md3-fab" title="新增账号">
              <Plus className="h-6 w-6" strokeWidth={2} />
            </button>
          </div>
        )}
      </main>

      {/* ── Modal (MD3 Dialog) ── */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-[var(--bg-overlay)]" onClick={() => setIsModalOpen(false)} />
          <div className="relative w-full max-w-md md3-surface-card !rounded-[28px] shadow-2xl overflow-hidden" style={{ animation: 'logSlideIn 0.2s ease-out' }}>
            <form onSubmit={handleSaveAccount}>
              <div className="px-6 pt-6 pb-2">
                <h3 className="mb-1 text-xl font-semibold text-[var(--fg-1)]">
                  {modalMode === 'add' ? '新增账号' : '重置密码'}
                </h3>
                <p className="mb-5 text-sm text-[var(--fg-3)]">
                  {modalMode === 'add' ? '创建一个新的系统账号' : `为 ${editUsername} 设置新的登录密码`}
                </p>

                {modalError && (
                  <div className="mb-4 rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] p-3 text-sm text-[var(--color-danger-500)]">{modalError}</div>
                )}

                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-[var(--fg-3)]">用户名</label>
                    <input type="text" required disabled={modalMode === 'reset'} value={editUsername}
                      onChange={e => setEditUsername(e.target.value)} className="md3-input" placeholder="输入用户名" />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-[var(--fg-3)]">密码</label>
                    <input type="password" required minLength={6} value={editPassword}
                      onChange={e => setEditPassword(e.target.value)} className="md3-input" placeholder="最少 6 位字符" />
                  </div>
                  {modalMode === 'add' && (
                    <div>
                      <label className="mb-1.5 block text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-[var(--fg-3)]">角色</label>
                      <select value={editRole} onChange={e => setEditRole(e.target.value)} className="md3-input">
                        <option value="user">普通用户</option>
                        <option value="admin">管理员</option>
                      </select>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-2 px-6 py-4">
                <button type="button" onClick={() => setIsModalOpen(false)} className="md3-btn-text">取消</button>
                <button type="submit" disabled={isSaving} className="md3-btn-filled">
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
