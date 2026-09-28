import React, { useState } from "react";
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
            取消
          </button>
        </header>
        <label>
          {withDescription ? "项目名称" : title}
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
          项目描述（可选）
          <textarea value={desc} maxLength={2000} rows={3}
            placeholder="简要说明项目背景、目标或需要关注的事项"
            onChange={e => setDesc(e.target.value)}
          />
        </label>}
        <button className="wb-primary" disabled={!text.trim() || busy}>
          {busy ? "正在保存…" : withDescription ? "创建项目" : "确认"}
        </button>
      </form>
    </div>
  );
}
