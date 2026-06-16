/*
 * 模块描述：工作区状态 Hook，同步本地 IndexedDB 文件与后端会话工作区。
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { fileDB } from '../lib/db';
import { uploadFile, getWorkspaceFiles, restoreFile, deleteWorkspaceFile, apiFetch } from '../services/api';
import { useAppDialog } from '../contexts/DialogContext';
import type { PendingUpload, WorkspaceFile } from '../types';

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

  useEffect(() => {
    currentIdRef.current = currentId;
    setPendingUploads([]);
    setUploadingFiles([]);
  }, [currentId]);

  const syncFiles = useCallback(async () => {
    if (!enabled || !currentId) return;
    try {
      const data = await getWorkspaceFiles(currentId);
      const serverFiles = (data.files || []) as WorkspaceFile[];
      const localFiles = await fileDB.getFilesByConvId(currentId);
      const localFilesByPath = new Map(localFiles.map(file => [file.path, file]));
      
      const serverPaths = new Set(serverFiles.map((f: any) => f.path));
      const mergedFiles: WorkspaceFile[] = [...serverFiles];
      
      // 1. Client -> Server: Restore missing files on Server
      for (const local of localFiles) {
        if (!serverPaths.has(local.path) && local.path) {
          const type: WorkspaceFile['type'] = local.path.startsWith('TEMP/') ? 'upload' : 'generated';
          
          mergedFiles.push({
            name: local.fileName,
            path: local.path,
            type: type
          });

          // Proactively restore missing files to server
          if (local.blob && local.blob.size > 0) {
            console.log(`[Sync] Restoring missing file to server: ${local.fileName}`);
            try {
              await restoreFile(local.blob, local.fileName, currentId, type);
            } catch (err) {
              console.error(`[Sync] Failed to restore file ${local.fileName}:`, err);
            }
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
              await fileDB.saveFile(currentId, serverFile.name, blob, serverFile.path);
            }
          } catch (err) {
            console.error(`[Sync] Failed to download server file to local: ${serverFile.name}`, err);
          }
        }
      }
      
      setWorkspaceFiles(mergedFiles);
    } catch (error) {
      console.error('Failed to sync workspace files:', error);
      // Fallback to local DB if server fails
      const files = await fileDB.getFilesByConvId(currentId);
      setWorkspaceFiles(files.map(f => ({
        name: f.fileName,
        path: f.path || '',
        type: (f.path && f.path.startsWith('TEMP/')) ? 'upload' : 'generated'
      })));
    }
  }, [currentId, enabled]);

  useEffect(() => {
    syncFiles();
  }, [syncFiles]);

  const handleFileUpload = useCallback(async (file: File) => {
    if (!currentId) return;

    const uploadConvId = currentId;
    const tempId = createUploadTempId();
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
      const filePath = data.file_path || data.path;
      await fileDB.saveFile(uploadConvId, file.name, file, filePath);

      if (currentIdRef.current === uploadConvId) {
        setPendingUploads(prev => {
          const nextUpload = { name: file.name, path: filePath };
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
      removeUploadingFile();
      await showAlert({
        title: '上传失败',
        message: error.message || 'Upload failed',
        tone: 'danger',
      });
    }
  }, [currentId, showAlert, syncFiles]);

  const handleGeneratedFile = useCallback(async (name: string, path: string) => {
    if (path) {
      try {
        const res = await apiFetch(`/api/download?file_path=${encodeURIComponent(path)}`);
        if (res.ok) {
          const blob = await res.blob();
          await fileDB.saveFile(currentId, name, blob, path);
        } else {
          await fileDB.saveFile(currentId, name, new Blob([]), path);
        }
      } catch (e) {
        console.error("Failed to download generated file for cache:", e);
        await fileDB.saveFile(currentId, name, new Blob([]), path);
      }
    }
    await syncFiles(); // Refresh from server to get the actual state
  }, [currentId, syncFiles]);

  const removeUploadedFile = useCallback((index: number) => {
    const fileToRemove = pendingUploads[index];
    if (fileToRemove) {
      setPendingUploads(prev => prev.filter((_, i) => i !== index));
      // Also remove from workspace view but keep in DB if it was already saved?
      // Actually pendingUploads are just for the current message.
    }
  }, [pendingUploads]);

  const deleteFile = useCallback(async (filePath: string) => {
    try {
      const fileToDelete = workspaceFiles.find(f => f.path === filePath);
      if (!fileToDelete) {
        return;
      }

      try {
        await deleteWorkspaceFile(currentId, fileToDelete.path);
      } catch (err: any) {
        console.error('Failed to delete file from server:', err);
        await showAlert({
          title: '删除失败',
          message: err?.message || '删除服务端文件失败，本地文件已保留。',
          tone: 'danger',
        });
        return;
      }

      await fileDB.deleteFile(currentId, fileToDelete.name, fileToDelete.path);
      setWorkspaceFiles(prev => prev.filter(f => f.path !== filePath));
      setPendingUploads(prev => prev.filter(f => f.path !== filePath));
    } catch (error) {
      console.error('Failed to delete file:', error);
    }
  }, [currentId, showAlert, workspaceFiles]);

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
