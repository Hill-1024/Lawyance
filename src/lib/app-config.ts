/*
 * 模块描述：全局域名与区域路径配置入口，由 Vite define 从 package.json appConfig 注入，与服务端共用同一份。
 */

export interface LawverAppConfig {
  domain: string;
  origin: string;
}

declare const __LAWVER_APP_CONFIG__: LawverAppConfig | undefined;
declare const __LAWVER_REGIONS__: string[] | undefined;
declare global {
  interface Window {
    /** 网关注入的区域前缀（如 /cn）；网关注入 <base> 时会由内联脚本写入，缺省时由 <base> 推断。 */
    __LAWVER_BASE_PATH__?: string;
  }
}

const FALLBACK_APP_CONFIG: LawverAppConfig = {
  domain: 'cn.lawver.dev',
  origin: 'https://cn.lawver.dev',
};

const CONFIGURED_REGIONS: string[] = typeof __LAWVER_REGIONS__ !== 'undefined' ? __LAWVER_REGIONS__ : [];

export const APP_CONFIG: LawverAppConfig = typeof __LAWVER_APP_CONFIG__ !== 'undefined'
  ? __LAWVER_APP_CONFIG__
  : FALLBACK_APP_CONFIG;

const normalizeBasePath = (value: string | null | undefined): string => {
  if (!value) return '';
  const trimmed = value.replace(/\/+$/, '');
  return trimmed;
};

/**
 * 区域路径前缀，形如 `/cn`；网关按该前缀分流到不同区域后端，应用内路由与 API 都要带上它。
 * 前缀以网关注入的 `<base href="/cn/">` 为权威来源（必须是静态注入：运行时插入会晚于浏览器
 * 预加载扫描器，导致资源被重复请求到默认区域）；未注入时退回按 `appConfig.regions` 推断，
 * 保证 SPA 仍可渲染。根路径部署时为空串，行为与改造前完全一致。
 */
export const BASE_PATH: string = (() => {
  if (typeof window === 'undefined') return '';

  const injected = normalizeBasePath(window.__LAWVER_BASE_PATH__);
  if (injected) return injected;

  const baseElement = typeof document !== 'undefined' ? document.querySelector('base') : null;
  if (baseElement) {
    try {
      const resolved = new URL(baseElement.getAttribute('href') || '/', window.location.href);
      const path = normalizeBasePath(resolved.pathname);
      if (path) return path;
    } catch {
      // 忽略非法 href，继续走区域兜底推断。
    }
  }

  const firstSegment = window.location.pathname.split('/')[1] || '';
  return CONFIGURED_REGIONS.includes(firstSegment) ? `/${firstSegment}` : '';
})();
