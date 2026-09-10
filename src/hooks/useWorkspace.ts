/*
 * 模块描述：工作区状态 Hook，同步本地 IndexedDB 文件与后端会话工作区。
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { fileDB } from '../lib/db';
import { uploadFile, getWorkspaceFiles, restoreFile, deleteWorkspaceFile, apiFetch } from '../services/api';
import { useAppDialog } from '../contexts/DialogContext';
import type { PendingUpload, WorkspaceFile } from '../types';
import { toWorkspaceRelativePath } from '../lib/workspace-path';

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'];

const isImageFile = (file: { name?: string; type?: string }) => {
  const mime = String(file.type || '').toLowerCase();
  if (mime.startsWith('image/')) return true;
  const name = String(file.name || '').toLowerCase();
  return IMAGE_EXTENSIONS.some(ext => name.endsWith(ext));
};

const createUploadTempId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `upload:${crypto.randomUUID()}`;
  }
  return `upload:${Date.now()}:${Math.random().toString(36).slice(2)}`;
};

export function useWorkspace(currentId: string, enabled = true) {
  const { showAlert } = useAppDialog();
  const [isWorkspaceOpen, setIsWorkspaceOpen] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState<WorkspaceFile[]>([]);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const currentIdRef = useRef(currentId);
  const syncGenerationRef = useRef(0);
  const deletionTombstonesRef = useRef(new Set<string>());
  // 待发送图片的本地预览 URL 必须在移除/切换会话时释放，否则会持续占用内存。
  const previewUrlsRef = useRef(new Set<string>());

  const deletionKey = useCallback((conversationId: string, path: string) => (
    `${conversationId}::${path}`
  ), []);

  const releasePreviewUrl = useCallback((url?: string) => {
    if (!url) return;
    previewUrlsRef.current.delete(url);
    URL.revokeObjectURL(url);
  }, []);

  const releaseAllPreviewUrls = useCallback(() => {
    previewUrlsRef.current.forEach(url => URL.revokeObjectURL(url));
    previewUrlsRef.current.clear();
  }, []);

  useEffect(() => {
    currentIdRef.current = currentId;
    syncGenerationRef.current += 1;
    releaseAllPreviewUrls();
    setWorkspaceFiles([]);
    setPendingUploads([]);
    setUploadingFiles([]);
  }, [currentId, releaseAllPreviewUrls]);

  useEffect(() => releaseAllPreviewUrls, [releaseAllPreviewUrls]);

  const syncFiles = useCallback(async () => {
    if (!enabled || !currentId) return;
    const syncConversationId = currentId;
    const generation = ++syncGenerationRef.current;
    const isCurrentSync = () => (
      currentIdRef.current === syncConversationId
      && syncGenerationRef.current === generation
    );
    try {
      const data = await getWorkspaceFiles(syncConversationId);
      if (!isCurrentSync()) return;
      const rawServerFiles = (data.files || []) as WorkspaceFile[];
      const serverFiles = rawServerFiles.filter(file => (
        !deletionTombstonesRef.current.has(deletionKey(syncConversationId, file.path))
      ));
      const rawLocalFiles = await fileDB.getFilesByConvId(syncConversationId);
      const localFiles = rawLocalFiles.filter(file => (
        !deletionTombstonesRef.current.has(deletionKey(syncConversationId, file.path))
      ));
      if (!isCurrentSync()) return;
      const localFilesByPath = new Map(localFiles.map(file => [file.path, file]));
      
      // 两侧都归一后再比对：历史记录里存的是绝对路径，而列表接口给的是
      // 工作区相对路径，直接字符串比较会永远判定"服务端缺失"并反复回灌。
      const normalize = (value: unknown) => toWorkspaceRelativePath(String(value ?? '')) ?? String(value ?? '');
      const serverPaths = new Set(serverFiles.map((f: any) => normalize(f.path)));
      const mergedFiles: WorkspaceFile[] = [...serverFiles];

      // 1. Client -> Server: Restore missing files on Server
      for (const local of localFiles) {
        const relativePath = toWorkspaceRelativePath(local.path);
        if (!relativePath || serverPaths.has(relativePath)) continue;

        // 只回灌工作区相对路径。历史版本的上传接口返回绝对路径，若按
        // "不以 TEMP/ 开头即 generated" 判断，会把上传文件重新灌进 Result，
        // 同一份文件于是在工作区里出现两次。
        const type: WorkspaceFile['type'] = relativePath.startsWith('Result/') ? 'generated' : 'upload';

        mergedFiles.push({
          name: local.fileName,
          path: relativePath,
          type,
        });

        // Proactively restore missing files to server
        if (local.blob && local.blob.size > 0) {
          try {
            await restoreFile(local.blob, local.fileName, syncConversationId, type);
            if (!isCurrentSync()) return;
          } catch (err) {
            console.error(`[Sync] Failed to restore file ${local.fileName}:`, err);
          }
        }
      }

      // 2. Server -> Client: Persist missing files locally
      for (const serverFile of serverFiles) {
        const localFile = localFilesByPath.get(serverFile.path);
        const needsDownload = !localFile || !localFile.blob || localFile.blob.size === 0;

        if (needsDownload) {
          console.log(`[Sync] Downloading missing server file to local cache: ${serverFile.name}`);
          try {
            const res = await apiFetch(`/api/download?file_path=${encodeURIComponent(serverFile.path)}`);
            if (res.ok) {
              const blob = await res.blob();
              await fileDB.saveFile(syncConversationId, serverFile.name, blob, serverFile.path);
              if (!isCurrentSync()) return;
            }
          } catch (err) {
            console.error(`[Sync] Failed to download server file to local: ${serverFile.name}`, err);
          }
        }
      }
      
      if (isCurrentSync()) {
        setWorkspaceFiles(mergedFiles);
        const confirmedPaths = new Set([
          ...rawServerFiles.map(file => file.path),
          ...rawLocalFiles.map(file => file.path),
        ]);
        for (const key of deletionTombstonesRef.current) {
          if (key.startsWith(`${syncConversationId}::`)) {
            const path = key.slice(syncConversationId.length + 2);
            if (!confirmedPaths.has(path)) deletionTombstonesRef.current.delete(key);
          }
        }
      }
    } catch (error) {
      console.error('Failed to sync workspace files:', error);
      // Fallback to local DB if server fails
      const files = await fileDB.getFilesByConvId(syncConversationId);
      if (!isCurrentSync()) return;
      setWorkspaceFiles(files.filter(file => (
        !deletionTombstonesRef.current.has(deletionKey(syncConversationId, file.path))
      )).map(f => ({
        name: f.fileName,
        path: f.path || '',
        type: (f.path && f.path.startsWith('TEMP/')) ? 'upload' : 'generated'
      })));
    }
  }, [currentId, deletionKey, enabled]);

  useEffect(() => {
    syncFiles();
  }, [syncFiles]);

  const handleFileUpload = useCallback(async (file: File) => {
    if (!currentId) return;

    const uploadConvId = currentId;
    const tempId = createUploadTempId();
    const isImage = isImageFile(file);
    // 图片在上传前就建立本地预览，发送前用户能直接确认内容。
    const previewUrl = isImage && typeof URL !== 'undefined' && URL.createObjectURL
      ? URL.createObjectURL(file)
      : undefined;
    if (previewUrl) previewUrlsRef.current.add(previewUrl);
    const updateUploadingFile = (patch: Partial<WorkspaceFile>) => {
      if (currentIdRef.current !== uploadConvId) return;
      setUploadingFiles(prev => prev.map(item => (
        item.tempId === tempId ? { ...item, ...patch } : item
      )));
    };
    const removeUploadingFile = () => {
      if (currentIdRef.current !== uploadConvId) return;
      setUploadingFiles(prev => prev.filter(item => item.tempId !== tempId));
    };

    setUploadingFiles(prev => [
      ...prev,
      {
        name: file.name,
        path: tempId,
        type: 'upload',
        size: file.size,
        uploadedBytes: 0,
        uploadProgress: 0,
        isUploading: true,
        tempId
      }
    ]);

    try {
      const data = await uploadFile(file, uploadConvId, snapshot => {
        updateUploadingFile({
          uploadedBytes: snapshot.loaded,
          uploadProgress: snapshot.progress
        });
      });
      // 统一存工作区相对路径：绝对路径会被附件解析拒绝，也会被误判为生成文件。
      const filePath = toWorkspaceRelativePath(data.file_path || data.path || '') || (data.file_path || data.path);
      await fileDB.saveFile(uploadConvId, file.name, file, filePath);

      if (currentIdRef.current === uploadConvId) {
        setPendingUploads(prev => {
          const nextUpload: PendingUpload = {
            name: file.name,
            path: filePath,
            kind: isImage ? 'image' : 'document',
            mime: file.type || undefined,
            previewUrl,
          };
          return prev.some(item => item.path === filePath) ? prev : [...prev, nextUpload];
        });
        updateUploadingFile({
          path: filePath,
          uploadedBytes: file.size,
          uploadProgress: 1
        });
        removeUploadingFile();
        await syncFiles(); // Refresh from server
      }
    } catch (error: any) {
      releasePreviewUrl(previewUrl);
      removeUploadingFile();
      await showAlert({
        title: '上传失败',
        message: error.message || 'Upload failed',
        tone: 'danger',
      });
    }
  }, [currentId, showAlert, syncFiles]);

  const handleGeneratedFile = useCallback(async (name: string, path: string) => {
    const generatedConversationId = currentId;
    if (path) {
      try {
        const res = await apiFetch(`/api/download?file_path=${encodeURIComponent(path)}`);
        if (res.ok) {
          const blob = await res.blob();
          await fileDB.saveFile(generatedConversationId, name, blob, path);
        } else {
          await fileDB.saveFile(generatedConversationId, name, new Blob([]), path);
        }
      } catch (e) {
        console.error("Failed to download generated file for cache:", e);
        await fileDB.saveFile(generatedConversationId, name, new Blob([]), path);
      }
    }
    if (currentIdRef.current === generatedConversationId) {
      await syncFiles(); // Refresh from server to get the actual state
    }
  }, [currentId, syncFiles]);

  const removeUploadedFile = useCallback((index: number) => {
    setPendingUploads(prev => {
      const fileToRemove = prev[index];
      if (!fileToRemove) return prev;
      // 预览 URL 与待发送条目同生命周期；已经发送的条目不在 pendingUploads 里。
      releasePreviewUrl(fileToRemove.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }, [releasePreviewUrl]);

  const deleteFile = useCallback(async (filePath: string) => {
    const deleteConversationId = currentId;
    const tombstoneKey = deletionKey(deleteConversationId, filePath);
    try {
      const fileToDelete = workspaceFiles.find(f => f.path === filePath);
      if (!fileToDelete) {
        return;
      }

      const localFiles = await fileDB.getFilesByConvId(deleteConversationId);
      const localFile = localFiles.find(file => file.path === fileToDelete.path);
      deletionTombstonesRef.current.add(tombstoneKey);

      try {
        // Delete the local cache first. If the authoritative server delete
        // fails, restore the captured cache record so both sides stay aligned.
        if (localFile) {
          await fileDB.deleteFile(deleteConversationId, localFile.fileName, localFile.path);
        }
        await deleteWorkspaceFile(deleteConversationId, fileToDelete.path);
      } catch (err: any) {
        if (localFile) {
          try {
            await fileDB.saveFile(deleteConversationId, localFile.fileName, localFile.blob, localFile.path);
          } catch (rollbackError) {
            console.error('Failed to roll back local file delete:', rollbackError);
          }
        }
        deletionTombstonesRef.current.delete(tombstoneKey);
        console.error('Failed to delete file from server:', err);
        await showAlert({
          title: '删除失败',
          message: err?.message || '文件删除未完成，本地缓存已恢复。',
          tone: 'danger',
        });
        return;
      }

      if (currentIdRef.current === deleteConversationId) {
        setWorkspaceFiles(prev => prev.filter(f => f.path !== filePath));
        setPendingUploads(prev => prev.filter(f => f.path !== filePath));
        await syncFiles();
      }
    } catch (error) {
      deletionTombstonesRef.current.delete(tombstoneKey);
      console.error('Failed to delete file:', error);
    }
  }, [currentId, deletionKey, showAlert, syncFiles, workspaceFiles]);

  const visibleWorkspaceFiles = useMemo(() => {
    const uploadingKeys = new Set(uploadingFiles.map(file => file.path || file.tempId || file.name));
    return [
      ...uploadingFiles,
      ...workspaceFiles.filter(file => !uploadingKeys.has(file.path || file.tempId || file.name))
    ];
  }, [uploadingFiles, workspaceFiles]);

  const isUploadingFiles = useMemo(() => (
    uploadingFiles.some(file => file.isUploading)
  ), [uploadingFiles]);

  return {
    isWorkspaceOpen,
    setIsWorkspaceOpen,
    workspaceFiles: visibleWorkspaceFiles,
    pendingUploads,
    setPendingUploads,
    isUploadingFiles,
    handleFileUpload,
    handleGeneratedFile,
    removeUploadedFile,
    deleteFile,
    syncFiles
  };
}
