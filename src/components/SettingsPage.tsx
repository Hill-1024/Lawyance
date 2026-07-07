/*
 * 模块描述：应用设置页，集中管理外观模式、自定义种子色和 Material You 占位状态。
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, BookOpen, Check, ChevronDown, ChevronRight, CirclePlay, Clock3, Cloud, CloudDownload, CloudUpload, ExternalLink, Folder, Gavel, Globe, KeyRound, Link2, Loader2, MessageSquareText, Monitor, Moon, PackageCheck, Palette, PanelLeftOpen, Paperclip, PlugZap, RotateCcw, Send, Server, Settings, Settings2, Smartphone, Sparkles, Sun, Trash2 } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { DEFAULT_SEED } from '../lib/palette';
import { useThemeContext, type ColorSource, type ThemeMode } from '../contexts/ThemeContext';
import { BUILD_INFO } from '../lib/buildInfo';
import { HoverInfo } from './HoverInfo';
import { BrandMark } from './Brand';
import { useAppDialog } from '../contexts/DialogContext';
import { getWebDavConfig, setWebDavConfig, emptyWebDavConfig, type WebDavConfig } from '../lib/webdav-storage';
import { webdavService, type WebDavFileInfo } from '../services/webdavService';
import { buildBackupSnapshot, restoreBackupSnapshot } from '../services/storageService';
import { AnimatedSwitch } from './AnimatedSwitch';
import { getResumeEnabled, notifyResumeEnabledChanged, setResumeEnabled } from '../lib/resume-prefs';
import { requestGuidedTour } from '../lib/guided-tour';
import { verifyAuth, getProviderStatus, getSettings, updateSettings, testProvider, type ProviderStatus } from '../services/api';

const MODE_OPTIONS: Array<{ value: ThemeMode; label: string; icon: React.ComponentType<{ size?: number; strokeWidth?: number }> }> = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'system', label: '系统', icon: Monitor },
  { value: 'dark', label: '深色', icon: Moon },
];

const COLOR_PRESETS = [
  '#3b62b8',
  '#0f766e',
  '#b83280',
  '#d97706',
  '#7c3aed',
  '#2563eb',
  '#dc2626',
  '#16a34a',
];

const COLOR_SOURCE_LABEL: Record<ColorSource, string> = {
  default: '默认品牌色',
  custom: '自定义种子色',
  monet: 'Material You',
};

const isHexColor = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

// ─── WebDAV 同步区块 ────────────────────────────────────────────────────────

type WebDavSyncState = 'idle' | 'testing' | 'uploading' | 'listing' | 'restoring' | 'deleting';

const WebDavSection: React.FC = () => {
  const { showAlert, showConfirm } = useAppDialog();
  const [cfg, setCfg] = useState<WebDavConfig>(emptyWebDavConfig);
  const [syncState, setSyncState] = useState<WebDavSyncState>('idle');
  const [activeFilename, setActiveFilename] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [backups, setBackups] = useState<WebDavFileInfo[] | null>(null);
  const [showBackupList, setShowBackupList] = useState(false);
  const busy = syncState !== 'idle';
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getWebDavConfig().then(saved => { if (saved) setCfg(saved); });
  }, []);

  const saveConfig = async (next: WebDavConfig) => {
    setCfg(next);
    await setWebDavConfig(next);
  };

  const handleTest = async () => {
    if (!cfg.url || !cfg.username) {
      await showAlert({ title: '请填写 URL 和用户名', message: '连接测试需要至少填写服务器 URL 和用户名。', tone: 'warning' });
      return;
    }
    setSyncState('testing');
    try {
      const result = await webdavService.testConnection(cfg);
      await showAlert({
        title: '连接成功',
        message: result.created_directory
          ? `已自动创建目录 ${cfg.directory}，可以开始备份。`
          : `目录 ${cfg.directory} 已存在，连接正常。`,
        tone: 'success',
      });
    } catch (e) {
      await showAlert({ title: '连接失败', message: (e as Error).message, tone: 'danger' });
    } finally {
      setSyncState('idle');
    }
  };

  const handleUpload = async () => {
    if (!cfg.url || !cfg.username) {
      await showAlert({ title: '请先配置 WebDAV', message: '填写服务器 URL 和账号后再备份。', tone: 'warning' });
      return;
    }
    setSyncState('uploading');
    try {
      const snapshot = await buildBackupSnapshot();
      const filename = webdavService.generateFilename();
      await webdavService.uploadBackup(cfg, filename, snapshot);
      await showAlert({ title: '备份成功', message: `已上传 ${filename} 到 ${cfg.directory}。`, tone: 'success' });
      setBackups(null); // 清空缓存，下次列表重新拉取
    } catch (e) {
      await showAlert({ title: '备份失败', message: (e as Error).message, tone: 'danger' });
    } finally {
      setSyncState('idle');
    }
  };

  const handleListBackups = async () => {
    if (!cfg.url || !cfg.username) {
      await showAlert({ title: '请先配置 WebDAV', message: '填写服务器 URL 和账号后再查看备份列表。', tone: 'warning' });
      return;
    }
    setSyncState('listing');
    try {
      const files = await webdavService.listBackups(cfg);
      setBackups(files);
      setShowBackupList(true);
      setTimeout(() => listRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
    } catch (e) {
      await showAlert({ title: '列举失败', message: (e as Error).message, tone: 'danger' });
    } finally {
      setSyncState('idle');
    }
  };

  const handleRestore = async (filename: string) => {
    const confirmed = await showConfirm({
      title: '确认恢复？',
      tone: 'danger',
      message: '镜像恢复会用该备份覆盖本机的全部对话与模拟法庭记录；本地比备份多出来的会话会被删除。建议先“立即备份”当前数据。确定继续？',
      confirmLabel: '覆盖并恢复',
      cancelLabel: '取消',
    });
    if (!confirmed) return;
    setActiveFilename(filename);
    setSyncState('restoring');
    try {
      const raw = await webdavService.downloadBackup(cfg, filename);
      const count = await restoreBackupSnapshot(raw);
      setShowBackupList(false);
      await showAlert({
        title: '恢复成功',
        message: `已从 ${filename} 镜像恢复，本机现有 ${count} 条记录，列表已自动刷新。`,
        tone: 'success',
      });
    } catch (e) {
      await showAlert({ title: '恢复失败', message: (e as Error).message, tone: 'danger' });
    } finally {
      setSyncState('idle');
      setActiveFilename(null);
    }
  };

  const handleDelete = async (filename: string) => {
    setActiveFilename(filename);
    setSyncState('deleting');
    try {
      await webdavService.deleteBackup(cfg, filename);
      setBackups(prev => prev ? prev.filter(f => f.filename !== filename) : prev);
    } catch (e) {
      await showAlert({ title: '删除失败', message: (e as Error).message, tone: 'danger' });
    } finally {
      setSyncState('idle');
      setActiveFilename(null);
    }
  };

  const inputClass = 'h-10 w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm outline-none transition-colors focus:border-[var(--accent)] placeholder:text-[var(--fg-4)]';

  return (
    <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
          <Cloud size={20} strokeWidth={2} />
        </span>
        <div>
          <h2 className="t-title-m">WebDAV 数据同步</h2>
          <p className="text-[13px] text-[var(--fg-3)]">备份至自己的 WebDAV 云（坚果云、Nextcloud 等）。</p>
        </div>
      </div>

      {/* 隐私提示 */}
      <div className="mb-4 flex gap-3 rounded-[var(--radius-md)] border border-[rgba(184,132,42,0.3)] bg-[rgba(184,132,42,0.08)] p-3">
        <AlertTriangle size={16} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--color-warning-500)]" />
        <p className="text-[12px] leading-relaxed text-[#5C3F0E] dark:text-[#FBEBC8]">
          备份文件以<strong>明文 JSON</strong>上传，对话内容对你的 WebDAV 服务商可见。请确保使用 HTTPS 且账号安全。密码仅存在本设备，不经过 Lawver 服务器保留。
        </p>
      </div>

      {/* 配置表单 */}
      <div className="flex flex-col gap-3">
        <div>
          <label className="mb-1 block text-[12px] font-medium text-[var(--fg-3)]">服务器 URL</label>
          <input
            className={inputClass}
            placeholder="https://dav.example.com/dav/"
            value={cfg.url}
            onChange={e => saveConfig({ ...cfg, url: e.target.value })}
            disabled={busy}
            autoComplete="url"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[12px] font-medium text-[var(--fg-3)]">用户名</label>
            <input
              className={inputClass}
              placeholder="username"
              value={cfg.username}
              onChange={e => saveConfig({ ...cfg, username: e.target.value })}
              disabled={busy}
              autoComplete="username"
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-medium text-[var(--fg-3)]">密码</label>
            <div className="relative">
              <input
                className={inputClass + ' pr-16'}
                type={showPassword ? 'text' : 'password'}
                placeholder="password"
                value={cfg.password}
                onChange={e => saveConfig({ ...cfg, password: e.target.value })}
                disabled={busy}
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword(p => !p)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-[var(--fg-3)] hover:text-[var(--fg-1)]"
              >
                {showPassword ? '隐藏' : '显示'}
              </button>
            </div>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-[var(--fg-3)]">备份目录（远端路径）</label>
          <input
            className={inputClass}
            placeholder="/Lawver/"
            value={cfg.directory}
            onChange={e => saveConfig({ ...cfg, directory: e.target.value })}
            disabled={busy}
          />
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={handleTest}
          disabled={busy}
          className="lawver-pressable inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface-2)] px-3 text-sm font-medium text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-inset)] disabled:opacity-50"
        >
          {syncState === 'testing' ? <Loader2 size={14} strokeWidth={2} className="animate-spin" /> : <Server size={14} strokeWidth={2} />}
          测试连接
        </button>

        <button
          onClick={handleUpload}
          disabled={busy}
          className="lawver-pressable inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--accent)] px-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {syncState === 'uploading' ? <Loader2 size={14} strokeWidth={2} className="animate-spin" /> : <CloudUpload size={14} strokeWidth={2} />}
          立即备份
        </button>

        <button
          onClick={handleListBackups}
          disabled={busy}
          className="lawver-pressable inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface-2)] px-3 text-sm font-medium text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-inset)] disabled:opacity-50"
        >
          {syncState === 'listing' ? <Loader2 size={14} strokeWidth={2} className="animate-spin" /> : <CloudDownload size={14} strokeWidth={2} />}
          从云端恢复
          <ChevronDown size={14} strokeWidth={2} className={`transition-transform ${showBackupList ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {/* 备份列表 */}
      {showBackupList && backups !== null && (
        <div ref={listRef} className="mt-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-inset)] overflow-hidden">
          {backups.length === 0 ? (
            <p className="p-4 text-center text-sm text-[var(--fg-3)]">目录下暂无备份文件。</p>
          ) : (
            <ul className="divide-y divide-[var(--border-subtle)]">
              {backups.map(file => (
                <li key={file.filename} className="flex items-center justify-between gap-2 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[var(--fg-1)]">{file.filename}</p>
                    <p className="text-[11px] text-[var(--fg-3)]">
                      {file.last_modified ? new Date(file.last_modified).toLocaleString('zh-CN') : '—'}
                      {file.size > 0 && <span className="ml-2">{(file.size / 1024).toFixed(1)} KB</span>}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      onClick={() => handleRestore(file.filename)}
                      disabled={busy}
                      className="lawver-pressable inline-flex h-8 items-center gap-1 rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] px-2.5 text-[12px] font-medium text-[var(--accent)] transition-colors hover:bg-[rgba(59,98,184,0.16)] disabled:opacity-50"
                    >
                      {syncState === 'restoring' && activeFilename === file.filename ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <CloudDownload size={12} />
                      )}
                      恢复
                    </button>
                    <button
                      onClick={() => handleDelete(file.filename)}
                      disabled={busy}
                      className="lawver-pressable inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] text-[var(--fg-3)] transition-colors hover:bg-[rgba(184,42,42,0.08)] hover:text-[var(--color-danger-500)] disabled:opacity-50"
                      title="删除此快照"
                    >
                      {syncState === 'deleting' && activeFilename === file.filename ? (
                        <Loader2 size={13} className="animate-spin text-[var(--color-danger-500)]" />
                      ) : (
                        <Trash2 size={13} strokeWidth={2} />
                      )}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
};

const getWebDavHostLabel = (cfg: WebDavConfig) => {
  if (!cfg.url) return '未配置';
  try {
    return new URL(cfg.url).host || cfg.url;
  } catch {
    return cfg.url;
  }
};

const WebDavEntry: React.FC<{ onOpen: () => void }> = ({ onOpen }) => {
  const [cfg, setCfg] = useState<WebDavConfig>(emptyWebDavConfig);

  useEffect(() => {
    getWebDavConfig().then(saved => {
      if (saved) setCfg(saved);
    });
  }, []);

  const configured = Boolean(cfg.url && cfg.username);

  return (
    <button
      type="button"
      onClick={onOpen}
      className="lawver-pressable flex min-w-0 items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-4 text-left shadow-[var(--shadow-1)] transition-colors hover:border-[var(--border-default)] hover:bg-[var(--bg-surface-2)]"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
        <Cloud size={21} strokeWidth={2} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-[var(--fg-1)]">WebDAV 数据同步</span>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${configured
            ? 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
            : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
            }`}>
            {configured ? '已配置' : '未配置'}
          </span>
        </span>
        <span className="mt-1 block truncate text-[12px] leading-5 text-[var(--fg-3)]">
          {configured ? `${getWebDavHostLabel(cfg)} · ${cfg.directory || '/Lawver/'}` : ''}
        </span>
      </span>
      <ChevronRight size={18} strokeWidth={2} className="shrink-0 text-[var(--fg-4)]" />
    </button>
  );
};

