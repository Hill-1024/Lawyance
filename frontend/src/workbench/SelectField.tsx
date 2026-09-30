/*
 * 模块描述：工作台的下拉选择控件，替代原生 <select>。
 *
 * 原生 select 的字色、圆角、箭头与展开态都由浏览器决定，和这套 UI 不同源——在输入框
 * 展开的「任务模式」里一眼就能看出违和（灰色方角输入条 + 系统箭头 + 系统下拉）。
 * 这里改成「胶囊按钮 + portal 菜单」，与标签菜单、空间菜单共用同一套观感与关闭逻辑
 * （usePortalMenuDismiss：外部点击、Escape、视口变化）。
 */

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { usePortalMenuDismiss } from "./usePortalMenu";

export type SelectOption = { value: string; label: string };

// 菜单 portal 到 body：豁免列表要含菜单自身类名，否则按下菜单项时它已被卸载。
const SELECT_MENU_SELECTORS = [".wb-select-menu", ".wb-select"] as const;

export function SelectField({
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label?: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<{ top: number; left: number } | null>(null);
  const current = options.find((option) => option.value === value) ?? options[0];
  const labelId = useId();
  const valueId = useId();

  const open = useCallback(() => {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    setMenu({
      top: Math.round(rect.bottom + 6),
      left: Math.round(Math.max(8, Math.min(rect.left, window.innerWidth - 168))),
    });
  }, []);

  usePortalMenuDismiss(menu !== null, () => setMenu(null), {
    selectors: SELECT_MENU_SELECTORS,
    closeOnResize: true,
  });
  useEffect(() => {
    if (disabled) setMenu(null);
  }, [disabled]);

  return (
    <span className="wb-select">
      {label && (
        <span className="wb-select-label" id={labelId}>
          {label}
        </span>
      )}
      {/* 可访问名用 aria-labelledby 拼「标签 + 当前值」，不用 aria-label：
          全局那条 `button[aria-label]:has(> .lucide:only-child)` 会把这种按钮当纯图标按钮
          压成 32×32，文字立刻折行。这里同时把当前值包进 span，子元素不再只有一个图标。 */}
      <button
        ref={buttonRef}
        type="button"
        className="wb-select-button"
        aria-haspopup="listbox"
        aria-expanded={menu !== null}
        aria-labelledby={label ? `${labelId} ${valueId}` : valueId}
        disabled={disabled}
        onClick={() => (menu ? setMenu(null) : open())}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" || menu) return;
          event.preventDefault();
          open();
        }}
      >
        <span id={valueId}>{current?.label}</span>
        <ChevronDown size={12} strokeWidth={2} aria-hidden="true" />
      </button>
      {menu &&
        createPortal(
          <div
            className="wb-tab-menu wb-select-menu"
            role="listbox"
            aria-label={label || "选择"}
            style={{ position: "fixed", top: menu.top, left: menu.left }}
          >
            {options.map((option) => {
              const selected = option.value === value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={selected ? "wb-select-option is-selected" : "wb-select-option"}
                  onClick={() => {
                    setMenu(null);
                    if (!selected) onChange(option.value);
                  }}
                >
                  <span className="wb-select-check" aria-hidden="true">
                    {selected ? <Check size={13} strokeWidth={2.4} /> : null}
                  </span>
                  {option.label}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </span>
  );
}
