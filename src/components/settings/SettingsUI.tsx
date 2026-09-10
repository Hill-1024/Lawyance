/*
 * 模块描述：设置/后台共享的界面原语，统一分组、行、状态标记与加载态样式。
 *
 * 设计约定（与主界面一致）：单一司法蓝强调色、中性底色、柔和阴影、
 * 统一圆角与 240ms 标准缓动；卡片只在需要表达层级时使用，列表用发丝分隔线。
 */

import React from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react';

/* ── 分组 ───────────────────────────────────────────────────────────────── */

export const SettingsGroup: React.FC<{
  label?: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}> = ({ label, hint, action, children, className = '' }) => (
  <section className={`min-w-0 ${className}`}>
    {(label || action) && (
      <div className="mb-2 flex min-w-0 items-end justify-between gap-3 px-1">
        <div className="min-w-0">
          {label && (
            <h2 className="t-label-m font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">
              {label}
            </h2>
          )}
          {hint && <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">{hint}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    )}
    <div className="min-w-0 divide-y divide-[var(--border-subtle)] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
      {children}
    </div>
  </section>
);

/* ── 行 ─────────────────────────────────────────────────────────────────── */

type RowProps = {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  trailing?: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  /** 紧凑模式用于二级信息行，减少垂直留白。 */
  dense?: boolean;
  className?: string;
};

export const SettingsRow: React.FC<RowProps> = ({
  icon,
  title,
  description,
  trailing,
  onClick,
  disabled = false,
  dense = false,
  className = '',
}) => {
  const interactive = Boolean(onClick) && !disabled;
  const padding = dense ? 'px-4 py-3' : 'px-4 py-3.5 sm:px-5';

  const content = (
    <>
      {icon && (
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium leading-5 text-[var(--fg-1)]">{title}</span>
        {description && (
          <span className="mt-0.5 block text-[12px] leading-5 text-[var(--fg-3)]">{description}</span>
        )}
      </span>
      {trailing && <span className="flex shrink-0 items-center gap-2">{trailing}</span>}
    </>
  );

  if (!interactive) {
    return (
      <div className={`flex min-w-0 items-center gap-3 ${padding} ${disabled ? 'opacity-60' : ''} ${className}`}>
        {content}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`lawver-pressable flex min-w-0 w-full items-center gap-3 text-left transition-colors hover:bg-[var(--bg-surface-2)] ${padding} ${className}`}
    >
      {content}
    </button>
  );
};

/* ── 状态标记 ───────────────────────────────────────────────────────────── */

export type ChipTone = 'ok' | 'warn' | 'danger' | 'muted' | 'accent';

const CHIP_TONES: Record<ChipTone, string> = {
  ok: 'bg-[rgba(46,125,85,0.12)] text-[var(--color-success-500)]',
  warn: 'bg-[rgba(184,132,42,0.14)] text-[var(--color-warning-500)]',
  danger: 'bg-[rgba(176,70,62,0.12)] text-[var(--color-danger-500)]',
  muted: 'bg-[var(--bg-inset)] text-[var(--fg-3)]',
  accent: 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]',
};

export const StatusChip: React.FC<{
  tone?: ChipTone;
  children: React.ReactNode;
  className?: string;
}> = ({ tone = 'muted', children, className = '' }) => (
  <span className={`md3-chip shrink-0 ${CHIP_TONES[tone]} ${className}`}>{children}</span>
);

/* ── 提示条 ─────────────────────────────────────────────────────────────── */

const BANNER_TONES = {
  info: {
    wrapper: 'border-[var(--border-default)] bg-[var(--bg-inset)] text-[var(--fg-2)]',
    icon: 'text-[var(--accent)]',
    Icon: Info,
  },
  warning: {
    wrapper: 'border-[rgba(184,132,42,0.3)] bg-[rgba(184,132,42,0.08)] text-[#5C3F0E] dark:text-[#FBEBC8]',
    icon: 'text-[var(--color-warning-500)]',
    Icon: AlertTriangle,
  },
  danger: {
    wrapper: 'border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.08)] text-[var(--color-danger-500)]',
    icon: 'text-[var(--color-danger-500)]',
    Icon: AlertTriangle,
  },
  success: {
    wrapper: 'border-[rgba(46,125,85,0.3)] bg-[rgba(46,125,85,0.08)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]',
    icon: 'text-[var(--color-success-500)]',
    Icon: CheckCircle2,
  },
} as const;

export const Banner: React.FC<{
  tone?: keyof typeof BANNER_TONES;
  children: React.ReactNode;
  className?: string;
}> = ({ tone = 'info', children, className = '' }) => {
  const config = BANNER_TONES[tone];
  const Icon = config.Icon;
  return (
    <div className={`flex min-w-0 gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5 ${config.wrapper} ${className}`}>
      <Icon size={16} strokeWidth={2} className={`mt-0.5 shrink-0 ${config.icon}`} />
      <div className="min-w-0 text-[12px] leading-5">{children}</div>
    </div>
  );
};

/* ── 加载态 ─────────────────────────────────────────────────────────────── */

export const SkeletonRows: React.FC<{ rows?: number; className?: string }> = ({ rows = 3, className = '' }) => (
  <div className={`min-w-0 divide-y divide-[var(--border-subtle)] ${className}`} aria-hidden="true">
    {Array.from({ length: rows }).map((_, index) => (
      <div key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
        <span className="h-10 w-10 shrink-0 animate-pulse rounded-[var(--radius-md)] bg-[var(--bg-inset)]" />
        <span className="min-w-0 flex-1">
          <span className="block h-3.5 w-1/3 animate-pulse rounded-full bg-[var(--bg-inset)]" />
          <span className="mt-2 block h-3 w-2/5 animate-pulse rounded-full bg-[var(--bg-inset)]" />
        </span>
      </div>
    ))}
  </div>
);

export const CenteredSpinner: React.FC<{ label?: string; className?: string }> = ({ label, className = '' }) => (
  <div className={`flex min-h-[30vh] flex-col items-center justify-center gap-3 text-[var(--fg-3)] ${className}`}>
    <Loader2 size={22} strokeWidth={2} className="animate-spin text-[var(--accent)]" />
    {label && <p className="text-[13px]">{label}</p>}
  </div>
);

/* ── 空状态 ─────────────────────────────────────────────────────────────── */

export const EmptyState: React.FC<{
  icon: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}> = ({ icon, title, description, action, className = '' }) => (
  <div className={`flex min-w-0 flex-col items-center justify-center gap-3 px-5 py-12 text-center ${className}`}>
    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
      {icon}
    </span>
    <div className="min-w-0">
      <p className="text-[14px] font-semibold text-[var(--fg-1)]">{title}</p>
      {description && (
        <p className="mx-auto mt-1 max-w-[36ch] text-[12px] leading-5 text-[var(--fg-3)]">{description}</p>
      )}
    </div>
    {action}
  </div>
);

/* ── 表单字段 ───────────────────────────────────────────────────────────── */

export const fieldInputClass =
  'h-11 min-w-0 w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm text-[var(--fg-1)] outline-none transition-colors placeholder:text-[var(--fg-4)] focus:border-[var(--accent)] disabled:opacity-60';

export const SettingsField: React.FC<{
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}> = ({ label, hint, error, children, className = '' }) => (
  <label className={`block min-w-0 ${className}`}>
    <span className="mb-1.5 block text-[12px] font-medium text-[var(--fg-3)]">{label}</span>
    {children}
    {error ? (
      <span className="mt-1 block text-[11px] leading-4 text-[var(--color-danger-500)]">{error}</span>
    ) : hint ? (
      <span className="mt-1 block text-[11px] leading-4 text-[var(--fg-4)]">{hint}</span>
    ) : null}
  </label>
);
