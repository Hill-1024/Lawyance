import { AnimatePresence, Reorder, motion, useReducedMotion } from "motion/react";
import { Gavel, Loader, Menu, MessageSquare, PenLine, Plus, X } from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { TabRef, tabKey } from "./tabs";
import { usePortalMenuDismiss } from "./usePortalMenu";

// 右键菜单是 portal 到 body 的：豁免列表里要有菜单自身的类名。
const TAB_MENU_SELECTORS = [".wb-tab-menu"] as const;
// 「+」的浮现菜单同理；触发按钮的容器也要在列，点「+」本身不算点外面。
const NEW_MENU_SELECTORS = [".wb-tab-new-menu", ".wb-tab-new-wrap"] as const;

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
  /** 「+」浮现菜单里的第二条路：新建模拟庭审。 */
  onCreateCourt: () => void;
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
  onCreateCourt,
  onNav,
}: Props) {
  const reduceMotion = useReducedMotion();
  const [menu, setMenu] = useState<{ x: number; y: number; tab: TabRef }>();
  const [newMenu, setNewMenu] = useState<{ top: number; left: number } | null>(null);
  const newMenuTimer = useRef<number | null>(null);
  const newMenuKeyboard = useRef(false);
  const newMenuItems = useRef<Array<HTMLButtonElement | null>>([]);
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
  const openNewMenu = useCallback(() => {
    const button = newTabButton.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const width = 200;
    setNewMenu({
      top: Math.round(rect.bottom + 6),
      left: Math.round(Math.max(8, Math.min(rect.left - 4, window.innerWidth - width - 8))),
    });
  }, []);
  const cancelNewMenuClose = useCallback(() => {
    if (newMenuTimer.current !== null) {
      window.clearTimeout(newMenuTimer.current);
      newMenuTimer.current = null;
    }
  }, []);
  const scheduleNewMenuClose = useCallback(() => {
    cancelNewMenuClose();
    // 宽限期：从「+」移到菜单上会先触发一次 mouseleave，立即关会让人够不着菜单项。
    newMenuTimer.current = window.setTimeout(() => setNewMenu(null), 240);
  }, [cancelNewMenuClose]);
  const openNewMenuSoon = useCallback(() => {
    cancelNewMenuClose();
    newMenuKeyboard.current = false;
    newMenuTimer.current = window.setTimeout(openNewMenu, 140);
  }, [cancelNewMenuClose, openNewMenu]);
  useEffect(() => () => cancelNewMenuClose(), [cancelNewMenuClose]);
  // 只有键盘打开时才把焦点移进菜单；悬停打开时抢焦点会打断正在做的事。
  useEffect(() => {
    if (!newMenu || !newMenuKeyboard.current) return;
    newMenuKeyboard.current = false;
    newMenuItems.current[0]?.focus();
  }, [newMenu]);
  usePortalMenuDismiss(newMenu !== null, () => setNewMenu(null), {
    selectors: NEW_MENU_SELECTORS,
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
                className={"wb-tab" + (key === activeKey ? " is-active" : "") + (isRunning ? " is-running" : "") + (!isRunning && state?.unseen ? " has-unseen" : "")}
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
      {/* 「+」是分裂控件：点它仍然新建会话（默认行为），鼠标悬停 / 按 ↓ / 长按右键
          才会浮现菜单，给出「会话」与「模拟庭审」两条路。菜单是整个移植里最容易漏的
          一类交互，所以悬停开、移开经 240ms 宽限关，键盘与触屏各留一条入口。 */}
      <div
        className="wb-tab-new-wrap"
        onMouseEnter={openNewMenuSoon}
        onMouseLeave={scheduleNewMenuClose}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setNewMenu(null);
        }}
      >
        <button
          className="wb-tab-new"
          aria-label="新建会话标签页"
          aria-haspopup="menu"
          aria-expanded={newMenu !== null}
          title="新建会话标签页（悬停或按 ↓ 可选择模拟庭审）"
          ref={newTabButton}
          onClick={() => {
            setNewMenu(null);
            onCreate();
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowDown") return;
            event.preventDefault();
            newMenuKeyboard.current = true;
            openNewMenu();
          }}
          onContextMenu={(event) => {
            // 触屏没有 hover：长按会走 contextmenu，这里同样浮出菜单。
            event.preventDefault();
            newMenuKeyboard.current = false;
            openNewMenu();
          }}
        >
          <Plus size={15} />
        </button>
      </div>
      {newMenu &&
        createPortal(
          <div
            className="wb-tab-menu wb-tab-new-menu"
            role="menu"
            aria-label="新建"
            style={{ position: "fixed", top: newMenu.top, left: newMenu.left }}
            onMouseEnter={cancelNewMenuClose}
            onMouseLeave={scheduleNewMenuClose}
          >
            <button
              role="menuitem"
              ref={(el) => {
                newMenuItems.current[0] = el;
              }}
              onClick={() => {
                setNewMenu(null);
                onCreate();
              }}
            >
              <MessageSquare size={14} />
              会话
            </button>
            <button
              role="menuitem"
              ref={(el) => {
                newMenuItems.current[1] = el;
              }}
              onClick={() => {
                setNewMenu(null);
                onCreateCourt();
              }}
            >
              <Gavel size={14} />
              模拟庭审
            </button>
          </div>,
          document.body,
        )}
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
