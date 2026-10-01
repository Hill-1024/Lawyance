/*
 * 模块描述：前端 API 客户端，封装认证、聊天、工作区、记忆同步和管理后台请求。
 */

import type { ConversationMemory, CourtSession } from '../types';
import { clearAuthToken, getAuthToken, setAuthToken } from '../lib/auth-storage';
import { APP_CONFIG, BASE_PATH } from '../lib/app-config';
import { isNative } from '../lib/platform';

const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};
// Web 端带上网关区域前缀（如 /cn），使 API 请求与页面落入同一区域后端；无前缀时为空串。
// 原生端不走网关路径分流，直连 appConfig.nativeApiBase 指定的后端。
const API_BASE = isNative()
  ? (env.VITE_LAWVER_API_BASE || APP_CONFIG.nativeApiBase)
  : BASE_PATH;

let unauthorizedHandler: (() => void | Promise<void>) | null = null;

export type Role = 'sudo' | 'admin' | 'user';

export interface LoginResult {
  status: string;
  message: string;
  username?: string;
  role?: Role;
  token?: string;
}

export interface AuthInfo {
  status: string;
  username: string;
  role: Role;
  max_online?: number | null;
  online_count?: number;
  max_users?: number | null;
  user_max_online?: number | null;
}

export interface Account {
  username: string;
  role: Role;
  owner?: string | null;
  max_online?: number | null;
  max_users?: number | null;
  user_max_online?: number | null;
  online_count?: number;
  owned_count?: number | null;
  /** 计费与状态：由 GET /api/admin/accounts 返回。 */
  plan?: string;
  billing_cycle?: string;
  credits?: number;
  status?: string;
  /** 仍被登录锁定多少秒；0 表示没被锁。 */
  locked_seconds?: number;
}

export interface AccountLimits {
  /** 0 表示不限制；不传表示沿用原值。 */
  max_online?: number;
  /** -1 表示不限制；不传表示沿用原值。 */
  max_users?: number;
  /** 0 表示不限制；不传表示沿用原值。 */
  user_max_online?: number;
}

export interface SessionInfo {
  sid: string;
  username: string;
  client?: string | null;
  user_agent?: string | null;
  ip_hash?: string | null;
  created_at: number;
  last_seen_at: number;
  expires_at: number;
  online: boolean;
}

export const setUnauthorizedHandler = (handler: (() => void | Promise<void>) | null) => {
  unauthorizedHandler = handler;
};

export const apiUrl = (path: string) => `${API_BASE}${path}`;

/** 登录/注册类端点的 401 表示凭据错误，而非会话失效。 */
const AUTH_ATTEMPT_PATHS = ['/api/login', '/api/register'];
const isAuthAttemptPath = (path: string) => AUTH_ATTEMPT_PATHS.some(p => path.startsWith(p));

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
  // /api/login 也会用 401 表达"密码错误"，不能因此清掉此前有效的原生会话令牌。
  if (response.status === 401 && !isAuthAttemptPath(path)) {
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

export const verifyAuth = async (): Promise<AuthInfo> => {
  const res = await apiFetch('/api/verify_auth');
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
};

export interface SessionProbe {
  authenticated: boolean;
  username?: string;
  role?: Role;
}

/** 自助改密：需要当前密码；改完其他设备下线，当前设备保留。 */
export const changePassword = async (
  currentPassword: string,
  newPassword: string
): Promise<{ status: string; message: string; revoked_sessions: number }> => {
  const res = await apiFetch('/api/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '修改密码失败');
  }
  return res.json();
};

/**
 * 登录态探测：服务端保证 200，用 authenticated 字段表达结果。
 * 启动时的这次探测走 verify_auth 必然 401，浏览器会把每个 4xx 资源响应记成
 * console error——每个未登录用户一打开页面就有一条噪音。
 */
export const fetchSession = async (): Promise<SessionProbe> => {
  const res = await apiFetch('/api/session');
  if (!res.ok) return { authenticated: false };
  return res.json();
};

// ─── 个人资料（自定义 ID / 头像）──────────────────────────────────────────

export interface AccountProfile {
  username: string;
  uid: string;
  custom_id: string | null;
  role: Role;
  plan: string;
  avatar_version: number;
}

export const fetchAccountProfile = async (): Promise<AccountProfile | null> => {
  const res = await apiFetch('/api/profile');
  if (!res.ok) return null;
  return res.json();
};

// ─── 自助用量控制台 ───────────────────────────────────────────────────────

export interface UsageDay {
  day: string;
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  tool_calls: number;
  documents: number;
  turns: number;
  credits: number;
}

export interface UsageSummary {
  days: number;
  plan: string;
  pending_plan: string | null;
  pending_effective_at: string | null;
  balance: number;
  quota: number | null;
  totals: { tokens: number; prompt_tokens: number; completion_tokens: number; tool_calls: number; documents: number; turns: number; credits: number };
  series: UsageDay[];
}

export const fetchUsageSummary = async (days: number): Promise<UsageSummary> => {
  const res = await apiFetch(`/api/usage/summary?days=${days}`);
  if (!res.ok) throw new Error('读取用量失败');
  return res.json();
};

/** 预约降级/切回按量：下一结算周期生效，可随时取消。返回端点确认（非 summary）。 */
export const schedulePlanChange = async (targetPlan: string): Promise<void> => {
  const res = await apiFetch('/api/subscription/change', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_plan: targetPlan }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '操作失败');
  }
};

