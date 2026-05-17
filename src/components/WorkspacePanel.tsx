/*
 * 模块描述：工作区面板组件，展示上传文件和生成结果并提供下载/删除操作。
 */

import React from 'react';
import { Folder, X, Paperclip, Download, Trash2, FileText } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

const WORKSPACE_PANEL_WIDTH = 320;
const PANEL_TRANSITION = { duration: 0.28, ease: [0.2, 0, 0, 1] } as const;
type WorkspaceFile = { name: string, path: string, type: 'upload' | 'generated' };

interface WorkspacePanelProps {
  isWorkspaceOpen: boolean;
  setIsWorkspaceOpen: (open: boolean) => void;
  workspaceFiles: WorkspaceFile[];
  onDeleteFile: (filePath: string) => void;
  isDesktopLayout: boolean;
}

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  isWorkspaceOpen,
  setIsWorkspaceOpen,
  workspaceFiles,
  onDeleteFile,
  isDesktopLayout
}) => {
  const uploadedFiles = workspaceFiles.filter(f => f.type === 'upload');
  const generatedFiles = workspaceFiles.filter(f => f.type === 'generated');
  const panelAnimation = isDesktopLayout
    ? {
      width: isWorkspaceOpen ? WORKSPACE_PANEL_WIDTH : 0,
      opacity: isWorkspaceOpen ? 1 : 0,
      borderLeftWidth: isWorkspaceOpen ? 1 : 0
    }
    : {
      x: isWorkspaceOpen ? 0 : '100%',
      opacity: isWorkspaceOpen ? 1 : 0
    };
  const workspaceContentWidth = isDesktopLayout ? `${WORKSPACE_PANEL_WIDTH}px` : 'min(85vw, 320px)';
  const workspaceStyle: React.CSSProperties = {
    pointerEvents: isWorkspaceOpen ? 'auto' : 'none',
    ...(!isDesktopLayout ? { width: workspaceContentWidth } : {})
  };

  const FileItem: React.FC<{ file: WorkspaceFile }> = ({ file }) => (
    <div className="lawyance-fade-up group flex items-center justify-between rounded-[12px] border border-[var(--border-subtle)] bg-[rgba(59,98,184,0.04)] px-3 py-2.5 dark:bg-white/[0.03]">
      <div className="flex min-w-0 items-center gap-3 overflow-hidden">
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] ${file.type === 'upload' ? 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]' : 'bg-[rgba(44,118,112,0.12)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'}`}>
          {file.type === 'upload' ? (
            <Paperclip size={15} strokeWidth={2} />
          ) : (
            <FileText size={15} strokeWidth={2} />
          )}
        </div>
        <span className="t-body-s truncate text-[13px] text-[var(--fg-1)]" title={file.name}>{file.name}</span>
      </div>
      <div className="flex items-center gap-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100">
        <button
          onClick={() => {
            const link = document.createElement('a');
            link.href = `/api/download?file_path=${encodeURIComponent(file.path)}`;
            link.download = file.name;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
          }}
          className="lawyance-pressable inline-flex h-[30px] w-[30px] items-center justify-center rounded-[8px] text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)]"
          title="Download"
        >
          <Download size={14} strokeWidth={2} />
        </button>
        <button
          onClick={() => onDeleteFile(file.path)}
          className="lawyance-pressable inline-flex h-[30px] w-[30px] items-center justify-center rounded-[8px] text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
          title="Delete"
        >
          <Trash2 size={14} strokeWidth={2} />
        </button>
      </div>
    </div>
  );

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
            : 'fixed right-0 top-0 z-50 rounded-l-[var(--radius-xl)] shadow-[var(--shadow-4)]'
        }`}
        style={workspaceStyle}
        aria-hidden={!isWorkspaceOpen}
      >
        <div className="flex h-full shrink-0 flex-col" style={{ width: workspaceContentWidth }}>
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-5 py-4">
            <h3 className="t-title-m flex items-center gap-2.5 text-[15px]">
              <Folder size={18} strokeWidth={2} className="text-[var(--accent)]" />
              Workspace
            </h3>
            <button onClick={() => setIsWorkspaceOpen(false)} className="lawyance-pressable rounded-full p-1.5 text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]" aria-label="Close workspace">
              <X size={18} strokeWidth={2} />
            </button>
          </div>

          <div className="custom-scrollbar flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto p-5">
            {/* Uploaded Section */}
            <section>
              <h4 className="t-label-s t-weak mb-3 px-1">
                Uploaded Documents
              </h4>
              <div className="flex flex-col gap-2">
                {uploadedFiles.length === 0 ? (
                  <p className="t-body-s t-weak px-1 italic">No uploaded files</p>
                ) : (
                  uploadedFiles.map((file, index) => <FileItem key={`up-${index}`} file={file} />)
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
                  generatedFiles.map((file, index) => <FileItem key={`gen-${index}`} file={file} />)
                )}
              </div>
            </section>
          </div>
        </div>
      </motion.aside>
    </>
  );
};
