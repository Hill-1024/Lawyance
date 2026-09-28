/*
 * 模块描述：工作区面板组件，展示上传文件和生成结果并提供下载/删除操作。
 */

import React, { useMemo } from 'react';
import { Folder, X, Paperclip, Download, Trash2, FileText } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { HoverInfo } from './HoverInfo';
import { downloadWorkspaceFile } from '../lib/download';
import { useAppDialog } from '../contexts/DialogContext';
import { FileUploadProgress } from './FileUploadProgress';
import type { WorkspaceFile } from '../types';

const WORKSPACE_PANEL_WIDTH = 320;
const PANEL_TRANSITION = { duration: 0.28, ease: [0.2, 0, 0, 1] } as const;

const getWorkspaceFileKey = (file: WorkspaceFile) => {
  return `${file.type}:${file.tempId || file.path || file.name}`;
};

const WorkspaceFileItem: React.FC<{
  file: WorkspaceFile;
  onDeleteFile: (filePath: string) => void;
  disableHoverInfo: boolean;
}> = React.memo(({ file, onDeleteFile, disableHoverInfo }) => {
  const { showAlert } = useAppDialog();

  return (
    <div className="lawver-fade-up group flex items-center justify-between gap-2 rounded-[12px] border border-[var(--border-subtle)] bg-[rgba(59,98,184,0.04)] px-3 py-2.5 dark:bg-white/[0.03]">
      <div className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] ${file.type === 'upload' ? 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]' : 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'}`}>
          {file.type === 'upload' ? (
            <Paperclip size={15} strokeWidth={2} />
          ) : (
            <FileText size={15} strokeWidth={2} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <HoverInfo label={file.name} placement="top" disabled={disableHoverInfo}>
            <span className="block truncate text-[13px] leading-5 text-[var(--fg-1)]">{file.name}</span>
          </HoverInfo>
          <FileUploadProgress file={file} />
        </div>
      </div>
      {!file.isUploading && (
        <div className="flex items-center gap-0.5 opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100">
          <HoverInfo label="Download" placement="top" disabled={disableHoverInfo}>
            <button
              onClick={async () => {
                try {
                  await downloadWorkspaceFile(file.path, file.name);
                } catch (error: any) {
                  await showAlert({
                    title: '下载失败',
                    message: error?.message || 'Download failed',
                    tone: 'danger',
                  });
                }
              }}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] xl:h-8 xl:w-8 lg:rounded-[8px]"
              aria-label="Download"
            >
              <Download size={14} strokeWidth={2} />
            </button>
          </HoverInfo>
          <HoverInfo label="Delete" placement="top" disabled={disableHoverInfo}>
            <button
              onClick={() => onDeleteFile(file.path)}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] xl:h-8 xl:w-8 lg:rounded-[8px]"
              aria-label="Delete"
            >
              <Trash2 size={14} strokeWidth={2} />
            </button>
          </HoverInfo>
        </div>
      )}
    </div>
  );
});

WorkspaceFileItem.displayName = 'WorkspaceFileItem';

interface WorkspacePanelProps {
  isWorkspaceOpen: boolean;
  setIsWorkspaceOpen: (open: boolean) => void;
  workspaceFiles: WorkspaceFile[];
  onDeleteFile: (filePath: string) => void;
  isDesktopLayout: boolean;
}

const WorkspacePanelComponent: React.FC<WorkspacePanelProps> = ({
  isWorkspaceOpen,
  setIsWorkspaceOpen,
  workspaceFiles,
  onDeleteFile,
  isDesktopLayout
}) => {
  const uploadedFiles = useMemo(() => workspaceFiles.filter(f => f.type === 'upload'), [workspaceFiles]);
  const generatedFiles = useMemo(() => workspaceFiles.filter(f => f.type === 'generated'), [workspaceFiles]);
  const panelAnimation = useMemo(() => isDesktopLayout
    ? {
      width: isWorkspaceOpen ? WORKSPACE_PANEL_WIDTH : 0,
      opacity: isWorkspaceOpen ? 1 : 0,
      borderLeftWidth: isWorkspaceOpen ? 1 : 0
    }
    : {
      x: isWorkspaceOpen ? 0 : '100%',
      opacity: isWorkspaceOpen ? 1 : 0
    }, [isDesktopLayout, isWorkspaceOpen]);
  const workspaceContentWidth = isDesktopLayout ? `${WORKSPACE_PANEL_WIDTH}px` : 'min(85vw, 320px)';
  const workspaceStyle: React.CSSProperties = useMemo(() => ({
    pointerEvents: isWorkspaceOpen ? 'auto' : 'none',
    ...(!isDesktopLayout ? { width: workspaceContentWidth } : {})
  }), [isDesktopLayout, isWorkspaceOpen, workspaceContentWidth]);

  return (
    <>
      <AnimatePresence>
        {!isDesktopLayout && isWorkspaceOpen && (
          <motion.div
            key="workspace-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={PANEL_TRANSITION}
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm"
            onClick={() => setIsWorkspaceOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      <motion.aside
        initial={false}
        animate={panelAnimation}
        transition={PANEL_TRANSITION}
        className={`flex h-full shrink-0 flex-col overflow-hidden border-l border-[var(--border-subtle)] bg-[var(--bg-surface)] ${
          isDesktopLayout
            ? 'relative'
            : 'lawver-mobile-drawer fixed right-0 top-0 z-50 rounded-l-[var(--radius-xl)] shadow-[var(--shadow-4)]'
        }`}
        style={workspaceStyle}
        aria-hidden={!isWorkspaceOpen}
      >
        <div className="flex h-full shrink-0 flex-col" style={{ width: workspaceContentWidth }}>
          <div className={`flex items-center justify-between border-b border-[var(--border-subtle)] ${
            isDesktopLayout ? 'px-4 py-3 sm:px-5 sm:py-4' : 'lawver-mobile-drawer-header'
          }`}>
            <h3 className="t-title-m flex items-center gap-2.5 text-[15px]">
              <Folder size={18} strokeWidth={2} className="text-[var(--accent)]" />
              Workspace
            </h3>
            <button onClick={() => setIsWorkspaceOpen(false)} className="lawver-drawer-close lawver-pressable inline-flex items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]" aria-label="Close workspace">
              <X size={21} strokeWidth={2} />
            </button>
          </div>

          <div className="custom-scrollbar flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto p-4 sm:p-5">
            {/* Uploaded Section */}
            <section>
              <h4 className="t-label-s t-weak mb-3 px-1">
                Uploaded Documents
              </h4>
              <div className="flex flex-col gap-2">
                {uploadedFiles.length === 0 ? (
                  <p className="t-body-s t-weak px-1 italic">No uploaded files</p>
                ) : (
                  uploadedFiles.map(file => (
                    <WorkspaceFileItem
                      key={getWorkspaceFileKey(file)}
                      file={file}
                      onDeleteFile={onDeleteFile}
                      disableHoverInfo={!isDesktopLayout && isWorkspaceOpen}
                    />
                  ))
                )}
              </div>
            </section>

            {/* Generated Section */}
            <section>
              <h4 className="t-label-s t-weak mb-3 px-1">
                Generated Results
              </h4>
              <div className="flex flex-col gap-2">
                {generatedFiles.length === 0 ? (
                  <p className="t-body-s t-weak px-1 italic">No generated files</p>
                ) : (
                  generatedFiles.map(file => (
                    <WorkspaceFileItem
                      key={getWorkspaceFileKey(file)}
                      file={file}
                      onDeleteFile={onDeleteFile}
                      disableHoverInfo={!isDesktopLayout && isWorkspaceOpen}
                    />
                  ))
                )}
              </div>
            </section>
          </div>
        </div>
      </motion.aside>
    </>
  );
};

export const WorkspacePanel = React.memo(WorkspacePanelComponent);
WorkspacePanel.displayName = 'WorkspacePanel';
