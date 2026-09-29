/*
 * Lawver PWA service worker.
 *
 * 只保留安装所需的最小能力（install/activate），不做任何缓存与导航回放：
 * 这个 SW 的 scope 覆盖整个站点根，而介绍页与功能页是同域的两个进程——
 *   · 缓存回放会把用户按在任意年龄的旧壳上（过期登录页、旧版本界面都来自这里）；
 *   · 功能页维护时，核心会把这些导航 302 到 /under_maintenance，缓存兜底会把它遮掉。
 * 代价是没有离线壳：离线时由浏览器给出自己的离线页，比静默回放旧页面更诚实。
 */

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});