const HelpEntry: React.FC<{ onOpen: () => void }> = ({ onOpen }) => (
  <button
    type="button"
    onClick={onOpen}
    className="lawver-pressable flex min-w-0 items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-4 text-left shadow-[var(--shadow-1)] transition-colors hover:border-[var(--border-default)] hover:bg-[var(--bg-surface-2)]"
  >
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
      <BookOpen size={21} strokeWidth={2} />
    </span>
    <span className="min-w-0 flex-1">
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-[15px] font-semibold text-[var(--fg-1)]">帮助与指引</span>
        <span className="shrink-0 rounded-full bg-[var(--accent-quiet)] px-2 py-0.5 text-[11px] font-medium text-[var(--accent)]">
          新
        </span>
      </span>
      <span className="mt-1 block truncate text-[12px] leading-5 text-[var(--fg-3)]">
        查看按钮手册，随时重播首次使用导览
      </span>
    </span>
    <ChevronRight size={18} strokeWidth={2} className="shrink-0 text-[var(--fg-4)]" />
  </button>
);

const PROVIDER_ICONS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  llm: Sparkles,
  deli: Gavel,
  searxng: Globe,
  qcc: Server,
  embedding: Link2,
};

const PROVIDER_LABELS: Record<string, string> = {
  llm: '大模型 (LLM)',
  deli: '得理法搜',
  searxng: '网页检索 (SearXNG)',
  qcc: '企业信息 (企查查)',
  embedding: '嵌入模型 (Embedding)',
};

