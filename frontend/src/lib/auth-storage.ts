/*
 * 模块描述：原生 Bearer token 存储封装，Web 端保持无状态 cookie 路径。
 */

import { Preferences } from '@capacitor/preferences';
import { isNative } from './platform';

const AUTH_TOKEN_KEY = 'auth_token';

export const getAuthToken = async () => {
  if (!isNative()) return null;
  const { value } = await Preferences.get({ key: AUTH_TOKEN_KEY });
  return value;
};

export const setAuthToken = async (token: string) => {
  if (!isNative()) return;
  await Preferences.set({ key: AUTH_TOKEN_KEY, value: token });
};

export const clearAuthToken = async () => {
  if (!isNative()) return;
  await Preferences.remove({ key: AUTH_TOKEN_KEY });
};