/** 取消预约中的变更：当前套餐与权益原样保留。 */
export const cancelScheduledPlanChange = async (): Promise<void> => {
  const res = await apiFetch('/api/subscription/cancel-change', { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '操作失败');
  }
};


export const updateCustomId = async (customId: string | null): Promise<AccountProfile> => {
  const res = await apiFetch('/api/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ custom_id: customId }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '保存失败');
  }
  const data = await res.json();
  return data.profile;
};

/** 头像 URL：version 参与缓存失效，改头像后换 URL 即可。 */
export const avatarUrl = (uid: string, version: number) =>
  `${apiUrl(`/api/avatars/${uid}`)}?v=${version}`;

export const uploadAvatar = async (file: File): Promise<AccountProfile> => {
  const body = new FormData();
  body.append('file', file);
  const res = await apiFetch('/api/profile/avatar', { method: 'PUT', body });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '上传失败');
  }
  const data = await res.json();
  return data.profile;
};

export const removeAvatar = async (): Promise<AccountProfile> => {
  const res = await apiFetch('/api/profile/avatar', { method: 'DELETE' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string })?.detail || '移除失败');
  }
  const data = await res.json();
  return data.profile;
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

export type UploadProgressSnapshot = {
  loaded: number;
  total: number;
  progress: number;
};

const buildUploadProgressSnapshot = (
  fileSize: number,
  loaded: number,
  total?: number
): UploadProgressSnapshot => {
  const safeFileSize = Math.max(fileSize, 0);
  const ratio = total && total > 0
    ? Math.min(Math.max(loaded / total, 0), 1)
    : safeFileSize > 0
    ? Math.min(Math.max(loaded / safeFileSize, 0), 1)
    : 0;
  const fileLoaded = safeFileSize > 0 ? Math.min(safeFileSize, Math.round(safeFileSize * ratio)) : 0;

  return {
    loaded: fileLoaded,
    total: safeFileSize,
    progress: ratio
  };
};

const parseUploadResponse = (xhr: XMLHttpRequest) => {
  if (xhr.response && typeof xhr.response === 'object') {
    return xhr.response;
  }
  try {
    return JSON.parse(xhr.responseText || '{}');
  } catch {
    return {};
  }
};

export const uploadFile = async (
  file: File,
  conversationId: string,
  onProgress?: (snapshot: UploadProgressSnapshot) => void
) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('conversation_id', conversationId);

  if (onProgress && typeof XMLHttpRequest !== 'undefined') {
    onProgress({ loaded: 0, total: file.size, progress: 0 });

    return new Promise<any>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', apiUrl('/api/upload'));
      xhr.responseType = 'json';

      xhr.upload.onprogress = event => {
        onProgress(buildUploadProgressSnapshot(file.size, event.loaded, event.lengthComputable ? event.total : undefined));
      };

      xhr.onload = async () => {
        const data = parseUploadResponse(xhr);

        if (xhr.status === 401) {
          await clearAuthToken();
          await unauthorizedHandler?.();
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress({ loaded: file.size, total: file.size, progress: 1 });
          resolve(data);
          return;
        }

        reject(new Error(data?.detail || data?.error || 'Upload failed'));
      };

      xhr.onerror = () => reject(new Error('Upload failed'));
      xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'));

      const sendUpload = async () => {
        if (isNative()) {
          const token = await getAuthToken();
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
          xhr.setRequestHeader('X-Lawver-Client', 'capacitor');
          xhr.withCredentials = false;
        } else {
          xhr.withCredentials = true;
        }
        xhr.send(formData);
      };

      sendUpload().catch(reject);
    });
  }

  const res = await apiFetch('/api/upload', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Upload failed');
  }

  onProgress?.({ loaded: file.size, total: file.size, progress: 1 });
  return res.json();
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

