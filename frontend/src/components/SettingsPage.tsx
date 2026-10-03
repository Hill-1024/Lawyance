/*
 * 模块描述：应用设置页，集中管理外观、技能与插件、操作快捷键、帮助与关于。
 *
 * 模型、服务连接与数据同步属于运维配置，已迁到后台控制台；
 * 服务连接子页（ProviderSubPage）与相关常量仍从这里导出，供后台「服务配置」复用。
 */

import { motion, useReducedMotion } from 'motion/react';
import React, { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import {
  X,
  Search,
  Info,
  BookOpen,
  Building2,
  Check,
  ChevronRight,
  CirclePlay,
  Clock3,
  ExternalLink,
  Folder,
  Gavel,
  Globe,
  ImagePlus,
  KeyRound,
  Keyboard,
  Link2,
  Loader2,
  MessageSquareText,
  Monitor,
  Moon,
  PackageCheck,
  Palette,
  Paperclip,
  PlugZap,
  RotateCcw,
  Server,
  Settings2,
  Smartphone,
  Sparkles,
  Sun,
  Trash2,
  UserRound,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { DEFAULT_SEED } from '../lib/palette';
import { useThemeContext, type ColorSource, type ThemeMode } from '../contexts/ThemeContext';
import { BUILD_INFO } from '../lib/buildInfo';
import { BrandMark } from './Brand';
import { useAppDialog } from '../contexts/DialogContext';
import { AnimatedSwitch } from './AnimatedSwitch';
import { requestGuidedTour } from '../lib/guided-tour';
import { getBinding, matchKeys, SHORTCUT_IDS } from '../lib/shortcuts';
import { useBackButton } from '../hooks/useBackButton';
import { SettingsEditContext, useSettingsEdit } from './settings/SettingsEditContext';
import './settings/settings-modal.css';
import { SettingsExtensions } from './settings/SettingsExtensions';
import {
  PLAN_BADGES as SharedPLAN_BADGES,
  PLAN_LABEL_KEYS as SharedPLAN_LABEL_KEYS,
  AccountAvatar,
} from './AccountIdentity';
import { SettingsShortcuts, ShortcutCheatSheet } from './settings/SettingsShortcuts';
import {
  avatarUrl,
  changePassword,
  clearSecret,
  fetchAccountProfile,
  fetchMyCredits,
  getProviderStatus,
  getSettings,
  removeAvatar,
  setSecret,
  testProvider,
  updateCustomId,
  updateSettings,
  uploadAvatar,
  verifyAuth,
  type AccountProfile,
  type ProviderStatus,
} from '../services/api';
import {
  Banner,
  CenteredSpinner,
  SettingsField,
  SettingsGroup,
  SettingsRow,
  StatusChip,
  fieldInputClass,
} from './settings/SettingsUI';
import { SelectField } from '../workbench/SelectField';
import { LOCALES, useT, type Locale, type MessageKey } from '../i18n';
import { describeError } from '../lib/errors';

/*
 * 账号：自助修改密码。
 * 此前只有管理员能在后台重置（且不需要旧密码），密码泄露后用户没有任何自助止损手段——
 * 管理员的「无校验重置」因此成了唯一改密通道，反过来说也是个社会工程面。
 * 改密语义：保留当前设备，其他设备的登录立即失效。
 */
/** 头像与订阅徽标的共享实现移到 components/AccountIdentity（工作台侧栏同用）。 */
const PLAN_BADGES = SharedPLAN_BADGES;
const PLAN_LABELS_I18N = SharedPLAN_LABEL_KEYS as Record<string, MessageKey>;


/** 个人资料卡：头像 + 自定义 ID（对外句柄）+ 只读 UID（稳定标识）。 */
const ProfileCard: React.FC = () => {
  const { t } = useT();
  const { showAlert } = useAppDialog();
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  const [handle, setHandle] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'id' | 'avatar' | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAccountProfile().then((data) => {
      if (cancelled || !data) return;
      setProfile(data);
      setHandle(data.custom_id ?? '');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const applyProfile = (next: AccountProfile) => {
    setProfile(next);
    setHandle(next.custom_id ?? '');
    setError('');
    // 侧栏底部的账户 chip 借此即时同步：设置弹窗开着时 URL 停在背景路径，
    // Workbench 感知不到「刚从设置回来」，所以用事件把新资料推过去。
    window.dispatchEvent(new CustomEvent("lawver:profile-updated", { detail: next }));
  };

  const saveHandle = async () => {
    const value = handle.trim().toLowerCase();
    if (value === (profile?.custom_id ?? '')) return;
    setBusy('id');
    try {
      applyProfile(await updateCustomId(value || null));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('settings.profile.saveFailed'));
    } finally {
      setBusy(null);
    }
  };

  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 1024 * 1024) {
      await showAlert({
        title: t('settings.profile.avatarTooLargeTitle'),
        message: t('settings.profile.avatarTooLarge'),
        tone: 'warning',
      });
      return;
    }
    setBusy('avatar');
    try {
      applyProfile(await uploadAvatar(file));
    } catch (e) {
      await showAlert({
        title: t('settings.profile.avatarFailedTitle'),
        message: e instanceof Error ? e.message : t('settings.profile.avatarFailed'),
        tone: 'danger',
      });
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const badge = profile ? PLAN_BADGES[profile.plan] : undefined;
  const handleValue = handle.trim().toLowerCase();

  return (
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
      <div className="flex min-w-0 items-center gap-3 border-b border-[var(--border-subtle)] p-4 sm:p-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
          <UserRound size={20} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="t-title-m">{t('settings.profile.title')}</h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
            {t('settings.profile.hint')}
          </p>
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-5 p-4 sm:p-5">
        {/* 身份行：头像 + 用户名 + 订阅徽标 */}
        <div className="flex min-w-0 items-center gap-4">
          <AccountAvatar profile={profile} size={56} />
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="truncate text-[15px] font-semibold text-[var(--fg-1)]">
                {profile?.username ?? '…'}
              </span>
              {badge && (
                <span
                  className={
                    'inline-flex h-5 items-center rounded-full px-2 text-[11px] font-semibold tracking-wide ' +
                    badge.className
                  }
                >
                  {badge.label}
                </span>
              )}
            </div>
            <p className="mt-0.5 truncate text-[12px] text-[var(--fg-3)]">
              {t(profile ? PLAN_LABELS_I18N[profile.plan] ?? 'settings.profile.planMetered' : 'settings.profile.planMetered')}
            </p>
          </div>
        </div>

        {/* 头像 */}
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className="text-[12px] font-medium text-[var(--fg-3)]">
            {t('settings.profile.avatarLabel')}
          </span>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy === 'avatar'}
              onClick={() => fileInput.current?.click()}
              className="lawver-pressable flex h-9 items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 text-[13px] font-medium text-[var(--fg-1)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy === 'avatar' ? <Loader2 size={14} className="animate-spin" /> : <ImagePlus size={14} strokeWidth={2} />}
              {t('settings.profile.avatarUpload')}
            </button>
            {profile && profile.avatar_version > 0 && (
              <button
                type="button"
                disabled={busy === 'avatar'}
                onClick={async () => {
                  setBusy('avatar');
                  try {
                    applyProfile(await removeAvatar());
                  } finally {
                    setBusy(null);
                  }
                }}
                className="lawver-pressable flex h-9 items-center rounded-[var(--radius-sm)] px-3 text-[13px] font-medium text-[var(--color-danger-500)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {t('settings.profile.avatarRemove')}
              </button>
            )}
            <span className="text-[12px] text-[var(--fg-3)]">{t('settings.profile.avatarHint')}</span>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={(e) => void onPickFile(e.target.files?.[0])}
          />
        </div>

        {/* 自定义 ID */}
        <div className="flex min-w-0 flex-col gap-1.5">
          <label
            htmlFor="profile-custom-id"
            className="text-[12px] font-medium text-[var(--fg-3)]"
          >
            {t('settings.profile.customIdLabel')}
          </label>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <input
              id="profile-custom-id"
              className={fieldInputClass + ' max-w-[240px] font-mono'}
              value={handle}
              placeholder={t('settings.profile.customIdPlaceholder')}
              maxLength={32}
              spellCheck={false}
              autoCapitalize="none"
              onChange={(e) => {
                setHandle(e.target.value);
                setError('');
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void saveHandle();
                }
              }}
            />
            <button
              type="button"
              disabled={busy === 'id' || handleValue === (profile?.custom_id ?? '')}
              onClick={() => void saveHandle()}
              className="lawver-pressable flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 text-[13px] font-medium text-[var(--accent-on)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy === 'id' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
              {t('settings.profile.customIdSave')}
            </button>
          </div>
          {error ? (
            <p className="text-[12px] text-[var(--color-danger-500)]" role="alert">
              {error}
            </p>
          ) : (
            <p className="text-[12px] text-[var(--fg-3)]">{t('settings.profile.customIdHint')}</p>
          )}
        </div>

        {/* 只读 UID：稳定标识，不随自定义 ID 改变 */}
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className="text-[12px] font-medium text-[var(--fg-3)]">
            {t('settings.profile.uidLabel')}
          </span>
          <code className="w-fit max-w-full truncate rounded-[var(--radius-sm)] bg-[var(--bg-inset)] px-2 py-1 font-mono text-[12px] text-[var(--fg-2)]">
            {profile?.uid ?? '…'}
          </code>
          <p className="text-[12px] text-[var(--fg-3)]">{t('settings.profile.uidHint')}</p>
        </div>
      </div>
    </section>
  );
};

const AccountCard: React.FC = () => {
  const { t } = useT();
  const { showAlert } = useAppDialog();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (next.length < 6) {
      await showAlert({ title: t('settings.password.cannotTitle'), message: t('settings.password.tooShort'), tone: 'danger' });
      return;
    }
    if (next !== repeat) {
      await showAlert({ title: t('settings.password.cannotTitle'), message: t('settings.password.mismatch'), tone: 'danger' });
      return;
    }
    setBusy(true);
    try {
      const result = await changePassword(current, next);
      setCurrent('');
      setNext('');
      setRepeat('');
      await showAlert({
        title: t('settings.password.changed'),
        message: result.revoked_sessions
          ? t('settings.password.revokedSome', { count: result.revoked_sessions })
          : t('settings.password.revokedAll'),
        tone: 'success',
      });
    } catch (error) {
      await showAlert({
        title: t('settings.password.failedTitle'),
        message: describeError(error, t('settings.password.failedMessage')),
        tone: 'danger',
      });
    } finally {
      setBusy(false);
    }
  };

  const field = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    autoComplete: string,
  ) => (
    <label className="flex min-w-0 flex-col gap-1.5 text-[12px] font-medium text-[var(--fg-3)]">
      {label}
      <input
        className={fieldInputClass}
        type="password"
        value={value}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );

  return (
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
      <div className="flex min-w-0 items-center gap-3 border-b border-[var(--border-subtle)] p-4 sm:p-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
          <KeyRound size={20} strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="t-title-m">{t("settings.password.title")}</h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
            {t("settings.password.hint")}
          </p>
        </div>
      </div>
      <form className="flex min-w-0 flex-col gap-4 p-4 sm:p-5" onSubmit={submit}>
        {field(t('settings.password.current'), current, setCurrent, 'current-password')}
        {field(t('settings.password.next'), next, setNext, 'new-password')}
        {field(t('settings.password.repeat'), repeat, setRepeat, 'new-password')}
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="submit"
            disabled={busy}
            className="lawver-pressable flex h-10 items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 text-[13px] font-medium text-[var(--accent-on)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2} />}
            {busy ? t('settings.password.saving') : t('settings.password.submit')}
          </button>
          <p className="text-[12px] text-[var(--fg-3)]">{t("settings.password.policy")}</p>
        </div>
      </form>
    </section>
  );
};

