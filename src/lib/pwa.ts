/*
 * 模块描述：浏览器端 PWA 安装能力注册，避免影响 Capacitor 原生壳。
 */

import { isNative } from './platform';
import { publicBase } from './public-base';

const canRegisterPwa = () => {
  if (typeof window === 'undefined') return false;
  if (isNative()) return false;
  if (!('serviceWorker' in navigator)) return false;

  const { hostname, protocol } = window.location;
  return protocol === 'https:' || hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
};

export const registerPwa = () => {
  if (!canRegisterPwa()) return;

  window.addEventListener('load', () => {
    const scope = publicBase();
    const workerUrl = `${scope}sw.js`.replace(/([^:]\/)\/+/g, '$1')
    navigator.serviceWorker.register(workerUrl, { scope }).catch(error => {
      console.warn('[PWA] Service worker registration failed:', error);
    });
  });
};
