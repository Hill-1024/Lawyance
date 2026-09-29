import { ChevronDown, Gavel, History, MessageSquare, Plus } from "lucide-react";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Item } from "./client";
import { getBinding, matchKeys, SHORTCUT_IDS } from "../lib/shortcuts";

/** 标签条右端的会话历史入口：下拉里是该空间的会话与庭审，外加新建会话。 */
export type HistoryMenuProps = {
  conversations: Item[];
  courts: Item[];
  currentConvId?: string;
  currentCourtId?: string;
  open: boolean;
  buttonRef: React.RefObject<HTMLButtonElement>;
  onToggle: (open: boolean) => void;
  onOpenConversation: (id: string) => void;
  onOpenCourt: (id: string) => void;
  onNewSession: () => void;
};

export function HistoryMenu({
  conversations,
  courts,
  currentConvId,
  currentCourtId,
  open,
  buttonRef,
  onToggle,
  onOpenConversation,
  onOpenCourt,
  onNewSession,
}: HistoryMenuProps) {
  const [pos, setPos] = useState<{ top: number; left: number }>();
  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 16);
    setPos({
      top: rect.bottom + 6,
      left: Math.max(
        8,
        Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8),
      ),
    });
  }, [open, buttonRef]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest?.(".wb-thread-history")) onToggle(false);
    };
    const esc = (event: KeyboardEvent) => {
      if (matchKeys(event, getBinding(SHORTCUT_IDS.overlayClose))) onToggle(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open, onToggle]);
  return (
    <div className="wb-thread-history">
      <button
        ref={buttonRef}
        aria-label="会话历史"
        aria-expanded={open}
        onClick={() => onToggle(!open)}
      >
        <History size={15} />
        <ChevronDown size={12} />
      </button>
      {open &&
        createPortal(
          <div
            className="wb-thread-menu"
            role="menu"
            aria-label="会话历史"
            style={{ position: "fixed", top: pos?.top, left: pos?.left }}
          >
            {conversations.map((item) => (
              <button
                key={item.id}
                role="menuitem"
                className={currentConvId === item.id ? "selected" : ""}
                onClick={() => {
                  onToggle(false);
                  onOpenConversation(item.id);
                }}
              >
                <MessageSquare size={14} />
                <span>{item.title}</span>
                <small>
                  {new Date(item.updated_at).toDateString() === new Date().toDateString()
                    ? "今天"
                    : new Date(item.updated_at).toLocaleDateString()}
                </small>
              </button>
            ))}
            {!!courts.length && <small className="wb-thread-group">模拟庭审</small>}
            {courts.map((item) => (
              <button
                key={item.id}
                role="menuitem"
                className={currentCourtId === item.id ? "selected" : ""}
                onClick={() => {
                  onToggle(false);
                  onOpenCourt(item.id);
                }}
              >
                <Gavel size={14} />
                <span>{item.title}</span>
              </button>
            ))}
            {!conversations.length && !courts.length && (
              <p className="wb-space-hint">还没有会话，发送第一条消息即开始。</p>
            )}
            <button
              role="menuitem"
              onClick={() => {
                onToggle(false);
                onNewSession();
              }}
            >
              <Plus size={14} />
              新会话
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}
