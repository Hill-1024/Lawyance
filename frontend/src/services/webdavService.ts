/*
 * 模块描述：WebDAV 数据同步前端服务，通过后端中转完成备份与恢复。
 */

import { apiFetch } from './api';
import type { WebDavConfig } from '../lib/webdav-storage';

export interface WebDavFileInfo {
  filename: string;
  size: number;
  last_modified: string;
}

const post = async (endpoint: string, body: object): Promise<any> => {
  const res = await apiFetch(`/api/webdav/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `WebDAV 请求失败（${res.status}）`);
  }
  return res.json();
};

export const webdavService = {
  async testConnection(config: WebDavConfig): Promise<{ created_directory: boolean }> {
    return post('test', { config });
  },

  async listBackups(config: WebDavConfig): Promise<WebDavFileInfo[]> {
    const data = await post('list', { config });
    return data.files as WebDavFileInfo[];
  },

  async uploadBackup(config: WebDavConfig, filename: string, jsonPayload: object): Promise<void> {
    const jsonStr = JSON.stringify(jsonPayload);
    const data_b64 = btoa(unescape(encodeURIComponent(jsonStr)));
    await post('upload', { config, filename, data_b64 });
  },

  async downloadBackup(config: WebDavConfig, filename: string): Promise<object> {
    const data = await post('download', { config, filename });
    const jsonStr = decodeURIComponent(escape(atob(data.data_b64 as string)));
    return JSON.parse(jsonStr);
  },

  async deleteBackup(config: WebDavConfig, filename: string): Promise<void> {
    await post('delete', { config, filename });
  },

  generateFilename(): string {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    return `lawver_backup_${date}_${time}.json`;
  },
};