// 同样只存键：模块级对象拿不到 t，取文案放在渲染处（含无障碍名）。
const MODE_OPTIONS: Array<{
  value: ThemeMode;
  labelKey: MessageKey;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
    { value: 'light', labelKey: 'settings.appearance.themeLight', icon: Sun },
    { value: 'system', labelKey: 'settings.appearance.themeSystem', icon: Monitor },
    { value: 'dark', labelKey: 'settings.appearance.themeDark', icon: Moon },
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

// 配色来源的显示名走词条：模块级表只能存键，取文案在渲染时做（Material You 是产品名，不翻）。
const COLOR_SOURCE_KEYS: Record<ColorSource, MessageKey> = {
  default: 'settings.appearance.sourceDefaultBrand',
  custom: 'settings.appearance.sourceCustomSeed',
  monet: 'settings.appearance.sourceMonet',
};

const isHexColor = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

/* ── 非 LLM provider 配置 ──────────────────────────────────────────────── */

export const PROVIDER_ICONS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  llm: Sparkles,
  deli: Gavel,
  searxng: Globe,
  qcc: Server,
  embedding: Link2,
};

export const PROVIDER_LABELS: Record<string, MessageKey> = {
  llm: 'settings.provider.llm',
  deli: 'settings.provider.deli',
  searxng: 'settings.provider.searxng',
  qcc: 'settings.provider.qcc',
  embedding: 'settings.provider.embedding',
};

