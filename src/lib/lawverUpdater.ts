/*
 * 模块描述：Lawver Android 原生更新插件的 TypeScript 类型封装。
 */

import { registerPlugin, type PluginListenerHandle } from '@capacitor/core';

export interface AndroidReleaseManifest {
  platform: 'android';
  packageName: string;
  versionName: string;
  versionCode: number;
  apkUrl: string;
  sha256: string;
  size: number;
  publishedAt?: string;
}

export interface DownloadProgress {
  receivedBytes: number;
  totalBytes: number;
  percent: number;
}

interface DownloadApkOptions {
  url: string;
  fileName: string;
  sha256: string;
}

interface DownloadApkResult {
  filePath: string;
  fileName: string;
  size: number;
}

interface InstallApkResult {
  needsPermission: boolean;
  started?: boolean;
}

export interface LawverUpdaterPlugin {
  checkForUpdate(options: { manifestUrl: string }): Promise<AndroidReleaseManifest>;
  downloadApk(options: DownloadApkOptions): Promise<DownloadApkResult>;
  installApk(options: { filePath: string }): Promise<InstallApkResult>;
  openInstallPermissionSettings(): Promise<void>;
  addListener(
    eventName: 'downloadProgress',
    listenerFunc: (progress: DownloadProgress) => void,
  ): Promise<PluginListenerHandle>;
}

export const LawverUpdater = registerPlugin<LawverUpdaterPlugin>('LawverUpdater');
