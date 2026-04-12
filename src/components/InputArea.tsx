import React, { useRef } from 'react';
import { Settings2, Paperclip, X, Send } from 'lucide-react';
import { motion } from 'motion/react';

interface InputAreaProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: () => void;
  isLoading: boolean;
  pendingUploads: { name: string, path: string }[];
  removeUploadedFile: (index: number) => void;
  handleFileUpload: (file: File) => void;
  isInputExpanded: boolean;
  setIsInputExpanded: (val: boolean) => void;
  isStreaming: boolean;
  setIsStreaming: (val: boolean) => void;
  agentMode: string;
  setAgentMode: (val: string) => void;
}

export const InputArea: React.FC<InputAreaProps> = ({
  input,
  setInput,
  handleSend,
  isLoading,
  pendingUploads,
  removeUploadedFile,
  handleFileUpload,
  isInputExpanded,
  setIsInputExpanded,
  isStreaming,
  setIsStreaming,
  agentMode,
  setAgentMode
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMac = /Mac|iPhone|iPod|iPad/i.test(navigator.userAgent);
    const isSendTriggered = isMac ? (e.metaKey && e.key === 'Enter') : (e.ctrlKey && e.key === 'Enter');

    if (isSendTriggered) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <footer className="bg-gray-50 dark:bg-gray-900 p-2 sm:p-4 shrink-0 pb-[calc(2rem+env(safe-area-inset-bottom))] sm:pb-8 border-t border-gray-200 dark:border-gray-800">
      <div className="max-w-3xl mx-auto relative flex flex-col gap-3">

        {isInputExpanded && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="absolute bottom-full mb-3 left-0 right-0 bg-white dark:bg-gray-800 rounded-3xl p-4 sm:p-5 flex flex-col gap-4 sm:gap-5 border border-gray-200 dark:border-gray-700 shadow-lg z-10"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Settings2 size={20} className="text-gray-600 dark:text-gray-400 sm:size-6" />
                <span className="text-sm sm:text-[15px] font-medium text-gray-900 dark:text-gray-100">Enable Streaming Output</span>
              </div>
              <button
                onClick={() => setIsStreaming(!isStreaming)}
                className={`relative inline-flex h-6 w-11 sm:h-7 sm:w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900 ${isStreaming ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-200 dark:bg-gray-700'}`}
              >
                <span className={`inline-block h-4 w-4 sm:h-5 sm:w-5 transform rounded-full bg-white transition-transform ${isStreaming ? 'translate-x-6 sm:translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
            <div className="h-px bg-gray-100 dark:bg-gray-700 w-full" />
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Settings2 size={20} className="text-gray-600 dark:text-gray-400 sm:size-6" />
                <span className="text-sm sm:text-[15px] font-medium text-gray-900 dark:text-gray-100">Agent Mode</span>
              </div>
              <select
                value={agentMode}
                onChange={(e) => setAgentMode(e.target.value)}
                className="text-sm sm:text-[15px] border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 cursor-pointer px-3 py-1.5 sm:px-4 sm:py-2 outline-none font-medium"
              >
                <option value="default">Default</option>
                <option value="plan_and_solve">Plan & Solve</option>
                <option value="react">ReAct</option>
              </select>
            </div>
          </motion.div>
        )}

        {pendingUploads.length > 0 && (
          <div className="flex flex-wrap gap-2 px-2 pb-1">
            {pendingUploads.map((file, index) => (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                key={index}
                className="flex items-center gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full px-3 py-1 sm:px-4 sm:py-1.5 shadow-sm"
              >
                <Paperclip size={12} className="text-blue-600 dark:text-blue-400 sm:size-3.5" />
                <span className="text-xs sm:text-sm text-gray-700 dark:text-gray-300 max-w-30 sm:max-w-50 truncate">{file.name}</span>
                <button
                  onClick={() => removeUploadedFile(index)}
                  className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full text-gray-500 hover:text-red-500 transition-colors"
                >
                  <X size={12} className="sm:size-3.5" />
                </button>
              </motion.div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-1 sm:gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-800 rounded-3xl sm:rounded-4xl p-1.5 sm:p-2 focus-within:border-blue-500 dark:focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-500 dark:focus-within:ring-blue-400 transition-all duration-300 shadow-sm">
          <button
            onClick={() => setIsInputExpanded(!isInputExpanded)}
            className={`p-3 sm:p-4 rounded-full shrink-0 transition-colors ${isInputExpanded ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'}`}
          >
            <Settings2 size={20} className="sm:size-6" />
          </button>
          
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="p-3 sm:p-4 rounded-full shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
            title="Upload file (Max 50MB)"
          >
            <Paperclip size={20} className="sm:size-6" />
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.md"
          />

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Lawver... (Ctrl+Enter to send)"
            className="flex-1 max-h-32 min-h-11 sm:min-h-14 bg-transparent border-none focus:ring-0 resize-none py-3 sm:py-4 text-gray-900 dark:text-gray-100 placeholder:text-gray-500 dark:placeholder:text-gray-400 text-sm sm:text-[16px] leading-relaxed outline-none"
            rows={1}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || (!input.trim() && pendingUploads.length === 0)}
            className={`p-3 sm:p-4 rounded-full shrink-0 transition-colors shadow-sm flex items-center justify-center ${
              input.trim() || pendingUploads.length > 0
                ? 'text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600'
                : 'text-gray-400 bg-gray-100 dark:bg-gray-800 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            <Send size={20} className="sm:size-6" />
          </button>
        </div>
      </div>
    </footer>
  );
};
