/*
 * 模块描述：读取 Vite 公开路径与站点根，供路由、接口和 PWA 共用。
 */

const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};

/** 以 / 结尾。本地为 /，东盟生产构建为 /asean/。 */
export const publicBase = () => {
  const base = env.BASE_URL || '/';
  return base.endsWith('/') ? base : `${base}/`;
};

/** React Router basename 不带结尾斜杠；根路径返回 undefined。 */
export const routerBasename = () => {
  const base = publicBase();
  return base === '/' ? undefined : base.replace(/\/$/, '');
};

export const publicOrigin = () => (env.VITE_PUBLIC_ORIGIN || 'https://global.lawver.dev').replace(/\/$/, '');