export const fetchAccounts = async (): Promise<{ status: string; accounts: Account[] }> => {
  const res = await apiFetch('/api/admin/accounts');
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch accounts');
  }
  return res.json();
};

export interface AccountProvision {
  /** 建账号时的套餐与计费方式；不传由后端填默认值。 */
  plan?: string;
  billing_cycle?: string;
  credit_multiplier?: number;
  /** 开户额度（credits）：只在新建账号时经账本入账。 */
  initial_credits?: number;
}

export const setAccount = async (
  username: string,
  password: string,
  role: Role = 'user',
  limits: AccountLimits = {},
  provision: AccountProvision = {}
) => {
  const res = await apiFetch('/api/admin/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role, ...limits, ...provision })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update account');
  }
  return res.json();
};

/** 解除登录锁定（账号桶 + 该账号名下全部来源桶）。 */
export const unlockAccount = async (username: string) => {
  const res = await apiFetch(`/api/admin/accounts/${encodeURIComponent(username)}/unlock`, {
    method: 'POST'
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || '解锁失败');
  }
  return res.json();
};

/** Business 母账号创建子账号（只能建普通用户，受 max_users 约束）。 */
export const createSubaccount = async (username: string, password: string) => {
  const res = await apiFetch('/api/business/subaccounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || '创建子账号失败');
  }
  return res.json();
};

/** Business 母账号停用/启用自己名下的子账号。 */
export const setSubaccountStatus = async (username: string, status: 'active' | 'suspended') => {
  const res = await apiFetch(`/api/business/subaccounts/${encodeURIComponent(username)}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || '状态更新失败');
  }
  return res.json();
};

export const setAccountStatus = async (username: string, status: 'active' | 'suspended') => {
  const res = await apiFetch(`/api/admin/accounts/${encodeURIComponent(username)}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update account status');
  }
  return res.json();
};

export interface TopUpResult {
  status: string;
  username: string;
  id: string;
  credited: number;
  balance: number;
}

export const topUpAccount = async (
  username: string,
  amountYuan: number,
  note = ''
): Promise<TopUpResult> => {
  const res = await apiFetch(`/api/admin/accounts/${encodeURIComponent(username)}/topups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount_yuan: amountYuan, note })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to top up account');
  }
  return res.json();
};

export const updateAccountLimits = async (username: string, limits: AccountLimits) => {
  const res = await apiFetch(`/api/admin/accounts/${encodeURIComponent(username)}/limits`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(limits)
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update limits');
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

export const fetchSessions = async (): Promise<{ status: string; sessions: SessionInfo[] }> => {
  const res = await apiFetch('/api/admin/sessions');
  if (!res.ok) {
    if (res.status === 403) throw new Error('Access denied. Admin role required.');
    throw new Error('Failed to fetch sessions');
  }
  return res.json();
};

export const revokeSession = async (sid: string) => {
  const res = await apiFetch(`/api/admin/sessions/${encodeURIComponent(sid)}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to revoke session');
  }
  return res.json();
};

export interface ProviderStatus {
  provider: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  ok: boolean;
  message: string;
}

export interface AppSettings {
  version: number;
  providers: Record<string, {
    enabled: boolean;
    base_url?: string;
    model?: string;
    endpoint?: string;
    language?: string;
    safe_search?: string;
    engines?: string;
    categories?: string;
  }>;
}

export const getSettings = async (): Promise<AppSettings> => {
  const response = await apiFetch('/api/settings');
  if (!response.ok) {
    throw await response.json().then(data => new Error((data as any)?.detail || '读取设置失败'));
  }
  return response.json();
};

export const updateSettings = async (payload: Partial<AppSettings>): Promise<AppSettings> => {
  const response = await apiFetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await response.json().then(data => new Error((data as any)?.detail || '保存失败'));
  return response.json();
};

