/*
 * 模块描述：Android Material You 动态色插件适配层，输出统一 Monet 色板结构。
 */

import { registerPlugin } from '@capacitor/core';
import type { MonetColors } from '../lib/palette';
import { isNativeAndroid } from '../lib/platform';

type MonetColorPlugin = {
  getColors?: () => Promise<unknown>;
};

const MonetColor = registerPlugin<MonetColorPlugin>('MonetColor');

const PALETTE_KEYS = ['accent1', 'accent2', 'accent3', 'neutral1', 'neutral2'] as const;

const isObject = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null
);

const normalizePalette = (raw: unknown): Partial<Record<string, string>> => {
  if (!isObject(raw)) return {};
  const palette: Partial<Record<string, string>> = {};
  Object.entries(raw).forEach(([key, value]) => {
    if (typeof value !== 'string') return;
    const normalizedKey = key.replace(/^tone/i, '');
    palette[normalizedKey] = value;
  });
  return palette;
};

const normalizeMonetColors = (raw: unknown): MonetColors | null => {
  if (!isObject(raw)) return null;
  const source = isObject(raw.colors) ? raw.colors : raw;
  const result = {} as MonetColors;
  for (const key of PALETTE_KEYS) {
    const palette = normalizePalette(source[key]);
    if (Object.keys(palette).length === 0) return null;
    result[key] = palette;
  }
  return result;
};

export const isMonetUnavailableError = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  return /android\s*(12|s)|31|unsupported|unavailable|not available/i.test(message);
};

export const getMonetPalette = async (): Promise<MonetColors | null> => {
  if (!isNativeAndroid()) {
    throw new Error('Material You 仅在 Android 客户端可用。');
  }

  if (!MonetColor.getColors) {
    throw new Error('Material You 插件未暴露 getColors。');
  }

  const colors = normalizeMonetColors(await MonetColor.getColors());
  if (!colors) {
    throw new Error('Material You 插件返回空色板。');
  }
  return colors;
};
