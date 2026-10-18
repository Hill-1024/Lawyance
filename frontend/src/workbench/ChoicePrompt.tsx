import React from "react";
import { Check, CircleHelp } from "lucide-react";
import { useT } from "../i18n";
import { describeError } from "../lib/errors";
import type { UserChoiceRequest } from "../types";

/**
 * ask_user 暂停后的选择卡片。
 *
 * 与旧版浮层不同，这里放在会话流里：问题、选项和提交路径都跟着 run 的状态走，
 * 刷新/换标签后从 run.data.pending_choice 恢复，不依赖浏览器里的临时状态。
 */
export function ChoicePrompt({
  choice,
  disabled = false,
  onSubmit,
}: {
  choice: UserChoiceRequest;
  disabled?: boolean;
  onSubmit: (value: string) => Promise<void>;
}) {
  const { t } = useT();
  const options = Array.isArray(choice.options) ? choice.options : [];
  const [selected, setSelected] = React.useState("");
  const [custom, setCustom] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    setSelected("");
    setCustom("");
    setError("");
    setSubmitting(false);
  }, [choice.id]);

  const selectedOption = options.find((option) => option.id === selected);
  const currentValue = custom.trim() || selectedOption?.value || "";

  async function submit(value?: string) {
    if (submitting || disabled) return;
    const answer = String(value ?? currentValue).trim();
    if (!answer) {
      setError(t("workbench.session.choiceNoSelection"));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(answer);
    } catch (cause) {
      setError(describeError(cause, t("workbench.session.choiceSubmitFailed")));
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Escape" && choice.allow_ignore) {
      event.preventDefault();
      void submit(choice.ignore_value || t("workbench.session.choiceIgnore"));
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <div
      className="wb-ask"
      role="group"
      aria-labelledby={`wb-ask-title-${choice.id}`}
      onKeyDown={handleKeyDown}
    >
      <div className="wb-ask-head">
        <span className="wb-ask-icon" aria-hidden="true">
          <CircleHelp size={17} strokeWidth={2.2} />
        </span>
        <div className="wb-ask-copy">
          <strong id={`wb-ask-title-${choice.id}`}>
            {t("workbench.session.choiceTitle")}
          </strong>
          <p className="wb-ask-question">{choice.question}</p>
          {options.length > 0 && (
            <p className="wb-ask-hint">{t("workbench.session.choiceHint")}</p>
          )}
        </div>
      </div>

      {options.length > 0 && (
        <div className="wb-ask-options" role="listbox" aria-label={t("workbench.session.choiceTitle")}>
          {options.map((option) => {
            const active = option.id === selected;
            return (
              <button
                key={option.id}
                type="button"
                role="option"
                aria-selected={active}
                className={"wb-ask-option" + (active ? " is-selected" : "")}
                disabled={submitting || disabled}
                onClick={() => {
                  setSelected(option.id);
                  setCustom("");
                  setError("");
                }}
                onDoubleClick={() => void submit(option.value)}
              >
                <span className="wb-ask-mark" aria-hidden="true">
                  {active && <Check size={12} strokeWidth={3} />}
                </span>
                <span className="wb-ask-option-copy">
                  <span className="wb-ask-option-label">{option.label}</span>
                  {option.description && (
                    <span className="wb-ask-option-desc">{option.description}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {choice.allow_free_text && (
        <label className="wb-ask-custom">
          <span>{t("workbench.session.choiceCustom")}</span>
          <input
            value={custom}
            disabled={submitting || disabled}
            placeholder={t("workbench.session.choiceCustomPlaceholder")}
            onChange={(event) => {
              setCustom(event.target.value);
              if (event.target.value.trim()) setSelected("");
              setError("");
            }}
          />
        </label>
      )}

      {error && (
        <p className="wb-ask-error" role="alert">
          {error}
        </p>
      )}

      <div className="wb-ask-actions">
        <button
          type="button"
          className="wb-ask-confirm"
          disabled={submitting || disabled || !currentValue}
          onClick={() => void submit()}
        >
          {submitting
            ? t("workbench.session.choiceSubmitting")
            : t("workbench.session.choiceConfirm")}
        </button>
        {choice.allow_ignore && (
          <button
            type="button"
            className="wb-ask-ignore"
            disabled={submitting || disabled}
            onClick={() =>
              void submit(choice.ignore_value || t("workbench.session.choiceIgnore"))
            }
          >
            {t("workbench.session.choiceIgnore")}
          </button>
        )}
      </div>
    </div>
  );
}
