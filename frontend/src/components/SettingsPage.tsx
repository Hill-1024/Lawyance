/*
 * 模块描述：应用设置页，集中管理外观、配色、数据同步、能力配置与帮助入口。
 */

import { motion, useReducedMotion } from 'motion/react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  X,
  Search,
  Info,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CirclePlay,
  Clock3,
  Cloud,
  CloudDownload,
  CloudUpload,
  ExternalLink,
  Folder,
  Gavel,
  Globe,
  KeyRound,
  Link2,
  Loader2,
  MessageSquareText,
  Monitor,
  Moon,
  PackageCheck,
  Palette,
  PanelLeftOpen,
  Paperclip,
  PlugZap,
  RotateCcw,
  Send,
  Server,
  Settings,
  Settings2,
  Smartphone,
  Sparkles,
  Sun,
  Trash2,
} from 'lucide-react';
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
import { useBackButton } from '../hooks/useBackButton';
import { SettingsEditContext, useSettingsEdit } from './settings/SettingsEditContext';
import './settings/settings-modal.css';
import { SettingsExtensions } from './settings/SettingsExtensions';
import {
  clearSecret,
  getProviderStatus,
  getSettings,
  setSecret,
  testProvider,
  updateSettings,
  verifyAuth,
  type ProviderStatus,
} from '../services/api';
import { LlmProfileManager } from './settings/LlmProfileManager';
import {
  Banner,
  CenteredSpinner,
  SettingsField,
  SettingsGroup,
  SettingsRow,
  StatusChip,
  fieldInputClass,
} from './settings/SettingsUI';

