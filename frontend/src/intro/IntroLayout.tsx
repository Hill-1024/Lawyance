/*
 * 模块描述：介绍页布局（首页/产品设计/下载中心共用）。
 * 头部学 quote.law：首屏融入纸面，滚动后变白色圆角悬浮条；右侧常驻「进入工作台」，
 * 按登录态与工作台灰度分别落 /home、/legacy、/login。页脚为固定深色表面。
 * 滚动入场 reveal、环境光背景与锚点定位由 effects.ts 提供。
 */

import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { BrandMark } from "../components/Brand";
import { useScrollEffects } from "./effects";
import "./intro-base.css";

const SECTION_ANCHORS = [
  { hash: "#document-demo", label: "交互体验" },
  { hash: "#abilities", label: "能力" },
  { hash: "#workbench", label: "工作台" },
  { hash: "#method", label: "工作方式" },
  { hash: "#memory", label: "记忆" },
  { hash: "#trust", label: "边界" },
];

interface IntroLayoutProps {
  activePage: "home" | "design" | "download";
  isAuthenticated: boolean;
  workbenchEnabled: boolean;
  children: React.ReactNode;
}

export default function IntroLayout({
  activePage,
  isAuthenticated,
  workbenchEnabled,
  children,
}: IntroLayoutProps) {
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();
  const isHome = activePage === "home";

  useScrollEffects();

  // 介绍页是长滚动页：锚点落点需要为悬浮头部预留空间；离开时还原，避免影响工作台。
  useEffect(() => {
    const root = document.documentElement;
    root.style.scrollPaddingTop = "104px";
    root.style.scrollBehavior = "smooth";
    return () => {
      root.style.scrollPaddingTop = "";
      root.style.scrollBehavior = "";
    };
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // 路由切换时回顶；带 hash 的跳转交给 hashchange 定位。
  const pathname = location.pathname;
  const hash = location.hash;
  const topFrame = useRef(0);
  useEffect(() => {
    if (hash) return;
    topFrame.current = window.requestAnimationFrame(() => window.scrollTo(0, 0));
    return () => window.cancelAnimationFrame(topFrame.current);
  }, [pathname, hash]);

  const workbenchPath = workbenchEnabled ? "/home" : "/legacy";

  return (
    <div className="lawver-intro">
      <header className={"site-header" + (scrolled ? " is-scrolled" : "")}>
        <Link to={isHome ? "#top" : "/"} className="intro-brand" aria-label="Lawver">
          <BrandMark className="h-7 w-7 shrink-0" />
          <span className="brand-wordmark">
            <span className="brand-wordmark-swash">L</span>awver
          </span>
        </Link>
        <nav className="site-nav" aria-label="页面导航">
          {SECTION_ANCHORS.map(({ hash: anchorHash, label }) => (
            <a
              key={anchorHash}
              className="site-nav__anchor"
              href={isHome ? anchorHash : "/" + anchorHash}
            >
              {label}
            </a>
          ))}
          <Link to="/design" className={activePage === "design" ? "is-active" : ""} aria-current={activePage === "design" ? "page" : undefined}>
            产品设计
          </Link>
          <Link to="/download" className={activePage === "download" ? "is-active" : ""} aria-current={activePage === "download" ? "page" : undefined}>
            下载中心
          </Link>
        </nav>
        <Link to={isAuthenticated ? workbenchPath : "/login"} className="site-header__cta">
          进入工作台
        </Link>
      </header>
      {children}
      <footer className="site-footer">
        <div className="site-footer__inner">
          <div className="site-footer__brand">
            <Link to="/" className="intro-brand" aria-label="Lawver">
              <BrandMark className="h-8 w-8 shrink-0" />
              <span className="brand-wordmark">
                <span className="brand-wordmark-swash">L</span>awver
              </span>
            </Link>
            <p>面向中文法律场景的 AI 工作台，把法律检索、卷宗处理、模拟法庭与输出审查收在同一套应用里。</p>
          </div>
          <nav className="site-footer__columns" aria-label="页脚导航">
            <div className="site-footer__column">
              <span>产品</span>
              <a href="/#abilities">能力介绍</a>
              <a href="/#workbench">应用工作台</a>
              <a href="/#method">工作方式</a>
              <a href="/#memory">注意力与记忆</a>
              <a href="/#trust">信任与边界</a>
            </div>
            <div className="site-footer__column">
              <span>页面</span>
              <Link to="/">产品首页</Link>
              <Link to="/design">产品设计</Link>
              <Link to="/download">下载中心</Link>
            </div>
            <div className="site-footer__column">
              <span>访问</span>
              <Link to={isAuthenticated ? workbenchPath : "/login"}>打开工作台</Link>
              <Link to="/download">Android 客户端</Link>
              <a href="https://github.com/Hill-1024/Lawyance" target="_blank" rel="noopener noreferrer">
                GitHub 仓库
              </a>
            </div>
          </nav>
        </div>
        <div className="site-footer__base">
          <p>&copy; {new Date().getFullYear()} Lawver，工大法智团队。</p>
        </div>
      </footer>
    </div>
  );
}
