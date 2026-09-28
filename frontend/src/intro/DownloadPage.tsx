/*
 * 模块描述：下载中心页（自 lawyance-intro 的 DownloadPage.vue 移植）。
 * 仅渲染页面主体：站点头尾、.page 背景与 reveal 入场均由应用布局和共享样式提供。
 */

import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Globe, Smartphone } from "lucide-react";
import { formatPublishedAt, useLatestRelease } from "./release";
import "./intro-download.css";

// hero 区元素与 Vue 版一致直接以 is-visible 呈现，仅保留 stagger 延迟变量。
const withDelay = (delay: string) => ({ "--delay": delay }) as CSSProperties;

export default function DownloadPage() {
  const release = useLatestRelease();
  const publishedLabel = formatPublishedAt(release.publishedAt);

  const releaseFacts = [
    { label: "最新版本", value: release.tagName },
    { label: "安装包大小", value: release.apkSize },
    { label: "发布时间", value: publishedLabel || "以 Release 页为准" },
    { label: "支持平台", value: "Web / Android" },
  ];

  return (
    <main id="top" className="page intro-page--download" aria-labelledby="download-hero-title">
      {/* Hero Section */}
      <section className="hero download-hero" aria-labelledby="download-hero-title">
        <div className="hero__content">
          <span className="hero__tag reveal is-visible" style={withDelay("80ms")}>
            DOWNLOAD CENTER
          </span>
          <h1 id="download-hero-title" className="reveal is-visible" style={withDelay("160ms")}>
            下载中心
          </h1>
          <p className="hero__lead reveal is-visible" style={withDelay("240ms")}>
            体验 Lawver 法律 AI 工作台的全部潜力。支持网页版直接访问及原生 Android
            客户端下载。
          </p>
          <dl className="hero-facts reveal is-visible" style={withDelay("320ms")}>
            {releaseFacts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* Download Options Section */}
      <section className="section section--download" aria-labelledby="options-title">
        <div className="section__heading reveal">
          <p>客户端下载与访问</p>
          <h2 id="options-title">多端联动，即刻开启法律工作流程。</h2>
        </div>

        <div className="download-content reveal">
          <div className="cards-layout">
            {/* Web Entrance Card */}
            <div className="download-card highlight-card">
              <div className="card-icon">
                <Globe aria-hidden="true" strokeWidth={1.75} />
              </div>
              <h3>Web 网页版</h3>
              <p>
                无需安装，支持全功能会话、文件沙箱上传以及完整的模拟法庭推演工作流，自适应现代桌面级及平板浏览器。
              </p>
              <div className="download-action-group">
                <Link to="/home" className="primary-cta">
                  打开 Web 工作台
                </Link>
                <p className="card-meta">推荐 Chrome / Safari / Edge 桌面浏览器</p>
              </div>
            </div>

            {/* Android Download Card */}
            <div className="download-card">
              <div className="card-icon">
                <Smartphone aria-hidden="true" strokeWidth={1.75} />
              </div>
              <h3>Android 客户端</h3>
              <p>
                基于 Capacitor
                深度原生化打包，支持流畅的手势操作、本地持久化数据库及离线缓存隔离文件服务。
              </p>

              <div className="download-action-group">
                <div className="cta-actions">
                  <a href={release.apkUrl} target="_blank" rel="noopener noreferrer" className="primary-cta">
                    <span>直接下载最新 APK</span>
                  </a>
                  <a
                    href={release.htmlUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="secondary-cta"
                  >
                    <span>查看 GitHub Release</span>
                  </a>
                </div>
                <p className="card-meta">侧载安装，首次安装需在系统设置中允许未知来源。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Final Section */}
      <section className="final download-final">
        <h2 className="reveal">让严肃的法律计算，以极速、优雅的多端体验呈现在您的工作流中。</h2>
        <div className="final__cta-group reveal" style={withDelay("160ms")}>
          <Link to="/" className="primary-cta">
            返回产品首页
          </Link>
          <Link to="/design" className="secondary-cta">
            了解系统设计
          </Link>
        </div>
      </section>
    </main>
  );
}
