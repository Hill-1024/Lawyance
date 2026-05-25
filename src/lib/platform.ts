/*
 * 模块描述：平台能力判断入口，隔离 Web 与 Capacitor 原生运行时差异。
 */

import { Capacitor } from '@capacitor/core';

export const isNative = () => Capacitor.isNativePlatform();

export const platform = () => Capacitor.getPlatform();

export const isNativeAndroid = () => isNative() && platform() === 'android';
