/*
 * 模块描述：本地存储状态组件，展示容量、持久化保护、清理和备份操作。
 */

import React, { useState } from 'react';
import { Database, AlertTriangle, Download, Trash2, ShieldCheck, ShieldAlert } from 'lucide-react';
import { useStorage } from '../hooks/useStorage';
import { storageService } from '../services/storageService';
import { motion, AnimatePresence } from 'motion/react';

interface StorageIndicatorProps {
  compact?: boolean;
}

export const StorageIndicator: React.FC<StorageIndicatorProps> = ({ compact }) => {
  const { usage, quota, usageRatio, isLowStorage, isPersistent, requestPersistence, updateEstimate, error } = useStorage();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const handleGC = async () => {
    setIsCleaning(true);
    try {
      const result = await storageService.garbageCollect();
      alert(`清理完成。已移除 ${result.cleanedCount} 个无效文件。`);
    } finally {
      setIsCleaning(false);
      updateEstimate();
    }
  };

  const handleRequestPersistence = async () => {
    const granted = await requestPersistence();
    if (granted) {
      alert('【开启成功】\n已启用永久保护模式。浏览器将绝对不会在磁盘紧张时自动清理本应用的数据。');
    } else {
      alert('【当前无法开启】\n原因：浏览器尚未授予此站点的持久化权限。\n\n解决办法：\n1. 继续使用一段时间（增加站点互动得分）\n2. 点击地址栏右侧图标，将本站【安装为应用(PWA)】\n3. 将本站加入书签');
    }
  };

  if (compact) {
    return (
      <div 
        className={`flex cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5 transition-colors ${
          isLowStorage ? 'bg-[rgba(184,132,42,0.12)] text-[var(--color-warning-500)]' : 'text-[var(--fg-2)] hover:bg-[rgba(20,23,31,0.06)] dark:hover:bg-white/[0.06]'
        }`}
        onClick={() => setIsModalOpen(true)}
        title="查看存储状态"
      >
        <Database size={16} strokeWidth={2} />
        <span className="t-label-m">
          {Math.round(usageRatio * 100)}%
        </span>
        {isLowStorage && <AlertTriangle size={14} strokeWidth={2} className="animate-pulse" />}
      </div>
    );
  }

  return (
    <>
      <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="t-title-s flex items-center gap-2">
            <Database size={18} strokeWidth={2} className="text-[var(--accent)]" />
            <span>本地存储状态</span>
          </div>
          <button 
            onClick={() => setIsModalOpen(true)}
            className="t-label-m text-[var(--accent)] hover:underline"
          >
            管理
          </button>
        </div>

        <div className="space-y-2">
          {error ? (
            <p className="t-label-s text-[var(--color-warning-500)]">{error}</p>
          ) : (
            <>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-inset)]">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${usageRatio * 100}%` }}
                  className={`h-full rounded-full ${
                    usageRatio > 0.8 ? 'bg-[var(--color-warning-500)]' : 'bg-[var(--accent)]'
                  }`}
                />
              </div>
              <div className="t-label-s t-muted flex justify-between">
                <span>已用: {formatSize(usage)}</span>
                <span>总量: {formatSize(quota)}</span>
              </div>
            </>
          )}
        </div>

        {!isPersistent && (
          <button 
            onClick={handleRequestPersistence}
            className="t-label-m mt-3 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] px-3 py-1.5 text-[var(--brand-primary-700)] transition-colors hover:bg-[rgba(59,98,184,0.16)] dark:text-[var(--accent)]"
          >
            <ShieldAlert size={14} strokeWidth={2} />
            开启永久保护模式
          </button>
        )}
        
        {isPersistent && (
          <div className="t-label-s mt-3 flex items-center justify-center gap-1.5 text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
            <ShieldCheck size={14} strokeWidth={2} />
            系统持久化模式已开启
          </div>
        )}
      </div>

      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[var(--bg-overlay)] backdrop-blur-sm"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-5)]"
            >
              <div className="p-6 flex-1 overflow-y-auto custom-scrollbar">
                <div className="flex items-center gap-3 mb-6">
                  <div className="rounded-[var(--radius-md)] bg-[var(--accent-quiet)] p-3 text-[var(--accent)]">
                    <Database size={24} strokeWidth={2} />
                  </div>
                  <div>
                    <h3 className="t-title-l">存储管理</h3>
                    <p className="t-body-m t-muted">数据全本地化存储，无后端云端备份</p>
                  </div>
                </div>

                {isLowStorage && (
                  <div className="mb-6 flex gap-3 rounded-[var(--radius-md)] border border-[rgba(184,132,42,0.3)] bg-[rgba(184,132,42,0.1)] p-4">
                    <AlertTriangle className="shrink-0 text-[var(--color-warning-500)]" size={20} strokeWidth={2} />
                    <div>
                      <p className="t-title-s text-[#5C3F0E] dark:text-[#FBEBC8]">存储空间不足</p>
                      <p className="t-body-s mt-1 text-[#5C3F0E]/80 dark:text-[#FBEBC8]/80">
                        可用空间已不足 20%，为防止数据丢失，请及时备份并清理旧数据。
                      </p>
                    </div>
                  </div>
                )}

                <div className="space-y-4">
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between">
                      <span className="t-body-m">总体使用率</span>
                      <span className="t-title-s">{Math.round(usageRatio * 100)}%</span>
                    </div>
                    <div className="h-3 overflow-hidden rounded-full bg-[var(--bg-inset)]">
                      <div 
                        className={`h-full rounded-full transition-all duration-500 ${
                          usageRatio > 0.8 ? 'bg-[var(--color-warning-500)]' : 'bg-[var(--accent)]'
                        }`}
                        style={{ width: `${usageRatio * 100}%` }}
                      />
                    </div>
                    <div className="t-body-s t-muted flex justify-between">
                      <span>{formatSize(usage)}</span>
                      <span>总额 {formatSize(quota)}</span>
                    </div>
                  </div>

                  <div className="pt-4 grid grid-cols-1 gap-3">
                    <button 
                      onClick={handleGC}
                      disabled={isCleaning}
                      className="group flex w-full items-center justify-between rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4 transition-colors hover:bg-[rgba(184,132,42,0.08)]"
                    >
                      <div className="flex items-center gap-3">
                        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-surface)] p-2 transition-colors group-hover:text-[var(--color-warning-500)]">
                          <Trash2 size={20} strokeWidth={2} />
                        </div>
                        <div className="text-left">
                          <p className="t-title-s">智能清理缓存</p>
                          <p className="t-body-s t-muted">移除冗余的系统级日志和过期缓存</p>
                        </div>
                      </div>
                      {isCleaning && <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--color-warning-500)] border-t-transparent" />}
                    </button>
                  </div>

                  <div className="border-t border-[var(--border-subtle)] pt-6">
                    <div className="mb-4 flex items-center">
                      <h4 className="t-label-s t-weak">数据导入与导出</h4>
                    </div>
                    
                    <div className="mb-4 rounded-[var(--radius-md)] border border-[rgba(59,98,184,0.18)] bg-[rgba(59,98,184,0.06)] p-4">
                      <div className="flex gap-3">
                        <AlertTriangle className="shrink-0 text-[var(--accent)]" size={18} strokeWidth={2} />
                        <p className="t-body-s leading-relaxed text-[var(--brand-primary-800)] dark:text-[var(--accent)]">
                          导出为经过安全混淆的单文件（.lawyer）。
                          <br />
                          <strong className="text-[var(--accent)]">注意：</strong> 为保证迁移的极速和安全性，导出的文件仅包含文字对话内容，不包含臃肿的附件，附件需在新设备重新上传。
                        </p>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <button 
                        onClick={async () => {
                          setIsExporting(true);
                          try {
                            await storageService.exportConversationsText();
                          } catch (err) {
                            console.error(err);
                            alert('导出失败：' + (err as Error).message);
                          } finally {
                            setIsExporting(false);
                          }
                        }}
                        disabled={isExporting}
                        className="group flex flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 transition-all hover:bg-[var(--accent-quiet)]"
                      >
                        <div className="rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] p-2 text-[var(--accent)] transition-transform group-hover:scale-105">
                          <Download size={20} strokeWidth={2} />
                        </div>
                        <span className="t-title-s">导出文字记录</span>
                      </button>

                      <div className="relative">
                        <input
                          type="file"
                          id="import-dialogues-input"
                          className="hidden"
                          accept=".lawyer,.json.enc"
                          onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            
                            setIsExporting(true);
                            try {
                              const count = await storageService.importConversationsFromFile(file);
                              alert(`成功导入 ${count} 个对话。\n请刷新页面以查看更新。`);
                              updateEstimate();
                            } catch (err) {
                              console.error(err);
                              alert('导入失败，请确保文件格式正确且未损坏。');
                            } finally {
                              setIsExporting(false);
                              e.target.value = ''; // Reset input
                            }
                          }}
                        />
                        <button 
                          onClick={() => {
                            document.getElementById('import-dialogues-input')?.click();
                          }}
                          disabled={isExporting}
                          className="group flex w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 transition-all hover:bg-[rgba(44,118,112,0.08)]"
                        >
                          <div className="rounded-[var(--radius-sm)] bg-[rgba(44,118,112,0.12)] p-2 text-[var(--brand-tertiary-700)] transition-transform group-hover:scale-105 dark:text-[#8ecdc7]">
                            <Database size={20} strokeWidth={2} />
                          </div>
                          <span className="t-title-s">导入文字记录</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex shrink-0 justify-end border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4">
                <button 
                  onClick={() => setIsModalOpen(false)}
                  className="md3-btn-tonal px-6 py-2"
                >
                  关闭
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
};
