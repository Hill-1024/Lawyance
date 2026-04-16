import { useState, useEffect, useCallback } from 'react';
import { fileDB } from '../lib/db';
import { uploadFile, getWorkspaceFiles } from '../services/api';

export function useWorkspace(currentId: string) {
  const [isWorkspaceOpen, setIsWorkspaceOpen] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<{ name: string, path: string, type: 'upload' | 'generated' }[]>([]);
  const [pendingUploads, setPendingUploads] = useState<{ name: string, path: string }[]>([]);

  const syncFiles = useCallback(async () => {
    if (!currentId) return;
    try {
      const data = await getWorkspaceFiles(currentId);
      const serverFiles = data.files || [];
      const localFiles = await fileDB.getFilesByConvId(currentId);
      
      const serverPaths = new Set(serverFiles.map((f: any) => f.path));
      const mergedFiles = [...serverFiles];
      
      for (const local of localFiles) {
        if (!serverPaths.has(local.path) && local.path) {
          mergedFiles.push({
            name: local.fileName,
            path: local.path,
            type: local.path.toUpperCase().includes('TEMP/') ? 'upload' : 'generated'
          });
        }
      }
      
      setWorkspaceFiles(mergedFiles);
      setPendingUploads([]);
    } catch (error) {
      console.error('Failed to sync workspace files:', error);
      // Fallback to local DB if server fails? Or just show empty.
      const files = await fileDB.getFilesByConvId(currentId);
      setWorkspaceFiles(files.map(f => ({
        name: f.fileName,
        path: f.path || '',
        type: (f.path && f.path.toUpperCase().includes('TEMP/')) ? 'upload' : 'generated'
      })));
    }
  }, [currentId]);

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

  const deleteFile = async (fileName: string) => {
    try {
      await fileDB.deleteFile(currentId, fileName);
      setWorkspaceFiles(prev => prev.filter(f => f.name !== fileName));
      setPendingUploads(prev => prev.filter(f => f.name !== fileName));
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