const MODE_OPTIONS: Array<{
  value: ThemeMode;
  label: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
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

/* ── WebDAV 同步 ───────────────────────────────────────────────────────── */

type WebDavSyncState = 'idle' | 'testing' | 'uploading' | 'listing' | 'restoring' | 'deleting';

const getWebDavHostLabel = (cfg: WebDavConfig) => {
  if (!cfg.url) return '未配置';
  try {
    return new URL(cfg.url).host || cfg.url;
  } catch {
    return cfg.url;
  }
};

const WebDavSection: React.FC = () => {
  const reportEdit = useSettingsEdit();
  const [saveStatus, setSaveStatus] = useState('');
  const saveQueue = useRef(Promise.resolve());
  const saveSequence = useRef(0);
  useEffect(() => {reportEdit('webdav', saveStatus === '正在保存…' || saveStatus.startsWith('保存失败'));}, [saveStatus, reportEdit]);
  const { showAlert, showConfirm } = useAppDialog();
  const [cfg, setCfg] = useState<WebDavConfig>(emptyWebDavConfig);
  // saveConfig 逐字段写入时需要读到最新配置，避免用旧快照覆盖刚输入的字段。
  // 在 effect 里同步而非渲染期赋值：并发渲染下渲染期写 ref 可能来自被丢弃的那次渲染。
  const cfgRef = useRef(cfg);
  useEffect(() => {
    cfgRef.current = cfg;
  }, [cfg]);
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

  const saveConfig = async (patch: Partial<WebDavConfig>) => {
    // 以 ref 为准做合并：表单逐字符保存，用渲染期快照会让连续输入互相覆盖。
    const next = { ...cfgRef.current, ...patch };
    cfgRef.current = next;
    setCfg(next);
    const sequence = ++saveSequence.current;
    setSaveStatus('正在保存…');
    saveQueue.current = saveQueue.current.catch(() => {}).then(async () => {
      try {await setWebDavConfig(next); if(sequence === saveSequence.current) setSaveStatus('已自动保存');}
      catch {if(sequence === saveSequence.current) setSaveStatus('保存失败，请重新修改后重试');}
    });
    await saveQueue.current;
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
      setBackups(null);
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
      message: '镜像恢复会用该备份覆盖本机的全部对话与模拟法庭记录；本地比备份多出来的会话会被删除。建议先「立即备份」当前数据。确定继续？',
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

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {saveStatus && <p role="status" className="settings-hint">{saveStatus}</p>}
      <SettingsGroup label="连接信息">
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
          <SettingsField label="服务器 URL">
            <input
              className={fieldInputClass}
              placeholder="https://dav.example.com/dav/"
              value={cfg.url}
              onChange={e => saveConfig({ url: e.target.value })}
              disabled={busy}
              autoComplete="url"
            />
          </SettingsField>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <SettingsField label="用户名">
              <input
                className={fieldInputClass}
                placeholder="username"
                value={cfg.username}
                onChange={e => saveConfig({ username: e.target.value })}
                disabled={busy}
                autoComplete="username"
              />
            </SettingsField>
            <SettingsField label="密码">
              <div className="relative">
                <input
                  className={`${fieldInputClass} pr-16`}
                  type={showPassword ? 'text' : 'password'}
                  placeholder="password"
                  value={cfg.password}
                  onChange={e => saveConfig({ password: e.target.value })}
                  disabled={busy}
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(p => !p)}
                  className="lawver-pressable absolute right-1 top-1/2 inline-flex h-11 min-w-11 -translate-y-1/2 items-center justify-center rounded-[var(--radius-sm)] px-2 text-[11px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg-1)]"
                >
                  {showPassword ? '隐藏' : '显示'}
                </button>
              </div>
            </SettingsField>
          </div>
          <SettingsField label="备份目录（远端路径）">
            <input
              className={fieldInputClass}
              placeholder="/Lawver/"
              value={cfg.directory}
              onChange={e => saveConfig({ directory: e.target.value })}
              disabled={busy}
            />
          </SettingsField>
        </div>
      </SettingsGroup>

      <SettingsGroup label="备份与恢复">
        <div className="flex min-w-0 flex-col gap-3 p-4 sm:p-5">
          <div className="flex min-w-0 flex-wrap gap-2">
            <button
              type="button"
              onClick={handleTest}
              disabled={busy}
              className="md3-btn-tonal lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {syncState === 'testing' ? <Loader2 size={15} className="animate-spin" /> : <Server size={15} strokeWidth={2} />}
              测试连接
            </button>
            <button
              type="button"
              onClick={handleUpload}
              disabled={busy}
              className="md3-btn-filled lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {syncState === 'uploading' ? <Loader2 size={15} className="animate-spin" /> : <CloudUpload size={15} strokeWidth={2} />}
              立即备份
            </button>
            <button
              type="button"
              onClick={handleListBackups}
              disabled={busy}
              className="md3-btn-tonal lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {syncState === 'listing' ? <Loader2 size={15} className="animate-spin" /> : <CloudDownload size={15} strokeWidth={2} />}
              从云端恢复
              <ChevronDown size={15} strokeWidth={2} className={`transition-transform ${showBackupList ? 'rotate-180' : ''}`} />
            </button>
          </div>

          <Banner tone="warning">
            备份文件以<strong>明文 JSON</strong>上传，对话内容对你的 WebDAV 服务商可见。请确保使用 HTTPS 且账号安全。
            密码仅存在本设备，不经过 Lawver 服务器保留。
          </Banner>

          {showBackupList && backups !== null && (
            <div
              ref={listRef}
              className="min-w-0 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-subtle)]"
            >
              {backups.length === 0 ? (
                <p className="p-5 text-center text-[13px] text-[var(--fg-3)]">目录下暂无备份文件。</p>
              ) : (
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {backups.map(file => (
                    <li key={file.filename} className="flex min-w-0 items-center justify-between gap-2 px-3 py-3 sm:px-4">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-[13px] font-medium text-[var(--fg-1)]">{file.filename}</p>
                        <p className="text-[11px] tabular-nums text-[var(--fg-3)]">
                          {file.last_modified ? new Date(file.last_modified).toLocaleString('zh-CN') : '—'}
                          {file.size > 0 && <span className="ml-2">{(file.size / 1024).toFixed(1)} KB</span>}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() => handleRestore(file.filename)}
                          disabled={busy}
                          className="md3-btn-tonal lawver-pressable !min-h-11 !px-3 text-[12px] disabled:opacity-50"
                        >
                          {syncState === 'restoring' && activeFilename === file.filename ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <CloudDownload size={13} strokeWidth={2} />
                          )}
                          恢复
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(file.filename)}
                          disabled={busy}
                          className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] disabled:opacity-50"
                          title="删除此快照"
                          aria-label={`删除备份 ${file.filename}`}
                        >
                          {syncState === 'deleting' && activeFilename === file.filename ? (
                            <Loader2 size={15} className="animate-spin text-[var(--color-danger-500)]" />
                          ) : (
                            <Trash2 size={15} strokeWidth={2} />
                          )}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </SettingsGroup>
    </div>
  );
};

const WebDavEntry: React.FC<{ onOpen: () => void }> = ({ onOpen }) => {
  const [cfg, setCfg] = useState<WebDavConfig>(emptyWebDavConfig);

  useEffect(() => {
    getWebDavConfig().then(saved => { if (saved) setCfg(saved); });
  }, []);

  const configured = Boolean(cfg.url && cfg.username);

  return (
    <SettingsRow
      icon={<Cloud size={20} strokeWidth={2} />}
      title={
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate">WebDAV 数据同步</span>
          <StatusChip tone={configured ? 'ok' : 'muted'}>{configured ? '已配置' : '未配置'}</StatusChip>
        </span>
      }
      description={configured ? `${getWebDavHostLabel(cfg)} · ${cfg.directory || '/Lawver/'}` : '备份到自己的 WebDAV 云盘'}
      trailing={<ChevronRight size={18} strokeWidth={2} className="text-[var(--fg-4)]" />}
      onClick={onOpen}
    />
  );
};

/* ── 非 LLM provider 配置 ──────────────────────────────────────────────── */

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
  llm: 'OpenAI 兼容聊天模型，主聊天、标题生成和代理流程都通过这里。',
  deli: '案例检索和类案匹配。',
  searxng: '自托管联网检索。',
  qcc: '企业画像、工商登记和联系方式查询。',
  embedding: '文本转向量，用于 RAG 召回。',
};

const PROVIDER_FIELDS: Record<string, { key: string; label: string; placeholder?: string; hint?: string }[]> = {
  llm: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.openai.com/v1' },
    { key: 'model', label: '模型', placeholder: 'gpt-4o / qwen-plus' },
  ],
  deli: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://openapi.delilegal.com/...' },
  ],
  searxng: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://searx.example.com' },
    { key: 'language', label: '语言', placeholder: 'all / zh-CN' },
    { key: 'safe_search', label: '安全搜索', placeholder: '0 / 1 / 2' },
    { key: 'engines', label: '搜索引擎', placeholder: 'bing,duckduckgo' },
    { key: 'categories', label: '分类', placeholder: 'general / news' },
  ],
  qcc: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://agent.qcc.com/mcp/company/stream' },
  ],
  embedding: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.siliconflow.cn/v1' },
    { key: 'model', label: '模型', placeholder: 'Qwen/Qwen3-Embedding-8B' },
  ],
};