const PROVIDER_DESCS: Record<string, string> = {
  llm: 'OpenAI-compatible 聊天模型，主聊天、标题生成和代理流程都通过这里。',
  deli: '案例检索和类案匹配。',
  searxng: '自托管联网检索。',
  qcc: '企业画像、工商登记和联系方式查询。',
  embedding: '文本转向量，用于 RAG 召回。',
};

const PROVIDER_FIELDS: Record<string, { key: string; label: string; placeholder?: string }[]> = {
  llm: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.openai.com/v1' },
    { key: 'model', label: '模型', placeholder: 'gpt-4o / qwen-plus' },
  ],
  deli: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://openapi.delilegal.com/api/qa/v3/search/queryListCase' },
  ],
  searxng: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://searx.example.com' },
    { key: 'engines', label: '引擎', placeholder: 'google,bing,duckduckgo' },
  ],
  qcc: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://agent.qcc.com/mcp/company/stream' },
  ],
  embedding: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.siliconflow.cn/v1' },
    { key: 'model', label: '模型', placeholder: 'Qwen/Qwen3-Embedding-8B' },
  ],
};

const PROVIDER_ORDER = ['llm', 'deli', 'searxng', 'qcc', 'embedding'];

const providerInputClass = 'h-10 w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm outline-none transition-colors focus:border-[var(--accent)] placeholder:text-[var(--fg-4)] disabled:opacity-60';