export const getProviderStatus = async (): Promise<ProviderStatus[]> => {
  try {
    const response = await apiFetch('/api/providers/status');
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
};

export const testProvider = async (provider: string): Promise<ProviderStatus> => {
  const response = await apiFetch(`/api/providers/test/${provider}`);
  if (!response.ok) throw await response.json().then(data => new Error((data as any)?.detail || '测试失败'));
  return response.json();
};

export const setSecret = async (provider: string, key: string, value: string): Promise<void> => {
  const response = await apiFetch('/api/settings/secret', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, key, value }),
  });
  if (!response.ok) {
    throw await response.json().then(data => new Error((data as any)?.detail || '保存凭据失败'));
  }
};

export const clearSecret = async (provider: string, key?: string): Promise<void> => {
  const response = await apiFetch('/api/settings/secret/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, key }),
  });
  if (!response.ok) {
    throw await response.json().then(data => new Error((data as any)?.detail || '清除凭据失败'));
  }
};

export type LlmModel = { id: string; owned_by: string };

export interface LlmProfile {
  id: string;
  name: string;
  base_url: string;
  model: string;
  enabled: boolean;
  has_api_key: boolean;
  /** 缺少端点或模型时后端会整体回退到环境变量，该档案不会生效。 */
  incomplete?: boolean;
  active: boolean;
}

export interface LlmProfileState {
  profiles: LlmProfile[];
  active: string;
  effective: { base_url: string; model: string; source: string };
}

const profileError = async (response: Response, fallback: string) =>
  response.json()
    .then(data => new Error((data as any)?.detail || fallback))
    .catch(() => new Error(fallback));

export const getLlmProfiles = async (): Promise<LlmProfileState> => {
  const response = await apiFetch('/api/settings/llm/profiles');
  if (!response.ok) throw await profileError(response, '读取模型档案失败');
  return response.json();
};

