/*
 * 模块描述：顶栏语言切换入口，图标按钮 + 下拉菜单，供聊天页与模拟庭审页共用。
 */

import React, { useEffect, useRef, useState } from 'react';
import { Check, Globe } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useLocale, useTranslation } from '../contexts/LocaleContext';
import { LOCALE_LABELS, LOCALES } from '../locales';
import { HoverInfo } from './HoverInfo';

/** 选项一律用本语言自称，用户在任何当前语言下都能认出自己的母语。 */
export const LanguageMenu: React.FC = () => {
  const { locale, setLocale } = useLocale();
  const t = useTranslation();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (containerRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <HoverInfo label={t('settings.language.title')} placement="bottom" disabled={open}>
        <button
          type="button"
          onClick={() => setOpen(prev => !prev)}
          className={`lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors ${
            open
              ? 'bg-[var(--accent-quiet)] text-[var(--accent)]'
              : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'
          }`}
          aria-label={t('settings.language.title')}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <Globe size={18} strokeWidth={2} className="sm:size-5" />
        </button>
      </HoverInfo>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
            role="menu"
            className="absolute right-0 top-[calc(100%+0.375rem)] z-40 w-44 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-3)]"
          >
            {LOCALES.map(value => {
              const active = value === locale;
              return (
                <button
                  key={value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  lang={value}
                  onClick={() => {
                    setLocale(value);
                    setOpen(false);
                  }}
                  className={`lawver-pressable flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-3 py-2 text-left text-[13px] transition-colors ${
                    active
                      ? 'bg-[var(--accent-quiet)] font-semibold text-[var(--accent)]'
                      : 'text-[var(--fg-1)] hover:bg-[var(--bg-inset)]'
                  }`}
                >
                  {LOCALE_LABELS[value]}
                  {active && <Check size={14} strokeWidth={2.5} />}
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