const ProviderConfigSection: React.FC = () => {
  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [userRole, setUserRole] = useState('user');
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([
      getProviderStatus().catch(() => [] as ProviderStatus[]),
      getSettings().catch(() => null),
      verifyAuth().catch(() => null),
    ]).then(([statusesResult, settingsResult, auth]) => {
      setStatuses(statusesResult);
      setSettings(settingsResult);
      setUserRole(auth?.role || 'user');
      setLoaded(true);
    });
  }, []);

  const updateProvider = (key: string, patch: Record<string, any>) => {
    setSettings(prev => prev ? {
      ...prev,
      providers: {
        ...prev.providers,
        [key]: { ...(prev.providers?.[key] || {}), ...patch },
      },
    } : prev);
  };

  const saveSettings = async () => {
    if (!settings) return;
    setBusy('save');
    try {
      const result = await updateSettings({ providers: settings.providers });
      setSettings(result);
      setStatuses(await getProviderStatus().catch(() => []));
    } catch (e) {
      console.error('Save failed:', e);
    } finally {
      setBusy('');
    }
  };

  const testConnection = async (key: string) => {
    setBusy(`${key}.test`);
    try {
      await testProvider(key);
      setStatuses(await getProviderStatus().catch(() => []));
    } catch {
      setBusy('');
    }
  };

  if (!loaded) return null;
  if (userRole !== 'admin') return null;

  const statusMap = new Map(statuses.map(s => [s.provider, s]));

  return (
    <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
          <Server size={20} strokeWidth={2} />
        </span>
        <div>
          <h2 className="t-title-m">服务端能力</h2>
          <p className="text-[13px] text-[var(--fg-3)]">远端 Python/FastAPI 服务端的模型、法源和检索服务配置。修改后需保存生效。</p>
        </div>
      </div>

      <div className="grid gap-3">
        {PROVIDER_ORDER.map(key => {
          const provider = settings?.providers?.[key] || {};
          const status = statusMap.get(key);
          const statusOk = Boolean(status?.ok && provider.enabled);
          const isBusy = busy.startsWith(key);

          return (
            <div key={key} className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-inset)] p-3">
              <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-[var(--fg-1)]">{PROVIDER_LABELS[key] || key}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] ${
                      statusOk
                        ? 'bg-[rgba(22,163,74,0.12)] text-[var(--color-success-500)]'
                        : provider.enabled
                          ? 'bg-[rgba(184,132,42,0.12)] text-[var(--color-warning-500)]'
                          : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
                    }`}>
                      {statusOk ? '已就绪' : provider.enabled ? '已启用，等待状态刷新' : '未配置'}
                    </span>
                  </div>
                  <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">{PROVIDER_DESCS[key] || ''}</p>
                </div>
                <label className="inline-flex shrink-0 items-center gap-2 text-sm text-[var(--fg-2)]">
                  <input
                    type="checkbox"
                    checked={Boolean(provider.enabled)}
                    onChange={e => updateProvider(key, { enabled: e.target.checked })}
                  />
                  启用
                </label>
              </div>

              {(PROVIDER_FIELDS[key] || []).length > 0 && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {(PROVIDER_FIELDS[key] || []).map(field => (
                    <label key={field.key} className="min-w-0">
                      <span className="mb-1 block text-[12px] font-medium text-[var(--fg-3)]">{field.label}</span>
                      <input
                        className={providerInputClass}
                        value={String(provider[field.key] || '')}
                        placeholder={field.placeholder}
                        onChange={e => updateProvider(key, { [field.key]: e.target.value })}
                      />
                    </label>
                  ))}
                </div>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => testConnection(key)}
                  disabled={isBusy}
                  className="lawver-pressable inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm font-medium text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-surface-2)] disabled:opacity-50"
                >
                  {busy === `${key}.test` ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                  测试连接
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={saveSettings}
          disabled={busy === 'save'}
          className="lawver-pressable inline-flex h-10 items-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--accent)] px-4 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {busy === 'save' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
          保存配置
        </button>
      </div>
    </section>
  );
};

const HELP_TOPICS: Array<{
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  title: string;
  description: string;
}> = [
    {
      icon: MessageSquareText,
      title: '对话与追问',
      description: '围绕案件事实、法条检索、文书草拟继续追问；对回答可重新生成、编辑或创建分叉。',
    },
    {
      icon: Paperclip,
      title: '上传材料',
      description: '在输入区上传 PDF、Word、Markdown 或文本，当前会话会带着材料上下文工作。',
    },
    {
      icon: Folder,
      title: '工作区',
      description: '右上角文件夹集中查看上传文件和生成文件，便于下载、清理和继续使用。',
    },
    {
      icon: Gavel,
      title: '模拟法庭',
      description: '从侧栏进入庭审推演，将公开案卷和用户私有作战笔记分开组织。',
    },
    {
      icon: Settings2,
      title: '输入区设置',
      description: '切换流式输出、OCP 检查流程和 Agent Mode，适配不同回答风格。',
    },
    {
      icon: Cloud,
      title: '数据同步',
      description: '在 WebDAV 二级页配置自己的云端备份，恢复前建议先保留当前快照。',
    },
  ];

const QUICK_ACTIONS: Array<{
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  label: string;
  hint: string;
}> = [
    { icon: PanelLeftOpen, label: '菜单', hint: '展开会话侧栏' },
    { icon: Send, label: '发送', hint: '提交问题或停止生成' },
    { icon: Paperclip, label: '上传', hint: '添加案件材料' },
    { icon: Folder, label: 'Workspace', hint: '管理文件' },
    { icon: Settings, label: '设置', hint: '外观、同步与帮助' },
    { icon: CirclePlay, label: '重播', hint: '再次打开动态导览' },
  ];

const HelpSection: React.FC<{ onStartTour: () => void }> = ({ onStartTour }) => (
  <div className="flex min-w-0 flex-col gap-5">
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
      <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
              <Sparkles size={21} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <h2 className="t-title-m">动态指引手册</h2>
              <p className="mt-1 text-[13px] leading-5 text-[var(--fg-3)]">
                用分步动画快速复习 Lawver 的主要区域、按钮和常见操作。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onStartTour}
            className="md3-btn-filled lawver-pressable min-h-10 shrink-0 whitespace-nowrap px-4 py-2.5 text-sm"
          >
            <CirclePlay size={17} strokeWidth={2} />
            重播动态指引
          </button>
        </div>
      </div>

      <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
        {HELP_TOPICS.map(topic => {
          const Icon = topic.icon;
          return (
            <div
              key={topic.title}
              className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4"
            >
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                  <Icon size={17} strokeWidth={2} />
                </span>
                <h3 className="text-[14px] font-semibold leading-5 text-[var(--fg-1)]">{topic.title}</h3>
              </div>
              <p className="text-[12px] leading-5 text-[var(--fg-3)]">{topic.description}</p>
            </div>
          );
        })}
      </div>
    </section>

    <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
          <BookOpen size={20} strokeWidth={2} />
        </span>
        <div className="min-w-0">
          <h2 className="t-title-m">常用按钮速查</h2>
          <p className="mt-1 text-[13px] text-[var(--fg-3)]">遇到不熟悉的入口，可以先从这些图标判断作用。</p>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {QUICK_ACTIONS.map(action => {
          const Icon = action.icon;
          return (
            <div
              key={action.label}
              className="flex min-w-0 items-center gap-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-3"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
                <Icon size={17} strokeWidth={2} />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold text-[var(--fg-1)]">{action.label}</span>
                <span className="mt-0.5 block truncate text-[12px] text-[var(--fg-3)]">{action.hint}</span>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  </div>
);

const AboutMetaRow: React.FC<{
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  label: string;
  children: React.ReactNode;
}> = ({ icon: Icon, label, children }) => (
  <div className="flex min-w-0 items-start gap-3 border-t border-[var(--border-subtle)] px-1 py-3 first:border-t-0 first:pt-0 last:pb-0">
    <Icon size={16} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--fg-4)]" />
    <div className="min-w-0 flex-1">
      <div className="text-[12px] font-medium text-[var(--fg-3)]">{label}</div>
      <div className="mt-0.5 min-w-0 text-[14px] leading-6 text-[var(--fg-1)]">{children}</div>
    </div>
  </div>
);

// ─── 主设置页 ────────────────────────────────────────────────────────────────

export const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    mode,
    colorSource,
    customSeed,
    resolvedTheme,
    monetStatus,
    isMonetAvailableOnPlatform,
    setMode,
    setColorSource,
    setCustomSeed,
    resetColors,
    refreshMonet,
  } = useThemeContext();
  const [seedDraft, setSeedDraft] = useState(customSeed);
  const [resumeEnabled, setResumeEnabledState] = useState(false);
  const seedValid = isHexColor(seedDraft);
  const normalizedPath = location.pathname.replace(/\/+$/, '');
  const isWebDavRoute = normalizedPath === '/settings/webdav';
  const isHelpRoute = normalizedPath === '/settings/help';
  const isSecondaryRoute = isWebDavRoute || isHelpRoute;
  const pageTitle = isWebDavRoute ? 'WebDAV 同步' : isHelpRoute ? '帮助与指引' : '设置';
  const pageSubtitle = isWebDavRoute ? '备份与恢复' : isHelpRoute ? '功能手册与首次使用指引' : '外观、同步与应用信息';
  const statusLabel = isWebDavRoute
    ? '数据同步'
    : isHelpRoute
      ? '使用手册'
      : `${resolvedTheme === 'dark' ? '深色' : '浅色'} · ${COLOR_SOURCE_LABEL[colorSource]}`;
  const handleBack = () => {
    if (isSecondaryRoute) {
      navigate('/settings');
      return;
    }
    navigate(-1);
  };

  useEffect(() => {
    setSeedDraft(customSeed);
  }, [customSeed]);

  useEffect(() => {
    getResumeEnabled().then(setResumeEnabledState).catch(() => setResumeEnabledState(false));
  }, []);

  const updateResumeEnabled = async (enabled: boolean) => {
    setResumeEnabledState(enabled);
    await setResumeEnabled(enabled);
    notifyResumeEnabledChanged(enabled);
  };

  const monetDescription = useMemo(() => {
    if (!isMonetAvailableOnPlatform) return '需 Android 客户端';
    if (monetStatus === 'available') return '跟随系统壁纸';
    if (monetStatus === 'loading') return '正在读取系统色';
    if (monetStatus === 'unavailable') return '此设备不支持 Material You';
    if (monetStatus === 'error') return '读取系统色失败';
    return '跟随系统壁纸';
  }, [isMonetAvailableOnPlatform, monetStatus]);

  const applySeedDraft = () => {
    if (!seedValid) return;
    setCustomSeed(seedDraft);
    setColorSource('custom');
  };

  const sourceButtonClass = (source: ColorSource, disabled = false) => [
    'lawver-pressable flex min-h-[86px] min-w-0 flex-1 flex-col justify-between rounded-[var(--radius-md)] border px-4 py-3 text-left transition-colors',
    source === colorSource
      ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--fg-1)] shadow-[0_0_0_1px_var(--accent)]'
      : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-2)] hover:border-[var(--border-default)] hover:bg-[var(--bg-surface-2)]',
    disabled ? 'cursor-not-allowed opacity-60 hover:border-[var(--border-subtle)] hover:bg-[var(--bg-surface)]' : ''
  ].join(' ');

  return (
    <div className="flex min-h-[100dvh] w-full max-w-full flex-col overflow-x-hidden bg-[var(--bg-app)] text-[var(--fg-1)]">
      <header className="lawver-topbar sticky top-0 z-30 flex w-full max-w-full shrink-0 items-center justify-between gap-3 overflow-hidden border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-3 pb-2 pt-[calc(0.625rem+var(--safe-top))] sm:px-5 sm:pb-3 sm:pt-[calc(0.75rem+var(--safe-top))]">
        <div className="flex min-w-0 items-center gap-2">
          <HoverInfo label="返回" placement="bottom">
            <button
              onClick={handleBack}
              className="lawver-pressable inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06] sm:h-11 sm:w-11"
              aria-label="返回"
            >
              <ArrowLeft size={20} strokeWidth={2} />
            </button>
          </HoverInfo>
          <div className="min-w-0">
            <h1 className="t-title-l truncate">{pageTitle}</h1>
            <p className="truncate text-[12px] text-[var(--fg-3)]">{pageSubtitle}</p>
          </div>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-1.5 text-[12px] text-[var(--fg-3)] sm:flex">
          <Settings size={14} strokeWidth={2} />
          {statusLabel}
        </div>
      </header>

      <main className="custom-scrollbar flex min-h-0 w-full max-w-full flex-1 overflow-x-hidden overflow-y-auto px-4 py-5 pb-[calc(1.25rem+var(--safe-bottom))] sm:px-6 sm:py-8">
        <div className={`mx-auto flex min-w-0 w-full flex-col gap-5 ${isWebDavRoute ? 'max-w-2xl' : 'max-w-3xl'}`}>
          {isWebDavRoute ? (
            <WebDavSection />
          ) : isHelpRoute ? (
            <HelpSection onStartTour={requestGuidedTour} />
          ) : (
            <>
              <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
                <div className="mb-4 flex items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                    <Sun size={20} strokeWidth={2} />
                  </span>
                  <div>
                    <h2 className="t-title-m">外观模式</h2>
                    <p className="text-[13px] text-[var(--fg-3)]">浅色、深色或跟随系统。</p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 rounded-[var(--radius-lg)] bg-[var(--bg-inset)] p-1.5">
                  {MODE_OPTIONS.map(option => {
                    const Icon = option.icon;
                    const active = mode === option.value;
                    return (
                      <button
                        key={option.value}
                        onClick={() => setMode(option.value)}
                        className={`lawver-pressable flex h-12 items-center justify-center gap-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors ${active
                          ? 'bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)]'
                          : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'
                          }`}
                      >
                        <Icon size={17} strokeWidth={2} />
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
                <div className="mb-4 flex items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                    <Palette size={20} strokeWidth={2} />
                  </span>
                  <div>
                    <h2 className="t-title-m">配色来源</h2>
                    <p className="text-[13px] text-[var(--fg-3)]">默认品牌、自定义种子色或 Android 动态色。</p>
                  </div>
                </div>

                <div className="grid gap-2 sm:grid-cols-3">
                  <button onClick={resetColors} className={sourceButtonClass('default')}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">默认</span>
                      {colorSource === 'default' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                    </span>
                    <span className="text-[12px] text-[var(--fg-3)]">Lawver 司法蓝</span>
                  </button>

                  <button onClick={() => setColorSource('custom')} className={sourceButtonClass('custom')}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">自定义</span>
                      {colorSource === 'custom' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                    </span>
                    <span className="text-[12px] text-[var(--fg-3)]">使用种子色生成全套色板</span>
                  </button>

                  <button
                    onClick={() => {
                      if (!isMonetAvailableOnPlatform) return;
                      setColorSource('monet');
                      refreshMonet();
                    }}
                    className={sourceButtonClass('monet', !isMonetAvailableOnPlatform)}
                    disabled={!isMonetAvailableOnPlatform}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-2 font-medium">
                        <Smartphone size={16} strokeWidth={2} />
                        Material You
                      </span>
                      {colorSource === 'monet' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                    </span>
                    <span className="text-[12px] text-[var(--fg-3)]">{monetDescription}</span>
                  </button>
                </div>

                {colorSource === 'custom' && (
                  <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                      <label className="flex items-center gap-3">
                        <input
                          type="color"
                          value={seedValid ? seedDraft : DEFAULT_SEED}
                          onChange={event => {
                            setSeedDraft(event.target.value);
                            setCustomSeed(event.target.value);
                          }}
                          className="h-11 w-14 cursor-pointer rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-transparent p-1"
                          aria-label="自定义种子色"
                        />
                        <input
                          value={seedDraft}
                          onChange={event => setSeedDraft(event.target.value)}
                          onBlur={applySeedDraft}
                          onKeyDown={event => {
                            if (event.key === 'Enter') applySeedDraft();
                          }}
                          className={`h-11 w-36 rounded-[var(--radius-md)] border bg-[var(--bg-surface)] px-3 font-mono text-sm outline-none transition-colors ${seedValid ? 'border-[var(--border-default)] focus:border-[var(--accent)]' : 'border-[var(--color-danger-500)]'
                            }`}
                          aria-label="十六进制颜色"
                        />
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {COLOR_PRESETS.map(color => (
                          <button
                            key={color}
                            onClick={() => {
                              setSeedDraft(color);
                              setCustomSeed(color);
                            }}
                            className="lawver-pressable h-8 w-8 rounded-full border border-[var(--border-default)] shadow-[var(--shadow-1)]"
                            style={{ backgroundColor: color }}
                            aria-label={`选择 ${color}`}
                          />
                        ))}
                      </div>
                      <button
                        onClick={() => {
                          setSeedDraft(DEFAULT_SEED);
                          setCustomSeed(DEFAULT_SEED);
                        }}
                        className="lawver-pressable inline-flex h-10 items-center justify-center gap-2 rounded-[var(--radius-md)] px-3 text-sm font-medium text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)]"
                      >
                        <RotateCcw size={15} strokeWidth={2} />
                        重置
                      </button>
                    </div>
                  </div>
                )}

              </section>

              <section className="min-w-0">
                <div className="mb-3 px-1">
                  <h2 className="t-title-m">数据与同步</h2>
                  <p className="mt-1 text-[13px] text-[var(--fg-3)]"></p>
                </div>
                <div className="flex flex-col gap-3">
                  <WebDavEntry onOpen={() => navigate('/settings/webdav')} />
                  <div className="flex min-w-0 items-start justify-between gap-4 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-4 shadow-[var(--shadow-1)]">
                    <div className="flex min-w-0 gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                        <RotateCcw size={20} strokeWidth={2} />
                      </span>
                      <div className="min-w-0">
                        <h3 className="text-[15px] font-semibold text-[var(--fg-1)]">断线续传</h3>
                        <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">
                          回答中断时临时使用服务器内存缓存，最多 45 分钟，设备确认接收后删除。
                        </p>
                      </div>
                    </div>
                    <AnimatedSwitch
                      checked={resumeEnabled}
                      onCheckedChange={updateResumeEnabled}
                      ariaLabel="切换断线续传"
                    />
                  </div>
                </div>
              </section>

              <ProviderConfigSection />

              <section className="min-w-0">
                <div className="mb-3 px-1">
                  <h2 className="t-title-m">帮助</h2>
                  <p className="mt-1 text-[13px] text-[var(--fg-3)]">查看按钮手册，或重新打开首次使用导览。</p>
                </div>
                <HelpEntry onOpen={() => navigate('/settings/help')} />
              </section>

              <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
                <div className="mb-4 flex items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                    <BrandMark className="h-5 w-5 [--brand-logo-ink:var(--accent)]" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="t-title-m truncate">{BUILD_INFO.appName}</h2>
                    <p className="truncate text-[13px] text-[var(--fg-3)]">{BUILD_INFO.description}</p>
                  </div>
                </div>
                <AboutMetaRow icon={PackageCheck} label="版本">
                  <span className="font-medium">{BUILD_INFO.version}</span>
                </AboutMetaRow>
                <AboutMetaRow icon={Server} label="构建环境">
                  <span className="font-medium">{BUILD_INFO.environment}</span>
                </AboutMetaRow>
                <AboutMetaRow icon={Clock3} label="构建时间">
                  <span className="break-words font-mono text-[13px]">{BUILD_INFO.buildTime}</span>
                </AboutMetaRow>
                <AboutMetaRow icon={Link2} label="项目地址">
                  <a
                    href={BUILD_INFO.projectUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-w-0 max-w-full items-center gap-1.5 break-all font-mono text-[13px] transition-opacity hover:opacity-80 hover:underline"
                  >
                    <span className="min-w-0 break-all">{BUILD_INFO.projectUrl}</span>
                    <ExternalLink size={13} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
                  </a>
                </AboutMetaRow>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
};
