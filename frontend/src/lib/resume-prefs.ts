/*
 * 模块描述：断线续传偏好持久化。Web 使用 localStorage，原生使用 Capacitor Preferences。
 */

import { Preferences } from '@capacitor/preferences';
import { isNative } from './platform';

const RESUME_ENABLED_KEY = 'lawver.resume.enabled';

export const getResumeEnabled = async (): Promise<boolean> => {
  try {
    if (isNative()) {
      const { value } = await Preferences.get({ key: RESUME_ENABLED_KEY });
      return value === '1';
    }
    return localStorage.getItem(RESUME_ENABLED_KEY) === '1';
  } catch {
    return false;
  }
};

export const setResumeEnabled = async (enabled: boolean): Promise<void> => {
  const value = enabled ? '1' : '0';
  if (isNative()) {
    await Preferences.set({ key: RESUME_ENABLED_KEY, value });
  } else {
    localStorage.setItem(RESUME_ENABLED_KEY, value);
  }
};

export const subscribeResumeEnabled = (listener: (enabled: boolean) => void) => {
  const handleStorage = (event: StorageEvent) => {
    if (event.key === RESUME_ENABLED_KEY) {
      listener(event.newValue === '1');
    }
  };
  window.addEventListener('storage', handleStorage);
  return () => window.removeEventListener('storage', handleStorage);
};

export const notifyResumeEnabledChanged = (enabled: boolean) => {
  window.dispatchEvent(new StorageEvent('storage', {
    key: RESUME_ENABLED_KEY,
    newValue: enabled ? '1' : '0',
    storageArea: localStorage,
  }));
};
