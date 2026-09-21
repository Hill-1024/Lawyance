/*
 * 模块描述：全局域名配置入口，由 Vite define 从 package.json appConfig 注入，与服务端共用同一份。
 */

export interface LawverAppConfig {
  domain: string;
  origin: string;
}

declare const __LAWVER_APP_CONFIG__: LawverAppConfig | undefined;

const FALLBACK_APP_CONFIG: LawverAppConfig = {
  domain: 'cn.lawver.dev',
  origin: 'https://cn.lawver.dev',
};

export const APP_CONFIG: LawverAppConfig = typeof __LAWVER_APP_CONFIG__ !== 'undefined'
  ? __LAWVER_APP_CONFIG__
  : FALLBACK_APP_CONFIG;
