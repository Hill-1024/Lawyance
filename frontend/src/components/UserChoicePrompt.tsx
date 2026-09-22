/*
 * 模块描述：输入区上方的待确认选项浮层，支持鼠标选择、双击确认和键盘确认。
 */

import React from 'react';
import { Check, CircleHelp } from 'lucide-react';
import { motion } from 'motion/react';
import type { UserChoiceRequest } from '../types';

type ChoicePrompt = {
  messageId: string;
  choice: UserChoiceRequest;
};

interface UserChoicePromptProps {
  prompt: ChoicePrompt;
  disabled?: boolean;
  style?: React.CSSProperties;
  onAnswerChoice: (messageId: string, value: string) => void;
}

export const UserChoicePrompt = React.forwardRef<HTMLDivElement, UserChoicePromptProps>(({
  prompt,
  disabled = false,
  style,
  onAnswerChoice
}, ref) => {
  const { messageId, choice } = prompt;
  const choices = choice.options;
  const [activeChoiceId, setActiveChoiceId] = React.useState(() => choices[0]?.id || '');
  const [customChoice, setCustomChoice] = React.useState('');
  const promptRootRef = React.useRef<HTMLDivElement | null>(null);
  const optionRefs = React.useRef<Record<string, HTMLButtonElement | null>>({});
  const customInputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const nextId = choices[0]?.id || '';
    setActiveChoiceId(nextId);
    setCustomChoice('');
    window.requestAnimationFrame(() => {
      if (nextId) {
        optionRefs.current[nextId]?.focus();
      } else if (choice.allow_free_text) {
        customInputRef.current?.focus();
      }
    });
  }, [choice.id, messageId, choice.allow_free_text, choices]);

  const activeIndex = choices.findIndex(item => item.id === activeChoiceId);
  const activeChoice = activeIndex >= 0 ? choices[activeIndex] : null;
  const customAnswer = customChoice.trim();
  const confirmAnswer = customAnswer || activeChoice?.value || '';
  const promptTitleId = `choice-prompt-title-${messageId}`;
  const promptQuestionId = `choice-prompt-question-${messageId}`;
  const ignoreAnswer = choice.ignore_value || '忽略此问题，请根据现有信息自行判断并继续。';

  const confirmValue = React.useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onAnswerChoice(messageId, trimmed);
    setCustomChoice('');
  }, [disabled, messageId, onAnswerChoice]);

  const selectChoice = React.useCallback((choiceId: string) => {
    setActiveChoiceId(choiceId);
    setCustomChoice('');
  }, []);

  const focusChoiceAt = React.useCallback((index: number) => {
    if (choices.length === 0) return;
    const nextIndex = (index + choices.length) % choices.length;
    const nextChoice = choices[nextIndex];
    selectChoice(nextChoice.id);
    window.requestAnimationFrame(() => {
      optionRefs.current[nextChoice.id]?.focus();
    });
  }, [choices, selectChoice]);

  const handleChoiceKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    const isTextField = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA';

    if (event.key === 'Tab') {
      const current = document.activeElement as HTMLElement | null;
      const choiceTargets = choices
        .map(item => optionRefs.current[item.id])
        .filter((element): element is HTMLButtonElement => Boolean(element && element.offsetParent !== null && !element.disabled));
      const customInput = choice.allow_free_text && customInputRef.current && !customInputRef.current.disabled
        ? customInputRef.current
        : null;
      const focusable = customInput
        ? [...choiceTargets, customInput]
        : choiceTargets;
      if (focusable.length === 0) return;

      const currentIndex = current ? focusable.findIndex(element => element === current) : -1;
      const nextIndex = event.shiftKey
        ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
        : (currentIndex < 0 || currentIndex >= focusable.length - 1 ? 0 : currentIndex + 1);
      event.preventDefault();
      const nextElement = focusable[nextIndex];
      const nextChoiceId = nextElement instanceof HTMLButtonElement ? nextElement.dataset.choiceId : '';
      if (nextChoiceId) {
        selectChoice(nextChoiceId);
        window.requestAnimationFrame(() => {
          optionRefs.current[nextChoiceId]?.focus();
        });
      } else {
        setActiveChoiceId('');
        window.requestAnimationFrame(() => {
          customInputRef.current?.focus();
        });
      }
      return;
    }

    if (event.key === 'Escape' && choice.allow_ignore) {
      event.preventDefault();
      confirmValue(ignoreAnswer);
      return;
    }

    if (disabled || choices.length === 0 || isTextField) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      event.preventDefault();
      focusChoiceAt(activeIndex >= 0 ? activeIndex + 1 : 0);
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
      event.preventDefault();
      focusChoiceAt(activeIndex >= 0 ? activeIndex - 1 : choices.length - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusChoiceAt(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusChoiceAt(choices.length - 1);
    }

    const optionButton = target?.closest<HTMLButtonElement>('[role="option"]');
    if (!optionButton) return;

    if (event.key === 'Enter') {
      const optionId = optionButton.dataset.choiceId;
      const option = choices.find(item => item.id === optionId);
      if (!option) return;
      event.preventDefault();
      confirmValue(option.value);
    } else if (event.key === ' ') {
      const optionId = optionButton.dataset.choiceId;
      if (!optionId) return;
      event.preventDefault();
      selectChoice(optionId);
    }
  };

  const setRootRef = React.useCallback((node: HTMLDivElement | null) => {
    promptRootRef.current = node;
    if (typeof ref === 'function') {
      ref(node);
    } else if (ref) {
      ref.current = node;
    }
  }, [ref]);

  return (
    <motion.div
      ref={setRootRef}
      key={`${messageId}:${choice.id}`}
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
      data-testid="active-user-choice-prompt"
      role="dialog"
      aria-labelledby={promptTitleId}
      aria-describedby={promptQuestionId}
      style={style}
      onKeyDown={handleChoiceKeyDown}
      className="lawver-choice-prompt glass lawver-popover z-[25] mb-2 flex max-h-[min(58dvh,420px)] w-full min-w-0 flex-col overflow-hidden rounded-[8px] border border-[var(--glass-border)] bg-[var(--glass-bg)] p-3 text-[var(--fg-1)] shadow-[var(--shadow-5)] backdrop-blur-xl sm:mb-3 sm:p-4"
    >
      <div className="flex min-h-0 min-w-0 items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-[var(--accent-quiet)] text-[var(--accent)]">
          <CircleHelp size={17} strokeWidth={2.2} />
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
            <div className="min-w-0">
              <div className="flex items-center justify-between">
                <div id={promptTitleId} className="text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-[var(--fg-3)]">
                  需要确认
                </div>
                {choices.length > 0 && (
                  <div className="pointer-events-none flex items-center gap-1 opacity-80" aria-hidden="true">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className="h-[18px] w-[18px] text-[var(--fg-4)]">
                      <path fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="m3 8l4-4l4 4M7 4v9m6 3l4 4l4-4m-4-6v10" />
                    </svg>
                    <kbd className="rounded-[5px] border border-[var(--border-default)] bg-[rgba(20,23,31,0.06)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--fg-4)] dark:bg-white/[0.08]">
                      Tab
                    </kbd>
                  </div>
                )}
              </div>
              <p id={promptQuestionId} className="mt-2 whitespace-pre-wrap break-words text-[15px] leading-6 text-[var(--fg-1)]">
                {choice.question}
              </p>
            </div>

            {choices.length > 0 && (
              <div className="relative min-w-0">
                <div
                  role="listbox"
                  aria-activedescendant={activeChoice ? `choice-option-${messageId}-${activeChoice.id}` : undefined}
                  className="grid min-w-0 grid-cols-1 gap-2"
                >
                  {choices.map(item => {
                    const isActive = item.id === activeChoice?.id;
                    return (
                      <button
                        key={item.id}
                        id={`choice-option-${messageId}-${item.id}`}
                        type="button"
                        role="option"
                        data-choice-id={item.id}
                        aria-keyshortcuts="Enter"
                        aria-selected={isActive}
                        tabIndex={isActive ? 0 : -1}
                        disabled={disabled}
                        ref={(node) => {
                          optionRefs.current[item.id] = node;
                        }}
                        onClick={() => selectChoice(item.id)}
                        onDoubleClick={() => confirmValue(item.value)}
                        className={`lawver-pressable flex min-h-11 w-full min-w-0 items-start gap-2 rounded-[8px] border px-3 py-2.5 text-left transition-colors ${
                          isActive
                            ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--accent)]'
                            : 'border-[var(--border-default)] bg-[var(--bg-inset)] text-[var(--fg-1)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-surface-2)]'
                        } ${disabled ? 'cursor-default opacity-60' : ''}`}
                      >
                        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full border ${isActive ? 'border-[var(--accent)] bg-[var(--accent)]' : 'border-[var(--fg-4)]'}`} />
                        <span className="flex min-w-0 flex-1 flex-col gap-1">
                          <span className="break-words text-sm font-medium leading-5">{item.label}</span>
                          {item.description && (
                            <span className="break-words text-xs leading-5 text-[var(--fg-3)]">{item.description}</span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {choice.allow_free_text && (
              <form
                className="flex min-w-0 items-center"
                onSubmit={(event) => {
                  event.preventDefault();
                  confirmValue(customChoice);
                }}
              >
                <input
                  ref={customInputRef}
                  value={customChoice}
                  onFocus={() => setActiveChoiceId('')}
                  onChange={(event) => {
                    setActiveChoiceId('');
                    setCustomChoice(event.target.value);
                  }}
                  disabled={disabled}
                  placeholder={choice.free_text_label || '自定义'}
                  className="lawver-choice-custom-input min-w-0 flex-1 rounded-[8px] border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm text-[var(--fg-1)] outline-none placeholder:text-[var(--fg-4)] focus:border-[var(--accent)] focus:ring-0 disabled:opacity-60"
                />
              </form>
            )}
          </div>

          <div className={`flex min-w-0 shrink-0 items-center gap-2 border-t border-[var(--border-default)] pt-3 ${choice.allow_ignore ? 'justify-between' : 'justify-end'}`}>
            {choice.allow_ignore && (
              <button
                type="button"
                tabIndex={-1}
                disabled={disabled}
                onClick={() => confirmValue(ignoreAnswer)}
                className="lawver-pressable inline-flex min-h-10 min-w-0 max-w-[48%] items-center justify-center gap-2 rounded-[8px] border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm font-medium text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)] disabled:cursor-default disabled:opacity-60"
                aria-keyshortcuts="Escape"
              >
                <span className="min-w-0 truncate">{choice.ignore_label || '忽略此问题'}</span>
                <kbd className="shrink-0 rounded-[5px] border border-[var(--border-default)] bg-[rgba(20,23,31,0.06)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--fg-4)] dark:bg-white/[0.08]">
                  Esc
                </kbd>
              </button>
            )}

            <button
              type="button"
              tabIndex={-1}
              disabled={disabled || !confirmAnswer}
              onClick={() => confirmValue(confirmAnswer)}
              className="lawver-pressable inline-flex min-h-10 min-w-0 max-w-[48%] items-center justify-center gap-2 rounded-[8px] bg-[var(--accent)] px-3 py-2 text-sm font-medium text-[var(--accent-on)] shadow-[var(--shadow-1)] transition-colors hover:bg-[var(--accent-hover)] disabled:cursor-default disabled:bg-[rgba(20,23,31,0.08)] disabled:text-[var(--fg-4)] disabled:shadow-none dark:disabled:bg-white/[0.08]"
              aria-keyshortcuts="Enter"
            >
              <span className="flex min-w-0 items-center gap-2">
                <Check size={16} strokeWidth={2.2} className="shrink-0" />
                <span className="truncate">确认</span>
              </span>
              <kbd className="shrink-0 rounded-[5px] border border-white/20 bg-white/20 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white/75">
                Enter
              </kbd>
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
});

UserChoicePrompt.displayName = 'UserChoicePrompt';
