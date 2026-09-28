/*
 * 模块描述：介绍页的滚动效果 hooks（自 lawyance-intro 的 utils 移植）。
 * setupScrollEffects → useScrollEffects：IntersectionObserver 驱动的 .reveal 入场；
 * setupAmbientBackground → useAmbientBackground：深色横幅淡入时整页背景随之变暗。
 * 两者都返回清理逻辑，随组件卸载执行。
 */

import { useEffect, useRef } from "react";

const revealSelector = ".reveal:not(.is-visible)";
const revealStaggerMs = 40;
const revealStaggerCapMs = 200;

/** 滚动入场 reveal + 锚点滚动补偿。介绍页布局组件挂载时调用一次。 */
export function useScrollEffects() {
  useEffect(() => {
    document.documentElement.dataset.revealReady = "true";

    // threshold 必须为 0：高于视口的整节若按比例阈值永远达不到，会被永久藏住。
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0, rootMargin: "0px 0px -6% 0px" },
    );

    Array.from(document.querySelectorAll<HTMLElement>(revealSelector)).forEach(
      (target, index) => {
        target.style.setProperty(
          "--delay",
          `${Math.min(index * revealStaggerMs, revealStaggerCapMs)}ms`,
        );
        observer.observe(target);
      },
    );

    const scrollToHashTarget = () => {
      const id = window.location.hash.slice(1);
      if (!id) return;
      document.getElementById(id)?.scrollIntoView({ block: "start" });
    };
    const hashFrame = window.requestAnimationFrame(scrollToHashTarget);
    window.addEventListener("hashchange", scrollToHashTarget);

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(hashFrame);
      window.removeEventListener("hashchange", scrollToHashTarget);
    };
  }, []);
}

const clamp = (value: number) => Math.min(1, Math.max(0, value));
const smoothstep = (value: number, start: number, end: number) => {
  const t = clamp((value - start) / (end - start));
  return t * t * (3 - 2 * t);
};
const mix = (from: number, to: number, progress: number) => from + (to - from) * progress;

// 与官网一致的纸面→深色端点；写死是因为背景合成层独立于主题 token。
const PAPER: [number, number, number] = [246, 248, 251];
const DARK: [number, number, number] = [11, 13, 20];

/**
 * 滚动驱动的整页背景：section 充满视口时，.page::before 固定层从纸面交叉淡化到
 * 深色，白色顶光褪去，--ambient-dark-wash 抬升（深色节的透明边缘依赖它）。
 */
export function useAmbientBackground(sectionRef: React.RefObject<HTMLElement | null>) {
  const teardownRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const section = sectionRef.current;
    const page = section?.closest<HTMLElement>(".page");
    if (!section || !page) return;

    let scrollFrame = 0;
    let animationFrame = 0;
    let targetProgress = 0;
    let renderedProgress = 0;

    const paint = (progress: number) => {
      const eased = smoothstep(progress, 0, 1);
      page.style.setProperty("--ambient-progress", eased.toFixed(4));
      page.style.setProperty("--ambient-r", mix(PAPER[0], DARK[0], eased).toFixed(2));
      page.style.setProperty("--ambient-g", mix(PAPER[1], DARK[1], eased).toFixed(2));
      page.style.setProperty("--ambient-b", mix(PAPER[2], DARK[2], eased).toFixed(2));
      page.style.setProperty("--ambient-light-wash", (0.88 * (1 - eased)).toFixed(4));
      page.style.setProperty("--ambient-dark-wash", (0.2 + 0.46 * eased).toFixed(4));
    };

    // 用可见覆盖率而非原始偏移，矮于视口的节也能在充满屏幕时达到全暗。
    const measure = () => {
      const rect = section.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      const visibleHeight = Math.max(
        0,
        Math.min(rect.bottom, viewportHeight) - Math.max(rect.top, 0),
      );
      const maxVisibleHeight = Math.max(1, Math.min(rect.height, viewportHeight));
      return smoothstep(visibleHeight / maxVisibleHeight, 0.08, 0.88);
    };

    const animate = () => {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const velocity = reducedMotion ? 1 : targetProgress > renderedProgress ? 0.42 : 0.3;
      if (targetProgress >= 0.999 || targetProgress <= 0.001) {
        renderedProgress = targetProgress;
        paint(renderedProgress);
        animationFrame = 0;
        return;
      }
      renderedProgress += (targetProgress - renderedProgress) * velocity;
      if (Math.abs(targetProgress - renderedProgress) < 0.001) {
        renderedProgress = targetProgress;
        paint(renderedProgress);
        animationFrame = 0;
        return;
      }
      paint(renderedProgress);
      animationFrame = window.requestAnimationFrame(animate);
    };

    const update = () => {
      if (scrollFrame) return;
      scrollFrame = window.requestAnimationFrame(() => {
        scrollFrame = 0;
        targetProgress = measure();
        if (!animationFrame) animationFrame = window.requestAnimationFrame(animate);
      });
    };

    // 同步先画一帧：直接落到页中部的加载（如刷新 /design#security）不会闪纸面底。
    targetProgress = measure();
    renderedProgress = targetProgress;
    paint(renderedProgress);

    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);

    teardownRef.current = () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      if (scrollFrame) window.cancelAnimationFrame(scrollFrame);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
    };
    return () => {
      teardownRef.current?.();
      teardownRef.current = null;
    };
  }, [sectionRef]);
}
