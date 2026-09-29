/*
 * 模块描述：全局域名与接入路径配置，由 Vite define 从 package.json appConfig 注入，与服务端共用同一份。
 *
 * 路径基址（BASE_PATH）只认 <base>：介绍页与功能页同域不同进程，功能页始终挂在站点根，
 * 所以实际取值是空串；保留解析逻辑是为了让 SPA 在任意基点下都能正确解析资源与 API。
 */

export interface LawverAppConfig {
  domain: string;
  origin: string;
  /** 原生客户端直连的后端地址，绕开网页入口（缺省时与 origin 相同）。 */
  nativeApiBase: string;
}

declare const __LAWVER_APP_CONFIG__: LawverAppConfig | undefined;
declare global {
  interface Window {
    /** 内联脚本注入的路径基址；缺省时由 <base> 推断。 */
    __LAWVER_BASE_PATH__?: string;
  }
}

const FALLBACK_APP_CONFIG: LawverAppConfig = {
  domain: 'lawver.dev',
  origin: 'https://lawver.dev',
  nativeApiBase: 'https://cn-origin.lawver.dev',
};

export const APP_CONFIG: LawverAppConfig = typeof __LAWVER_APP_CONFIG__ !== 'undefined'
  ? __LAWVER_APP_CONFIG__
  : FALLBACK_APP_CONFIG;

const normalizeBasePath = (value: string | null | undefined): string => {
  if (!value) return '';
  return value.replace(/\/+$/, '');
};

/**
 * 应用内路由与 API 的基址，形如 `/cn`；根路径部署时为空串。
 * 以服务端注入的 <base href="/"> 为权威来源——必须是静态注入：运行时插入会晚于浏览器
 * 预加载扫描器，资源会被请求到错误路径。
 */
export const BASE_PATH: string = (() => {
  if (typeof window === 'undefined') return '';

  const injected = normalizeBasePath(window.__LAWVER_BASE_PATH__);
  if (injected) return injected;

  const baseElement = typeof document !== 'undefined' ? document.querySelector('base') : null;
  if (!baseElement) return '';

  try {
    const resolved = new URL(baseElement.getAttribute('href') || '/', window.location.href);
    return normalizeBasePath(resolved.pathname);
  } catch {
    // 非法 href：当作根路径部署处理。
    return '';
  }
})();
