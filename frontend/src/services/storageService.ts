/*
 * 模块描述：浏览器本地存储服务，负责垃圾回收、导出备份和容量维护。
 */

import { fileDB } from '../lib/db';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { isNative } from '../lib/platform';
import { notifyLocalStorageDataChanged } from './storageEvents';
import type { Conversation, CourtAgentStates, CourtPublicEvent, CourtSession } from '../types';
import { getResumeEnabled, notifyResumeEnabledChanged, setResumeEnabled } from '../lib/resume-prefs';
import { decryptBackupData, encryptBackupData } from '../lib/backup-crypto';

const decodeCodes = (codes: number[]) => codes.map(code => String.fromCharCode(code)).join('');
const LEGACY_EXPORT_EXTENSION = decodeCodes([46, 108, 97, 119, 118, 101, 114]);

const bytesToBase64 = (bytes: Uint8Array): string => {
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
};


const generateUUID = (): string => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    return (([1e7] as any)+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, (c: any) =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
};

const nowIso = () => new Date().toISOString();

const replaceIdInText = (value: unknown, oldId: string, newId: string) => {
  return typeof value === 'string' ? value.replaceAll(oldId, newId) : value;
};

const remapConversation = (conv: any): Conversation => {
  const oldId = String(conv.id || '');
  const newId = generateUUID();
  const updatedAt = nowIso();

  const newConv = { ...conv, id: newId };
  if (newConv.memory) {
    newConv.memory = {
      ...newConv.memory,
      conversation_id: newId,
      last_synced_at: '',
      updated_at: updatedAt
    };
  }

  newConv.messages = Array.isArray(conv.messages)
    ? conv.messages.map((msg: any) => {
      const thought_blocks = Array.isArray(msg.thought_blocks)
        ? msg.thought_blocks.map((block: any) => ({
          ...block,
          content: replaceIdInText(block.content, oldId, newId)
        }))
        : msg.thought_blocks;

      return {
        ...msg,
        content: replaceIdInText(msg.content || '', oldId, newId),
        reasoning_content: replaceIdInText(msg.reasoning_content || '', oldId, newId),
        thought_blocks
      };
    })
    : [];

  return newConv as Conversation;
};

const remapCourtEvent = (event: any, oldId: string, newId: string): CourtPublicEvent => {
  const timestamp = nowIso();
  return {
    ...event,
    id: generateUUID(),
    content: replaceIdInText(event?.content || '', oldId, newId) as string,
    created_at: event?.created_at || timestamp,
    updated_at: event?.updated_at || timestamp
  };
};

const remapCourtAgentStates = (agentStates: any, newId: string): CourtAgentStates => {
  const roles: Array<keyof CourtAgentStates> = ['judge', 'opponent', 'reviewer', 'user'];
  const timestamp = nowIso();
  return roles.reduce((result, role) => {
    const state = agentStates?.[role] || {};
    result[role] = {
      ...state,
      status: 'idle',
      memory_snapshot: state.memory_snapshot
        ? {
          ...state.memory_snapshot,
          conversation_id: `${newId}:${role}`,
          last_synced_at: '',
          updated_at: timestamp
        }
        : null
    };
    return result;
  }, {} as CourtAgentStates);
};

const remapCourtSession = (session: any): CourtSession => {
  const oldId = String(session.id || '');
  const newId = generateUUID();
  const timestamp = nowIso();

  return {
    ...session,
    id: newId,
    title: (replaceIdInText(session.title || '模拟法庭', oldId, newId) as string) || '模拟法庭',
    shared_dossier: {
      summary: replaceIdInText(session.shared_dossier?.summary || '', oldId, newId) as string,
      claims: replaceIdInText(session.shared_dossier?.claims || '', oldId, newId) as string,
      evidence: replaceIdInText(session.shared_dossier?.evidence || '', oldId, newId) as string
    },
    private_brief: {
      strategy: replaceIdInText(session.private_brief?.strategy || '', oldId, newId) as string,
      logic_chain: replaceIdInText(session.private_brief?.logic_chain || '', oldId, newId) as string,
      risk_notes: replaceIdInText(session.private_brief?.risk_notes || '', oldId, newId) as string
    },
    public_events: Array.isArray(session.public_events)
      ? session.public_events.map((event: any) => remapCourtEvent(event, oldId, newId))
      : [],
    pending_interjections: Array.isArray(session.pending_interjections)
      ? session.pending_interjections.map((event: any) => remapCourtEvent(event, oldId, newId))
      : [],
    agent_states: remapCourtAgentStates(session.agent_states, newId),
    created_at: timestamp,
    updated_at: timestamp
  } as CourtSession;
};

