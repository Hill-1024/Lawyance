/*
 * 模块描述：原生 Android 返回键 LIFO 回调栈，优先关闭浮层再执行路由返回。
 */

import { useEffect } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { isNativeAndroid } from '../lib/platform';

type BackHandler = () => boolean | void;

const handlers: BackHandler[] = [];
let removeNativeListener: (() => Promise<void>) | null = null;
let nativeListenerRegistration: Promise<void> | null = null;

const dispatchBackButton = () => {
  for (let index = handlers.length - 1; index >= 0; index -= 1) {
    const handler = handlers[index];
    if (!handler) continue;

    try {
      if (handler()) return;
    } catch (error) {
      // One broken overlay must not prevent older handlers from receiving Back.
      console.error('Native back-button handler failed:', error);
    }
  }
};

const ensureListener = () => {
  if (!isNativeAndroid() || removeNativeListener || nativeListenerRegistration) return;

  nativeListenerRegistration = CapacitorApp.addListener('backButton', dispatchBackButton)
    .then(handle => {
      removeNativeListener = () => handle.remove();
    })
    .catch(error => {
      // Allow a later mounted consumer to retry a failed native registration.
      nativeListenerRegistration = null;
      console.error('Failed to register native back-button listener:', error);
    });
};

export const useBackButton = (handler: BackHandler, enabled = true) => {
  useEffect(() => {
    if (!enabled || !isNativeAndroid()) return;
    ensureListener();
    handlers.push(handler);
    return () => {
      const index = handlers.lastIndexOf(handler);
      if (index >= 0) handlers.splice(index, 1);
    };
  }, [enabled, handler]);
};

export const exitNativeApp = async () => {
  if (!isNativeAndroid()) return;
  await CapacitorApp.exitApp();
};
