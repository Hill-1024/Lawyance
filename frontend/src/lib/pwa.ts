/*
 * 模块描述：浏览器端 PWA 安装能力注册，避免影响 Capacitor 原生壳。
 */

import { isNative } from './platform';
import { BASE_PATH } from './app-config';

const canRegisterPwa = () => {
  if (typeof window === 'undefined') return false;
  if (isNative()) return false;
  if (!('serviceWorker' in navigator)) return false;

  const { hostname, protocol } = window.location;
  return protocol === 'https:' || hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
};

export const registerPwa = () => {
  if (!canRegisterPwa()) return;
  // 开发模式下不注册 SW：vite 的 HMR 模块流与 SW 缓存互相干扰，且旧 SW 会劫持请求导致白屏。
  if (import.meta.env.DEV) return;

  window.addEventListener('load', () => {
    // 区域前缀部署时，service worker 与 scope 都要落在前缀内，否则会跨区域接管。
    navigator.serviceWorker.register(`${BASE_PATH}/sw.js`, { scope: `${BASE_PATH}/` }).catch(error => {
      console.warn('[PWA] Service worker registration failed:', error);
    });
  });
};