const PROVIDER_SECRETS: Record<string, { key: string; label: string; placeholder?: string }[]> = {
  llm: [{ key: 'api_key', label: 'API Key', placeholder: 'sk-...' }],
  deli: [
    { key: 'appid', label: 'App ID' },
    { key: 'secret', label: 'Secret' },
  ],
  searxng: [
    { key: 'cf_client_id', label: 'CF Client ID', placeholder: '可选' },
    { key: 'cf_client_secret', label: 'CF Client Secret', placeholder: '可选' },
  ],
  qcc: [{ key: 'access_token', label: 'Access Token' }],
  embedding: [{ key: 'api_key', label: 'API Key' }],
};

const PROVIDER_ORDER = ['deli', 'searxng', 'qcc', 'embedding'];

const ProviderSubPage: React.FC<{ providerKey: string }> = ({ providerKey }) => {
  const { showAlert, showConfirm } = useAppDialog();
  const reportEdit = useSettingsEdit();
  const [feedback, setFeedback] = useState('');
  const [savedProvider, setSavedProvider] = useState('');
  const label = PROVIDER_LABELS[providerKey] || providerKey;
  const fields = PROVIDER_FIELDS[providerKey] || [];
  const secrets = PROVIDER_SECRETS[providerKey] || [];
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [userRole, setUserRole] = useState<string | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const loadProviderPage = async () => {
      try {
        const auth = await verifyAuth();
        const role = auth?.role || 'user';
        if (cancelled) return;
        setUserRole(role);
        if (role !== 'sudo') return;

        const [nextSettings, nextStatuses] = await Promise.all([
          getSettings().catch(() => null),
          getProviderStatus().catch(() => [] as ProviderStatus[]),
        ]);
        if (cancelled) return;
        setSettings(nextSettings);
        setSavedProvider(JSON.stringify(nextSettings?.providers?.[providerKey] || {}));
        setStatuses(nextStatuses);
      } catch (error) {
        if (!cancelled) {
          setUserRole('user');
          setLoadError((error as Error).message);
        }
      }
    };

    loadProviderPage();
    return () => { cancelled = true; };
  }, [providerKey]);

  useEffect(() => {
    reportEdit(providerKey, Boolean(savedProvider && JSON.stringify(settings?.providers?.[providerKey] || {}) !== savedProvider) || Object.values(secretDrafts).some(Boolean));
  }, [settings, secretDrafts, savedProvider, providerKey, reportEdit]);
  if (userRole === null) {
    return <CenteredSpinner label="正在读取配置…" />;
  }

  if (userRole !== 'sudo') {
    return (
      <Banner tone="danger">
        需要管理员权限才能访问此配置。请联系管理员在后台开启相应能力。
      </Banner>
    );
  }

  const provider = settings?.providers?.[providerKey] || {};
  const status = statuses.find(s => s.provider === providerKey);
  const statusOk = Boolean(status?.ok && provider.enabled);
  const isBusy = busy !== '';

  const updateField = (k: string, v: any) => {
    setSettings(prev => prev ? {
      ...prev,
      providers: { ...prev.providers, [providerKey]: { ...(prev.providers?.[providerKey] || {}), [k]: v } },
    } : prev);
  };

  const saveSettings = async () => {
    if (!settings) return;
    setBusy('save');
    try {
      const result = await updateSettings({ providers: { [providerKey]: settings.providers[providerKey] } });
      setSettings(result);
      setSavedProvider(JSON.stringify(result.providers?.[providerKey] || {}));
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(`${label} 的非敏感配置已保存。`);
    } catch (error) {
      await showAlert({ title: '保存失败', message: (error as Error).message || '保存配置时发生未知错误。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const saveSecrets = async () => {
    const entries = secrets.map(s => ({ ...s, value: (secretDrafts[s.key] || '').trim() })).filter(s => s.value);
    if (!entries.length) return;
    setBusy(`${providerKey}.secrets`);
    try {
      await Promise.all(entries.map(e => setSecret(providerKey, e.key, e.value)));
      setSecretDrafts(prev => { const n = { ...prev }; entries.forEach(e => delete n[e.key]); return n; });
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(`${label} 的凭据已更新。`);
    } catch (error) {
      await showAlert({ title: '保存失败', message: (error as Error).message || '保存凭据时发生未知错误。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const clearSecrets = async () => {
    if (!await showConfirm({title:'清除凭据', message:`清除 ${label} 的凭据后，该服务将无法继续认证。`, tone:'danger'})) return;
    setBusy(`${providerKey}.clear`);
    try {
      await clearSecret(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(`${label} 的已保存凭据已清除。`);
    } catch (error) {
      await showAlert({ title: '清除失败', message: (error as Error).message || '清除凭据时发生未知错误。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const testConn = async () => {
    setBusy(`${providerKey}.test`);
    try {
      const result = await testProvider(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(result.message || `${label} 配置完整。`);
    } catch (error) {
      await showAlert({ title: '检测失败', message: (error as Error).message || '连接检测失败。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const Icon = PROVIDER_ICONS[providerKey] || Server;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {feedback && <div role="status"><Banner tone="success">{feedback}</Banner></div>}
      {loadError && <Banner tone="danger">{loadError}</Banner>}

      <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
        <div className="flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
          <div className="flex min-w-0 gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
              <Icon size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="t-title-m">{label}</h2>
                <StatusChip tone={statusOk ? 'ok' : provider.enabled ? 'warn' : 'muted'}>
                  {statusOk ? '已就绪' : provider.enabled ? '已启用，待检测' : '未启用'}
                </StatusChip>
              </div>
              <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">{PROVIDER_DESCS[providerKey]}</p>
            </div>
          </div>
          <label className="flex min-h-11 shrink-0 cursor-pointer items-center gap-2.5 text-[13px] text-[var(--fg-2)]">
            <AnimatedSwitch
              checked={Boolean(provider.enabled)}
              onCheckedChange={checked => updateField('enabled', checked)}
              ariaLabel={`启用 ${label}`}
            />
            启用
          </label>
        </div>
        {status?.message && (
          <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-2.5 sm:px-5">
            <p className="text-[12px] leading-5 text-[var(--fg-3)]">{status.message}</p>
          </div>
        )}
      </section>

      {fields.length > 0 && (
        <SettingsGroup label="端点配置">
          <div className="grid min-w-0 gap-4 p-4 sm:grid-cols-2 sm:p-5">
            {fields.map(field => (
              <SettingsField key={field.key} label={field.label} hint={field.hint}>
                <input
                  className={fieldInputClass}
                  value={String(provider[field.key] || '')}
                  placeholder={field.placeholder}
                  onChange={e => updateField(field.key, e.target.value)}
                  spellCheck={false}
                />
              </SettingsField>
            ))}
          </div>
        </SettingsGroup>
      )}

      {secrets.length > 0 && (
        <SettingsGroup label="凭据" hint="凭据仅保存在服务端，保存后不会回传到前端。">
          <div className="grid min-w-0 gap-4 p-4 sm:grid-cols-2 sm:p-5">
            {secrets.map(s => (
              <SettingsField key={s.key} label={s.label} hint="留空则不覆盖已保存凭据">
                <input
                  className={fieldInputClass}
                  type="password"
                  value={secretDrafts[s.key] || ''}
                  placeholder={s.placeholder}
                  onChange={e => setSecretDrafts(prev => ({ ...prev, [s.key]: e.target.value }))}
                  autoComplete="new-password"
                />
              </SettingsField>
            ))}
          </div>
        </SettingsGroup>
      )}

      <div className="flex min-w-0 flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={saveSecrets}
          disabled={isBusy || secrets.length === 0}
          className="md3-btn-tonal lawver-pressable text-sm disabled:opacity-50"
        >
          {busy === `${providerKey}.secrets` ? <Loader2 size={15} className="animate-spin" /> : <KeyRound size={15} strokeWidth={2} />}
          保存凭据
        </button>
        <button
          type="button"
          onClick={testConn}
          disabled={isBusy}
          className="md3-btn-tonal lawver-pressable text-sm disabled:opacity-50"
        >
          {busy === `${providerKey}.test` ? <Loader2 size={15} className="animate-spin" /> : <PlugZap size={15} strokeWidth={2} />}
          测试连接
        </button>
        <button
          type="button"
          onClick={clearSecrets}
          disabled={isBusy || secrets.length === 0}
          className="md3-btn-text lawver-pressable text-sm !text-[var(--color-danger-500)] disabled:opacity-50"
        >
          {busy === `${providerKey}.clear` ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} strokeWidth={2} />}
          清除凭据
        </button>
        <button
          type="button"
          onClick={saveSettings}
          disabled={busy === 'save'}
          className="md3-btn-filled lawver-pressable text-sm disabled:opacity-50"
        >
          {busy === 'save' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2.4} />}
          保存配置
        </button>
      </div>
    </div>
  );
};

/* ── 帮助 ──────────────────────────────────────────────────────────────── */

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
      icon: Sparkles,
      title: '图片多模态识别',
      description: '点击输入区的图片按钮上传照片、截图或扫描件，模型会直接看图作答，无需先转成文字。',
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
    { icon: Sparkles, label: '图片', hint: '上传图片让模型识图' },
    { icon: Folder, label: 'Workspace', hint: '管理文件' },
    { icon: Settings, label: '设置', hint: '外观、同步与帮助' },
    { icon: CirclePlay, label: '重播', hint: '再次打开动态导览' },
  ];

const HelpSection: React.FC<{ onStartTour: () => void }> = ({ onStartTour }) => (
  <div className="flex min-w-0 flex-col gap-5">
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
      <div className="flex min-w-0 flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="flex min-w-0 gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
            <CirclePlay size={20} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h2 className="t-title-m">动态指引手册</h2>
            <p className="mt-1 text-[13px] leading-5 text-[var(--fg-3)]">
              用分步动画快速复习 Lawver 的主要区域、按钮和常见操作。
            </p>
          </div>
        </div>
        <button type="button" onClick={onStartTour} className="md3-btn-filled lawver-pressable shrink-0 text-sm">
          <CirclePlay size={16} strokeWidth={2} /> 重播动态指引
        </button>
      </div>
    </section>

    <SettingsGroup label="功能地图">
      {HELP_TOPICS.map(topic => {
        const Icon = topic.icon;
        return (
          <SettingsRow
            key={topic.title}
            icon={<Icon size={18} strokeWidth={2} />}
            title={topic.title}
            description={topic.description}
          />
        );
      })}
    </SettingsGroup>

    <SettingsGroup label="常用按钮速查">
      {QUICK_ACTIONS.map(action => {
        const Icon = action.icon;
        return (
          <SettingsRow
            key={action.label}
            dense
            icon={<Icon size={17} strokeWidth={2} />}
            title={action.label}
            description={action.hint}
          />
        );
      })}
    </SettingsGroup>
  </div>
);

/* ── 关于 ──────────────────────────────────────────────────────────────── */

const AboutSection: React.FC = () => (
  <SettingsGroup label="关于">
    <SettingsRow
      icon={<BrandMark className="h-5 w-5 [--brand-logo-ink:var(--accent)]" />}
      title={BUILD_INFO.appName}
      description={BUILD_INFO.description}
    />
    <SettingsRow dense icon={<PackageCheck size={17} strokeWidth={2} />} title="版本" trailing={<span className="font-medium tabular-nums">{BUILD_INFO.version}</span>} />
    <SettingsRow dense icon={<Server size={17} strokeWidth={2} />} title="构建环境" trailing={<span className="font-medium">{BUILD_INFO.environment}</span>} />
    <SettingsRow dense icon={<Clock3 size={17} strokeWidth={2} />} title="构建时间" trailing={<span className="font-mono text-[12px] tabular-nums">{BUILD_INFO.buildTime}</span>} />
    <SettingsRow
      dense
      icon={<Link2 size={17} strokeWidth={2} />}
      title="项目地址"
      trailing={
        <a
          href={BUILD_INFO.projectUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-w-0 max-w-[46vw] items-center gap-1.5 text-[12px] transition-opacity hover:opacity-80 hover:underline sm:max-w-none"
        >
          <span className="truncate font-mono">{BUILD_INFO.projectUrl}</span>
          <ExternalLink size={13} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
        </a>
      }
    />
  </SettingsGroup>
);

/* ── 外观 ──────────────────────────────────────────────────────────────── */

const AppearanceCard: React.FC<{
  mode: ThemeMode;
  colorSource: ColorSource;
  customSeed: string;
  monetStatus: string;
  isMonetAvailableOnPlatform: boolean;
  setMode: (mode: ThemeMode) => void;
  setColorSource: (source: ColorSource) => void;
  setCustomSeed: (seed: string) => void;
  resetColors: () => void;
  refreshMonet: () => void;
  resolvedTheme: string;
}> = ({
  mode,
  colorSource,
  customSeed,
  monetStatus,
  isMonetAvailableOnPlatform,
  setMode,
  setColorSource,
  setCustomSeed,
  resetColors,
  refreshMonet,
  resolvedTheme,
}) => {
  const [seedDraft, setSeedDraft] = useState(customSeed);
  const seedValid = isHexColor(seedDraft);

  useEffect(() => {
    setSeedDraft(customSeed);
  }, [customSeed]);

  // 纯字符串选择，比 useMemo 本身还便宜，直接每次渲染计算。
  const monetDescription = (() => {
    if (!isMonetAvailableOnPlatform) return '需 Android 客户端';
    if (monetStatus === 'available') return '跟随系统壁纸';
    if (monetStatus === 'loading') return '正在读取系统色';
    if (monetStatus === 'unavailable') return '此设备不支持';
    if (monetStatus === 'error') return '读取系统色失败';
    return '跟随系统壁纸';
  })();

  const applySeedDraft = () => {
    if (!seedValid) return;
    setCustomSeed(seedDraft);
    setColorSource('custom');
  };

  const sourceButtonClass = (source: ColorSource, disabled = false) => [
    'lawver-pressable flex min-h-[74px] min-w-0 flex-1 flex-col justify-between gap-2 rounded-[var(--radius-md)] border px-3.5 py-3 text-left',
    source === colorSource
      ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--fg-1)] shadow-[0_0_0_1px_var(--accent)]'
      : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-2)] hover:border-[var(--border-default)] hover:bg-[var(--bg-surface-2)]',
    disabled ? 'cursor-not-allowed opacity-60 hover:border-[var(--border-subtle)] hover:bg-[var(--bg-surface)]' : '',
  ].join(' ');

  return (
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
      <div className="flex min-w-0 items-center gap-3 border-b border-[var(--border-subtle)] p-4 sm:p-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
          <Palette size={20} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="t-title-m">外观与配色</h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
            当前 {resolvedTheme === 'dark' ? '深色' : '浅色'} · {COLOR_SOURCE_LABEL[colorSource]}
          </p>
        </div>
        <span
          className="hidden h-9 w-9 shrink-0 rounded-full border border-[var(--border-default)] shadow-[var(--shadow-1)] sm:block"
          style={{ backgroundColor: 'var(--accent)' }}
          aria-hidden="true"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-5 p-4 sm:p-5">
        <div className="min-w-0">
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">显示模式</p>
          <div className="grid grid-cols-3 gap-2 rounded-[var(--radius-md)] bg-[var(--bg-inset)] p-1.5">
            {MODE_OPTIONS.map(option => {
              const Icon = option.icon;
              const active = mode === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMode(option.value)}
                  aria-pressed={active}
                  className={`lawver-pressable flex h-11 items-center justify-center gap-2 rounded-[var(--radius-sm)] text-[13px] font-medium transition-colors ${active
                    ? 'bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)]'
                    : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'
                    }`}
                >
                  <Icon size={16} strokeWidth={2} />
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0">
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">配色来源</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <button type="button" onClick={resetColors} className={sourceButtonClass('default')} aria-pressed={colorSource === 'default'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">默认</span>
                {colorSource === 'default' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">Lawver 司法蓝</span>
            </button>

            <button type="button" onClick={() => setColorSource('custom')} className={sourceButtonClass('custom')} aria-pressed={colorSource === 'custom'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">自定义</span>
                {colorSource === 'custom' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">用种子色生成色板</span>
            </button>

            <button
              type="button"
              onClick={() => {
                if (!isMonetAvailableOnPlatform) return;
                setColorSource('monet');
                refreshMonet();
              }}
              className={sourceButtonClass('monet', !isMonetAvailableOnPlatform)}
              disabled={!isMonetAvailableOnPlatform}
              aria-pressed={colorSource === 'monet'}
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-[13px] font-medium">
                  <Smartphone size={14} strokeWidth={2} />
                  Material You
                </span>
                {colorSource === 'monet' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">{monetDescription}</span>
            </button>
          </div>
        </div>

        {colorSource === 'custom' && (
          <div className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3.5">
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
              <label className="flex shrink-0 items-center gap-3">
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
                  className={`h-11 w-32 rounded-[var(--radius-md)] border bg-[var(--bg-surface)] px-3 font-mono text-sm tabular-nums outline-none transition-colors ${seedValid ? 'border-[var(--border-default)] focus:border-[var(--accent)]' : 'border-[var(--color-danger-500)]'
                    }`}
                  aria-label="十六进制颜色"
                  aria-invalid={!seedValid}
                />
              </label>
              <div className="flex min-w-0 flex-wrap gap-2">
                {COLOR_PRESETS.map(color => (
                  <button
                    key={color}
                    type="button"
                    onClick={() => {
                      setSeedDraft(color);
                      setCustomSeed(color);
                    }}
                    className={`lawver-pressable h-10 w-10 shrink-0 rounded-full border shadow-[var(--shadow-1)] transition-transform hover:scale-105 ${seedDraft.toLowerCase() === color.toLowerCase()
                      ? 'border-[var(--fg-1)] ring-2 ring-[var(--accent)]'
                      : 'border-[var(--border-default)]'
                      }`}
                    style={{ backgroundColor: color }}
                    aria-label={`选择 ${color}`}
                    title={color}
                  />
                ))}
                <button
                  type="button"
                  onClick={() => {
                    setSeedDraft(DEFAULT_SEED);
                    setCustomSeed(DEFAULT_SEED);
                  }}
                  className="md3-btn-text lawver-pressable !min-h-10 shrink-0 !px-3 !text-[12px]"
                >
                  <RotateCcw size={14} strokeWidth={2} />
                  重置
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
};

/* ── 主设置页 ──────────────────────────────────────────────────────────── */

export const SettingsPage: React.FC<{onClose?: () => void}> = ({onClose}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const {showConfirm, showAlert} = useAppDialog();
  const theme = useThemeContext();
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const closing = useRef(false);
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('user');
  const [resumeEnabled, setResumeEnabledState] = useState(false);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const reportEdit = useCallback((key: string, value: boolean) => setDirty(old => old[key] === value ? old : {...old, [key]:value}), []);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const path = location.pathname.replace(/\/+$/, '');
  const provider = path.match(/^\/settings\/providers\/(.+)$/)?.[1];
  const category = provider === 'llm' ? 'models' : provider ? 'providers' : path === '/settings/webdav' ? 'data' : path.split('/')[2] || 'appearance';
  const pane = provider && provider !== 'llm' ? `provider:${provider}` : path === '/settings/webdav' ? 'webdav' : category;
  const reduceMotion = useReducedMotion();
  const [visited, setVisited] = useState<string[]>([pane]);
  useEffect(() => {setVisited(old => old.includes(pane) ? old : [...old, pane]);}, [pane]);
  const categories = [
    {id:'appearance', label:'外观', icon:Palette, hint:'主题、配色与显示'},
    ...(role === 'sudo' ? [{id:'models', label:'模型', icon:Sparkles, hint:'模型档案、API 与切换'}, {id:'providers', label:'服务连接', icon:PlugZap, hint:'法律检索、企业信息与嵌入'}] : []),
    {id:'extensions', label:'技能与插件', icon:PlugZap, hint:'技能指令与 MCP 插件'},
    {id:'data', label:'数据', icon:Cloud, hint:'备份、恢复与断线续传'},
    {id:'help', label:'帮助', icon:BookOpen, hint:'功能说明与使用指引'},
    {id:'about', label:'关于', icon:Info, hint:'版本与项目地址'},
  ];
  const active = categories.find(c => c.id === category) || categories[0];
  useEffect(() => {
    dialog.current?.querySelector('[aria-current="page"]')?.scrollIntoView({block:'nearest', inline:'nearest'});
  }, [category, role]);
  const close = useCallback(async () => {
    if(closing.current) return false;
    closing.current = true;
    try {
      if(Object.values(dirtyRef.current).some(Boolean) && !await showConfirm({title:'放弃未保存的配置？', message:'尚未保存的配置和凭据会被丢弃。已保存的设置不受影响。', confirmLabel:'放弃并关闭', cancelLabel:'继续编辑', tone:'warning'})) return false;
      if(onClose) onClose(); else navigate('/', {replace:true});
      return true;
    } finally {closing.current = false;}
  }, [onClose, navigate, showConfirm]);
  const closeRef = useRef(close); closeRef.current = close;
  useBackButton(() => {void closeRef.current(); return true;});
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const root = document.querySelector('[data-settings-background]') as HTMLElement | null;
    if(root) root.inert = true;
    const beforeUnload = (e: BeforeUnloadEvent) => {if(Object.values(dirtyRef.current).some(Boolean)) {e.preventDefault(); e.returnValue = '';}};
    window.addEventListener('beforeunload', beforeUnload);
    const keydown = (e: KeyboardEvent) => {
      // Existing confirmation dialogs own focus and Escape while they are open.
      if(document.querySelector('[role="alertdialog"]') || document.querySelector('[role="dialog"]:not(.settings-dialog)')) return;
      if(e.key === 'Escape') {e.preventDefault(); void closeRef.current();}
      if(e.key === 'Tab' && dialog.current) {
        const items = Array.from(dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')).filter(el => el.getClientRects().length > 0);
        const first=items[0], last=items[items.length-1];
        if(e.shiftKey && document.activeElement === first) {e.preventDefault(); last?.focus();}
        else if(!e.shiftKey && document.activeElement === last) {e.preventDefault(); first?.focus();}
      }
    };
    document.addEventListener('keydown', keydown);
    return () => {document.removeEventListener('keydown', keydown); window.removeEventListener('beforeunload', beforeUnload); if(root) root.inert=false; previous?.focus();};
  }, []);
  useEffect(() => {
    getResumeEnabled().then(setResumeEnabledState).catch(() => {});
    verifyAuth().then(auth => setRole(auth?.role || 'user')).catch(() => {});
  }, []);
  const select = (id: string) => {setQuery(''); navigate(id === 'models' ? '/settings/providers/llm' : `/settings/${id}`, {replace:true});};
  const setResume = async (enabled: boolean) => {
    setResumeBusy(true);
    try {await setResumeEnabled(enabled); setResumeEnabledState(enabled); notifyResumeEnabledChanged(enabled);}
    catch(e) {void showAlert({title:'保存失败',message:(e as Error).message,tone:'danger'});}
    finally {setResumeBusy(false);}
  };
  const renderPane = (key: string) => {
    if(key === 'extensions') return <SettingsExtensions/>;
    if(key === 'appearance') return <><p className="settings-hint">外观调整即时生效，并保存在当前设备。</p><AppearanceCard {...theme} /></>;
    if(key === 'models') return role === 'sudo' ? <><p className="settings-hint">保存模型档案后，可选择何时切换使用。服务端配置会影响使用该服务的账号。</p><LlmProfileManager /></> : <Banner>此配置由服务管理员管理。</Banner>;
    if(key.startsWith('provider:')) return <><button className="settings-back" onClick={() => select('providers')}><ArrowLeft size={16}/>全部服务</button><ProviderSubPage providerKey={key.slice(9)} /></>;
    if(key === 'providers') return <><p className="settings-hint">管理法律与检索服务。配置、凭据保存与连接测试分别操作。</p><SettingsGroup>{PROVIDER_ORDER.map(id => {const Icon=PROVIDER_ICONS[id] || Server; return <SettingsRow key={id} icon={<Icon size={18}/>} title={PROVIDER_LABELS[id]} description={PROVIDER_DESCS[id]} trailing={<ChevronRight size={16}/>} onClick={() => navigate(`/settings/providers/${id}`,{replace:true})}/>;})}</SettingsGroup></>;
    if(key === 'data') return <><p className="settings-hint">WebDAV 用于本地旧资料备份，不是云端工作台的同步来源。项目云端备份仍可在工作台管理中操作。</p><SettingsGroup label="备份与恢复"><WebDavEntry onOpen={() => navigate('/settings/webdav',{replace:true})}/></SettingsGroup><SettingsGroup label="任务恢复"><SettingsRow title="断线续传" description="仅适用于旧版会话：临时缓存最多保留 45 分钟。云端工作台通过任务事件恢复。" trailing={<AnimatedSwitch checked={resumeEnabled} onCheckedChange={setResume} disabled={resumeBusy} ariaLabel="切换断线续传"/>}/></SettingsGroup></>;
    if(key === 'webdav') return <><button className="settings-back" onClick={() => select('data')}><ArrowLeft size={16}/>数据设置</button><p className="settings-hint">连接信息保存在当前设备，修改后自动保存。</p><WebDavSection/></>;
    if(key === 'help') return <HelpSection onStartTour={() => {void closeRef.current().then(closed => {if(closed) requestGuidedTour();});}}/>;
    if(key === 'about') return <AboutSection/>;
    return <Banner>未找到此设置，请从左侧选择分类。</Banner>;
  };
  return <SettingsEditContext.Provider value={reportEdit}>
    <motion.div initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduceMotion?0:.16}} className="settings-overlay" onMouseDown={e => {if(e.target === e.currentTarget) void close();}}>
      <motion.section initial={{scale:reduceMotion?1:.98,y:reduceMotion?0:8}} animate={{scale:1,y:0}} exit={{scale:reduceMotion?1:.99,y:reduceMotion?0:4}} transition={{duration:reduceMotion?0:.2,ease:[.2,.8,.2,1]}} className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title" ref={dialog}>
        <header className="settings-header"><h1 id="settings-title">设置</h1><button ref={closeButton} className="settings-close" aria-label="关闭设置" onClick={() => void close()}><X size={20}/></button></header>
        <aside className="settings-navigation"><label className="settings-search"><Search size={16}/><input aria-label="搜索设置分类" placeholder="搜索设置" value={query} onChange={e => setQuery(e.target.value)}/></label><nav aria-label="设置分类">{categories.filter(c => (c.label+c.hint).includes(query)).map(c => <button key={c.id} aria-current={category === c.id ? 'page' : undefined} onClick={() => select(c.id)}><c.icon size={18}/><span>{c.label}</span></button>)}{!categories.some(c => (c.label+c.hint).includes(query)) && <p className="settings-hint">没有匹配的分类</p>}</nav></aside>
        <main className="settings-content"><header className="settings-section-heading"><h2>{active.label}</h2><p>{active.hint}</p>{Object.values(dirty).some(Boolean) && <span className="settings-unsaved" role="status">有未保存的配置</span>}</header>{Array.from(new Set([...visited,pane])).map(key => <div key={key} hidden={key !== pane} className="settings-pane">{renderPane(key)}</div>)}</main>
      </motion.section>
    </motion.div>
  </SettingsEditContext.Provider>;
};
