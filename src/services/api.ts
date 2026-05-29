/*
 * 模块描述：前端 API 客户端，封装认证、聊天、工作区、记忆同步和管理后台请求。
 */

import type { ConversationMemory, CourtSession } from '../types';
import { clearAuthToken, getAuthToken, setAuthToken } from '../lib/auth-storage';
import { isNative } from '../lib/platform';

const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};
const API_BASE = isNative()
  ? (env.VITE_LAWVER_API_BASE || 'https://law.mutsumi.moe')
  : '';

let unauthorizedHandler: (() => void | Promise<void>) | null = null;

export interface LoginResult {
  status: string;
  message: string;
  username?: string;
  role?: string;
  token?: string;
}

export const setUnauthorizedHandler = (handler: (() => void | Promise<void>) | null) => {
  unauthorizedHandler = handler;
};

export const apiUrl = (path: string) => `${API_BASE}${path}`;

export const apiFetch = async (path: string, init: RequestInit = {}): Promise<Response> => {
  const headers = new Headers(init.headers);
  let finalInit: RequestInit;

  if (isNative()) {
    const token = await getAuthToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    headers.set('X-Lawver-Client', 'capacitor');
    finalInit = { ...init, credentials: 'omit', headers };
  } else {
    finalInit = { ...init, credentials: 'include', headers };
  }

  const response = await fetch(apiUrl(path), finalInit);
  if (response.status === 401) {
    await clearAuthToken();
    await unauthorizedHandler?.();
  }
  return response;
};

export class MemoryRevisionConflictError extends Error {
  detail: any;

  constructor(detail: any) {
    super('Memory revision conflict');
    this.name = 'MemoryRevisionConflictError';
    this.detail = detail;
  }
}

export class StreamExpiredError extends Error {
  constructor() {
    super('Stream expired');
    this.name = 'StreamExpiredError';
  }
}

export const buildChatRequestBody = (
  message: string,
  history: any[],
  conversationId: string,
  stream: boolean,
  agentMode: string,
  useOcp: boolean,
  memorySnapshot?: ConversationMemory | null,
  memorySyncMode?: 'merge' | 'rebuild',
  memoryConflictStrategy?: 'server_merge',
  lastContextTokens?: number | null,
  resumeEnabled = false
) => ({
  message,
  history,
  conversation_id: conversationId,
  stream,
  resume_enabled: resumeEnabled,
  agent_mode: agentMode,
  use_ocp: useOcp,
  memory_snapshot: memorySnapshot || null,
  memory_sync_mode: memorySyncMode,
  expected_revision: memorySnapshot?.revision,
  memory_conflict_strategy: memoryConflictStrategy,
  last_context_tokens: lastContextTokens ?? null
});

export const verifyAuth = async () => {
  const res = await apiFetch('/api/verify_auth');
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
};

export const login = async (username: string, password: string) => {
  const res = await apiFetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Login failed');
  }
  const data = await res.json() as LoginResult;
  if (isNative()) {
    if (!data.token) {
      throw new Error('原生登录未返回 Bearer token，请确认服务端已部署原生鉴权支持并允许 https://localhost。');
    }
    await setAuthToken(data.token);
  }
  return data;
};

export const logout = async () => {
  const res = await apiFetch('/api/logout', { method: 'POST' });
  await clearAuthToken();
  if (!res.ok) throw new Error('Logout failed');
  return res.json();
};

export const uploadFile = async (file: File, conversationId: string) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('conversation_id', conversationId);

  const res = await apiFetch('/api/upload', {
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
  memoryConflictStrategy?: 'server_merge',
  lastContextTokens?: number | null,
  resumeEnabled = false,
  signal?: AbortSignal
) => {
  const response = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify(buildChatRequestBody(
      message,
      history,
      conversationId,
      stream,
      agentMode,
      useOcp,
      memorySnapshot,
      memorySyncMode,
      memoryConflictStrategy,
      lastContextTokens,
      resumeEnabled
    ))
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

export const resumeStream = async (streamId: string, fromSeq: number, signal?: AbortSignal) => {
  const response = await apiFetch(`/api/chat/resume/${encodeURIComponent(streamId)}?from_seq=${encodeURIComponent(String(fromSeq))}`, {
    signal,
  });
  if (response.status === 410) {
    throw new StreamExpiredError();
  }
  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || errorData?.error || 'Resume stream failed');
  }
  return response;
};

