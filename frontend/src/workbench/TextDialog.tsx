import React, { useState } from "react";
import { useT } from "../i18n";
export function TextDialog({
  title,
  initial = "",
  withDescription = false,
  onSubmit,
  onClose,
}: {
  title: string;
  initial?: string;
  withDescription?: boolean;
  onSubmit: (text: string, desc?: string) => void | Promise<void>;
  onClose: () => void;
}) {
  const { t } = useT();
  const [text, setText] = useState(initial);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div
      className="wb-modal-backdrop"
      // 点遮罩关闭、Esc 关闭都挂在遮罩上：原来只有输入框自己监听了 Esc，
      // 一旦焦点移到描述框或按钮，这个对话框就再也关不掉。
      onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape" && !busy) { e.stopPropagation(); onClose(); } }}
    >
      <form
        className="wb-modal wb-small-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!text.trim() || busy) return;
          setBusy(true);
          try { await onSubmit(text.trim(), withDescription ? desc.trim() : undefined); }
          finally { setBusy(false); }
        }}
      >
        <header>
          <h2>{title}</h2>
          <button type="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </header>
        <label>
          {withDescription ? t("workbench.textDialog.projectName") : title}
          <input
            autoFocus
            value={text}
            maxLength={300}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing && e.key === "Enter")
                e.preventDefault();
            }}
          />
        </label>
        {withDescription && <label>
          {t("workbench.textDialog.projectDesc")}
          <textarea value={desc} maxLength={2000} rows={3}
            placeholder={t("workbench.textDialog.projectDescPlaceholder")}
            onChange={e => setDesc(e.target.value)}
          />
        </label>}
        <button className="wb-primary" disabled={!text.trim() || busy}>
          {busy ? t("workbench.textDialog.saving") : withDescription ? t("workbench.sidebar.newProject") : t("common.confirm")}
        </button>
      </form>
    </div>
  );
}