// ─── 快照 v4（对话 + 庭审 + 应用设置，WebDAV 和本地导出共用对象结构）──────────

const THEME_STORAGE_KEY = 'lawver.theme.settings';

export interface BackupSnapshot {
  version: 4;
  conversations: Conversation[];
  courtSessions: CourtSession[];
  settings: {
    theme: string | null;
    resumeEnabled?: boolean;
  };
}

export const buildBackupSnapshot = async (): Promise<BackupSnapshot> => {
  const [conversations, courtSessions] = await Promise.all([
    fileDB.getConversations(),
    fileDB.getCourtSessions(),
  ]);
  return {
    version: 4,
    conversations,
    courtSessions,
    settings: {
      theme: localStorage.getItem(THEME_STORAGE_KEY),
      resumeEnabled: await getResumeEnabled(),
    },
  };
};

export const applyBackupSnapshot = async (raw: any): Promise<number> => {
  const conversations: any[] = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.conversations) ? raw.conversations : [];
  const courtSessions: any[] = Array.isArray(raw)
    ? []
    : Array.isArray(raw?.courtSessions) ? raw.courtSessions : [];

  const newConversations = conversations.map(remapConversation);
  const newCourtSessions = courtSessions.map(remapCourtSession);

  await Promise.all([
    newConversations.length ? fileDB.addConversations(newConversations) : Promise.resolve(),
    newCourtSessions.length ? fileDB.addCourtSessions(newCourtSessions) : Promise.resolve(),
  ]);

  // 恢复设置并通知 ThemeContext 刷新
  const themeRaw = raw?.settings?.theme;
  if (themeRaw && typeof themeRaw === 'string') {
    localStorage.setItem(THEME_STORAGE_KEY, themeRaw);
    window.dispatchEvent(new StorageEvent('storage', {
      key: THEME_STORAGE_KEY,
      newValue: themeRaw,
      storageArea: localStorage,
    }));
  }

  const resumeEnabledRaw = raw?.settings?.resumeEnabled;
  if (typeof resumeEnabledRaw === 'boolean') {
    await setResumeEnabled(resumeEnabledRaw);
    notifyResumeEnabledChanged(resumeEnabledRaw);
  }

  notifyLocalStorageDataChanged({
    source: 'import',
    conversationIds: newConversations.map(c => c.id),
    courtSessionIds: newCourtSessions.map(s => s.id),
  });

  return newConversations.length + newCourtSessions.length;
};

/**
 * 镜像式还原：让本地状态完全对齐备份——按原 id 保留（不重发 UUID），
 * fileDB.saveConversations / saveCourtSessions 会删除备份里不存在的本地记录，
 * 从而消除"恢复即重复"并让删除得以传播。仅用于 WebDAV 云端恢复，
 * 不可用于"导入他人分享文件"（那会误删本地数据，文件导入仍走 applyBackupSnapshot）。
 */
export const restoreBackupSnapshot = async (raw: any): Promise<number> => {
  const hasConversations = Array.isArray(raw?.conversations);
  const hasCourtSessions = Array.isArray(raw?.courtSessions);
  if (!Array.isArray(raw) && !hasConversations && !hasCourtSessions) {
    throw new Error('备份文件格式无法识别，已取消恢复（避免误清空本地数据）。');
  }

  const conversations: Conversation[] = Array.isArray(raw)
    ? raw
    : hasConversations ? raw.conversations : [];
  const courtSessions: CourtSession[] = Array.isArray(raw)
    ? []
    : hasCourtSessions ? raw.courtSessions : [];

  await Promise.all([
    fileDB.saveConversations(conversations),
    fileDB.saveCourtSessions(courtSessions),
  ]);

  const themeRaw = raw?.settings?.theme;
  if (themeRaw && typeof themeRaw === 'string') {
    localStorage.setItem(THEME_STORAGE_KEY, themeRaw);
    window.dispatchEvent(new StorageEvent('storage', {
      key: THEME_STORAGE_KEY,
      newValue: themeRaw,
      storageArea: localStorage,
    }));
  }

  const resumeEnabledRaw = raw?.settings?.resumeEnabled;
  if (typeof resumeEnabledRaw === 'boolean') {
    await setResumeEnabled(resumeEnabledRaw);
    notifyResumeEnabledChanged(resumeEnabledRaw);
  }

  notifyLocalStorageDataChanged({
    source: 'import',
    conversationIds: conversations.map(c => c.id),
    courtSessionIds: courtSessions.map(s => s.id),
  });

  return conversations.length + courtSessions.length;
};