export const saveLlmProfile = async (payload: {
  id?: string;
  name: string;
  base_url: string;
  model: string;
  api_key?: string;
  enabled?: boolean;
  activate?: boolean;
}): Promise<LlmProfileState> => {
  const response = await apiFetch('/api/settings/llm/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await profileError(response, '保存模型档案失败');
  return response.json();
};

export const activateLlmProfile = async (profileId: string): Promise<LlmProfileState> => {
  const response = await apiFetch(
    `/api/settings/llm/profiles/${encodeURIComponent(profileId)}/activate`,
    { method: 'POST' },
  );
  if (!response.ok) throw await profileError(response, '切换模型档案失败');
  return response.json();
};

export const deleteLlmProfile = async (profileId: string): Promise<LlmProfileState> => {
  const response = await apiFetch(`/api/settings/llm/profiles/${encodeURIComponent(profileId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw await profileError(response, '删除模型档案失败');
  return response.json();
};

export const clearLlmProfileSecret = async (profileId: string): Promise<void> => {
  const response = await apiFetch(
    `/api/settings/llm/profiles/${encodeURIComponent(profileId)}/secret/clear`,
    { method: 'POST' },
  );
  if (!response.ok) throw await profileError(response, '清除该档案的 API Key 失败');
};

export const fetchLlmModels = async (): Promise<LlmModel[]> => {
  try {
    const response = await apiFetch('/api/llm/models');
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
};

/* ── 用量与监控 ───────────────────────────────────────────────────────── */

export interface UsageRow {
  day: string;
  prompt_tokens: number;
  completion_tokens: number;
  tool_calls: number;
  documents: number;
  turns: number;
  credits: number;
}

export interface UsageAccount {
  username: string;
  plan: string;
  billing_cycle: string;
  status: string;
  credits: number;
  usage: UsageRow[];
}

export const fetchAdminUsage = async (): Promise<{ status: string; accounts: UsageAccount[] }> => {
  const res = await apiFetch('/api/admin/usage');
  if (!res.ok) {
    if (res.status === 403) throw new Error('需要管理员权限。');
    throw new Error('读取用量数据失败。');
  }
  return res.json();
};

/* ── 我的额度 ─────────────────────────────────────────────────────────── */

export interface MyCredits {
  username: string;
  plan: string;
  billing_cycle: string;
  credits: number;
  multiplier: number;
  credit_quota: number | null;
  exempt: boolean;
}

/** 当前账号的余额与套餐：侧栏余额、Business 入口与设置页都读这一份。 */
export const fetchMyCredits = async (): Promise<MyCredits> => {
  const res = await apiFetch('/api/credits');
  if (!res.ok) throw new Error('读取额度失败。');
  return res.json();
};

/* ── Business：母账号管理子账号 ───────────────────────────────────────── */

/** 403 表示当前账号不是 Business 套餐：调用方据此渲染说明页，而不是错误屏。 */
export class PlanForbiddenError extends Error {
  constructor(message = '仅 Business 账号可用。') {
    super(message);
    this.name = 'PlanForbiddenError';
  }
}

export interface BusinessSubAccount {
  username: string;
  status: string;
  credits: number;
  /** 预算上限；null 表示不限。 */
  quota: number | null;
  usage: UsageRow[];
}

export interface BusinessOverview {
  parent_credits: number;
  max_users: number | null;
  subaccounts: BusinessSubAccount[];
}

export const fetchBusinessOverview = async (): Promise<BusinessOverview> => {
  const res = await apiFetch('/api/business/subaccounts');
  if (res.status === 403) throw new PlanForbiddenError();
  if (!res.ok) throw new Error('读取子账号失败。');
  return res.json();
};

export interface BusinessAllocation {
  status: string;
  username: string;
  parent_credits: number;
  child_credits: number;
}

/** 母账号划转 credits 给子账号；返回划转后的双方余额。 */
export const allocateSubaccountCredits = async (
  username: string,
  credits: number
): Promise<BusinessAllocation> => {
  const res = await apiFetch(`/api/business/subaccounts/${encodeURIComponent(username)}/credits`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credits })
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data?.detail === 'string' ? data.detail : '分配 credits 失败。');
  }
  return res.json();
};

/* ── 开屏公告 ─────────────────────────────────────────────────────────── */

export type AnnouncementLevel = 'info' | 'warning' | 'danger';

export interface Announcement {
  id: string;
  title: string;
  body: string;
  level: AnnouncementLevel;
  audience?: string[];
  starts_at?: string | null;
  ends_at?: string | null;
  active?: boolean;
  created_by?: string | null;
  created_at?: string | null;
}

export interface AnnouncementInput {
  title: string;
  body: string;
  level: AnnouncementLevel;
  audience: string[];
  starts_at?: string | null;
  ends_at?: string | null;
  active: boolean;
}

const announcementError = async (response: Response, fallback: string) =>
  response.json()
    .then(data => {
      const detail = (data as any)?.detail;
      if (typeof detail === 'string') return new Error(detail);
      return new Error(fallback);
    })
    .catch(() => new Error(fallback));

export const fetchAnnouncements = async (): Promise<{ status: string; announcements: Announcement[] }> => {
  const res = await apiFetch('/api/announcements');
  if (!res.ok) throw new Error('读取公告失败。');
  return res.json();
};

export const fetchAdminAnnouncements = async (): Promise<{ status: string; announcements: Announcement[] }> => {
  const res = await apiFetch('/api/admin/announcements');
  if (!res.ok) throw await announcementError(res, '读取公告列表失败。');
  return res.json();
};

export const createAnnouncement = async (payload: AnnouncementInput): Promise<Announcement> => {
  const res = await apiFetch('/api/admin/announcements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw await announcementError(res, '保存公告失败。');
  const data = await res.json();
  return data.announcement as Announcement;
};

export const updateAnnouncement = async (
  id: string,
  patch: Partial<AnnouncementInput>
): Promise<Announcement> => {
  const res = await apiFetch(`/api/admin/announcements/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  });
  if (!res.ok) throw await announcementError(res, '保存公告失败。');
  const data = await res.json();
  return data.announcement as Announcement;
};

export const deleteAnnouncement = async (id: string): Promise<void> => {
  const res = await apiFetch(`/api/admin/announcements/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
  if (!res.ok) throw await announcementError(res, '删除公告失败。');
};


export type ThrottleBucket = {
  scope: 'account' | 'client';
  key: string;
  fails: number;
  locked_seconds: number;
  last_failed_at: number;
};

export const fetchThrottleBuckets = async (): Promise<{ buckets: ThrottleBucket[] }> => {
  const response = await apiFetch('/api/admin/throttle');
  if (!response.ok) throw new Error('无法读取登录节流状态');
  return response.json();
};
