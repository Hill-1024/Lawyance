/*
 * Lawver PWA service worker.
 * 提供安装所需的 service worker 能力，并避免改写 API 请求语义。
 */

const SHELL_CACHE = 'lawver-shell-v2';

const scopePathname = () => {
  try {
    return new URL(self.registration.scope).pathname || '/';
  } catch {
    return '/';
  }
};

const underScope = (relativePath) => {
  const scope = scopePathname().replace(/\/?$/, '/');
  return `${scope}${String(relativePath || '').replace(/^\//, '')}`;
};

const SHELL_ASSETS = [
  scopePathname(),
  underScope('manifest.webmanifest'),
  underScope('pwa-icon-192.png'),
  underScope('pwa-icon-512.png'),
];

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
  const apiPrefix = underScope('api/');
  if (request.method !== 'GET' || url.pathname.startsWith(apiPrefix) || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(scopePathname())));
    return;
  }

  event.respondWith(fetch(request).catch(() => caches.match(request)));
});