export const storageService = {
  acceptedConversationFileExtensions: [".lawver", ".json.enc", LEGACY_EXPORT_EXTENSION].join(","),

  getConversationTimestamp(c: any): number {
    const timestamps = [
      Date.parse(c.updated_at || ''),
      Date.parse(c.created_at || ''),
      ...(c.messages || []).map((msg: any) => {
        const explicit = Date.parse(msg.updated_at || msg.created_at || '');
        if (!Number.isNaN(explicit)) return explicit;
        const numericId = Number(msg.id);
        return Number.isFinite(numericId) ? numericId : 0;
      })
    ].filter(value => Number.isFinite(value));
    return Math.max(...timestamps, 0);
  },

  async garbageCollect() {
    const files = await fileDB.getAllFiles();
    let cleanedCount = 0;
    let spaceSaved = 0;

    for (const file of files) {
      // Logic for "unimportant" data:
      // 1. Empty blobs
      // 2. Old logs or previews (if distinguishable)
      // For now, let's target very old files (> 30 days) that are not "upload" type if we had that info
      // Or just empty/invalid ones.
      
      if (!file.blob || file.blob.size === 0) {
        await fileDB.deleteFile(file.convId, file.fileName, file.path);
        cleanedCount++;
      }
    }
    
    return { cleanedCount, spaceSaved };
  },

  async clearOldData(daysThreshold: number = 30) {
    const conversations = await fileDB.getConversations();
    const now = Date.now();
    const threshold = daysThreshold * 24 * 60 * 60 * 1000;
    
    const oldConvs = conversations.filter(c => {
      const ts = this.getConversationTimestamp(c);
      return (now - ts) > threshold;
    });

    for (const conv of oldConvs) {
      await fileDB.deleteFilesByConvId(conv.id);
    }
    
    // Update conversations list
    const remainingConvs = conversations.filter(c => !oldConvs.find(oc => oc.id === c.id));
    await fileDB.saveConversations(remainingConvs);
    
    return oldConvs.length;
  },

  // --- Dialogue Migration (Text Only) ---

  async encryptDataToBlob(data: string, passphrase: string): Promise<Blob> {
    const encrypted = await encryptBackupData(data, passphrase);
    return new Blob([encrypted], { type: 'application/octet-stream' });
  },

  async decryptDataFromFile(file: File, passphrase: string): Promise<string> {
    const arrayBuffer = await file.arrayBuffer();
    const result = await decryptBackupData(new Uint8Array(arrayBuffer), passphrase);
    return result.data;
  },

  async exportConversationsText(passphrase: string) {
    const snapshot = await buildBackupSnapshot();
    const data = JSON.stringify(snapshot);
    const fileName = `lawver_dialogues_${new Date().toISOString().split('T')[0]}.lawver`;
    const encrypted = await encryptBackupData(data, passphrase);

    if (isNative()) {
      const targetPath = `exports/${fileName}`;
      await Filesystem.writeFile({
        directory: Directory.Cache,
        path: targetPath,
        data: bytesToBase64(encrypted),
        recursive: true
      });

      const stored = await Filesystem.getUri({
        directory: Directory.Cache,
        path: targetPath
      });

      await Share.share({
        title: fileName,
        dialogTitle: '导出或分享备份',
        files: [stored.uri]
      });
      return;
    }

    const blob = new Blob([encrypted], { type: 'application/octet-stream' });
    
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  async importConversationsFromFile(file: File, passphrase: string) {
    const decrypted = await this.decryptDataFromFile(file, passphrase);
    const parsed = JSON.parse(decrypted);
    return applyBackupSnapshot(parsed);
  }
};
