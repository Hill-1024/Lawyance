import React from 'react';
import { Folder, X, Paperclip, Download, Trash2, FileText } from 'lucide-react';

interface WorkspacePanelProps {
  isWorkspaceOpen: boolean;
  setIsWorkspaceOpen: (open: boolean) => void;
  workspaceFiles: { name: string, path: string, type: 'upload' | 'generated' }[];
  onDeleteFile: (fileName: string) => void;
}

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  isWorkspaceOpen,
  setIsWorkspaceOpen,
  workspaceFiles,
  onDeleteFile
}) => {
  const uploadedFiles = workspaceFiles.filter(f => f.type === 'upload');
  const generatedFiles = workspaceFiles.filter(f => f.type === 'generated');

  const FileItem = ({ file }: { file: { name: string, path: string, type: 'upload' | 'generated' } }) => (
    <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-900/50 rounded-xl border border-gray-100 dark:border-gray-700 group">
      <div className="flex items-center gap-3 overflow-hidden">
        <div className={`p-2 rounded-lg shrink-0 ${file.type === 'upload' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-green-100 dark:bg-green-900/30'}`}>
          {file.type === 'upload' ? (
            <Paperclip size={16} className="text-blue-600 dark:text-blue-400" />
          ) : (
            <FileText size={16} className="text-green-600 dark:text-green-400" />
          )}
        </div>
        <span className="text-sm text-gray-700 dark:text-gray-300 truncate" title={file.name}>{file.name}</span>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => {
            const link = document.createElement('a');
            link.href = `/api/download?file_path=${encodeURIComponent(file.path)}`;
            link.download = file.name;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
          }}
          className="p-2 text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
          title="Download"
        >
          <Download size={16} />
        </button>
        <button
          onClick={() => onDeleteFile(file.name)}
          className="p-2 text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
          title="Delete"
        >
          <Trash2 size={16} />
        </button>
      </div>
    </div>
  );

  return (
    <div className={`w-80 bg-white dark:bg-gray-800 border-l border-gray-200 dark:border-gray-700 flex flex-col shrink-0 transition-all duration-300 ${isWorkspaceOpen ? 'translate-x-0' : 'translate-x-full absolute right-0 h-full'}`}>
      <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <h3 className="font-medium flex items-center gap-2 text-gray-900 dark:text-gray-100">
          <Folder size={18} className="text-blue-600 dark:text-blue-400" />
          Workspace
        </h3>
        <button onClick={() => setIsWorkspaceOpen(false)} className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full text-gray-500 transition-colors">
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-6 custom-scrollbar">
        {/* Uploaded Section */}
        <section>
          <h4 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-3 px-1">
            Uploaded Documents
          </h4>
          <div className="flex flex-col gap-2">
            {uploadedFiles.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-600 italic px-1">No uploaded files</p>
            ) : (
              uploadedFiles.map((file, index) => <FileItem key={`up-${index}`} file={file} />)
            )}
          </div>
        </section>

        {/* Generated Section */}
        <section>
          <h4 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-3 px-1">
            Generated Results
          </h4>
          <div className="flex flex-col gap-2">
            {generatedFiles.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-600 italic px-1">No generated files</p>
            ) : (
              generatedFiles.map((file, index) => <FileItem key={`gen-${index}`} file={file} />)
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
