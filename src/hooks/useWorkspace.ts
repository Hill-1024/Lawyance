import { useState, useEffect, useCallback } from 'react';
import { fileDB } from '../lib/db';
import { uploadFile, getWorkspaceFiles, restoreFile, deleteWorkspaceFile } from '../services/api';

export function useWorkspace(currentId: string, enabled = true) {
  const [isWorkspaceOpen, setIsWorkspaceOpen] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<{ name: string, path: string, type: 'upload' | 'generated' }[]>([]);
  const [pendingUploads, setPendingUploads] = useState<{ name: string, path: string }[]>([]);

  const syncFiles = useCallback(async () => {
    if (!enabled || !currentId) return;
    try {
      const data = await getWorkspaceFiles(currentId);
      const serverFiles = data.files || [];
      const localFiles = await fileDB.getFilesByConvId(currentId);
      const localFilesByPath = new Map(localFiles.map(file => [file.path, file]));
      
      const serverPaths = new Set(serverFiles.map((f: any) => f.path));
      const localPaths = new Set(localFiles.map(f => f.path));
      const mergedFiles = [...serverFiles];
      
      // 1. Client -> Server: Restore missing files on Server
      for (const local of localFiles) {
        if (!serverPaths.has(local.path) && local.path) {
          const type = local.path.toUpperCase().includes('TEMP/') ? 'upload' : 'generated';
          
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
            const res = await fetch(`/api/download?file_path=${encodeURIComponent(serverFile.path)}`);
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
      setPendingUploads([]);
    } catch (error) {
      console.error('Failed to sync workspace files:', error);
      // Fallback to local DB if server fails
      const files = await fileDB.getFilesByConvId(currentId);
      setWorkspaceFiles(files.map(f => ({
        name: f.fileName,
        path: f.path || '',
        type: (f.path && f.path.toUpperCase().includes('TEMP/')) ? 'upload' : 'generated'
      })));
    }
  }, [currentId, enabled]);

  useEffect(() => {
    syncFiles();
  }, [syncFiles]);

  const handleFileUpload = async (file: File) => {
    try {
      const data = await uploadFile(file, currentId);
      const filePath = data.file_path || data.path;
      await fileDB.saveFile(currentId, file.name, file, filePath);
      await syncFiles(); // Refresh from server
    } catch (error: any) {
      alert(error.message || 'Upload failed');
    }
  };

  const handleGeneratedFile = async (name: string, path: string) => {
    if (path) {
      try {
        const res = await fetch(`/api/download?file_path=${encodeURIComponent(path)}`);
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
  };

  const removeUploadedFile = (index: number) => {
    const fileToRemove = pendingUploads[index];
    if (fileToRemove) {
      setPendingUploads(prev => prev.filter((_, i) => i !== index));
      // Also remove from workspace view but keep in DB if it was already saved?
      // Actually pendingUploads are just for the current message.
    }
  };

  const deleteFile = async (filePath: string) => {
    try {
      const fileToDelete = workspaceFiles.find(f => f.path === filePath);
      if (!fileToDelete) {
        return;
      }

      try {
        await deleteWorkspaceFile(currentId, fileToDelete.path);
      } catch (err: any) {
        console.error('Failed to delete file from server:', err);
        alert(err?.message || '删除服务端文件失败，本地文件已保留。');
        return;
      }

      await fileDB.deleteFile(currentId, fileToDelete.name, fileToDelete.path);
      setWorkspaceFiles(prev => prev.filter(f => f.path !== filePath));
      setPendingUploads(prev => prev.filter(f => f.path !== filePath));
    } catch (error) {
      console.error('Failed to delete file:', error);
    }
  };

  return {
    isWorkspaceOpen,
    setIsWorkspaceOpen,
    workspaceFiles,
    pendingUploads,
    setPendingUploads,
    handleFileUpload,
    handleGeneratedFile,
    removeUploadedFile,
    deleteFile,
    syncFiles
  };
}
