/*
 * 模块描述：前端 API 客户端，封装认证、聊天、工作区、记忆同步和管理后台请求。
 */

import type { ConversationMemory } from '../types';

export class MemoryRevisionConflictError extends Error {
  detail: any;

  constructor(detail: any) {
    super('Memory revision conflict');
    this.name = 'MemoryRevisionConflictError';
    this.detail = detail;
  }
}

export const verifyAuth = async () => {
  const res = await fetch('/api/verify_auth');
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
};

export const login = async (username: string, password: string) => {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Login failed');
  }
  return res.json();
};

export const logout = async () => {
  const res = await fetch('/api/logout', { method: 'POST' });
  if (!res.ok) throw new Error('Logout failed');
  return res.json();
};

export const uploadFile = async (file: File, conversationId: string) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('conversation_id', conversationId);

  const res = await fetch('/api/upload', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Upload failed');
  }

  return res.json();
};

export const chat = async (
  message: string,
  history: any[],
  conversationId: string,
  stream: boolean,
  agentMode: string,
  useOcp: boolean,
  memorySnapshot?: ConversationMemory | null,
  memorySyncMode?: 'merge' | 'rebuild',
  memoryConflictStrategy?: 'server_merge'
) => {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      history,
      conversation_id: conversationId,
      stream,
      agent_mode: agentMode,
      use_ocp: useOcp,
      memory_snapshot: memorySnapshot || null,
      memory_sync_mode: memorySyncMode,
      expected_revision: memorySnapshot?.revision,
      memory_conflict_strategy: memoryConflictStrategy
    })
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const detail = errorData?.detail || errorData;
    if (response.status === 409 && detail?.error === 'memory_revision_conflict') {
      throw new MemoryRevisionConflictError(detail);
    }
    throw new Error(errorData?.detail || errorData?.error || 'Network response was not ok');
  }

  return response;
};

export const syncConversationMemory = async (
  conversationId: string,
  memorySnapshot?: ConversationMemory | null,
  history: any[] = [],
  mode: 'merge' | 'rebuild' = 'rebuild',
  memoryConflictStrategy?: 'server_merge'
) => {
  const res = await fetch('/api/memory/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      memory_snapshot: memorySnapshot || null,
      history,
      mode,
      expected_revision: memorySnapshot?.revision,
      memory_conflict_strategy: memoryConflictStrategy
    })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => null);
    const detail = errorData?.detail || errorData;
    if (res.status === 409 && detail?.error === 'memory_revision_conflict') {
      throw new MemoryRevisionConflictError(detail);
    }
    throw new Error(errorData?.detail || 'Memory sync failed');
  }
  return res.json();
};

export const getWorkspaceFiles = async (conversationId: string) => {
  const res = await fetch(`/api/workspace/files?conversation_id=${encodeURIComponent(conversationId)}`);
  if (!res.ok) {
    throw new Error('Failed to fetch workspace files');
  }
  return res.json();
};

export const restoreFile = async (file: Blob, filename: string, conversationId: string, type: 'upload' | 'generated') => {
  const formData = new FormData();
  formData.append('file', file, filename);
  formData.append('conversation_id', conversationId);
  formData.append('file_type', type);

  const res = await fetch('/api/workspace/restore', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    throw new Error('Restore failed');
  }
  return res.json();
};

export const deleteWorkspace = async (conversationId: string) => {
  const res = await fetch(`/api/workspace/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error('Delete workspace failed');
  }
  return res.json();
};

export const deleteWorkspaceFile = async (conversationId: string, path: string) => {
  const res = await fetch(`/api/workspace/file?conversation_id=${encodeURIComponent(conversationId)}&file_path=${encodeURIComponent(path)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error('Delete workspace file failed');
  }
  return res.json();
};

export const sendHeartbeat = async (conversationId: string) => {
  const res = await fetch(`/api/heartbeat/${encodeURIComponent(conversationId)}`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error('Heartbeat failed');
  }
  return res.json();
};

export const fetchLogs = async (ip?: string, ignoreHeartbeat?: boolean) => {
  const params = new URLSearchParams();
  if (ip) params.append('ip', ip);
  if (ignoreHeartbeat) params.append('ignore_heartbeat', 'true');
  
  const res = await fetch(`/api/admin/logs?${params.toString()}`);
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch logs');
  }
  return res.json();
};

export const fetchAccounts = async () => {
  const res = await fetch('/api/admin/accounts');
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch accounts');
  }
  return res.json();
};

export const setAccount = async (username: string, password: string, role: string = 'user') => {
  const res = await fetch('/api/admin/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update account');
  }
  return res.json();
};
export const deleteAccount = async (username: string) => {
  const res = await fetch(`/api/admin/accounts/${encodeURIComponent(username)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to delete account');
  }
  return res.json();
};
