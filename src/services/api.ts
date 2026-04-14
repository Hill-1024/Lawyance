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
  agentMode: string
) => {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      history,
      conversation_id: conversationId,
      stream,
      agent_mode: agentMode
    })
  });

  if (!response.ok) {
    throw new Error('Network response was not ok');
  }

  return response;
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

export const sendHeartbeat = async (conversationId: string) => {
  const res = await fetch(`/api/heartbeat/${encodeURIComponent(conversationId)}`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error('Heartbeat failed');
  }
  return res.json();
};
