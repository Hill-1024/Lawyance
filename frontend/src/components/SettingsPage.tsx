/*
 * 模块描述：应用设置页，集中管理外观、配色、数据同步、能力配置与帮助入口。
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
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
import { LOCALE_LABELS, LOCALES, type MessageKey } from '../locales';
import { useLocale, useTranslation } from '../contexts/LocaleContext';
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
import { useAppBack } from '../hooks/useAppBack';
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
  labelKey: MessageKey;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
    { value: 'light', labelKey: 'settings.appearance.mode.light', icon: Sun },
    { value: 'system', labelKey: 'settings.appearance.mode.system', icon: Monitor },
    { value: 'dark', labelKey: 'settings.appearance.mode.dark', icon: Moon },
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

const COLOR_SOURCE_LABEL: Record<ColorSource, MessageKey> = {
  default: 'settings.appearance.source.defaultLabel',
  custom: 'settings.appearance.source.customLabel',
  monet: 'settings.appearance.source.monetLabel',
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
  const t = useTranslation();
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
          <span className="truncate">{t('settings.webdav.entryTitle')}</span>
          <StatusChip tone={configured ? 'ok' : 'muted'}>
            {configured ? t('settings.webdav.configured') : t('settings.webdav.unconfigured')}
          </StatusChip>
        </span>
      }
      description={configured
        ? `${getWebDavHostLabel(cfg)} · ${cfg.directory || '/Lawver/'}`
        : t('settings.webdav.entryDescription')}
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

const PROVIDER_LABELS: Record<string, MessageKey> = {
  llm: 'settings.provider.llm.label',
  deli: 'settings.provider.deli.label',
  searxng: 'settings.provider.searxng.label',
  qcc: 'settings.provider.qcc.label',
  embedding: 'settings.provider.embedding.label',
};

const PROVIDER_DESCS: Record<string, MessageKey> = {
  llm: 'settings.provider.llm.desc',
  deli: 'settings.provider.deli.desc',
  searxng: 'settings.provider.searxng.desc',
  qcc: 'settings.provider.qcc.desc',
  embedding: 'settings.provider.embedding.desc',
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
  const t = useTranslation();
  const { showAlert } = useAppDialog();
  const label = PROVIDER_LABELS[providerKey] ? t(PROVIDER_LABELS[providerKey]) : providerKey;
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
      const result = await updateSettings({ providers: settings.providers });
      setSettings(result);
      setStatuses(await getProviderStatus().catch(() => []));
      await showAlert({ title: '保存成功', message: `${label} 的非敏感配置已保存。`, tone: 'success' });
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
      await showAlert({ title: '保存成功', message: `${label} 的凭据已更新。`, tone: 'success' });
    } catch (error) {
      await showAlert({ title: '保存失败', message: (error as Error).message || '保存凭据时发生未知错误。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const clearSecrets = async () => {
    setBusy(`${providerKey}.clear`);
    try {
      await clearSecret(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      await showAlert({ title: '清除成功', message: `${label} 的已保存凭据已清除。`, tone: 'success' });
    } catch (error) {
      await showAlert({ title: '清除失败', message: (error as Error).message || '清除凭据时发生未知错误。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const testConn = async () => {
    setBusy(`${providerKey}.test`);
    try {
      const result = await testProvider(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      await showAlert({ title: '连接检测通过', message: result.message || `${label} 配置完整。`, tone: 'success' });
    } catch (error) {
      await showAlert({ title: '检测失败', message: (error as Error).message || '连接检测失败。', tone: 'danger' });
    } finally { setBusy(''); }
  };

  const Icon = PROVIDER_ICONS[providerKey] || Server;

  return (
    <div className="flex min-w-0 flex-col gap-5">
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
              <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">{PROVIDER_DESCS[providerKey] && t(PROVIDER_DESCS[providerKey])}</p>
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

const AboutSection: React.FC = () => {
  const t = useTranslation();
  return (
    <SettingsGroup label={t('settings.about.group')}>
      <SettingsRow
        icon={<BrandMark className="h-5 w-5 [--brand-logo-ink:var(--accent)]" />}
        title={BUILD_INFO.appName}
        description={BUILD_INFO.description}
      />
      <SettingsRow dense icon={<PackageCheck size={17} strokeWidth={2} />} title={t('settings.about.version')} trailing={<span className="font-medium tabular-nums">{BUILD_INFO.version}</span>} />
      <SettingsRow dense icon={<Server size={17} strokeWidth={2} />} title={t('settings.about.environment')} trailing={<span className="font-medium">{BUILD_INFO.environment}</span>} />
      <SettingsRow dense icon={<Clock3 size={17} strokeWidth={2} />} title={t('settings.about.buildTime')} trailing={<span className="font-mono text-[12px] tabular-nums">{BUILD_INFO.buildTime}</span>} />
      <SettingsRow
        dense
        icon={<Link2 size={17} strokeWidth={2} />}
        title={t('settings.about.projectUrl')}
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
};

/* ── 语言 ──────────────────────────────────────────────────────────────── */

