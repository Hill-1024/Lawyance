/*
 * Lawver PWA service worker.
 * 提供安装所需的 service worker 能力，并避免改写 API 请求语义。
 */

// 区域前缀部署时 scope 形如 https://host/cn/，根路径部署为 https://host/。
const BASE = new URL('./', self.registration.scope).pathname;
const API_PREFIX = `${BASE}api/`;
const SHELL_CACHE = 'lawver-shell-v2';
const SHELL_ASSETS = [`${BASE}`, `${BASE}manifest.webmanifest`, `${BASE}pwa-icon-192.png`, `${BASE}pwa-icon-512.png`];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== SHELL_CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.pathname.startsWith(API_PREFIX)) return;
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(BASE)));
    return;
  }

  event.respondWith(fetch(request).catch(() => caches.match(request)));
});
