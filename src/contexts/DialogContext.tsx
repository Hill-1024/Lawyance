/*
 * 模块描述：全局自实现弹窗上下文，替代浏览器原生 alert / confirm。
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, ShieldAlert } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

type DialogTone = 'info' | 'success' | 'warning' | 'danger';

interface DialogOptions {
  title?: string;
  message: React.ReactNode;
  tone?: DialogTone;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface DialogRequest extends Required<Pick<DialogOptions, 'message' | 'tone' | 'confirmLabel'>> {
  id: number;
  kind: 'alert' | 'confirm';
  title: string;
  cancelLabel: string;
  resolve: (value: boolean) => void;
}

interface DialogContextValue {
  showAlert: (options: string | DialogOptions) => Promise<void>;
  showConfirm: (options: DialogOptions) => Promise<boolean>;
}

const DialogContext = createContext<DialogContextValue | null>(null);

const toneMeta: Record<DialogTone, {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  iconClass: string;
  title: string;
}> = {
  info: {
    icon: Info,
    iconClass: 'bg-[var(--accent-quiet)] text-[var(--accent)]',
    title: '提示',
  },
  success: {
    icon: CheckCircle2,
    iconClass: 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]',
    title: '已完成',
  },
  warning: {
    icon: AlertTriangle,
    iconClass: 'bg-[rgba(184,132,42,0.14)] text-[var(--color-warning-500)]',
    title: '请注意',
  },
  danger: {
    icon: ShieldAlert,
    iconClass: 'bg-[rgba(176,70,62,0.12)] text-[var(--color-danger-500)]',
    title: '需要确认',
  },
};

let dialogId = 0;

const normalizeAlertOptions = (options: string | DialogOptions): DialogOptions => (
  typeof options === 'string' ? { message: options } : options
);

export const DialogProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeDialog, setActiveDialog] = useState<DialogRequest | null>(null);
  const activeDialogRef = useRef<DialogRequest | null>(null);
  const queueRef = useRef<DialogRequest[]>([]);

  useEffect(() => {
    activeDialogRef.current = activeDialog;
  }, [activeDialog]);

  const openNextDialog = useCallback(() => {
    if (activeDialogRef.current) return;
    const next = queueRef.current.shift() || null;
    activeDialogRef.current = next;
    setActiveDialog(next);
  }, []);

  const enqueueDialog = useCallback((request: Omit<DialogRequest, 'id' | 'resolve'>) => (
    new Promise<boolean>(resolve => {
      queueRef.current.push({
        ...request,
        id: ++dialogId,
        resolve,
      });
      openNextDialog();
    })
  ), [openNextDialog]);

  const settleDialog = useCallback((value: boolean) => {
    const current = activeDialogRef.current;
    if (!current) return;

    current.resolve(value);
    activeDialogRef.current = null;
    setActiveDialog(null);
    window.setTimeout(openNextDialog, 0);
  }, [openNextDialog]);

  const showAlert = useCallback(async (options: string | DialogOptions) => {
    const normalized = normalizeAlertOptions(options);
    const tone = normalized.tone || 'info';
    await enqueueDialog({
      kind: 'alert',
      tone,
      title: normalized.title || toneMeta[tone].title,
      message: normalized.message,
      confirmLabel: normalized.confirmLabel || '知道了',
      cancelLabel: normalized.cancelLabel || '取消',
    });
  }, [enqueueDialog]);

  const showConfirm = useCallback((options: DialogOptions) => {
    const tone = options.tone || 'warning';
    return enqueueDialog({
      kind: 'confirm',
      tone,
      title: options.title || toneMeta[tone].title,
      message: options.message,
      confirmLabel: options.confirmLabel || '确认',
      cancelLabel: options.cancelLabel || '取消',
    });
  }, [enqueueDialog]);

  useEffect(() => {
    if (!activeDialog) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        settleDialog(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeDialog, settleDialog]);

  const value = useMemo<DialogContextValue>(() => ({
    showAlert,
    showConfirm,
  }), [showAlert, showConfirm]);

  const Icon = activeDialog ? toneMeta[activeDialog.tone].icon : Info;

  return (
    <DialogContext.Provider value={value}>
      {children}
      <AnimatePresence>
        {activeDialog && (
          <div className="fixed inset-0 z-[1200] flex min-h-[100dvh] items-center justify-center p-4">
            <motion.div
              key={`dialog-overlay-${activeDialog.id}`}
              className="absolute inset-0 bg-[var(--bg-overlay)] backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18, ease: [0.2, 0, 0, 1] }}
              onClick={() => settleDialog(false)}
              aria-hidden="true"
            />
            <motion.div
              key={`dialog-card-${activeDialog.id}`}
              role={activeDialog.kind === 'confirm' ? 'alertdialog' : 'dialog'}
              aria-modal="true"
              aria-labelledby="lawver-dialog-title"
              aria-describedby="lawver-dialog-message"
              className="relative w-full max-w-md overflow-hidden rounded-[28px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-1)] shadow-[var(--shadow-5)]"
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
            >
              <div className="flex gap-4 px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${toneMeta[activeDialog.tone].iconClass}`}>
                  <Icon className="h-5 w-5" strokeWidth={2} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 id="lawver-dialog-title" className="t-title-l break-words">
                    {activeDialog.title}
                  </h2>
                  <div id="lawver-dialog-message" className="mt-2 whitespace-pre-line break-words text-sm leading-6 text-[var(--fg-3)]">
                    {activeDialog.message}
                  </div>
                </div>
              </div>
              <div className="flex justify-end gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-5 py-4 sm:px-6">
                {activeDialog.kind === 'confirm' && (
                  <button
                    type="button"
                    className="md3-btn-text px-4 py-2"
                    onClick={() => settleDialog(false)}
                    autoFocus
                  >
                    {activeDialog.cancelLabel}
                  </button>
                )}
                <button
                  type="button"
                  className={activeDialog.tone === 'danger' ? 'md3-btn-tonal !text-[var(--color-danger-500)] px-4 py-2' : 'md3-btn-tonal px-4 py-2'}
                  onClick={() => settleDialog(true)}
                  autoFocus={activeDialog.kind === 'alert'}
                >
                  {activeDialog.confirmLabel}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </DialogContext.Provider>
  );
};

export const useAppDialog = () => {
  const context = useContext(DialogContext);
  if (!context) {
    throw new Error('useAppDialog must be used within DialogProvider');
  }
  return context;
};