export const ackStream = async (streamId: string, ackedSeq: number) => {
  const response = await apiFetch('/api/chat/ack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stream_id: streamId, acked_seq: ackedSeq })
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || errorData?.error || 'Ack stream failed');
  }
  return response.json();
};

export const cancelStream = async (streamId: string) => {
  const response = await apiFetch('/api/chat/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stream_id: streamId })
  });
  if (!response.ok && response.status !== 404) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || errorData?.error || 'Cancel stream failed');
  }
  return response.ok ? response.json() : { ok: true };
};

export const courtTurn = async (session: CourtSession, signal?: AbortSignal) => {
  const response = await apiFetch('/api/court/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      court_session_id: session.id,
      court_state: session.court_state,
      shared_dossier: session.shared_dossier,
      private_brief: session.private_brief,
      public_events_recent: session.public_events.slice(-30),
      public_summary: session.public_summary,
      agent_states: session.agent_states
    })
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || errorData.error || 'Court turn failed');
  }

  return response;
};

export const clearCourtMemory = async (courtSessionId: string, roles?: string[]) => {
  const res = await apiFetch('/api/court/memory/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      court_session_id: courtSessionId,
      roles: roles ?? null
    })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Clear court memory failed');
  }
  return res.json();
};

export const syncConversationMemory = async (
  conversationId: string,
  memorySnapshot?: ConversationMemory | null,
  history: any[] = [],
  mode: 'merge' | 'rebuild' = 'rebuild',
  memoryConflictStrategy?: 'server_merge'
) => {
  const res = await apiFetch('/api/memory/sync', {
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
  const res = await apiFetch(`/api/workspace/files?conversation_id=${encodeURIComponent(conversationId)}`);
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

  const res = await apiFetch('/api/workspace/restore', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    throw new Error('Restore failed');
  }
  return res.json();
};

export const deleteWorkspace = async (conversationId: string) => {
  const res = await apiFetch(`/api/workspace/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error('Delete workspace failed');
  }
  return res.json();
};

export const deleteWorkspaceFile = async (conversationId: string, path: string) => {
  const res = await apiFetch(`/api/workspace/file?conversation_id=${encodeURIComponent(conversationId)}&file_path=${encodeURIComponent(path)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error('Delete workspace file failed');
  }
  return res.json();
};

export const sendHeartbeat = async (conversationId: string) => {
  const res = await apiFetch(`/api/heartbeat/${encodeURIComponent(conversationId)}`, {
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
  
  const res = await apiFetch(`/api/admin/logs?${params.toString()}`);
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch logs');
  }
  return res.json();
};

export const clearLogs = async () => {
  const res = await apiFetch('/api/admin/logs', {
    method: 'DELETE'
  });
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to clear logs');
  }
  return res.json();
};

export const fetchAccounts = async () => {
  const res = await apiFetch('/api/admin/accounts');
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch accounts');
  }
  return res.json();
};

export const setAccount = async (username: string, password: string, role: string = 'user') => {
  const res = await apiFetch('/api/admin/accounts', {
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
  const res = await apiFetch(`/api/admin/accounts/${encodeURIComponent(username)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to delete account');
  }
  return res.json();
};

export const summarizeTitle = async (titleSource: string) => {
  const response = await apiFetch('/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      history: [{ role: 'user', content: titleSource.substring(0, 200) }]
    })
  });
  if (!response.ok) throw new Error('Summarize failed');
  return response.json();
};
