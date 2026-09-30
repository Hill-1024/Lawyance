/*
 * 模块描述：通用复选框，替代原生 <input type="checkbox">。
 *
 * 原生方框的字色、圆角、勾选态与焦点环都由浏览器决定，和这套 UI 不同源——在庭审材料
 * 清单、迁移会话列表、连接器工具勾选里一眼就能看出违和。这里按 --accent / --radius-xs /
 * --dur-fast 画一个 18px 的方框，选中填色 + 白勾，语义仍是 role="checkbox"。
 *
 * 与 AnimatedSwitch 的分工：**多选列表**用 CheckBox（可同时选中多项，勾选态是"属于集合"）；
 * **开/关某个模式**用 AnimatedSwitch（如自动推进、公告启用）。
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface CheckBoxProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'aria-checked' | 'onChange' | 'role' | 'type' | 'onClick'
> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label?: ReactNode;
  ariaLabel?: string;
}

export function CheckBox({
  checked,
  onCheckedChange,
  label,
  ariaLabel,
  className = '',
  disabled,
  ...props
}: CheckBoxProps) {
  return (
    <button
      {...props}
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={`group/check inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] text-left outline-none disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      <span
        aria-hidden="true"
        className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[var(--radius-xs)] border transition-[background-color,border-color,box-shadow] duration-[var(--dur-fast)] ease-[var(--ease-standard)] group-focus-visible/check:ring-2 group-focus-visible/check:ring-[var(--accent)] group-focus-visible/check:ring-offset-2 group-focus-visible/check:ring-offset-[var(--bg-surface)] motion-reduce:transition-none ${
          checked
            ? 'border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-on)]'
            : 'border-[var(--border-strong)] bg-[var(--bg-surface)] text-transparent group-hover/check:border-[var(--accent)]'
        }`}
      >
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
          <path
            d="M3.5 8.5l3 3 6-6.5"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      {label ? <span className="min-w-0 select-none text-[var(--fg-2)]">{label}</span> : null}
    </button>
  );
}