const LanguageSection: React.FC = () => {
  const t = useTranslation();
  const { locale, setLocale } = useLocale();

  return (
    <SettingsGroup label={t('settings.language.group')} hint={t('settings.language.hint')}>
      <div className="flex min-w-0 flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <span className="min-w-0">
          <span className="block text-[14px] font-medium leading-5 text-[var(--fg-1)]">
            {t('settings.language.title')}
          </span>
          <span className="mt-0.5 block text-[12px] leading-5 text-[var(--fg-3)]">
            {t('settings.language.description')}
          </span>
        </span>
        {/* 选项用本语言自称，用户在任何当前语言下都能认出自己的母语。 */}
        <div className="grid shrink-0 grid-cols-2 gap-2 rounded-[var(--radius-md)] bg-[var(--bg-inset)] p-1.5">
          {LOCALES.map(value => {
            const active = locale === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setLocale(value)}
                aria-pressed={active}
                lang={value}
                className={`lawver-pressable flex h-10 items-center justify-center rounded-[var(--radius-sm)] px-3 text-[13px] font-medium transition-colors sm:min-w-[96px] ${active
                  ? 'bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)]'
                  : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'
                  }`}
              >
                {LOCALE_LABELS[value]}
              </button>
            );
          })}
        </div>
      </div>
    </SettingsGroup>
  );
};

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
  const t = useTranslation();
  const [seedDraft, setSeedDraft] = useState(customSeed);
  const seedValid = isHexColor(seedDraft);

  useEffect(() => {
    setSeedDraft(customSeed);
  }, [customSeed]);

  // 纯字符串选择，比 useMemo 本身还便宜，直接每次渲染计算。
  const monetDescription = (() => {
    if (!isMonetAvailableOnPlatform) return t('settings.appearance.monet.platform');
    if (monetStatus === 'available') return t('settings.appearance.monet.followWallpaper');
    if (monetStatus === 'loading') return t('settings.appearance.monet.loading');
    if (monetStatus === 'unavailable') return t('settings.appearance.monet.unsupported');
    if (monetStatus === 'error') return t('settings.appearance.monet.error');
    return t('settings.appearance.monet.followWallpaper');
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
          <h2 className="t-title-m">{t('settings.appearance.title')}</h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
            {t('settings.appearance.current', {
              theme: resolvedTheme === 'dark' ? t('settings.appearance.mode.dark') : t('settings.appearance.mode.light'),
              colorSource: t(COLOR_SOURCE_LABEL[colorSource]),
            })}
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
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">{t('settings.appearance.displayMode')}</p>
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
                  {t(option.labelKey)}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0">
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">{t('settings.appearance.colorSource')}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <button type="button" onClick={resetColors} className={sourceButtonClass('default')} aria-pressed={colorSource === 'default'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{t('settings.appearance.source.default')}</span>
                {colorSource === 'default' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">{t('settings.appearance.source.defaultHint')}</span>
            </button>

            <button type="button" onClick={() => setColorSource('custom')} className={sourceButtonClass('custom')} aria-pressed={colorSource === 'custom'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{t('settings.appearance.source.custom')}</span>
                {colorSource === 'custom' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">{t('settings.appearance.source.customHint')}</span>
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
                  aria-label={t('settings.appearance.seedLabel')}
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
                  aria-label={t('settings.appearance.hexLabel')}
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
                    aria-label={t('settings.appearance.selectColor', { color })}
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
                  {t('settings.appearance.reset')}
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

export const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const t = useTranslation();
  // 返回一律走退栈，避免用 navigate(父级) 压栈导致返回错乱。
  const goBack = useAppBack();
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
  const [resumeEnabled, setResumeEnabledState] = useState(false);
  const [userRole, setUserRole] = useState('user');
  const [providerStatuses, setProviderStatuses] = useState<ProviderStatus[]>([]);

  const normalizedPath = location.pathname.replace(/\/+$/, '');
  const providerMatch = normalizedPath.match(/^\/settings\/providers\/(.+)$/);
  const isProviderRoute = !!providerMatch;
  const providerKey = providerMatch ? providerMatch[1] : '';
  const isWebDavRoute = normalizedPath === '/settings/webdav';
  const isHelpRoute = normalizedPath === '/settings/help';
  const isLlmRoute = isProviderRoute && providerKey === 'llm';

  const pageTitle = isWebDavRoute
    ? t('settings.webdav.pageTitle')
    : isHelpRoute
      ? t('settings.help.pageTitle')
      : isProviderRoute
        ? (PROVIDER_LABELS[providerKey] ? t(PROVIDER_LABELS[providerKey]) : providerKey)
        : t('settings.title');
  const pageSubtitle = isWebDavRoute
    ? t('settings.webdav.pageSubtitle')
    : isHelpRoute
      ? t('settings.help.pageSubtitle')
      : isLlmRoute
        ? t('settings.capability.llmSubtitle')
        : isProviderRoute
          ? t('settings.capability.providerSubtitle')
          : t('settings.subtitle');

  const handleBack = () => {
    if (isProviderRoute || isWebDavRoute || isHelpRoute) {
      goBack('/settings');
      return;
    }
    goBack('/');
  };

  useEffect(() => {
    getResumeEnabled().then(setResumeEnabledState).catch(() => setResumeEnabledState(false));
    verifyAuth()
      .then(auth => {
        const role = auth?.role || 'user';
        setUserRole(role);
        if (role === 'sudo') {
          return getProviderStatus().then(setProviderStatuses).catch(() => {});
        }
        return undefined;
      })
      .catch(() => {});
  }, []);

  const updateResumeEnabled = async (enabled: boolean) => {
    setResumeEnabledState(enabled);
    await setResumeEnabled(enabled);
    notifyResumeEnabledChanged(enabled);
  };

  // 每行服务都要按 key 取状态（LLM 一行取三次），建索引后是 O(1) 而不是每行线性扫描。
  const providerStatusByKey = useMemo(
    () => new Map(providerStatuses.map(status => [status.provider, status])),
    [providerStatuses]
  );
  const providerStatusOf = (key: string) => providerStatusByKey.get(key);

  const statusLabel = isWebDavRoute
    ? t('settings.webdav.statusLabel')
    : isHelpRoute
      ? t('settings.help.statusLabel')
      : t('settings.appearance.current', {
        theme: resolvedTheme === 'dark' ? t('settings.appearance.mode.dark') : t('settings.appearance.mode.light'),
        colorSource: t(COLOR_SOURCE_LABEL[colorSource]),
      });
  const isIndexRoute = !isWebDavRoute && !isHelpRoute && !isProviderRoute;

  return (
    <div className="flex min-h-[100dvh] w-full max-w-full flex-col overflow-x-hidden bg-[var(--bg-app)] text-[var(--fg-1)]">
      <header className="lawver-topbar sticky top-0 z-30 flex w-full max-w-full shrink-0 items-center justify-between gap-3 overflow-hidden border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-3 pb-2 pt-[calc(0.625rem+var(--safe-top))] sm:px-5 sm:pb-3 sm:pt-[calc(0.75rem+var(--safe-top))]">
        <div className="flex min-w-0 items-center gap-2">
          <HoverInfo label={isIndexRoute ? t('common.back') : t('settings.backToSettings')} placement="bottom">
            <button
              onClick={handleBack}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              aria-label={t('common.back')}
            >
              <ArrowLeft size={20} strokeWidth={2} />
            </button>
          </HoverInfo>
          <div className="min-w-0">
            {!isIndexRoute && (
              <nav aria-label={t('settings.breadcrumb')} className="mb-0.5 flex items-center gap-1 text-[11px] leading-4 text-[var(--fg-4)]">
                <span>{t('settings.title')}</span>
                <ChevronRight size={11} strokeWidth={2} />
                <span className="text-[var(--fg-3)]">{pageTitle}</span>
              </nav>
            )}
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
        <div className={`mx-auto flex min-w-0 w-full flex-col gap-6 ${isWebDavRoute ? 'max-w-2xl' : 'max-w-3xl'}`}>
          {isWebDavRoute ? (
            <WebDavSection />
          ) : isHelpRoute ? (
            <HelpSection onStartTour={requestGuidedTour} />
          ) : isLlmRoute ? (
            <LlmProfileManager />
          ) : isProviderRoute ? (
            <ProviderSubPage providerKey={providerKey} />
          ) : (
            <>
              <AppearanceCard
                mode={mode}
                colorSource={colorSource}
                customSeed={customSeed}
                monetStatus={monetStatus}
                isMonetAvailableOnPlatform={isMonetAvailableOnPlatform}
                setMode={setMode}
                setColorSource={setColorSource}
                setCustomSeed={setCustomSeed}
                resetColors={resetColors}
                refreshMonet={refreshMonet}
                resolvedTheme={resolvedTheme}
              />

              <LanguageSection />

              <SettingsGroup label={t('settings.data.group')} hint={t('settings.data.hint')}>
                <WebDavEntry onOpen={() => navigate('/settings/webdav')} />
                <SettingsRow
                  icon={<RotateCcw size={20} strokeWidth={2} />}
                  title={t('settings.data.resume.title')}
                  description={t('settings.data.resume.description')}
                  trailing={
                    <AnimatedSwitch
                      checked={resumeEnabled}
                      onCheckedChange={updateResumeEnabled}
                      ariaLabel={t('settings.data.resume.toggle')}
                    />
                  }
                />
              </SettingsGroup>

              {userRole === 'sudo' && (
                <SettingsGroup
                  label={t('settings.capability.group')}
                  hint={t('settings.capability.hint')}
                >
                  <SettingsRow
                    icon={<Sparkles size={20} strokeWidth={2} />}
                    title={
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate">{t('settings.capability.llm')}</span>
                        <StatusChip
                          tone={providerStatusOf('llm')?.ok ? 'ok' : providerStatusOf('llm')?.configured ? 'warn' : 'muted'}
                        >
                          {providerStatusOf('llm')?.ok
                            ? t('settings.status.ready')
                            : providerStatusOf('llm')?.configured
                              ? t('settings.status.pending')
                              : t('settings.status.unconfigured')}
                        </StatusChip>
                      </span>
                    }
                    description={t('settings.capability.llm.description')}
                    trailing={<ChevronRight size={18} strokeWidth={2} className="text-[var(--fg-4)]" />}
                    onClick={() => navigate('/settings/providers/llm')}
                  />
                  {PROVIDER_ORDER.map(key => {
                    const status = providerStatusOf(key);
                    const Icon = PROVIDER_ICONS[key] || Server;
                    return (
                      <SettingsRow
                        key={key}
                        icon={<Icon size={19} strokeWidth={2} />}
                        title={
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate">{t(PROVIDER_LABELS[key])}</span>
                            <StatusChip tone={status?.ok && status?.enabled ? 'ok' : status?.configured ? 'warn' : 'muted'}>
                              {status?.ok && status?.enabled
                                ? t('settings.status.ready')
                                : status?.configured
                                  ? t('settings.status.pending')
                                  : t('settings.status.unconfigured')}
                            </StatusChip>
                          </span>
                        }
                        description={t(PROVIDER_DESCS[key])}
                        trailing={<ChevronRight size={18} strokeWidth={2} className="text-[var(--fg-4)]" />}
                        onClick={() => navigate(`/settings/providers/${key}`)}
                      />
                    );
                  })}
                </SettingsGroup>
              )}

              <SettingsGroup label={t('settings.help.group')}>
                <SettingsRow
                  icon={<BookOpen size={20} strokeWidth={2} />}
                  title={
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate">{t('settings.help.title')}</span>
                      <StatusChip tone="accent">{t('settings.help.badge')}</StatusChip>
                    </span>
                  }
                  description={t('settings.help.description')}
                  trailing={<ChevronRight size={18} strokeWidth={2} className="text-[var(--fg-4)]" />}
                  onClick={() => navigate('/settings/help')}
                />
              </SettingsGroup>

              <AboutSection />
            </>
          )}
        </div>
      </main>
    </div>
  );
};
