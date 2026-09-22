/*
 * 模块描述：WebDAV 同步配置持久化封装，原生用 Preferences，Web 用 localStorage。
 */

import { Preferences } from '@capacitor/preferences';
import { isNative } from './platform';

export interface WebDavConfig {
  url: string;
  username: string;
  password: string;
  directory: string;
}

const STORAGE_KEY = 'lawver.webdav.config';
const DEFAULT_DIRECTORY = '/Lawver/';

export const emptyWebDavConfig = (): WebDavConfig => ({
  url: '',
  username: '',
  password: '',
  directory: DEFAULT_DIRECTORY,
});

export const getWebDavConfig = async (): Promise<WebDavConfig | null> => {
  try {
    if (isNative()) {
      const { value } = await Preferences.get({ key: STORAGE_KEY });
      if (!value) return null;
      return JSON.parse(value) as WebDavConfig;
    }
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as WebDavConfig;
  } catch {
    return null;
  }
};

export const setWebDavConfig = async (config: WebDavConfig): Promise<void> => {
  const serialized = JSON.stringify(config);
  if (isNative()) {
    await Preferences.set({ key: STORAGE_KEY, value: serialized });
  } else {
    localStorage.setItem(STORAGE_KEY, serialized);
  }
};

export const clearWebDavConfig = async (): Promise<void> => {
  if (isNative()) {
    await Preferences.remove({ key: STORAGE_KEY });
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
};
