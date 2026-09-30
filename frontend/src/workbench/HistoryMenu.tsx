import { ChevronDown, Gavel, History, MessageSquare, Plus } from "lucide-react";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Item } from "./client";
import { usePortalMenuDismiss } from "./usePortalMenu";

// 菜单 portal 到 body，必须把菜单自身类名也列进来，否则按下菜单项时菜单已被卸载。
const KEEP_OPEN_SELECTORS = [".wb-thread-menu", ".wb-thread-history"] as const;

/** 标签条右端的会话历史入口：下拉里是该空间的会话与庭审，外加新建会话/庭审。 */
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
  onNewCourt: () => void;
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
  onNewCourt,
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
  usePortalMenuDismiss(open, () => onToggle(false), { selectors: KEEP_OPEN_SELECTORS });
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
            {/* 此前全应用没有发起新建庭审的入口：/court/new 只能靠手输地址，而那条路径
                又会被标签清理 effect 弹回 /home（同一张卡的另一半）。 */}
            <button
              role="menuitem"
              onClick={() => {
                onToggle(false);
                onNewCourt();
              }}
            >
              <Gavel size={14} />
              新建庭审
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}
