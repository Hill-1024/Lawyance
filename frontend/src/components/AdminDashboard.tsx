/*
 * 模块描述：后台管理控制台，按 sudo / admin 权限展示账号计费、用量监控、开屏公告与服务配置。
 * 视觉沿用工作台（workbench）岛式语言：.wb-app 令牌、32px 控件网格、.wb-modal 弹窗。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SelectField } from "../workbench/SelectField";
import { AnimatedSwitch } from "./AnimatedSwitch";
import { CheckBox } from "./CheckBox";
import {
  Activity,
  ArrowLeft,
  EyeOff,
  KeyRound,
  Loader2,
  LogOut,
  Megaphone,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Unlock,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { useAppBack } from '../hooks/useAppBack';
import { useAppDialog } from '../contexts/DialogContext';
import { translate, useT } from '../i18n';
import { BrandMark } from './Brand';
import { HoverInfo } from './HoverInfo';
import { describeError } from '../lib/errors';
import { LlmProfileManager } from './settings/LlmProfileManager';
import {
  PROVIDER_DESCS,
  PROVIDER_ICONS,
  PROVIDER_LABELS,
  PROVIDER_ORDER,
  ProviderSubPage,
} from './SettingsPage';
import { Banner, EmptyState, StatusChip, type ChipTone } from './settings/SettingsUI';
import {
  clearLogs,
  createAnnouncement,
  deleteAccount,
  deleteAnnouncement,
  fetchAccounts,
  fetchAdminAnnouncements,
  fetchAdminUsage,
  fetchThrottleBuckets,
  fetchLogs,
  setAccount,
  setAccountStatus,
  unlockAccount,
  topUpAccount,
  updateAccountLimits,
  updateAnnouncement,
  verifyAuth,
  type Account,
  type AccountLimits,
  type AccountProvision,
  type Announcement,
  type AnnouncementInput,
  type AnnouncementLevel,
  type Role,
  type UsageAccount,
  type ThrottleBucket,
} from '../services/api';
import '../workbench/workbench.css';

/* ── 展示常量与格式化 ─────────────────────────────────────────────────── */

// 角色/套餐/计费/告警级别是展示文案：取词放在函数里用 translate()，
// 模块级常量会停在首次加载的语言（与 CourtSetup phases 同理）。
const roleLabel = (role: Role): string =>
  role === 'sudo'
    ? translate('admin.roleSudo')
    : role === 'admin'
      ? translate('admin.roleAdmin')
      : translate('admin.roleUser');

const ROLE_TONE: Record<Role, ChipTone> = {
  sudo: 'accent',
  admin: 'warn',
  user: 'muted',
};

const planLabel = (plan: string | undefined): string => {
  switch (plan) {
    case 'metered': return translate('admin.planMetered');
    case 'go': return translate('admin.planGo');
    case 'pro': return translate('admin.planPro');
    case 'max': return translate('admin.planMax');
    case 'business': return translate('admin.planBusiness');
    default: return plan || '';
  }
};

const cycleLabel = (cycle: string | undefined): string =>
  cycle === 'monthly'
    ? translate('admin.cycleMonthly')
    : cycle === 'yearly'
      ? translate('admin.cycleYearly')
      : translate('admin.cyclePrepaid');

const PAID_PLANS = ['go', 'pro', 'max', 'business'] as const;

const levelLabel = (level: AnnouncementLevel): string =>
  level === 'warning'
    ? translate('admin.levelWarning')
    : level === 'danger'
      ? translate('admin.levelDanger')
      : translate('admin.levelInfo');

const LEVEL_TONE: Record<AnnouncementLevel, ChipTone> = {
  info: 'accent',
  warning: 'warn',
  danger: 'danger',
};

const ALL_PLANS = ['metered', ...PAID_PLANS];

const formatCredits = (value: number | null | undefined) =>
  Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const formatNumber = (value: number | null | undefined) =>
  Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 });

const formatDateTime = (iso?: string | null) => {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

/** datetime-local 输入值（本地时区）↔ ISO 字符串。 */
const toLocalInput = (iso?: string | null) => {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const fromLocalInput = (value: string): string | null => {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};

/* ── 日志解析（沿用原后台的格式约定） ─────────────────────────────────── */

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
      method: (hasClientType ? fields[3] : fields[2] || '').trim(),
      path: (hasClientType ? fields[4] : fields[3] || '').trim(),
      status: (hasClientType ? fields[5] : fields[4] || '').trim(),
      raw,
    };
  }
  return { time: '', ip: '', user: '', method: '', path: '', status: '', raw };
}

const statusTone = (status: string): ChipTone => {
  const code = Number.parseInt(status, 10);
  if (Number.isNaN(code)) return 'muted';
  if (code >= 200 && code < 300) return 'ok';
  if (code >= 300 && code < 400) return 'warn';
  return 'danger';
};

const METHOD_TONE: Record<string, ChipTone> = {
  GET: 'accent',
  POST: 'ok',
  PUT: 'warn',
  DELETE: 'danger',
};

/* ── 弹窗外壳 ─────────────────────────────────────────────────────────── */

