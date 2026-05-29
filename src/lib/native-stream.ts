/*
 * 模块描述：Android 原生前台服务流式接收插件的 TypeScript 适配层。
 */

import { registerPlugin, type PluginListenerHandle } from '@capacitor/core';
import { isNativeAndroid } from './platform';

export interface NativeStreamStartOptions {
  url: string;
  headers: Record<string, string>;
  body: string;
}

export interface NativeStreamStartResult {
  streamId: string;
}

export interface NativeStreamDrainResult {
  events: string[];
  nextIndex: number;
  done: boolean;
  error?: string;
}

export interface NativeStreamEvent {
  streamId: string;
  index: number;
  payload: string;
}

export interface NativeStreamDone {
  streamId: string;
  finalIndex: number;
  error?: string;
}

export interface NativeStreamPlugin {
  startStream(options: NativeStreamStartOptions): Promise<NativeStreamStartResult>;
  drain(options: { streamId: string; fromIndex: number }): Promise<NativeStreamDrainResult>;
  stop(options: { streamId: string }): Promise<void>;
  requestNotificationPermission?(): Promise<{ granted: boolean }>;
  addListener(
    eventName: 'streamEvent',
    listenerFunc: (event: NativeStreamEvent) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    eventName: 'streamDone',
    listenerFunc: (event: NativeStreamDone) => void,
  ): Promise<PluginListenerHandle>;
}

export const NativeStream = registerPlugin<NativeStreamPlugin>('StreamService');

export const requestNativeStreamNotificationPermission = async () => {
  if (!isNativeAndroid() || !NativeStream.requestNotificationPermission) return false;
  const result = await NativeStream.requestNotificationPermission();
  return Boolean(result.granted);
};
