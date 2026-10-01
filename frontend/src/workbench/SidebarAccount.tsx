/*
 * 模块描述：工作台侧栏底部的账户入口——头像 + @自定义 ID + 订阅徽标，替代原先
 * 一行纯文本用户名。悬停/点击浮出菜单：非交互的用户 ID 行、个人资料、退出登录，
 * 与介绍页右上角同一套信息与交互约定（120ms 悬停意图、200ms 离开宽限、Esc/外点关闭）。
 *
 * 浮层 portal 到 body、position:fixed、按触发器实测矩形定位并**夹取在视窗内**：
 * 窄抽屉/移动布局里「右对齐 + 绝对定位」会把菜单推出视窗（x 为负、底部越界）。
 * 优先贴触发器上方，上方放不下就翻到下方，再不行就近夹取；层高取抽屉之上，
 * 避免 portal 到 body 后被移动端抽屉盖住。
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChartColumn, LogOut, Sparkles, UserRound } from "lucide-react";
import { AccountAvatar, PLAN_BADGES, PLAN_LABEL_KEYS } from "../components/AccountIdentity";
import { logout, type AccountProfile } from "../services/api";
import { useT, type MessageKey } from "../i18n";
import { usePortalMenuDismiss } from "./usePortalMenu";

export function SidebarAccount({
  profile,
  username,
  onOpen,
}: {
  profile: AccountProfile | null;
  username: string;
  onOpen: (view: string) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<FlyoutPos | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const flyoutRef = useRef<HTMLDivElement>(null);
  const hoverTimers = useRef<{ open?: number; close?: number }>({});

  // 外点/Esc 关闭；豁免名单含 portal 后的菜单自身类名，点菜单项不会被当成外点关掉。
  usePortalMenuDismiss(open, () => setOpen(false), {
    selectors: [".wb-account", ".wb-account__flyout"],
    closeOnResize: true,
  });

  useEffect(
    () => () => {
      window.clearTimeout(hoverTimers.current.open);
      window.clearTimeout(hoverTimers.current.close);
    },
    [],
  );

  const scheduleOpen = useCallback(() => {
    window.clearTimeout(hoverTimers.current.close);
    hoverTimers.current.open = window.setTimeout(() => setOpen(true), 120);
  }, []);

  const scheduleClose = useCallback(() => {
    window.clearTimeout(hoverTimers.current.open);
    hoverTimers.current.close = window.setTimeout(() => setOpen(false), 200);
  }, []);

  const cancelClose = useCallback(() => {
    window.clearTimeout(hoverTimers.current.close);
  }, []);

  const handle = profile?.custom_id || username;
  const badge = profile ? PLAN_BADGES[profile.plan] : undefined;
  // 非 max/business 用户给出升级入口；max/business 已是顶配，不打扰。
  const plan = profile?.plan ?? "metered";
  const showUpgrade = plan !== "max" && plan !== "business";
  const planLabel = t(
    ((profile && PLAN_LABEL_KEYS[profile.plan]) || "settings.profile.planMetered") as MessageKey,
  );

  const doLogout = useCallback(async () => {
    setOpen(false);
    await logout();
    // 硬跳转：标签簿/草稿缓存都留在本地，登录页兜住后续。
    window.location.assign("/login");
  }, []);

  // 打开后按触发器与菜单实测矩形定位：优先上方，放不下翻下方，最后夹取在视窗内。
  // 依赖里的 pos===null 只负责「从无到有」跑一次；重算由 open 翻转触发。
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = flyoutRef.current?.offsetWidth || 208;
    const height = flyoutRef.current?.offsetHeight || 141;
    const margin = 8;
    const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin));
    const above = rect.top - height - 10 >= margin || rect.bottom + 10 + height > window.innerHeight - margin;
    const rawTop = above ? rect.top - height - 10 : rect.bottom + 10;
    const top = Math.max(margin, Math.min(rawTop, window.innerHeight - height - margin));
    setPos((old) => {
      if (old && old.left === left && old.top === top && old.above === above) return old;
      return { left, top, above };
    });
  }, [open, pos === null]);

  return (
    <div
      className="wb-account"
      ref={rootRef}
      onMouseEnter={scheduleOpen}
      onMouseLeave={scheduleClose}
    >
      <button
        type="button"
        ref={triggerRef}
        className="wb-account__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("workbench.sidebar.accountMenu", { handle })}
        onFocus={cancelClose}
        onClick={() => setOpen((value) => !value)}
      >
        <AccountAvatar profile={profile} fallbackName={username} size={22} />
        <span className="wb-account__handle">@{handle}</span>
        {badge && (
          <span className={`plan-badge ${badge.className}`} aria-hidden="true">
            {badge.label}
          </span>
        )}
      </button>

      {open &&
        createPortal(
          <div
            className="wb-account__flyout"
            role="menu"
            aria-label={t("workbench.sidebar.accountMenu", { handle })}
            ref={flyoutRef}
            style={{
              position: "fixed",
              left: pos?.left ?? -9999,
              top: pos?.top ?? -9999,
              visibility: pos ? "visible" : "hidden",
              zIndex: "calc(var(--z-drawer) + 1)",
              transformOrigin: pos?.above ? "bottom right" : "top right",
            }}
          >
            {/* 用户 ID 行：纯展示，不可点。 */}
            <div className="wb-account__identity" role="presentation">
              <AccountAvatar profile={profile} fallbackName={username} size={30} />
              <span className="wb-account__id-text">
                <span className="wb-account__id">@{handle}</span>
                <span className="wb-account__plan">{planLabel}</span>
              </span>
            </div>
            <div className="wb-account__divider" aria-hidden="true" />
            {showUpgrade && (
              <a
                className="wb-account__item wb-account__item--upgrade"
                role="menuitem"
                href="/pricing"
                onClick={() => setOpen(false)}
              >
                <Sparkles size={15} strokeWidth={2} aria-hidden="true" />
                <span className="wb-account__upgrade-text">{t("workbench.sidebar.upgrade")}</span>
              </a>
            )}
            <button
              type="button"
              className="wb-account__item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onOpen("/usage");
              }}
            >
              <ChartColumn size={15} strokeWidth={2} aria-hidden="true" />
              {t("workbench.sidebar.usageConsole")}
            </button>
            <button
              type="button"
              className="wb-account__item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onOpen("/settings/account");
              }}
            >
              <UserRound size={15} strokeWidth={2} aria-hidden="true" />
              {t("workbench.sidebar.profile")}
            </button>
            <button
              type="button"
              className="wb-account__item wb-account__item--danger"
              role="menuitem"
              onClick={() => void doLogout()}
            >
              <LogOut size={15} strokeWidth={2} aria-hidden="true" />
              {t("workbench.shell.logout")}
            </button>
          </div>,
          // 挂进 .wb-app 而不是 body：--wb-* token 定义在 .wb-app 作用域上，
          // portal 到 body 会取不到表面色（菜单变透明）；.wb-app 本身无 transform，
          // fixed 定位仍以视口为基准。层高 calc(--z-drawer + 1) 压过移动端抽屉。
          document.querySelector(".wb-app") ?? document.body,
        )}
    </div>
  );
}

type FlyoutPos = { left: number; top: number; above: boolean };
