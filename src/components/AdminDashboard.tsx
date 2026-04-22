import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchLogs, fetchAccounts, setAccount, logout as apiLogout, deleteAccount } from '../services/api';
import { useTheme } from '../hooks/useTheme';
import { Search, ShieldAlert, Users, Activity, EyeOff, RefreshCw, ArrowLeft, LogOut, Plus, KeyRound, Globe, Clock, User, Trash2 } from 'lucide-react';

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
    const infoParts = parts[2].split(' | ');
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
  if (code >= 200 && code < 300) return 'text-emerald-600 dark:text-emerald-400';
  if (code >= 300 && code < 400) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-500 dark:text-red-400';
}

function methodBadge(m: string) {
  const colors: Record<string, string> = {
    GET: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
    POST: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
    DELETE: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
    PUT: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  };
  return colors[m] || 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300';
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
    <div className="flex flex-col h-screen bg-gradient-to-br from-slate-50 via-purple-50/30 to-slate-100 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 transition-colors duration-500">

      {/* ── Top Bar (Liquid Glass) ── */}
      <header className="liquid-glass flex items-center justify-between px-5 py-3 z-20 shrink-0" style={{ borderRadius: 0, borderTop: 'none', borderLeft: 'none', borderRight: 'none' }}>
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/')} className="md3-btn-text !p-2 !rounded-full" title="返回聊天">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-md">
            <ShieldAlert className="w-4.5 h-4.5 text-white" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-gray-900 dark:text-gray-50 leading-tight">管理后台</h1>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-tight">Admin Console</p>
          </div>
        </div>
        <button onClick={handleLogout} className="md3-btn-text !text-red-500 dark:!text-red-400 !gap-1.5 text-sm">
          <LogOut className="w-4 h-4" /> 退出
        </button>
      </header>

      {/* ── Navigation (MD3 Segmented Buttons) ── */}
      <div className="px-5 pt-4 pb-2 shrink-0">
        <div className="inline-flex p-1 rounded-full border border-black/6 dark:border-white/8 bg-white/50 dark:bg-white/5">
          <button onClick={() => setActiveTab('logs')} className={`md3-seg-btn ${activeTab === 'logs' ? 'active' : ''}`}>
            <Activity className="w-4 h-4" /> 使用日志
          </button>
          <button onClick={() => setActiveTab('accounts')} className={`md3-seg-btn ${activeTab === 'accounts' ? 'active' : ''}`}>
            <Users className="w-4 h-4" /> 用户管理
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
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                <input
                  type="text" placeholder="按 IP 地址过滤…" value={ipFilter}
                  onChange={e => setIpFilter(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && loadLogs()}
                  className="md3-input !pl-10 !rounded-full !py-2.5"
                />
              </div>
              <label className="flex items-center gap-2 select-none cursor-pointer text-sm text-gray-600 dark:text-gray-400">
                <div className="relative">
                  <input type="checkbox" checked={ignoreHeartbeat} onChange={e => setIgnoreHeartbeat(e.target.checked)}
                    className="peer sr-only" />
                  <div className="w-9 h-5 rounded-full bg-gray-200 dark:bg-gray-700 peer-checked:bg-violet-500 dark:peer-checked:bg-violet-400 transition-colors" />
                  <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform peer-checked:translate-x-4" />
                </div>
                隐藏心跳
              </label>
              <button onClick={loadLogs} disabled={isLogsLoading} className="md3-btn-tonal">
                <RefreshCw className={`w-4 h-4 ${isLogsLoading ? 'animate-spin' : ''}`} /> 刷新
              </button>
            </div>

            {logsError && (
              <div className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-red-50 dark:bg-red-900/15 text-red-600 dark:text-red-400 text-sm border border-red-200/60 dark:border-red-800/20">
                <ShieldAlert className="w-4 h-4 shrink-0" /> {logsError}
              </div>
            )}

            {/* Log Table Card */}
            <div className="md3-surface-card flex-1 overflow-hidden flex flex-col">
              {parsedLogs.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center text-gray-400 dark:text-gray-500 gap-3">
                  <EyeOff className="w-14 h-14 opacity-30" />
                  <p className="text-sm">暂无日志记录</p>
                </div>
              ) : (
                <div className="flex-1 overflow-auto md3-scroll">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10">
                      <tr className="bg-gray-50/80 dark:bg-gray-800/80 backdrop-blur-sm text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        <th className="text-left px-4 py-3 font-medium">时间</th>
                        <th className="text-left px-4 py-3 font-medium">IP</th>
                        <th className="text-left px-4 py-3 font-medium">用户</th>
                        <th className="text-left px-4 py-3 font-medium">方法</th>
                        <th className="text-left px-4 py-3 font-medium">路径</th>
                        <th className="text-right px-4 py-3 font-medium">状态</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800/60">
                      {parsedLogs.map((log, i) => (
                        log.ip ? (
                          <tr key={i} className="log-row hover:bg-violet-50/40 dark:hover:bg-violet-900/10 transition-colors" style={{ animationDelay: `${Math.min(i * 15, 300)}ms` }}>
                            <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                              <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 opacity-50" />{log.time.split(',')[0]}</span>
                            </td>
                            <td className="px-4 py-2.5 font-mono text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">
                              <span className="flex items-center gap-1.5"><Globe className="w-3.5 h-3.5 opacity-40" />{log.ip}</span>
                            </td>
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <span className="flex items-center gap-1.5"><User className="w-3.5 h-3.5 opacity-40" /><span className="text-gray-800 dark:text-gray-200">{log.user}</span></span>
                            </td>
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <span className={`md3-chip text-[11px] ${methodBadge(log.method)}`}>{log.method}</span>
                            </td>
                            <td className="px-4 py-2.5 font-mono text-xs text-gray-600 dark:text-gray-400 max-w-[300px] truncate">{log.path}</td>
                            <td className={`px-4 py-2.5 text-right font-semibold tabular-nums ${statusColor(log.status)}`}>{log.status}</td>
                          </tr>
                        ) : (
                          <tr key={i} className="log-row"><td colSpan={6} className="px-4 py-2 text-xs text-gray-500 dark:text-gray-500 break-all">{log.raw}</td></tr>
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
              <div className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-red-50 dark:bg-red-900/15 text-red-600 dark:text-red-400 text-sm border border-red-200/60 dark:border-red-800/20">
                <ShieldAlert className="w-4 h-4 shrink-0" /> {accountsError}
              </div>
            )}

            {isAccountsLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="w-10 h-10 border-3 border-violet-200 dark:border-violet-800 border-t-violet-500 dark:border-t-violet-400 rounded-full animate-spin" />
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 overflow-auto md3-scroll flex-1 content-start pb-20">
                {accounts.map((acc, i) => (
                  <div key={i} className="md3-surface-card p-4 flex items-center gap-4 hover:shadow-md transition-shadow group cursor-default">
                    <div className={`w-11 h-11 rounded-full flex items-center justify-center text-white font-semibold text-sm shrink-0 shadow-sm ${acc.role === 'admin'
                        ? 'bg-gradient-to-br from-violet-500 to-purple-600'
                        : 'bg-gradient-to-br from-teal-400 to-cyan-500'
                      }`}>
                      {acc.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">{acc.username}</p>
                      <span className={`md3-chip mt-1 ${acc.role === 'admin' ? 'md3-chip-primary' : 'md3-chip-tertiary'}`}>
                        {acc.role === 'admin' ? '管理员' : '普通用户'}
                      </span>
                    </div>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button onClick={() => openResetModal(acc.username, acc.role)}
                        className="md3-btn-text !p-2 !rounded-full" title="重置密码">
                        <KeyRound className="w-4 h-4" />
                      </button>
                      {acc.username === 'admin' ? (
                        <button className="md3-btn-text !p-2 !rounded-full opacity-30 cursor-not-allowed" title="系统管理员不可删除">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      ) : (
                        <button onClick={() => handleDeleteAccount(acc.username)}
                          className="md3-btn-text !p-2 !rounded-full !text-red-500 dark:!text-red-400" title="删除账号">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* FAB */}
            <button onClick={openAddModal} className="md3-fab" title="新增账号">
              <Plus className="w-6 h-6" />
            </button>
          </div>
        )}
      </main>

      {/* ── Modal (MD3 Dialog) ── */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/30 dark:bg-black/50" onClick={() => setIsModalOpen(false)} />
          <div className="relative w-full max-w-md md3-surface-card !rounded-[28px] shadow-2xl overflow-hidden" style={{ animation: 'logSlideIn 0.2s ease-out' }}>
            <form onSubmit={handleSaveAccount}>
              <div className="px-6 pt-6 pb-2">
                <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-50 mb-1">
                  {modalMode === 'add' ? '新增账号' : '重置密码'}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
                  {modalMode === 'add' ? '创建一个新的系统账号' : `为 ${editUsername} 设置新的登录密码`}
                </p>

                {modalError && (
                  <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-900/15 text-red-600 dark:text-red-400 text-sm border border-red-200/50 dark:border-red-800/20">{modalError}</div>
                )}

                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">用户名</label>
                    <input type="text" required disabled={modalMode === 'reset'} value={editUsername}
                      onChange={e => setEditUsername(e.target.value)} className="md3-input" placeholder="输入用户名" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">密码</label>
                    <input type="password" required minLength={6} value={editPassword}
                      onChange={e => setEditPassword(e.target.value)} className="md3-input" placeholder="最少 6 位字符" />
                  </div>
                  {modalMode === 'add' && (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">角色</label>
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
