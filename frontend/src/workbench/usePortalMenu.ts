/*
 * 模块描述：工作台里所有浮层菜单共用的「点外面关掉」逻辑。
 *
 * 这些菜单都经 createPortal 挂在 document.body 下，不在触发按钮的子树里。判断
 * 「本次 mousedown 是否落在菜单内」时，必须把菜单自身的类名也列出来；只写触发容器
 * （closest('.wb-thread-history')、closest('.wb-overflow') 那两处）的话，按下菜单项的
 * 那一刻菜单就被卸载，click 根本派发不出去——鼠标用户打不开菜单，而键盘和程序化
 * .click() 却照常工作，于是这类缺陷只在真实鼠标路径上暴露（会话历史、文档「更多操作」
 * 都踩过同一个坑）。收敛到这一处，新增菜单时不会再漏。
 *
 * selectors 请作为模块级常量传入（数组身份稳定），否则每次渲染都会重挂监听。
 */

import { useEffect } from "react";

import { getBinding, matchKeys, SHORTCUT_IDS } from "../lib/shortcuts";

interface PortalMenuOptions {
  /** 落在其中就不关闭：菜单自身 + 触发按钮容器，例如 [".wb-thread-menu", ".wb-thread-history"]。 */
  selectors: readonly string[];
  /** 视口变化时关闭：锚定计算的菜单（标签右键菜单）需要。 */
  closeOnResize?: boolean;
}

export const usePortalMenuDismiss = (
  open: boolean,
  onClose: () => void,
  { selectors, closeOnResize = false }: PortalMenuOptions,
) => {
  useEffect(() => {
    if (!open) return;
    const insideMenu = (target: EventTarget | null) =>
      selectors.some((selector) => Boolean((target as HTMLElement | null)?.closest?.(selector)));
    const onPointerDown = (event: MouseEvent) => {
      if (!insideMenu(event.target)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (matchKeys(event, getBinding(SHORTCUT_IDS.overlayClose))) onClose();
    };
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    if (closeOnResize) window.addEventListener("resize", onPointerDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
      if (closeOnResize) window.removeEventListener("resize", onPointerDown);
    };
  }, [open, onClose, selectors, closeOnResize]);
};
