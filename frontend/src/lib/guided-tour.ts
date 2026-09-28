/*
 * 模块描述：应用功能指引弹窗的持久化与全局唤起事件。
 */

import { Preferences } from '@capacitor/preferences';
import { isNative } from './platform';

const GUIDED_TOUR_SEEN_KEY = 'lawver.guidedTour.v1.seen';
const GUIDED_TOUR_REQUEST_EVENT = 'lawver:guided-tour-request';

export const getGuidedTourSeen = async (): Promise<boolean> => {
  try {
    if (isNative()) {
      const { value } = await Preferences.get({ key: GUIDED_TOUR_SEEN_KEY });
      return value === '1';
    }
    return localStorage.getItem(GUIDED_TOUR_SEEN_KEY) === '1';
  } catch {
    return false;
  }
};

export const setGuidedTourSeen = async (seen: boolean): Promise<void> => {
  const value = seen ? '1' : '0';
  if (isNative()) {
    await Preferences.set({ key: GUIDED_TOUR_SEEN_KEY, value });
  } else {
    localStorage.setItem(GUIDED_TOUR_SEEN_KEY, value);
  }
};

export const requestGuidedTour = () => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(GUIDED_TOUR_REQUEST_EVENT));
};

export const subscribeGuidedTourRequest = (listener: () => void) => {
  if (typeof window === 'undefined') return () => undefined;
  const handleRequest = () => listener();
  window.addEventListener(GUIDED_TOUR_REQUEST_EVENT, handleRequest);
  return () => window.removeEventListener(GUIDED_TOUR_REQUEST_EVENT, handleRequest);
};