const AdminModal: React.FC<{
  title: string;
  subtitle?: string;
  small?: boolean;
  onClose: () => void;
  children: React.ReactNode;
}> = ({ title, subtitle, small = false, onClose, children }) => {
  const { t } = useT();
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);
  return (
    <div
      className="wb-modal-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <section
        className={`wb-modal${small ? ' wb-small-form' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button aria-label={t("common.close")} onClick={onClose}><X size={18} /></button>
        </header>
        {subtitle && <p>{subtitle}</p>}
        {children}
      </section>
    </div>
  );
};

/* ── 反馈条（成功/失败共用，成功后自动淡出） ─────────────────────────── */

const useFeedback = () => {
  const [feedback, setFeedback] = useState('');
  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(''), 8000);
    return () => window.clearTimeout(timer);
  }, [feedback]);
  return [feedback, setFeedback] as const;
};

/* ── 账号 ─────────────────────────────────────────────────────────────── */

type BillingMode = 'metered' | 'monthly' | 'yearly';

const CreateAccountDialog: React.FC<{
  role: Role;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ role, onClose, onDone }) => {
  const { t } = useT();
  const isSudo = role === 'sudo';
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newRole, setNewRole] = useState<Role>('user');
  const [mode, setMode] = useState<BillingMode>('metered');
  const [plan, setPlan] = useState<string>('pro');
  const [credits, setCredits] = useState('');
  const [maxOnline, setMaxOnline] = useState('');
  const [maxUsers, setMaxUsers] = useState('');
  const [userMaxOnline, setUserMaxOnline] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!username.trim()) return setError(t('admin.errUsernameRequired'));
    if (password.length < 6) return setError(t('admin.errPasswordTooShort'));

    const limits: AccountLimits = {};
    if (isSudo && newRole !== 'sudo') {
      limits.max_online = maxOnline.trim() === '' ? 0 : Number(maxOnline);
      if (newRole === 'admin') {
        limits.max_users = maxUsers.trim() === '' ? -1 : Number(maxUsers);
        limits.user_max_online = userMaxOnline.trim() === '' ? 0 : Number(userMaxOnline);
      }
      if (Object.values(limits).some((value) => Number.isNaN(value))) {
        return setError(t('admin.errQuotaNotNumber'));
      }
    }

    const provision: AccountProvision = {};
    if (mode === 'metered') {
      provision.plan = 'metered';
      provision.billing_cycle = 'prepaid';
    } else {
      provision.plan = plan;
      provision.billing_cycle = mode;
    }
    if (credits.trim() !== '') {
      const amount = Number(credits);
      if (!Number.isFinite(amount) || amount < 0) return setError(t('admin.errInitialCredits'));
      provision.initial_credits = amount;
    }

    setBusy(true);
    try {
      await setAccount(username.trim(), password, isSudo ? newRole : 'user', limits, provision);
      onDone(t('admin.createdNotice', { username: username.trim() }));
    } catch (e: any) {
      setError(describeError(e, t('admin.createFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminModal title={t(isSudo ? "admin.createSudoTitle" : "admin.createUserTitle")} subtitle={t('admin.createSubtitle')} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="wb-admin-form-grid">
          <label>
            {t('admin.fieldUsername')}
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label>
            {t('admin.fieldPassword')}
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t('admin.passwordHint')}
              autoComplete="new-password"
            />
          </label>
        </div>

        <label>
          {t('admin.fieldRole')}
          {isSudo ? (
            <div className="wb-admin-choices" role="group" aria-label={t("admin.roleGroup")}>
              {(['user', 'admin', 'sudo'] as Role[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={newRole === option}
                  onClick={() => setNewRole(option)}
                >
                  {roleLabel(option)}
                </button>
              ))}
            </div>
          ) : (
            <div className="wb-admin-choices">
              <button type="button" aria-pressed onClick={() => undefined}>{roleLabel('user')}</button>
            </div>
          )}
        </label>

        <label>
          {t('admin.fieldBilling')}
          <div className="wb-admin-choices" role="group" aria-label={t("admin.billingGroup")}>
            {([
              'metered',
              'monthly',
              'yearly',
            ] as BillingMode[]).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {cycleLabel(value)}
              </button>
            ))}
          </div>
        </label>

        {mode !== 'metered' && (
          <label>
            {t('admin.fieldPlan')}
            <div className="wb-admin-choices" role="group" aria-label={t("admin.planGroup")}>
              {PAID_PLANS.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={plan === value}
                  onClick={() => setPlan(value)}
                >
                  {planLabel(value)}
                </button>
              ))}
            </div>
          </label>
        )}

        <div className="wb-admin-form-grid">
          <label>
            {t('admin.fieldInitialCredits')}
            <input
              type="number"
              min={0}
              step="0.01"
              value={credits}
              onChange={(event) => setCredits(event.target.value)}
              placeholder={t('admin.initialCreditsHint')}
            />
          </label>
          {isSudo && newRole !== 'sudo' && (
            <label>
              {t('admin.fieldMaxOnline')}
              <input
                type="number"
                min={0}
                max={1000}
                value={maxOnline}
                onChange={(event) => setMaxOnline(event.target.value)}
                placeholder={t('admin.unlimitedHint')}
              />
            </label>
          )}
        </div>

        {isSudo && newRole === 'admin' && (
          <div className="wb-admin-form-grid">
            <label>
              {t('admin.fieldMaxUsers')}
              <input
                type="number"
                min={0}
                max={10000}
                value={maxUsers}
                onChange={(event) => setMaxUsers(event.target.value)}
                placeholder={t('admin.unlimitedHint')}
              />
            </label>
            <label>
              {t('admin.fieldUserMaxOnline')}
              <input
                type="number"
                min={0}
                max={1000}
                value={userMaxOnline}
                onChange={(event) => setUserMaxOnline(event.target.value)}
                placeholder={t('admin.unlimitedHint')}
              />
            </label>
          </div>
        )}

        {error && <Banner tone="danger">{error}</Banner>}
        <div className="wb-admin-modal-actions">
          <button type="button" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button type="submit" className="wb-primary" disabled={busy}>
            {busy && <Loader2 size={15} className="wb-spin" />} {t('admin.createAction')}
          </button>
        </div>
      </form>
    </AdminModal>
  );
};

const ResetPasswordDialog: React.FC<{
  account: Account;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ account, onClose, onDone }) => {
  const { t } = useT();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password.length < 6) return setError(t('admin.errPasswordTooShort'));
    setBusy(true);
    setError('');
    try {
      await setAccount(account.username, password, account.role, {});
      onDone(t('admin.resetDoneNotice', { username: account.username }));
    } catch (e: any) {
      setError(describeError(e, t('admin.resetFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminModal
      title={t("admin.resetPasswordTitle")}
      subtitle={t('admin.resetSubtitle', { username: account.username, role: roleLabel(account.role) })}
      small
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <label>
          {t('admin.fieldNewPassword')}
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={t('admin.passwordHint')}
            autoComplete="new-password"
          />
        </label>
        {error && <Banner tone="danger">{error}</Banner>}
        <div className="wb-admin-modal-actions">
          <button type="button" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button type="submit" className="wb-primary" disabled={busy}>
            {busy && <Loader2 size={15} className="wb-spin" />} {t('admin.resetAction')}
          </button>
        </div>
      </form>
    </AdminModal>
  );
};

const LimitsDialog: React.FC<{
  account: Account;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ account, onClose, onDone }) => {
  const { t } = useT();
  const [maxOnline, setMaxOnline] = useState(account.max_online == null ? '' : String(account.max_online));
  const [maxUsers, setMaxUsers] = useState(account.max_users == null ? '' : String(account.max_users));
  const [userMaxOnline, setUserMaxOnline] = useState(account.user_max_online == null ? '' : String(account.user_max_online));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    const limits: AccountLimits =
      account.role === 'admin'
        ? {
            max_users: maxUsers.trim() === '' ? -1 : Number(maxUsers),
            user_max_online: userMaxOnline.trim() === '' ? 0 : Number(userMaxOnline),
          }
        : { max_online: maxOnline.trim() === '' ? 0 : Number(maxOnline) };
    if (Object.values(limits).some((value) => Number.isNaN(value))) {
      return setError(t('admin.errQuotaNotNumber'));
    }
    setBusy(true);
    try {
      await updateAccountLimits(account.username, limits);
      onDone(t('admin.limitsDoneNotice', { username: account.username }));
    } catch (e: any) {
      setError(describeError(e, t('admin.limitsFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminModal title={t("admin.limitsTitle")} subtitle={t('admin.usernameWithRole', { username: account.username, role: roleLabel(account.role) })} small onClose={onClose}>
      <form onSubmit={submit}>
        {account.role === 'admin' ? (
          <>
            <label>
              {t('admin.fieldAdminMaxUsers')}
              <input
                type="number"
                min={0}
                max={10000}
                value={maxUsers}
                onChange={(event) => setMaxUsers(event.target.value)}
                placeholder={t('admin.unlimitedHint')}
              />
            </label>
            <label>
              {t('admin.fieldAdminUserMaxOnline')}
              <input
                type="number"
                min={0}
                max={1000}
                value={userMaxOnline}
                onChange={(event) => setUserMaxOnline(event.target.value)}
                placeholder={t('admin.unlimitedHint')}
              />
            </label>
          </>
        ) : (
          <label>
            {t('admin.fieldMaxOnline')}
            <input
              type="number"
              min={0}
              max={1000}
              value={maxOnline}
              onChange={(event) => setMaxOnline(event.target.value)}
              placeholder={t('admin.unlimitedHint')}
            />
          </label>
        )}
        {error && <Banner tone="danger">{error}</Banner>}
        <div className="wb-admin-modal-actions">
          <button type="button" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button type="submit" className="wb-primary" disabled={busy}>
            {busy && <Loader2 size={15} className="wb-spin" />} {t('admin.saveAction')}
          </button>
        </div>
      </form>
    </AdminModal>
  );
};

const TopUpDialog: React.FC<{
  account: Account;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ account, onClose, onDone }) => {
  const { t } = useT();
  const [amount, setAmount] = useState('100');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const yuan = Number(amount);
    if (!Number.isInteger(yuan) || yuan <= 0) return setError(t('admin.errTopUpAmount'));
    setBusy(true);
    setError('');
    try {
      const result = await topUpAccount(account.username, yuan, note.trim());
      onDone(
        t('admin.topUpDoneNotice', {
          username: account.username,
          yuan,
          credited: formatCredits(result.credited),
          balance: formatCredits(result.balance),
        }),
      );
    } catch (e: any) {
      setError(describeError(e, t('admin.topUpFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminModal
      title={t("admin.topUpTitle")}
      subtitle={t('admin.topUpSubtitle', { username: account.username, balance: formatCredits(account.credits ?? 0) })}
      small
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <label>
          {t('admin.fieldTopUpAmount')}
          <input
            type="number"
            min={1}
            step={1}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label>
          {t('admin.fieldNote')}
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t('admin.notePlaceholder')}
          />
        </label>
        {error && <Banner tone="danger">{error}</Banner>}
        <div className="wb-admin-modal-actions">
          <button type="button" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button type="submit" className="wb-primary" disabled={busy}>
            {busy && <Loader2 size={15} className="wb-spin" />} {t('admin.topUpAction')}
          </button>
        </div>
      </form>
    </AdminModal>
  );
};

const AccountsPanel: React.FC<{ role: Role }> = ({ role }) => {
  const { t } = useT();
  const isSudo = role === 'sudo';
  const { showConfirm } = useAppDialog();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useFeedback();
  const [myUsername, setMyUsername] = useState('');
  const [myQuota, setMyQuota] = useState<{ max_users?: number | null }>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<Account | null>(null);
  const [limitsTarget, setLimitsTarget] = useState<Account | null>(null);
  const [topUpTarget, setTopUpTarget] = useState<Account | null>(null);
  const [busyUser, setBusyUser] = useState('');
  const requestIdRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const data = await fetchAccounts();
      if (requestId !== requestIdRef.current) return;
      setAccounts(data.accounts || []);
    } catch (e: any) {
      if (requestId !== requestIdRef.current) return;
      setError(describeError(e, t('admin.loadAccountsFailed')));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => { requestIdRef.current += 1; };
  }, [load]);

  useEffect(() => {
    verifyAuth()
      .then((info) => {
        setMyUsername(info.username);
        setMyQuota({ max_users: info.max_users ?? null });
      })
      .catch(() => {});
  }, []);

  const quotaReached = role === 'admin' && myQuota.max_users != null && accounts.length >= myQuota.max_users;

  const toggleStatus = async (account: Account) => {
    const suspending = account.status !== 'suspended';
    const confirmed = await showConfirm({
      title: suspending ? t('admin.disableConfirmTitle') : t('admin.enableConfirmTitle'),
      message: suspending
        ? t('admin.disableConfirmMessage', { username: account.username })
        : t('admin.enableConfirmMessage', { username: account.username }),
      tone: suspending ? 'danger' : 'info',
      confirmLabel: suspending ? t('admin.disableAction') : t('admin.enableAction'),
    });
    if (!confirmed) return;
    setBusyUser(account.username);
    setError('');
    try {
      await setAccountStatus(account.username, suspending ? 'suspended' : 'active');
      setFeedback(suspending
        ? t('admin.statusSuspendedNotice', { username: account.username })
        : t('admin.statusEnabledNotice', { username: account.username }));
      void load();
    } catch (e: any) {
      setError(describeError(e, t('admin.statusUpdateFailed')));
    } finally {
      setBusyUser('');
    }
  };

  const unlock = async (account: Account) => {
    setBusyUser(account.username);
    setError('');
    try {
      const result = await unlockAccount(account.username);
      setFeedback(t('admin.unlockDoneNotice', { username: account.username }));
      void load();
      return result;
    } catch (e: any) {
      setError(e.message || t('admin.unlockFailed'));
    } finally {
      setBusyUser('');
    }
  };

  const remove = async (account: Account) => {
    const confirmed = await showConfirm({
      title: t('admin.deleteAccountTitle'),
      message: t('admin.deleteAccountMessage', { username: account.username }),
      tone: 'danger',
      confirmLabel: t('admin.deleteAction'),
    });
    if (!confirmed) return;
    setBusyUser(account.username);
    setError('');
    try {
      await deleteAccount(account.username);
      setFeedback(t('admin.deleteDoneNotice', { username: account.username }));
      void load();
    } catch (e: any) {
      setError(e.message || t('admin.deleteFailed'));
    } finally {
      setBusyUser('');
    }
  };

  return (
    <div className="wb-admin-main">
      {feedback && <Banner tone="success">{feedback}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}
      {quotaReached && (
        <Banner tone="warning">
          {t('admin.quotaReachedNotice', { count: myQuota.max_users ?? 0 })}
        </Banner>
      )}

      <div className="wb-admin-toolbar">
        <p className="wb-admin-note">
          {isSudo
            ? t('admin.accountsNoteSudo', { count: accounts.length })
            : myQuota.max_users != null
              ? t('admin.accountsNoteSelfLimited', { count: accounts.length, limit: myQuota.max_users })
              : t('admin.accountsNoteSelfUnlimited', { count: accounts.length })}
        </p>
        <div className="wb-admin-toolbar-actions">
          <button onClick={() => void load()} disabled={loading} aria-label={t("admin.refreshAccounts")}>
            {loading ? <Loader2 size={16} className="wb-spin" /> : <RefreshCw size={16} />}
          </button>
          <button className="wb-primary" onClick={() => setCreateOpen(true)} disabled={quotaReached}>
            <Plus size={16} /> {t('admin.createAccountAction')}
          </button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <EmptyState
          icon={<Users size={22} strokeWidth={2} />}
          title={isSudo ? t('admin.emptyAccountsTitle') : t('admin.emptyUsersTitle')}
          description={loading ? t('admin.loadingAccounts') : t('admin.emptyAccountsDescription')}
        />
      ) : (
        <div className="wb-admin-table-scroll">
          <div className="wb-admin-table" role="table" aria-label={t("admin.accountsTable")}>
            <div className="wb-admin-table-head" role="row">
              {(['colUsername', 'colRole', 'colPlan', 'colBilling', 'colCredits', 'colOnline', 'colStatus', 'colActions'] as const).map((key) => (
                <span key={key} role="columnheader">{t(`admin.${key}`)}</span>
              ))}
            </div>
            {accounts.map((account) => (
              <div className="wb-admin-table-row" role="row" key={account.username}>
                <span className="wb-admin-cell wb-admin-cell-strong" role="cell" title={account.username}>
                  {account.username}
                  {(account.owner || account.role === 'admin') && (
                    <small className="wb-admin-cell-sub">
                      {account.owner ? t('admin.ownerCell', { owner: account.owner }) : ''}
                      {account.role === 'admin'
                        ? account.max_users == null
                          ? t('admin.ownedCellUnlimited', { owned: account.owned_count ?? 0 })
                          : t('admin.ownedCellLimited', { owned: account.owned_count ?? 0, limit: account.max_users })
                        : ''}
                    </small>
                  )}
                </span>
                <span className="wb-admin-cell" role="cell">
                  <StatusChip tone={ROLE_TONE[account.role]}>{roleLabel(account.role)}</StatusChip>
                </span>
                <span className="wb-admin-cell" role="cell">
                  <StatusChip tone={account.plan === 'metered' || !account.plan ? 'muted' : 'accent'}>
                    {planLabel(account.plan || 'metered')}
                  </StatusChip>
                </span>
                <span className="wb-admin-cell wb-admin-cell-muted" role="cell">
                  {cycleLabel(account.billing_cycle || 'prepaid')}
                </span>
                <span className="wb-admin-cell wb-admin-cell-num" role="cell">{formatCredits(account.credits)}</span>
                <span className="wb-admin-cell wb-admin-cell-num wb-admin-cell-muted" role="cell">
                  {t('admin.deviceCount', { count: account.online_count ?? 0 })}
                </span>
                <span className="wb-admin-cell" role="cell">
                  <StatusChip tone={account.status === 'suspended' ? 'danger' : 'ok'}>
                    {account.status === 'suspended' ? t('admin.statusSuspended') : t('admin.statusActive')}
                  </StatusChip>
                  {Boolean(account.locked_seconds) && (
                    <StatusChip tone="warn">
                      {t('admin.lockedMinutes', { minutes: Math.ceil((account.locked_seconds || 0) / 60) })}
                    </StatusChip>
                  )}
                </span>
                <span className="wb-admin-row-actions" role="cell">
                  {isSudo && (
                    <HoverInfo label={t('admin.editLimitsLabel')} placement="top">
                      <button
                        aria-label={t('admin.editLimitsAria', { username: account.username })}
                        onClick={() => setLimitsTarget(account)}
                        disabled={busyUser === account.username}
                        className="wb-admin-accent"
                      >
                        <SlidersHorizontal size={16} />
                      </button>
                    </HoverInfo>
                  )}
                  <HoverInfo label={t('admin.topUpHover')} placement="top">
                    <button
                      aria-label={t('admin.topUpAria', { username: account.username })}
                      onClick={() => setTopUpTarget(account)}
                      className="wb-admin-accent"
                    >
                      <Wallet size={16} />
                    </button>
                  </HoverInfo>
                  <HoverInfo label={account.status === 'suspended' ? t('admin.enableAction') : t('admin.disableAction')} placement="top">
                    <button
                      aria-label={account.status === 'suspended'
                        ? t('admin.enableAria', { username: account.username })
                        : t('admin.disableAria', { username: account.username })}
                      onClick={() => void toggleStatus(account)}
                      disabled={busyUser === account.username || account.username === myUsername}
                    >
                      <Power size={16} />
                    </button>
                  </HoverInfo>
                  {Boolean(account.locked_seconds) && (
                    <HoverInfo label={t('admin.unlockHover')} placement="top">
                      <button
                        aria-label={t('admin.unlockAria', { username: account.username })}
                        onClick={() => void unlock(account)}
                        disabled={busyUser === account.username}
                        className="wb-admin-accent"
                      >
                        <Unlock size={16} />
                      </button>
                    </HoverInfo>
                  )}
                  <HoverInfo label={t('admin.resetPasswordHover')} placement="top">
                    <button
                      aria-label={t('admin.resetAria', { username: account.username })}
                      onClick={() => setResetTarget(account)}
                      className="wb-admin-accent"
                    >
                      <KeyRound size={16} />
                    </button>
                  </HoverInfo>
                  <HoverInfo
                    label={account.username === 'admin' ? t('admin.systemAdminNoDelete') : t('admin.deleteHover')}
                    placement="top"
                  >
                    <button
                      aria-label={t('admin.deleteAria', { username: account.username })}
                      onClick={() => void remove(account)}
                      disabled={account.username === 'admin' || account.username === myUsername || busyUser === account.username}
                      className="wb-admin-danger"
                    >
                      <Trash2 size={16} />
                    </button>
                  </HoverInfo>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="wb-admin-note">
        {t('admin.accountsFootnote')}
      </p>

      {createOpen && (
        <CreateAccountDialog
          role={role}
          onClose={() => setCreateOpen(false)}
          onDone={(message) => {
            setCreateOpen(false);
            setFeedback(message);
            void load();
          }}
        />
      )}
      {resetTarget && (
        <ResetPasswordDialog
          account={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={(message) => {
            setResetTarget(null);
            setFeedback(message);
          }}
        />
      )}
      {limitsTarget && (
        <LimitsDialog
          account={limitsTarget}
          onClose={() => setLimitsTarget(null)}
          onDone={(message) => {
            setLimitsTarget(null);
            setFeedback(message);
            void load();
          }}
        />
      )}
      {topUpTarget && (
        <TopUpDialog
          account={topUpTarget}
          onClose={() => setTopUpTarget(null)}
          onDone={(message) => {
            setTopUpTarget(null);
            setFeedback(message);
            void load();
          }}
        />
      )}
    </div>
  );
};

/* ── 用量与监控 ───────────────────────────────────────────────────────── */

const LOG_SKELETON_ROWS = 6;

const AccessLogsPanel: React.FC = () => {
  const { t } = useT();
  const { showConfirm } = useAppDialog();
  const [logs, setLogs] = useState<string[]>([]);
  const [ipFilter, setIpFilter] = useState('');
  const [ignoreHeartbeat, setIgnoreHeartbeat] = useState(true);
  const [loading, setLoading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState('');
  const queryRef = useRef({ ipFilter: '', ignoreHeartbeat: true });
  const requestIdRef = useRef(0);

  const load = useCallback(async (query?: { ipFilter: string; ignoreHeartbeat: boolean }) => {
    const next = query || queryRef.current;
    queryRef.current = next;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const data = await fetchLogs(next.ipFilter, next.ignoreHeartbeat);
      if (requestId !== requestIdRef.current) return;
      setLogs(data.logs || []);
    } catch (e: any) {
      if (requestId !== requestIdRef.current) return;
      setError(e.message || t('admin.loadLogsFailed'));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => { requestIdRef.current += 1; };
  }, [load]);

  const clear = async () => {
    const confirmed = await showConfirm({
      title: t('admin.clearLogsTitle'),
      message: t('admin.clearLogsMessage'),
      tone: 'danger',
      confirmLabel: t('admin.clearAction'),
    });
    if (!confirmed) return;
    setClearing(true);
    setError('');
    try {
      await clearLogs();
      setLogs([]);
    } catch (e: any) {
      setError(e.message || t('admin.clearLogsFailed'));
    } finally {
      setClearing(false);
    }
  };

  const parsed = useMemo(() => logs.map(parseLogLine), [logs]);

  return (
    <section className="wb-admin-section">
      <h2 className="wb-admin-section-title">{t('admin.accessLogsTitle')}</h2>
      <div className="wb-admin-toolbar" style={{ marginTop: 8 }}>
        <div className="wb-admin-toolbar-actions">
          <input
            value={ipFilter}
            onChange={(event) => setIpFilter(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void load({ ipFilter, ignoreHeartbeat });
            }}
            placeholder={t('admin.ipFilterPlaceholder')}
            aria-label={t("admin.logIpFilter")}
            style={{ width: 180 }}
          />
          <CheckBox
            className="wb-admin-inline text-[12px]"
            label={t('admin.hideHeartbeat')}
            checked={ignoreHeartbeat}
            onCheckedChange={(checked) => {
              const next = { ipFilter, ignoreHeartbeat: checked };
              setIgnoreHeartbeat(checked);
              void load(next);
            }}
          />
          <button onClick={() => void load({ ipFilter, ignoreHeartbeat })} disabled={loading} className="wb-quiet">
            {loading ? <Loader2 size={15} className="wb-spin" /> : <Search size={15} />} {t('admin.queryAction')}
          </button>
        </div>
        <div className="wb-admin-toolbar-actions">
          <button onClick={() => void load()} disabled={loading} className="wb-quiet">
            <RefreshCw size={15} /> {t('admin.refreshAction')}
          </button>
          <button onClick={() => void clear()} disabled={clearing || loading} className="wb-quiet wb-danger">
            {clearing ? <Loader2 size={15} className="wb-spin" /> : <Trash2 size={15} />} {t('admin.clearLogsAction')}
          </button>
        </div>
      </div>

      {error && <Banner tone="danger">{error}</Banner>}

      <div className="wb-admin-list" style={{ marginTop: 8 }}>
        {loading && parsed.length === 0 ? (
          <div className="wb-admin-item" aria-busy="true">
            <span className="wb-admin-note">{t('admin.loadingLogs')}</span>
          </div>
        ) : parsed.length === 0 ? (
          <EmptyState
            icon={<EyeOff size={22} strokeWidth={2} />}
            title={t("admin.noLogs")}
            description={t("admin.noLogsDescription")}
          />
        ) : (
          parsed.map((log, index) =>
            log.ip ? (
              <div className="wb-admin-item" key={index}>
                <div className="wb-admin-item-main">
                  <div className="wb-admin-item-title">
                    <span className="wb-admin-cell-muted">{log.time}</span>
                    <StatusChip tone={METHOD_TONE[log.method] || 'muted'}>{log.method || '—'}</StatusChip>
                    <StatusChip tone={statusTone(log.status)}>{log.status || '—'}</StatusChip>
                  </div>
                  <div className="wb-admin-item-meta">
                    <span>{log.ip}</span>
                    <span>{log.user || t('admin.anonymous')}</span>
                    <span>{log.path}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="wb-admin-item" key={index}>
                <div className="wb-admin-item-main">
                  <span className="wb-admin-item-body">{log.raw}</span>
                </div>
              </div>
            ),
          )
        )}
      </div>
    </section>
  );
};

const UsagePanel: React.FC<{ role: Role }> = ({ role }) => {
  const { t } = useT();
  const isSudo = role === 'sudo';
  const [usage, setUsage] = useState<UsageAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [logsOpen, setLogsOpen] = useState(false);
  /** 正在被登录节流的桶：运营时得看得见「谁被挡了、还剩多久」。 */
  const [buckets, setBuckets] = useState<ThrottleBucket[]>([]);
  const requestIdRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const [data, throttleData] = await Promise.all([
        fetchAdminUsage(),
        fetchThrottleBuckets().catch(() => ({ buckets: [] })),
      ]);
      if (requestId !== requestIdRef.current) return;
      setUsage(data.accounts || []);
      setBuckets(throttleData.buckets || []);
    } catch (e: any) {
      if (requestId !== requestIdRef.current) return;
      setError(e.message || t('admin.loadUsageFailed'));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => { requestIdRef.current += 1; };
  }, [load]);

  const rows = useMemo(() => {
    const cutoff = new Date();
    cutoff.setHours(0, 0, 0, 0);
    cutoff.setDate(cutoff.getDate() - 29);
    return usage.map((account) => {
      let promptTokens = 0;
      let completionTokens = 0;
      let toolCalls = 0;
      let credits = 0;
      for (const day of account.usage || []) {
        const dayStart = new Date(`${day.day}T00:00:00`);
        if (Number.isNaN(dayStart.getTime()) || dayStart < cutoff) continue;
        promptTokens += day.prompt_tokens || 0;
        completionTokens += day.completion_tokens || 0;
        toolCalls += day.tool_calls || 0;
        credits += day.credits || 0;
      }
      return { account, tokens: promptTokens + completionTokens, toolCalls, credits };
    });
  }, [usage]);

  const totals = useMemo(
    () => rows.reduce(
      (acc, row) => ({
        tokens: acc.tokens + row.tokens,
        toolCalls: acc.toolCalls + row.toolCalls,
        credits: acc.credits + row.credits,
      }),
      { tokens: 0, toolCalls: 0, credits: 0 },
    ),
    [rows],
  );

  return (
    <div className="wb-admin-main">
      {error && <Banner tone="danger">{error}</Banner>}
      {buckets.length > 0 && (
        <section className="wb-admin-throttle" aria-label={t("admin.throttleSection")}>
          <header>
            <strong>{t('admin.throttleActive')}</strong>
            <span>{t('admin.throttleNote')}</span>
          </header>
          <ul>
            {buckets.slice(0, 8).map((bucket) => (
              <li key={`${bucket.scope}-${bucket.key}`}>
                <span className="wb-admin-throttle__scope">
                  {bucket.scope === 'account' ? t('admin.scopeAccount') : t('admin.scopeClient')}
                </span>
                <code>{bucket.key}</code>
                <span>{t('admin.failCount', { count: bucket.fails })}</span>
                <span className="wb-admin-throttle__lock">
                  {bucket.locked_seconds > 0
                    ? t('admin.lockedMinutes', { minutes: Math.ceil(bucket.locked_seconds / 60) })
                    : t('admin.observing')}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="wb-admin-stats">
        {[
          { label: t('admin.statAccounts'), value: formatNumber(usage.length) },
          { label: t('admin.statTokens'), value: formatNumber(totals.tokens) },
          { label: t('admin.statToolCalls'), value: formatNumber(totals.toolCalls) },
          { label: t('admin.statCredits'), value: formatCredits(totals.credits) },
        ].map((stat) => (
          <div className="wb-admin-stat" key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </div>

      <div className="wb-admin-toolbar">
        <p className="wb-admin-note">
          {isSudo ? t('admin.usageNoteSudo') : t('admin.usageNoteSelf')}
        </p>
        <div className="wb-admin-toolbar-actions">
          <button onClick={() => void load()} disabled={loading} className="wb-quiet">
            {loading ? <Loader2 size={15} className="wb-spin" /> : <RefreshCw size={15} />} {t('admin.refreshAction')}
          </button>
          {isSudo && (
            <button onClick={() => setLogsOpen((open) => !open)} className="wb-quiet" aria-pressed={logsOpen}>
              <Activity size={15} /> {logsOpen ? t('admin.hideAccessLogs') : t('admin.showAccessLogs')}
            </button>
          )}
        </div>
      </div>

      {loading && rows.length === 0 ? (
        <div className="wb-admin-cards" aria-busy="true">
          {Array.from({ length: 3 }).map((_, index) => (
            <div className="wb-admin-card" key={index}>
              <span className="wb-admin-note">{t('admin.loadingUsage')}</span>
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Activity size={22} strokeWidth={2} />}
          title={t("admin.noUsage")}
          description={t("admin.noUsageDescription")}
        />
      ) : (
        <div className="wb-admin-cards">
          {rows.map(({ account, tokens, toolCalls, credits }) => (
            <div className="wb-admin-card" key={account.username}>
              <div className="wb-admin-card-head">
                <span className="wb-admin-card-user">
                  {account.username}
                  <StatusChip tone={account.plan === 'metered' || !account.plan ? 'muted' : 'accent'}>
                    {planLabel(account.plan || 'metered')}
                  </StatusChip>
                  {account.status === 'suspended' && <StatusChip tone="danger">{t('admin.statusSuspended')}</StatusChip>}
                </span>
                <span className="wb-admin-cell-muted">
                  {t('admin.balanceLine', { balance: formatCredits(account.credits) })}
                </span>
              </div>
              <div className="wb-admin-metrics">
                <div className="wb-admin-metric">
                  <span>{t('admin.statTokens')}</span>
                  <strong>{formatNumber(tokens)}</strong>
                </div>
                <div className="wb-admin-metric">
                  <span>{t('admin.metricToolCalls')}</span>
                  <strong>{formatNumber(toolCalls)}</strong>
                </div>
                <div className="wb-admin-metric">
                  <span>{t('admin.metricCredits')}</span>
                  <strong>{formatCredits(credits)}</strong>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {isSudo && logsOpen && <AccessLogsPanel />}
    </div>
  );
};

/* ── 开屏公告 ─────────────────────────────────────────────────────────── */

const AnnouncementDialog: React.FC<{
  initial: Announcement | null;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ initial, onClose, onDone }) => {
  const { t } = useT();
  const [title, setTitle] = useState(initial?.title || '');
  const [body, setBody] = useState(initial?.body || '');
  const [level, setLevel] = useState<AnnouncementLevel>(initial?.level || 'info');
  const [audience, setAudience] = useState<string[]>(initial?.audience || []);
  const [startsAt, setStartsAt] = useState(toLocalInput(initial?.starts_at));
  const [endsAt, setEndsAt] = useState(toLocalInput(initial?.ends_at));
  const [active, setActive] = useState(initial?.active ?? true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const toggleAudience = (plan: string) => {
    setAudience((prev) => (prev.includes(plan) ? prev.filter((item) => item !== plan) : [...prev, plan]));
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return setError(t('admin.errAnnouncementTitle'));
    const payload: AnnouncementInput = {
      title: title.trim(),
      body,
      level,
      audience,
      starts_at: fromLocalInput(startsAt),
      ends_at: fromLocalInput(endsAt),
      active,
    };
    if (payload.starts_at && payload.ends_at && new Date(payload.ends_at) <= new Date(payload.starts_at)) {
      return setError(t('admin.errAnnouncementTime'));
    }
    setBusy(true);
    setError('');
    try {
      if (initial) {
        await updateAnnouncement(initial.id, payload);
        onDone(t('admin.announcementSaved'));
      } else {
        await createAnnouncement(payload);
        onDone(t('admin.announcementCreated'));
      }
    } catch (e: any) {
      setError(e.message || t('admin.saveAnnouncementFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminModal
      title={initial ? t("admin.editAnnouncementTitle") : t("admin.createAnnouncementTitle")}
      subtitle={t('admin.announcementSubtitle')}
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <label>
          {t('admin.fieldAnnouncementTitle')}
          <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} />
        </label>
        <label>
          {t('admin.fieldAnnouncementBody')}
          <textarea value={body} onChange={(event) => setBody(event.target.value)} maxLength={5000} />
        </label>
        <div className="wb-admin-form-grid">
          <SelectField
            label={t('admin.fieldLevel')}
            value={level}
            onChange={(value) => setLevel(value as AnnouncementLevel)}
            options={(['info', 'warning', 'danger'] as AnnouncementLevel[]).map((value) => ({
              value,
              label: t('admin.levelOption', { label: levelLabel(value), value }),
            }))}
          />
          <AnimatedSwitch
            size="sm"
            label={t('admin.announcementActiveLabel')}
            checked={active}
            onCheckedChange={setActive}
          />
        </div>

        <label>
          {t('admin.fieldAudience')}
          <div className="wb-admin-choices" role="group" aria-label={t("admin.audienceGroup")}>
            <button type="button" aria-pressed={audience.length === 0} onClick={() => setAudience([])}>
              {t('admin.audienceAll')}
            </button>
            {ALL_PLANS.map((plan) => (
              <button
                key={plan}
                type="button"
                aria-pressed={audience.includes(plan)}
                onClick={() => toggleAudience(plan)}
              >
                {planLabel(plan)}
              </button>
            ))}
          </div>
        </label>

        <div className="wb-admin-form-grid">
          <label>
            {t('admin.fieldStartsAt')}
            <input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} />
          </label>
          <label>
            {t('admin.fieldEndsAt')}
            <input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} />
          </label>
        </div>

        {error && <Banner tone="danger">{error}</Banner>}
        <div className="wb-admin-modal-actions">
          <button type="button" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button type="submit" className="wb-primary" disabled={busy}>
            {busy && <Loader2 size={15} className="wb-spin" />} {t('admin.saveAction')}
          </button>
        </div>
      </form>
    </AdminModal>
  );
};

const AnnouncementsPanel: React.FC = () => {
  const { t } = useT();
  const { showConfirm } = useAppDialog();
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useFeedback();
  const [editing, setEditing] = useState<Announcement | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState('');
  const requestIdRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const data = await fetchAdminAnnouncements();
      if (requestId !== requestIdRef.current) return;
      setItems(data.announcements || []);
    } catch (e: any) {
      if (requestId !== requestIdRef.current) return;
      setError(e.message || t('admin.loadAnnouncementsFailed'));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => { requestIdRef.current += 1; };
  }, [load]);

  const toggleActive = async (item: Announcement) => {
    setBusyId(item.id);
    setError('');
    try {
      await updateAnnouncement(item.id, { active: !item.active });
      setFeedback(item.active
        ? t('admin.announcementDisabledNotice', { title: item.title })
        : t('admin.announcementEnabledNotice', { title: item.title }));
      void load();
    } catch (e: any) {
      setError(e.message || t('admin.updateAnnouncementFailed'));
    } finally {
      setBusyId('');
    }
  };

  const remove = async (item: Announcement) => {
    const confirmed = await showConfirm({
      title: t('admin.deleteAnnouncementTitle'),
      message: t('admin.deleteAnnouncementMessage', { title: item.title }),
      tone: 'danger',
      confirmLabel: t('admin.deleteAction'),
    });
    if (!confirmed) return;
    setBusyId(item.id);
    setError('');
    try {
      await deleteAnnouncement(item.id);
      setFeedback(t('admin.announcementDeletedNotice', { title: item.title }));
      void load();
    } catch (e: any) {
      setError(e.message || t('admin.deleteAnnouncementFailed'));
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="wb-admin-main">
      {feedback && <Banner tone="success">{feedback}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}

      <div className="wb-admin-toolbar">
        <p className="wb-admin-note">{t('admin.announcementsNote')}</p>
        <div className="wb-admin-toolbar-actions">
          <button onClick={() => void load()} disabled={loading} aria-label={t("admin.refreshAnnouncements")}>
            {loading ? <Loader2 size={16} className="wb-spin" /> : <RefreshCw size={16} />}
          </button>
          <button className="wb-primary" onClick={() => setCreating(true)}>
            <Plus size={16} /> {t('admin.createAnnouncementAction')}
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon={<Megaphone size={22} strokeWidth={2} />}
          title={t("admin.noAnnouncements")}
          description={loading ? t("admin.noAnnouncementsLoading") : t("admin.noAnnouncementsDescription")}
        />
      ) : (
        <div className="wb-admin-list">
          {items.map((item) => (
            <div className="wb-admin-item" key={item.id}>
              <div className="wb-admin-item-main">
                <div className="wb-admin-item-title">
                  {item.title}
                  <StatusChip tone={LEVEL_TONE[item.level] || 'muted'}>{levelLabel(item.level)}</StatusChip>
                  <StatusChip tone={item.active ? 'ok' : 'muted'}>{item.active ? t('admin.announcementOn') : t('admin.announcementOff')}</StatusChip>
                </div>
                {item.body && <div className="wb-admin-item-body">{item.body}</div>}
                <div className="wb-admin-item-meta">
                  <span>{t('admin.audienceCell', { list: item.audience && item.audience.length > 0 ? item.audience.map((plan) => planLabel(plan)).join(t('admin.audienceSeparator')) : t('admin.audienceAll') })}</span>
                  <span>{t('admin.startsAtCell', { time: formatDateTime(item.starts_at) })}</span>
                  <span>{t('admin.endsAtCell', { time: item.ends_at ? formatDateTime(item.ends_at) : t('admin.endsNever') })}</span>
                  <span>{t('admin.createdCell', { by: item.created_by || '—', time: formatDateTime(item.created_at) })}</span>
                </div>
              </div>
              <div className="wb-admin-item-actions">
                <button onClick={() => setEditing(item)} disabled={busyId === item.id}>
                  <Pencil size={13} /> {t('admin.editAction')}
                </button>
                <button onClick={() => void toggleActive(item)} disabled={busyId === item.id}>
                  <Power size={13} /> {item.active ? t('admin.disableAction') : t('admin.enableAction')}
                </button>
                <button className="wb-admin-danger" onClick={() => void remove(item)} disabled={busyId === item.id}>
                  <Trash2 size={13} /> {t('admin.deleteAction')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {creating && (
        <AnnouncementDialog
          initial={null}
          onClose={() => setCreating(false)}
          onDone={(message) => {
            setCreating(false);
            setFeedback(message);
            void load();
          }}
        />
      )}
      {editing && (
        <AnnouncementDialog
          initial={editing}
          onClose={() => setEditing(null)}
          onDone={(message) => {
            setEditing(null);
            setFeedback(message);
            void load();
          }}
        />
      )}
    </div>
  );
};

/* ── 服务配置 ─────────────────────────────────────────────────────────── */

const ConfigPanel: React.FC<{ role: Role }> = ({ role }) => {
  const { t } = useT();
  const isSudo = role === 'sudo';
  const [section, setSection] = useState<string>('models');

  if (!isSudo) {
    return (
      <div className="wb-admin-main">
        <Banner tone="warning">{t('admin.configForbiddenNote')}</Banner>
      </div>
    );
  }

  return (
    <div className="wb-admin-main">
      <div className="wb-admin-config">
        <nav className="wb-admin-config-nav" aria-label={t("admin.configNav")}>
          <button
            className={section === 'models' ? 'selected' : ''}
            onClick={() => setSection('models')}
            aria-pressed={section === 'models'}
          >
            <Sparkles size={16} /> {t('admin.configModels')}
          </button>
          <div className="wb-admin-config-sep" />
          <span className="wb-admin-config-label">{t('admin.configConnections')}</span>
          {PROVIDER_ORDER.map((providerKey) => {
            const Icon = PROVIDER_ICONS[providerKey] || Settings2;
            return (
              <button
                key={providerKey}
                className={section === providerKey ? 'selected' : ''}
                onClick={() => setSection(providerKey)}
                aria-pressed={section === providerKey}
                title={PROVIDER_DESCS[providerKey]}
              >
                <Icon size={16} /> {PROVIDER_LABELS[providerKey] || providerKey}
              </button>
            );
          })}
        </nav>
        <div className="wb-admin-config-pane">
          {section === 'models' ? <LlmProfileManager /> : <ProviderSubPage providerKey={section} />}
        </div>
      </div>
    </div>
  );
};

/* ── 页面外壳 ─────────────────────────────────────────────────────────── */

type AdminTab = 'accounts' | 'usage' | 'announcements' | 'config';

interface AdminDashboardProps {
  role: Role;
  onLogout?: () => void | Promise<void>;
}

export const AdminDashboard: React.FC<AdminDashboardProps> = ({ role, onLogout }) => {
  const { t } = useT();
  const goBack = useAppBack();
  const [tab, setTab] = useState<AdminTab>('accounts');
  const isSudo = role === 'sudo';

  const tabs: { id: AdminTab; label: string; icon: React.ComponentType<{ size?: number }> }[] = [
    { id: 'accounts', label: t('admin.tabAccounts'), icon: Users },
    { id: 'usage', label: t('admin.tabUsage'), icon: Activity },
    { id: 'announcements', label: t('admin.tabAnnouncements'), icon: Megaphone },
    { id: 'config', label: t('admin.tabConfig'), icon: Settings2 },
  ];

  const selectTab = (next: AdminTab) => setTab(next);

  return (
    <div className="wb-app wb-admin">
      <div className="wb-admin-shell">
        <header className="wb-admin-head">
          <div className="wb-admin-identity">
            <HoverInfo label={t("admin.backToChat")} placement="bottom">
              <button aria-label={t("admin.backToChat")} onClick={() => goBack('/')}>
                <ArrowLeft size={18} />
              </button>
            </HoverInfo>
            <span className="wb-admin-mark"><BrandMark className="h-5 w-5" /></span>
            <div className="wb-admin-title">
              <h1>{isSudo ? t('admin.titleSudo') : t('admin.titleSelf')}</h1>
              <p>{isSudo ? t('admin.subtitleSudo') : t('admin.subtitleSelf')}</p>
            </div>
          </div>
          <div className="wb-admin-head-actions">
            <button className="wb-quiet wb-danger" onClick={() => { void onLogout?.(); }}>
              <LogOut size={16} /> {t('admin.logoutAction')}
            </button>
          </div>
        </header>

        <nav className="wb-manager-tabs" role="tablist" aria-label={t("admin.tabsNav")}>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              tabIndex={tab === id ? 0 : -1}
              onClick={() => selectTab(id)}
              onKeyDown={(event) => {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                event.preventDefault();
                const index = tabs.findIndex((item) => item.id === tab);
                const nextIndex =
                  event.key === 'Home' ? 0
                    : event.key === 'End' ? tabs.length - 1
                      : event.key === 'ArrowLeft'
                        ? (index + tabs.length - 1) % tabs.length
                        : (index + 1) % tabs.length;
                selectTab(tabs[nextIndex].id);
                const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
                buttons?.[nextIndex]?.focus();
              }}
            >
              <Icon size={16} /> {label}
            </button>
          ))}
        </nav>

        <main className="wb-admin-main" aria-label={tabs.find((item) => item.id === tab)?.label}>
          {tab === 'accounts' && <AccountsPanel role={role} />}
          {tab === 'usage' && <UsagePanel role={role} />}
          {tab === 'announcements' && <AnnouncementsPanel />}
          {tab === 'config' && <ConfigPanel role={role} />}
        </main>
      </div>
    </div>
  );
};