export const PROVIDER_DESCS: Record<string, MessageKey> = {
  llm: 'settings.provider.llmDesc',
  deli: 'settings.provider.deliDesc',
  searxng: 'settings.provider.searxngDesc',
  qcc: 'settings.provider.qccDesc',
  embedding: 'settings.provider.embeddingDesc',
};

const PROVIDER_FIELDS: Record<string, { key: string; labelKey?: MessageKey; label?: string; placeholder?: string; hint?: string }[]> = {
  llm: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.openai.com/v1' },
    { key: 'model', labelKey: 'settings.field.model' as MessageKey, placeholder: 'gpt-4o / qwen-plus' },
  ],
  deli: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://openapi.delilegal.com/...' },
  ],
  searxng: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://searx.example.com' },
    { key: 'language', labelKey: 'settings.field.language' as MessageKey, placeholder: 'all / zh-CN' },
    { key: 'safe_search', labelKey: 'settings.field.safeSearch' as MessageKey, placeholder: '0 / 1 / 2' },
    { key: 'engines', labelKey: 'settings.field.engines' as MessageKey, placeholder: 'bing,duckduckgo' },
    { key: 'categories', labelKey: 'settings.field.categories' as MessageKey, placeholder: 'general / news' },
  ],
  qcc: [
    { key: 'endpoint', label: 'Endpoint', placeholder: 'https://agent.qcc.com/mcp/company/stream' },
  ],
  embedding: [
    { key: 'base_url', label: 'Base URL', placeholder: 'https://api.siliconflow.cn/v1' },
    { key: 'model', labelKey: 'settings.field.model' as MessageKey, placeholder: 'Qwen/Qwen3-Embedding-8B' },
  ],
};

