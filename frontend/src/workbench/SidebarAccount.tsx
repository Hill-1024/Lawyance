/*
 * 模块描述：工作台侧栏底部的账户入口——头像 + @自定义 ID + 订阅徽标，替代原先
 * 一行纯文本用户名。悬停/点击浮出菜单：非交互的用户 ID 行、个人资料、退出登录，
 * 与介绍页右上角同一套信息与交互约定（120ms 悬停意图、200ms 离开宽限、Esc/外点关闭）。
 * 侧栏贴底，所以浮层向上开；profile 未取到时回退显示用户名。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { LogOut, UserRound } from "lucide-react";
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
  const rootRef = useRef<HTMLDivElement>(null);
  const hoverTimers = useRef<{ open?: number; close?: number }>({});

  usePortalMenuDismiss(open, () => setOpen(false), { selectors: [".wb-account"] });

  // 卸载兜底：清悬停计时器。
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
  const planLabel = t(
    (profile && (PLAN_LABEL_KEYS[profile.plan] as MessageKey)) || "settings.profile.planMetered",
  );

  const doLogout = useCallback(async () => {
    setOpen(false);
    await logout();
    // 硬跳转：标签簿/草稿缓存都留在本地，登录页兜住后续。
    window.location.assign("/login");
  }, []);

  return (
    <div
      className="wb-account"
      ref={rootRef}
      onMouseEnter={scheduleOpen}
      onMouseLeave={scheduleClose}
    >
      <button
        type="button"
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

      {open && (
        <div className="wb-account__flyout" role="menu" aria-label={t("workbench.sidebar.accountMenu", { handle })}>
          {/* 用户 ID 行：纯展示，不可点。 */}
          <div className="wb-account__identity" role="presentation">
            <AccountAvatar profile={profile} fallbackName={username} size={30} />
            <span className="wb-account__id-text">
              <span className="wb-account__id">@{handle}</span>
              <span className="wb-account__plan">{planLabel}</span>
            </span>
          </div>
          <div className="wb-account__divider" aria-hidden="true" />
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
        </div>
      )}
    </div>
  );
}
