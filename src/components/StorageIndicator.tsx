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

  const handleExport = async () => {
    setIsExporting(true);
    try {
      await storageService.exportAllData();
    } finally {
      setIsExporting(false);
      updateEstimate();
    }
  };

  const handleGC = async () => {
    setIsCleaning(true);
    try {
      const result = await storageService.garbageCollect();
      alert(`清理完成！移除了 ${result.cleanedCount} 个无效文件。`);
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
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
          isLowStorage ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' : 'hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400'
        }`}
        onClick={() => setIsModalOpen(true)}
        title="查看存储状态"
      >
        <Database size={16} />
        <span className="text-xs font-medium">
          {Math.round(usageRatio * 100)}%
        </span>
        {isLowStorage && <AlertTriangle size={14} className="animate-pulse" />}
      </div>
    );
  }

  return (
    <>
      <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 text-gray-900 dark:text-gray-100 font-medium">
            <Database size={18} className="text-blue-500" />
            <span>本地存储状态</span>
          </div>
          <button 
            onClick={() => setIsModalOpen(true)}
            className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
          >
            管理
          </button>
        </div>

        <div className="space-y-2">
          {error ? (
            <p className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">{error}</p>
          ) : (
            <>
              <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${usageRatio * 100}%` }}
                  className={`h-full rounded-full ${
                    usageRatio > 0.8 ? 'bg-amber-500' : 'bg-blue-500'
                  }`}
                />
              </div>
              <div className="flex justify-between text-[10px] text-gray-500 dark:text-gray-400">
                <span>已用: {formatSize(usage)}</span>
                <span>总量: {formatSize(quota)}</span>
              </div>
            </>
          )}
        </div>

        {!isPersistent && (
          <button 
            onClick={handleRequestPersistence}
            className="mt-3 w-full flex items-center justify-center gap-1.5 py-1.5 px-3 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded-lg text-xs font-medium hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
          >
            <ShieldAlert size={14} />
            开启永久保护模式
          </button>
        )}
        
        {isPersistent && (
          <div className="mt-3 flex items-center justify-center gap-1.5 text-emerald-600 dark:text-emerald-400 text-[10px] font-medium">
            <ShieldCheck size={14} />
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
              className="absolute inset-0 bg-black/50 backdrop-blur-sm"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden border border-gray-200 dark:border-gray-700"
            >
              <div className="p-6">
                <div className="flex items-center gap-3 mb-6">
                  <div className="p-3 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-xl">
                    <Database size={24} />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">存储管理</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">数据全本地化存储，无后端云端备份</p>
                  </div>
                </div>

                {isLowStorage && (
                  <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl flex gap-3">
                    <AlertTriangle className="text-amber-500 shrink-0" size={20} />
                    <div>
                      <p className="text-sm font-medium text-amber-800 dark:text-amber-300">存储空间告急</p>
                      <p className="text-xs text-amber-700/80 dark:text-amber-400/80 mt-1">
                        可用空间已不足 20%，为防止数据丢失，请及时备份并清理旧数据。
                      </p>
                    </div>
                  </div>
                )}

                <div className="space-y-4">
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600 dark:text-gray-400">总体使用率</span>
                      <span className="font-medium text-gray-900 dark:text-gray-100">{Math.round(usageRatio * 100)}%</span>
                    </div>
                    <div className="h-3 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all duration-500 ${
                          usageRatio > 0.8 ? 'bg-amber-500' : 'bg-blue-500'
                        }`}
                        style={{ width: `${usageRatio * 100}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-gray-500">
                      <span>{formatSize(usage)}</span>
                      <span>总额 {formatSize(quota)}</span>
                    </div>
                  </div>

                  <div className="pt-4 grid grid-cols-1 gap-3">
                    <button 
                      onClick={handleExport}
                      disabled={isExporting}
                      className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-blue-900/20 border border-gray-100 dark:border-gray-700 rounded-xl transition-colors group"
                    >
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-white dark:bg-gray-700 rounded-lg group-hover:text-blue-500 transition-colors">
                          <Download size={20} />
                        </div>
                        <div className="text-left">
                          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">导出数据到本地</p>
                          <p className="text-xs text-gray-500">打包所有对话和文件为 .zip</p>
                        </div>
                      </div>
                      {isExporting && <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-500 border-t-transparent" />}
                    </button>

                    <button 
                      onClick={handleGC}
                      disabled={isCleaning}
                      className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 hover:bg-amber-50 dark:hover:bg-amber-900/20 border border-gray-100 dark:border-gray-700 rounded-xl transition-colors group"
                    >
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-white dark:bg-gray-700 rounded-lg group-hover:text-amber-500 transition-colors">
                          <Trash2 size={20} />
                        </div>
                        <div className="text-left">
                          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">智能清理缓存</p>
                          <p className="text-xs text-gray-500">移除冗余的系统级日志和过期缓存</p>
                        </div>
                      </div>
                      {isCleaning && <div className="animate-spin rounded-full h-4 w-4 border-2 border-amber-500 border-t-transparent" />}
                    </button>
                  </div>

                  <div className="pt-6 border-t border-gray-100 dark:border-gray-800">
                    <div className="flex items-center gap-2 mb-4 text-gray-900 dark:text-gray-100 font-semibold">
                      <div className="w-1.5 h-4 bg-blue-500 rounded-full" />
                      <h4>跨域名对话迁移</h4>
                    </div>
                    
                    <div className="p-4 bg-blue-50/50 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-900/30 rounded-xl mb-4">
                      <div className="flex gap-3">
                        <AlertTriangle className="text-blue-500 shrink-0" size={18} />
                        <p className="text-xs text-blue-800/80 dark:text-blue-300/80 leading-relaxed">
                          如果您从旧地址（如 IP 访问）切换到新域名，请在此导出对话记录。
                          <br />
                          <strong className="text-blue-600 dark:text-blue-400">注意：</strong> 导入/导出仅包含文字内容，原对话中的文件需手动重新上传。
                        </p>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <button 
                        onClick={async () => {
                          setIsExporting(true);
                          try {
                            await storageService.exportConversationsText();
                          } finally {
                            setIsExporting(false);
                          }
                        }}
                        disabled={isExporting}
                        className="flex flex-col items-center justify-center gap-2 p-4 bg-white dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-blue-900/20 border border-gray-200 dark:border-gray-700 rounded-xl transition-all group"
                      >
                        <div className="p-2 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg group-hover:scale-110 transition-transform">
                          <Download size={20} />
                        </div>
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100">导出文字记录</span>
                      </button>

                      <button 
                        onClick={() => {
                          const input = document.createElement('input');
                          input.type = 'file';
                          input.accept = '.lawyer,.json.enc';
                          input.onchange = async (e) => {
                            const file = (e.target as HTMLInputElement).files?.[0];
                            if (file) {
                              setIsExporting(true);
                              try {
                                const count = await storageService.importConversationsFromFile(file);
                                alert(`成功导入 ${count} 个对话！\n请刷新页面以查看更新。`);
                                updateEstimate();
                              } catch (err) {
                                console.error(err);
                                alert('导入失败，请确保文件格式正确且未损坏。');
                              } finally {
                                setIsExporting(false);
                              }
                            }
                          };
                          input.click();
                        }}
                        disabled={isExporting}
                        className="flex flex-col items-center justify-center gap-2 p-4 bg-white dark:bg-gray-800 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 border border-gray-200 dark:border-gray-700 rounded-xl transition-all group"
                      >
                        <div className="p-2 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 rounded-lg group-hover:scale-110 transition-transform">
                          <Database size={20} />
                        </div>
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100">导入文字记录</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="p-4 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-700 flex justify-end">
                <button 
                  onClick={() => setIsModalOpen(false)}
                  className="px-6 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
