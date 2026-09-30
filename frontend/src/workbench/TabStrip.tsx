import { AnimatePresence, Reorder, motion, useReducedMotion } from "motion/react";
import { Gavel, Loader, Menu, MessageSquare, PenLine, Plus, X } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { TabRef, tabKey } from "./tabs";
import { usePortalMenuDismiss } from "./usePortalMenu";

// 右键菜单是 portal 到 body 的：豁免列表里要有菜单自身的类名。
const TAB_MENU_SELECTORS = [".wb-tab-menu"] as const;

export type TabMenuItem = {
  label: string;
  icon?: React.ReactNode;
  danger?: boolean;
  onSelect: () => void;
};

type Props = {
  /** 空间键即换台动画的分组键：切换空间时整组左移穿过侧栏，新组从右侧进入。 */
  space: string;
  tabs: TabRef[];
  activeKey: string;
  titleOf: (tab: TabRef) => string;
  runs: Record<string, { status: string; unseen?: boolean }>;
  menuItems: (tab: TabRef) => TabMenuItem[];
  chrome: React.ReactNode;
  onActivate: (tab: TabRef) => void;
  onClose: (tab: TabRef) => void;
  onReorder: (tabs: TabRef[]) => void;
  onCreate: () => void;
  onNav: () => void;
};

const RUNNING = ["queued", "running", "waiting_confirmation"];
/** 关闭最后一个标签时没有邻标签可落焦，改落到「新建会话标签页」。 */
const NEW_TAB = "new-tab";

export function TabStrip({
  space,
  tabs,
  activeKey,
  titleOf,
  runs,
  menuItems,
  chrome,
  onActivate,
  onClose,
  onReorder,
  onCreate,
  onNav,
}: Props) {
  const reduceMotion = useReducedMotion();
  const [menu, setMenu] = useState<{ x: number; y: number; tab: TabRef }>();
  const dragged = useRef(false);
  const tabButtons = useRef(new Map<string, HTMLButtonElement>());
  const newTabButton = useRef<HTMLButtonElement>(null);
  // 关闭键被点掉的同时它也消失了，焦点会掉到 body，键盘用户就此丢掉位置；
  // 记下要接替的标签，等关闭提交完再落焦。
  const pendingFocus = useRef<string | null>(null);
  useEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    (target === NEW_TAB ? newTabButton.current : tabButtons.current.get(target))?.focus();
  });
  // 菜单 portal 到 body：豁免列表必须含菜单自身类名，否则鼠标按下菜单项时它已被卸载。
  usePortalMenuDismiss(menu !== undefined, () => setMenu(undefined), {
    selectors: TAB_MENU_SELECTORS,
    closeOnResize: true,
  });
  const group = (
    <motion.div
      className="wb-tabstrip-group"
      key={space}
      initial={reduceMotion ? { opacity: 0 } : { x: "106%", opacity: 0 }}
      animate={reduceMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
      exit={reduceMotion ? { opacity: 0 } : { x: "-106%", opacity: 0 }}
      // 换台用定时缓动而不是 spring：spring 收敛不了百分比位移，离场组会一直挂在 DOM 里。
      transition={
        reduceMotion
          ? { duration: 0.12 }
          : {
              x: { duration: 0.42, ease: [0.22, 0.9, 0.24, 1] },
              opacity: { duration: 0.22, ease: "easeOut" },
            }
      }
    >
      <Reorder.Group
        as="div"
        axis="x"
        className="wb-tabstrip-list"
        values={tabs}
        onReorder={onReorder}
      >
        <AnimatePresence initial={false}>
          {tabs.map((tab) => {
            const key = tabKey(tab);
            const state = runs[key];
            const isRunning = RUNNING.includes(state?.status || "");
            return (
              <Reorder.Item
                key={key}
                value={tab}
                className={"wb-tab" + (key === activeKey ? " is-active" : "")}
                onDragStart={() => {
                  dragged.current = true;
                }}
                onDragEnd={() => {
                  setTimeout(() => {
                    dragged.current = false;
                  }, 0);
                }}
                onContextMenu={(event) => {
                  event.preventDefault();
                  const width = Math.min(240, window.innerWidth - 16);
                  setMenu({
                    x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
                    y: event.clientY,
                    tab,
                  });
                }}
                exit={reduceMotion ? { opacity: 0 } : { opacity: 0, width: 0 }}
                transition={{ duration: reduceMotion ? 0.1 : 0.18, ease: [0.2, 0, 0, 1] }}
              >
                <button
                  className="wb-tab-button"
                  aria-current={key === activeKey ? "page" : undefined}
                  title={titleOf(tab)}
                  ref={(node) => {
                    if (node) tabButtons.current.set(key, node);
                    else tabButtons.current.delete(key);
                  }}
                  onClick={() => {
                    if (!dragged.current) onActivate(tab);
                  }}
                >
                  {tab.kind === "court" ? (
                    <Gavel size={14} />
                  ) : tab.kind === "new" ? (
                    // 空白标签用「书写」而不是「＋」：否则紧挨着真正的新建按钮，像凭空多出一个新会话按钮
                    <PenLine size={14} />
                  ) : (
                    <MessageSquare size={14} />
                  )}
                  <span>{titleOf(tab)}</span>
                  {isRunning && (
                    <span className="wb-tab-running" role="status" aria-label="任务运行中">
                      <Loader size={12} className="wb-spin" />
                    </span>
                  )}
                  {!isRunning && state?.unseen && (
                    <span className="wb-tab-unseen" role="status" aria-label="已有新结果" />
                  )}
                </button>
                {/* 空间仅剩这一个空白标签时不给关闭键：关掉它也会立刻补一个新的，等于点了没反应 */}
                {!(tab.kind === "new" && tabs.length === 1) && (
                  <button
                    className="wb-tab-close"
                    aria-label={"关闭 " + titleOf(tab)}
                    onClick={() => {
                      const index = tabs.findIndex((item) => tabKey(item) === key);
                      const neighbour = tabs[index + 1] || tabs[index - 1];
                      pendingFocus.current = neighbour ? tabKey(neighbour) : NEW_TAB;
                      onClose(tab);
                    }}
                  >
                    <X size={12} />
                  </button>
                )}
              </Reorder.Item>
            );
          })}
        </AnimatePresence>
      </Reorder.Group>
      <button
        className="wb-tab-new"
        aria-label="新建会话标签页"
        title="新建会话标签页"
        ref={newTabButton}
        onClick={onCreate}
      >
        <Plus size={15} />
      </button>
    </motion.div>
  );
  return (
    <div className="wb-tabstrip" data-tour="wb-tabstrip">
      <button
        className="wb-mobile-only wb-tabstrip-nav"
        data-tour="wb-nav-toggle"
        aria-label="打开导航"
        onClick={onNav}
      >
        <Menu size={19} />
      </button>
      <div className="wb-tabstrip-viewport">
        {/* 换台顺序：旧组滑出侧栏 → 新组从右侧滑入停靠；wait 模式避免两组同屏残留。 */}
        <AnimatePresence initial={false} mode="wait">
          {group}
        </AnimatePresence>
      </div>
      {chrome}
      {menu &&
        createPortal(
          <div
            className="wb-tab-menu"
            role="menu"
            aria-label={titleOf(menu.tab) + " 标签操作"}
            style={{ position: "fixed", top: menu.y, left: menu.x }}
          >
            {menuItems(menu.tab).map((item) => (
              <button
                key={item.label}
                role="menuitem"
                className={item.danger ? "danger" : ""}
                onClick={() => {
                  setMenu(undefined);
                  item.onSelect();
                }}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