const PROVIDER_SECRETS: Record<string, { key: string; label?: string; labelKey?: MessageKey; placeholder?: string; placeholderKey?: MessageKey }[]> = {
  llm: [{ key: 'api_key', label: 'API Key', placeholder: 'sk-...' }],
  deli: [
    { key: 'appid', label: 'App ID' },
    { key: 'secret', label: 'Secret' },
  ],
  searxng: [
    { key: 'cf_client_id', label: 'CF Client ID', placeholderKey: 'settings.field.optional' },
    { key: 'cf_client_secret', label: 'CF Client Secret', placeholderKey: 'settings.field.optional' },
  ],
  qcc: [{ key: 'access_token', label: 'Access Token' }],
  embedding: [{ key: 'api_key', label: 'API Key' }],
};

export const PROVIDER_ORDER = ['deli', 'searxng', 'qcc', 'embedding'];

/** 服务连接子页：设置页与后台「服务配置」共用；由父级决定返回与布局。 */
export const ProviderSubPage: React.FC<{ providerKey: string }> = ({ providerKey }) => {
  const { t } = useT();
  const { showAlert, showConfirm } = useAppDialog();
  const reportEdit = useSettingsEdit();
  const [feedback, setFeedback] = useState('');
  const [savedProvider, setSavedProvider] = useState('');
  const label = PROVIDER_LABELS[providerKey] ? t(PROVIDER_LABELS[providerKey]) : providerKey;
  const fields = PROVIDER_FIELDS[providerKey] || [];
  const secrets = PROVIDER_SECRETS[providerKey] || [];
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [userRole, setUserRole] = useState<string | null>(null);
  const [loadError, setLoadError] = useState('');
  // 失败提示要用当前语言的兜底文案，但语言变化不应该让整页配置重新拉取（会冲掉未保存的编辑）：
  // 这段读 t 的逻辑放进 effect event，effect 本身只随 providerKey 重跑。
  const reportLoadFailure = useEffectEvent((error: unknown) => {
    setUserRole('user');
    setLoadError(describeError(error, t('settings.loadFailed')));
  });

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
        if (!cancelled) reportLoadFailure(error);
      }
    };

    loadProviderPage();
    return () => { cancelled = true; };
  }, [providerKey]);

  useEffect(() => {
    reportEdit(providerKey, Boolean(savedProvider && JSON.stringify(settings?.providers?.[providerKey] || {}) !== savedProvider) || Object.values(secretDrafts).some(Boolean));
  }, [settings, secretDrafts, savedProvider, providerKey, reportEdit]);
  if (userRole === null) {
    return <CenteredSpinner label={t("settings.loading")} />;
  }

  if (userRole !== 'sudo') {
    return (
      <Banner tone="danger">
        {t("settings.adminRequired")}
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
      setFeedback(t('settings.provider.savedSettings', { label }));
    } catch (error) {
      await showAlert({ title: t('settings.provider.saveFailed'), message: describeError(error, t('settings.provider.saveSettingsFailed')), tone: 'danger' });
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
      setFeedback(t('settings.provider.savedSecrets', { label }));
    } catch (error) {
      await showAlert({ title: t('settings.provider.saveFailed'), message: describeError(error, t('settings.provider.saveSecretsFailed')), tone: 'danger' });
    } finally { setBusy(''); }
  };

  const clearSecrets = async () => {
    if (!await showConfirm({ title: t('settings.provider.clearTitle'), message: t('settings.provider.clearMessage', { label }), tone: 'danger' })) return;
    setBusy(`${providerKey}.clear`);
    try {
      await clearSecret(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(t('settings.provider.cleared', { label }));
    } catch (error) {
      await showAlert({ title: t('settings.provider.clearFailed'), message: describeError(error, t('settings.provider.clearFailedMessage')), tone: 'danger' });
    } finally { setBusy(''); }
  };

  const testConn = async () => {
    setBusy(`${providerKey}.test`);
    try {
      const result = await testProvider(providerKey);
      setStatuses(await getProviderStatus().catch(() => []));
      setFeedback(result.message || t('settings.provider.testOk', { label }));
    } catch (error) {
      await showAlert({ title: t('settings.provider.testFailed'), message: describeError(error, t('settings.provider.testFailedMessage')), tone: 'danger' });
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
                  {statusOk ? t('settings.provider.ready') : provider.enabled ? t('settings.provider.enabledPending') : t('settings.provider.disabled')}
                </StatusChip>
              </div>
              <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">{t(PROVIDER_DESCS[providerKey])}</p>
            </div>
          </div>
          <label className="flex min-h-11 shrink-0 cursor-pointer items-center gap-2.5 text-[13px] text-[var(--fg-2)]">
            <AnimatedSwitch
              checked={Boolean(provider.enabled)}
              onCheckedChange={checked => updateField('enabled', checked)}
              ariaLabel={t("settings.provider.enableLabel", { label })}
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
        <SettingsGroup label={t("settings.provider.endpointGroup")}>
          <div className="grid min-w-0 gap-4 p-4 sm:grid-cols-2 sm:p-5">
            {fields.map(field => (
              <SettingsField key={field.key} label={field.labelKey ? t(field.labelKey) : field.label} hint={field.hint}>
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
        <SettingsGroup label={t("settings.provider.credentialGroup")} hint={t("settings.provider.credentialHint")}>
          <div className="grid min-w-0 gap-4 p-4 sm:grid-cols-2 sm:p-5">
            {secrets.map(s => (
              <SettingsField key={s.key} label={s.labelKey ? t(s.labelKey) : s.label} hint={t("settings.provider.credentialFieldHint")}>
                <input
                  className={fieldInputClass}
                  type="password"
                  value={secretDrafts[s.key] || ''}
                  placeholder={s.placeholderKey ? t(s.placeholderKey) : s.placeholder}
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
          {t("settings.provider.saveSecrets")}
        </button>
        <button
          type="button"
          onClick={testConn}
          disabled={isBusy}
          className="md3-btn-tonal lawver-pressable text-sm disabled:opacity-50"
        >
          {busy === `${providerKey}.test` ? <Loader2 size={15} className="animate-spin" /> : <PlugZap size={15} strokeWidth={2} />}
          {t("settings.provider.testConnection")}
        </button>
        <button
          type="button"
          onClick={clearSecrets}
          disabled={isBusy || secrets.length === 0}
          className="md3-btn-text lawver-pressable text-sm !text-[var(--color-danger-500)] disabled:opacity-50"
        >
          {busy === `${providerKey}.clear` ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} strokeWidth={2} />}
          {t("settings.provider.clearSecrets")}
        </button>
        <button
          type="button"
          onClick={saveSettings}
          disabled={busy === 'save'}
          className="md3-btn-filled lawver-pressable text-sm disabled:opacity-50"
        >
          {busy === 'save' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2.4} />}
          {t("settings.provider.saveSettings")}
        </button>
      </div>
    </div>
  );
};

/* ── 帮助 ──────────────────────────────────────────────────────────────── */

const HELP_TOPICS: Array<{
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  titleKey: MessageKey;
  descriptionKey: MessageKey;
}> = [
    { icon: MessageSquareText, titleKey: 'settings.help.chatTitle', descriptionKey: 'settings.help.chatDesc' },
    { icon: Paperclip, titleKey: 'settings.help.uploadTitle', descriptionKey: 'settings.help.uploadDesc' },
    { icon: Sparkles, titleKey: 'settings.help.imageTitle', descriptionKey: 'settings.help.imageDesc' },
    { icon: Folder, titleKey: 'settings.help.workspaceTitle', descriptionKey: 'settings.help.workspaceDesc' },
    { icon: Gavel, titleKey: 'settings.help.courtTitle', descriptionKey: 'settings.help.courtDesc' },
    { icon: Settings2, titleKey: 'settings.help.composerTitle', descriptionKey: 'settings.help.composerDesc' },
  ];

const HelpSection: React.FC<{ onStartTour: () => void }> = ({ onStartTour }) => {
  const { t } = useT();
  return (
  <div className="flex min-w-0 flex-col gap-5">
    <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
      <div className="flex min-w-0 flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="flex min-w-0 gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
            <CirclePlay size={20} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h2 className="t-title-m">{t("settings.help.guideTitle")}</h2>
            <p className="mt-1 text-[13px] leading-5 text-[var(--fg-3)]">
              {t("settings.help.guideLead")}
            </p>
          </div>
        </div>
        <button type="button" onClick={onStartTour} className="md3-btn-filled lawver-pressable shrink-0 text-sm">
          <CirclePlay size={16} strokeWidth={2} /> {t("settings.help.replay")}
        </button>
      </div>
    </section>

    <SettingsGroup label={t("settings.help.featureMap")}>
      {HELP_TOPICS.map(topic => {
        const Icon = topic.icon;
        return (
          <SettingsRow
            key={topic.titleKey}
            icon={<Icon size={18} strokeWidth={2} />}
            title={t(topic.titleKey)}
            description={t(topic.descriptionKey)}
          />
        );
      })}
    </SettingsGroup>

    <ShortcutCheatSheet />
  </div>
  );
};

/* ── 关于 ──────────────────────────────────────────────────────────────── */

const AboutSection: React.FC<{ onOpenBusiness?: () => void }> = ({ onOpenBusiness }) => {
  const { t } = useT();
  return (
  <SettingsGroup label={t("settings.about.group")}>
    <SettingsRow
      icon={<BrandMark className="h-5 w-5 [--brand-logo-ink:var(--accent)]" />}
      title={BUILD_INFO.appName}
      description={t('settings.about.description')}
    />
    <SettingsRow dense icon={<PackageCheck size={17} strokeWidth={2} />} title={t("settings.about.version")} trailing={<span className="font-medium tabular-nums">{BUILD_INFO.version}</span>} />
    <SettingsRow dense icon={<Server size={17} strokeWidth={2} />} title={t("settings.about.environment")} trailing={<span className="font-medium">{BUILD_INFO.environment}</span>} />
    <SettingsRow dense icon={<Clock3 size={17} strokeWidth={2} />} title={t("settings.about.buildTime")} trailing={<span className="font-mono text-[12px] tabular-nums">{BUILD_INFO.buildTime}</span>} />
    <SettingsRow
      dense
      icon={<Link2 size={17} strokeWidth={2} />}
      title={t("settings.about.projectUrl")}
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
    {/* Business 母账号才有的出口：侧栏之外，设置里也能进控制台。 */}
    {onOpenBusiness && (
      <SettingsRow
        icon={<Building2 size={17} strokeWidth={2} />}
        title={t("settings.about.businessTitle")}
        description={t("settings.about.businessDesc")}
        trailing={<ChevronRight size={17} strokeWidth={2} className="text-[var(--fg-4)]" />}
        onClick={onOpenBusiness}
      />
    )}
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
  const { t } = useT();
  const { locale, setLocale } = useT();
  const [seedDraft, setSeedDraft] = useState(customSeed);
  const seedValid = isHexColor(seedDraft);

  useEffect(() => {
    setSeedDraft(customSeed);
  }, [customSeed]);

  // 纯字符串选择，比 useMemo 本身还便宜，直接每次渲染计算。
  const monetDescription = (() => {
    if (!isMonetAvailableOnPlatform) return t('settings.appearance.monetUnsupported');
    if (monetStatus === 'available') return t('settings.appearance.monetFollowWallpaper');
    if (monetStatus === 'loading') return t('settings.appearance.monetLoading');
    if (monetStatus === 'unavailable') return t('settings.appearance.monetUnavailable');
    if (monetStatus === 'error') return t('settings.appearance.monetError');
    return t('settings.appearance.monetFollowWallpaper');
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
          <h2 className="t-title-m">{t("settings.appearance.title")}</h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--fg-3)]">
            {t("settings.appearance.current", { theme: resolvedTheme === "dark" ? t("settings.appearance.themeDark") : t("settings.appearance.themeLight"), source: t(COLOR_SOURCE_KEYS[colorSource]) })}
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
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">{t("settings.appearance.displayMode")}</p>
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
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">{t("settings.appearance.colorSource")}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <button type="button" onClick={resetColors} className={sourceButtonClass('default')} aria-pressed={colorSource === 'default'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{t("settings.appearance.sourceDefault")}</span>
                {colorSource === 'default' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">{t("settings.appearance.sourceDefaultHint")}</span>
            </button>

            <button type="button" onClick={() => setColorSource('custom')} className={sourceButtonClass('custom')} aria-pressed={colorSource === 'custom'}>
              <span className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{t("settings.appearance.sourceCustom")}</span>
                {colorSource === 'custom' && <Check size={16} strokeWidth={2.4} className="text-[var(--accent)]" />}
              </span>
              <span className="text-[11px] leading-4 text-[var(--fg-3)]">{t("settings.appearance.sourceCustomHint")}</span>
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

        {/* 界面语言：词条表在 frontend/src/i18n，新增语言只需在 LOCALES 里登记。 */}
        <div className="min-w-0">
          <p className="mb-2 text-[12px] font-medium text-[var(--fg-3)]">{t("settings.appearance.languageLabel")}</p>
          <SelectField
            value={locale}
            onChange={(value) => setLocale(value as Locale)}
            options={Object.entries(LOCALES).map(([value, entry]) => ({
              value,
              label: entry.label,
            }))}
            ariaLabel={t("settings.appearance.languageLabel")}
          />
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
                  aria-label={t("settings.appearance.seedLabel")}
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
                  aria-label={t("settings.appearance.hexLabel")}
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
                    aria-label={t("settings.appearance.chooseColor", { color })}
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
                  {t("settings.appearance.reset")}
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
  const { t } = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const {showConfirm, showAlert} = useAppDialog();
  const theme = useThemeContext();
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const closing = useRef(false);
  const [query, setQuery] = useState('');
  const [plan, setPlan] = useState('');
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const reportEdit = useCallback((key: string, value: boolean) => setDirty(old => old[key] === value ? old : {...old, [key]:value}), []);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const reduceMotion = useReducedMotion();
  const categories = useMemo(() => [
    {id:'appearance', label:t('settings.categories.appearance'), icon:Palette, hint:t('settings.categories.appearanceHint')},
    {id:'account', label:t('settings.categories.account'), icon:KeyRound, hint:t('settings.categories.accountHint')},
    {id:'extensions', label:t('settings.categories.extensions'), icon:PlugZap, hint:t('settings.categories.extensionsHint')},
    {id:'shortcuts', label:t('settings.categories.shortcuts'), icon:Keyboard, hint:t('settings.categories.shortcutsHint')},
    {id:'help', label:t('settings.categories.help'), icon:BookOpen, hint:t('settings.categories.helpHint')},
    {id:'about', label:t('settings.categories.about'), icon:Info, hint:t('settings.categories.aboutHint')},
  ], [t]);
  // 旧分类（模型 / 服务连接 / 数据同步）已迁到后台控制台：深链一并落到外观，
  // 不做「未找到」的空面板，避免用户停在空白页。
  const LEGACY_PANES: Record<string, string> = {models:'appearance', providers:'appearance', data:'appearance', sync:'appearance', webdav:'appearance'};
  const path = location.pathname.replace(/\/+$/, '');
  const requestedPane = path.split('/')[2] || 'appearance';
  const category = categories.some(c => c.id === requestedPane) ? requestedPane : (LEGACY_PANES[requestedPane] || 'appearance');
  const pane = category;
  const [visited, setVisited] = useState<string[]>([pane]);
  useEffect(() => {setVisited(old => old.includes(pane) ? old : [...old, pane]);}, [pane]);
  // 把 /settings/webdav、/settings/providers/* 之类的旧地址换成规范路径；
  // 裸 /settings 保持原样，交给分类默认值（外观）渲染。
  // 离场动画期间组件仍在挂载、location 已指向别处（如从设置里跳 Business 控制台），
  // 此时必须放手，否则会把刚跳出去的地址又改回 /settings/appearance。
  useEffect(() => {
    if (!path.startsWith('/settings')) return;
    const canonical = `/settings/${category}`;
    if (path !== canonical && path !== '/settings') navigate(canonical, {replace:true});
  }, [path, category, navigate]);
  const active = categories.find(c => c.id === category) || categories[0];
  useEffect(() => {
    dialog.current?.querySelector('[aria-current="page"]')?.scrollIntoView({block:'nearest', inline:'nearest'});
  }, [category]);
  const close = useCallback(async () => {
    if(closing.current) return false;
    closing.current = true;
    try {
      if(Object.values(dirtyRef.current).some(Boolean) && !await showConfirm({title:t('settings.discardTitle'), message:t('settings.discardMessage'), confirmLabel:t('settings.discardConfirm'), cancelLabel:t('settings.discardCancel'), tone:'warning'})) return false;
      if(onClose) onClose(); else navigate('/', {replace:true});
      return true;
    } finally {closing.current = false;}
  }, [onClose, navigate, showConfirm, t]);
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
      if(matchKeys(e, getBinding(SHORTCUT_IDS.overlayClose))) {e.preventDefault(); void closeRef.current();}
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
  // 只有 Business 套餐才显示控制台入口；读取失败按普通账号处理，不打断设置页。
  useEffect(() => {
    let cancelled = false;
    fetchMyCredits()
      .then(data => {if(!cancelled) setPlan(data.plan || '');})
      .catch(() => undefined);
    return () => {cancelled = true;};
  }, []);
  const openBusiness = useCallback(() => {
    void closeRef.current().then(closed => {if(closed) navigate('/business');});
  }, [navigate]);
  const select = (id: string) => {setQuery(''); navigate(`/settings/${id}`, {replace:true});};
  const renderPane = (key: string) => {
    if(key === 'extensions') return <SettingsExtensions/>;
    if(key === 'account') return <><p className="settings-hint">{t('settings.accountHint')}</p><ProfileCard/><AccountCard/></>;
    if(key === 'appearance') return <><p className="settings-hint">{t('settings.appearanceHint')}</p><AppearanceCard {...theme} /></>;
    if(key === 'shortcuts') return <SettingsShortcuts/>;
    if(key === 'help') return <HelpSection onStartTour={() => {void closeRef.current().then(closed => {if(closed) requestGuidedTour();});}}/>;
    if(key === 'about') return <AboutSection onOpenBusiness={plan === 'business' ? openBusiness : undefined}/>;
    return <Banner>{t('settings.notFound')}</Banner>;
  };
  return <SettingsEditContext.Provider value={reportEdit}>
    <motion.div initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduceMotion?0:.16}} className="settings-overlay" onMouseDown={e => {if(e.target === e.currentTarget) void close();}}>
      <motion.section initial={{scale:reduceMotion?1:.98,y:reduceMotion?0:8}} animate={{scale:1,y:0}} exit={{scale:reduceMotion?1:.99,y:reduceMotion?0:4}} transition={{duration:reduceMotion?0:.2,ease:[.2,.8,.2,1]}} className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title" ref={dialog}>
        <header className="settings-header"><h1 id="settings-title">{t("settings.title")}</h1><button ref={closeButton} className="settings-close" aria-label={t("settings.close")} onClick={() => void close()}><X size={20}/></button></header>
        <aside className="settings-navigation"><label className="settings-search"><Search size={16}/><input aria-label={t("settings.searchLabel")} placeholder={t("settings.searchPlaceholder")} value={query} onChange={e => setQuery(e.target.value)}/></label><nav aria-label={t("settings.navLabel")}>{categories.filter(c => (c.label+c.hint).includes(query)).map(c => <button key={c.id} aria-current={category === c.id ? 'page' : undefined} onClick={() => select(c.id)}><c.icon size={18}/><span>{c.label}</span></button>)}{!categories.some(c => (c.label+c.hint).includes(query)) && <p className="settings-hint">{t("settings.noMatch")}</p>}</nav></aside>
        <main className="settings-content"><header className="settings-section-heading"><h2>{active.label}</h2><p>{active.hint}</p>{Object.values(dirty).some(Boolean) && <span className="settings-unsaved" role="status">{t("settings.unsaved")}</span>}</header>{Array.from(new Set([...visited,pane])).map(key => <div key={key} hidden={key !== pane} className="settings-pane">{renderPane(key)}</div>)}</main>
      </motion.section>
    </motion.div>
  </SettingsEditContext.Provider>;
};
