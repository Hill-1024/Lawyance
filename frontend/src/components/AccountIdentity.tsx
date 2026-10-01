/*
 * 模块描述：账户身份的共享件——头像（自定义头像或首字母落品牌渐变）与订阅徽标。
 * 介绍页约定同源：Go=品牌蓝 / Pro=品牌青 / Max=琥珀 / Business=墨色；按量不出徽标。
 * 设置页与工作台侧栏都从这里取，避免两处各养一套颜色。
 */

import { avatarUrl, type AccountProfile } from "../services/api";

export const PLAN_BADGES: Record<string, { label: string; className: string }> = {
  go: { label: "Go", className: "plan-badge--go" },
  pro: { label: "Pro", className: "plan-badge--pro" },
  max: { label: "Max", className: "plan-badge--max" },
  business: { label: "Business", className: "plan-badge--business" },
};

export const PLAN_LABEL_KEYS: Record<string, string> = {
  metered: "settings.profile.planMetered",
  go: "settings.profile.planGo",
  pro: "settings.profile.planPro",
  max: "settings.profile.planMax",
  business: "settings.profile.planBusiness",
};

/** 头像：有图用图（version 参与缓存失效），没图用名字首字母落在品牌蓝渐变上。 */
export function AccountAvatar({
  profile,
  size,
  fallbackName,
  className = "",
}: {
  profile: AccountProfile | null;
  size: number;
  /** profile 未取到（离线/加载中）时的兜底名字。 */
  fallbackName?: string;
  className?: string;
}) {
  const version = profile?.avatar_version ?? 0;
  const src = profile && version > 0 ? avatarUrl(profile.uid, version) : null;
  const initial = (profile?.username || fallbackName || "?").slice(0, 1).toUpperCase();
  return (
    <span
      className={
        "account-avatar inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full bg-[var(--accent)] text-[var(--accent-on)] " +
        className
      }
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      aria-hidden="true"
    >
      {src ? (
        <img src={src} alt="" className="h-full w-full object-cover" />
      ) : (
        <span className="font-semibold leading-none">{initial}</span>
      )}
    </span>
  );
}
