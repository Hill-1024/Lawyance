/*
 * 模块描述：通用动画开关组件，统一 switch 语义、轨道/滑块动效和焦点状态。
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';

type SwitchSize = 'sm' | 'md';

interface AnimatedSwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'role'> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label?: ReactNode;
  labelPosition?: 'left' | 'right';
  size?: SwitchSize;
  ariaLabel?: string;
}

const switchSizes: Record<SwitchSize, { track: string; thumb: string; off: string; on: string }> = {
  sm: {
    track: 'h-5 w-9',
    thumb: 'h-4 w-4',
    off: 'translate-x-0.5',
    on: 'translate-x-[18px]',
  },
  md: {
    track: 'h-6 w-11',
    thumb: 'h-4 w-4',
    off: 'translate-x-1',
    on: 'translate-x-6',
  },
};

export function AnimatedSwitch({
  checked,
  onCheckedChange,
  label,
  labelPosition = 'right',
  size = 'md',
  ariaLabel,
  className = '',
  disabled,
  onClick,
  ...props
}: AnimatedSwitchProps) {
  const sizing = switchSizes[size];
  const labelNode = label ? (
    <span className="select-none text-sm text-[var(--fg-2)]">{label}</span>
  ) : null;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onCheckedChange(!checked);
        }
      }}
      className={`group/switch inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-full outline-none disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    >
      {labelPosition === 'left' && labelNode}
      <span
        aria-hidden="true"
        className={`${sizing.track} relative inline-flex shrink-0 overflow-hidden rounded-full transition-[background-color,box-shadow,transform] duration-300 ease-[var(--ease-emphasized)] group-active/switch:scale-[0.97] group-focus-visible/switch:ring-2 group-focus-visible/switch:ring-[var(--accent)] group-focus-visible/switch:ring-offset-2 group-focus-visible/switch:ring-offset-[var(--bg-surface)] motion-reduce:transition-none ${
          checked
            ? 'bg-[var(--accent)] shadow-[0_0_0_1px_rgba(59,98,184,0.22)]'
            : 'bg-[rgba(20,23,31,0.12)] shadow-[inset_0_0_0_1px_rgba(20,23,31,0.05)] group-hover/switch:bg-[rgba(20,23,31,0.16)] dark:bg-white/[0.1] dark:group-hover/switch:bg-white/[0.16]'
        }`}
      >
        <span
          className={`pointer-events-none absolute inset-0 rounded-full bg-[linear-gradient(120deg,rgba(255,255,255,0.36),rgba(255,255,255,0)_48%,rgba(255,255,255,0.18))] transition-opacity duration-300 motion-reduce:transition-none ${
            checked ? 'opacity-100' : 'opacity-0'
          }`}
        />
        <span
          className={`${sizing.thumb} pointer-events-none absolute left-0 top-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_1px_3px_rgba(20,23,31,0.24),0_0_0_1px_rgba(20,23,31,0.04)] transition-[transform,box-shadow] duration-300 ease-[var(--ease-spring)] group-hover/switch:shadow-[0_2px_6px_rgba(20,23,31,0.28),0_0_0_1px_rgba(20,23,31,0.04)] motion-reduce:transition-none ${
            checked ? sizing.on : sizing.off
          }`}
        />
      </span>
      {labelPosition === 'right' && labelNode}
    </button>
  );
}
