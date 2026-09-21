/*
 * 模块描述：本地存储状态组件，展示容量、持久化保护、清理和备份操作。
 */

import React, { useState } from 'react';
import { Database, AlertTriangle, Download, Trash2, ShieldCheck, ShieldAlert } from 'lucide-react';
import { useStorage } from '../hooks/useStorage';
import { storageService } from '../services/storageService';
import { motion, AnimatePresence } from 'motion/react';
import { HoverInfo } from './HoverInfo';
import { isNative } from '../lib/platform';
import { useAppDialog } from '../contexts/DialogContext';
import { useTranslation } from '../contexts/LocaleContext';
import { backupPassphraseMinLength } from '../lib/backup-crypto';

interface StorageIndicatorProps {
  compact?: boolean;
}

export const StorageIndicator: React.FC<StorageIndicatorProps> = ({ compact }) => {
  const t = useTranslation();
  const { usage, quota, usageRatio, isLowStorage, isPersistent, requestPersistence, updateEstimate, error } = useStorage();
  const { showAlert } = useAppDialog();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);
  const [backupPassphrase, setBackupPassphrase] = useState('');
  const [backupPassphraseConfirm, setBackupPassphraseConfirm] = useState('');
  const showPersistenceControls = !isNative();
  const canExportBackup = backupPassphrase.length >= backupPassphraseMinLength
    && backupPassphrase === backupPassphraseConfirm;

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
      await showAlert({
        title: t('storage.gc.doneTitle'),
        message: t('storage.gc.doneMessage', { count: result.cleanedCount }),
        tone: 'success',
      });
    } finally {
      setIsCleaning(false);
      updateEstimate();
    }
  };

  const handleRequestPersistence = async () => {
    if (!window.isSecureContext) {
      await showAlert({
        title: t('storage.persistence.insecureTitle'),
        message: t('storage.persistence.insecureMessage'),
        tone: 'warning',
      });
      return;
    }

    const granted = await requestPersistence();
    if (granted) {
      await showAlert({
        title: t('storage.persistence.grantedTitle'),
        message: t('storage.persistence.grantedMessage'),
        tone: 'success',
      });
    } else if (isNative()) {
      await showAlert({
        title: t('storage.persistence.nativeTitle'),
        message: t('storage.persistence.nativeMessage'),
        tone: 'info',
      });
    } else {
      await showAlert({
        title: t('storage.persistence.deniedTitle'),
        message: t('storage.persistence.deniedMessage'),
        tone: 'warning',
      });
    }
  };

  if (compact) {
    return (
      <HoverInfo label={t('storage.view')} placement="top">
        <button
          type="button"
          className={`lawver-pressable flex min-h-11 min-w-11 cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5 transition-colors ${
            isLowStorage ? 'bg-[rgba(184,132,42,0.12)] text-[var(--color-warning-500)]' : 'text-[var(--fg-2)] hover:bg-[rgba(20,23,31,0.06)] dark:hover:bg-white/[0.06]'
          }`}
          onClick={() => setIsModalOpen(true)}
          aria-label={t('storage.view')}
        >
          <Database size={16} strokeWidth={2} />
          <span className="t-label-m">
            {Math.round(usageRatio * 100)}%
          </span>
          {isLowStorage && <AlertTriangle size={14} strokeWidth={2} className="animate-pulse" />}
        </button>
      </HoverInfo>
    );
  }

  return (
    <>
      <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="t-title-s flex items-center gap-2">
            <Database size={18} strokeWidth={2} className="text-[var(--accent)]" />
            <span>{t('storage.title')}</span>
          </div>
          <button 
            onClick={() => setIsModalOpen(true)}
            className="lawver-pressable t-label-m inline-flex min-h-11 min-w-11 items-center justify-center rounded-full px-2 text-[var(--accent)] hover:underline"
          >
            {t('storage.manage')}
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
                <span>{t('storage.used', { size: formatSize(usage) })}</span>
                <span>{t('storage.quota', { size: formatSize(quota) })}</span>
              </div>
            </>
          )}
        </div>

        {showPersistenceControls && !isPersistent && (
          <button 
            onClick={handleRequestPersistence}
            className="lawver-pressable t-label-m mt-3 flex min-h-11 w-full items-center justify-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] px-3 py-1.5 text-[var(--brand-primary-700)] transition-colors hover:bg-[rgba(59,98,184,0.16)] dark:text-[var(--accent)]"
          >
            <ShieldAlert size={14} strokeWidth={2} />
            {t('storage.enablePersistent')}
          </button>
        )}
        
        {showPersistenceControls && isPersistent && (
          <div className="t-label-s mt-3 flex items-center justify-center gap-1.5 text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
            <ShieldCheck size={14} strokeWidth={2} />
            {t('storage.persistentOn')}
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
                    <h3 className="t-title-l">{t('storage.modal.title')}</h3>
                    <p className="t-body-m t-muted">{t('storage.modal.subtitle')}</p>
                  </div>
                </div>

                {isLowStorage && (
                  <div className="mb-6 flex gap-3 rounded-[var(--radius-md)] border border-[rgba(184,132,42,0.3)] bg-[rgba(184,132,42,0.1)] p-4">
                    <AlertTriangle className="shrink-0 text-[var(--color-warning-500)]" size={20} strokeWidth={2} />
                    <div>
                      <p className="t-title-s text-[#5C3F0E] dark:text-[#FBEBC8]">{t('storage.low.title')}</p>
                      <p className="t-body-s mt-1 text-[#5C3F0E]/80 dark:text-[#FBEBC8]/80">
                        {t('storage.low.body')}
                      </p>
                    </div>
                  </div>
                )}

                <div className="space-y-4">
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between">
                      <span className="t-body-m">{t('storage.usageRate')}</span>
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
                      <span>{t('storage.total', { size: formatSize(quota) })}</span>
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
                          <p className="t-title-s">{t('storage.gc.action')}</p>
                          <p className="t-body-s t-muted">{t('storage.gc.actionHint')}</p>
                        </div>
                      </div>
                      {isCleaning && <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--color-warning-500)] border-t-transparent" />}
                    </button>
                  </div>

                  <div className="border-t border-[var(--border-subtle)] pt-6">
                    <div className="mb-4 flex items-center">
                      <h4 className="t-label-s t-weak">{t('storage.backup.section')}</h4>
                    </div>
                    
                    <div className="mb-4 rounded-[var(--radius-md)] border border-[rgba(59,98,184,0.18)] bg-[rgba(59,98,184,0.06)] p-4">
                      <div className="flex gap-3">
                        <AlertTriangle className="shrink-0 text-[var(--accent)]" size={18} strokeWidth={2} />
                        <p className="t-body-s leading-relaxed text-[var(--brand-primary-800)] dark:text-[var(--accent)]">
                          {t('storage.backup.notice')}
                          <br />
                          <strong className="text-[var(--accent)]">{t('storage.backup.noticeStrong')}</strong> {t('storage.backup.noticeRest')}
                        </p>
                      </div>
                    </div>

                    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2" id="backup-passphrase-help">
                      <label className="flex min-w-0 flex-col gap-1.5">
                        <span className="t-label-s text-[var(--fg-2)]">{t('storage.backup.passphrase')}</span>
                        <input
                          type="password"
                          value={backupPassphrase}
                          onChange={event => setBackupPassphrase(event.target.value)}
                          autoComplete="new-password"
                          className="md3-input min-h-11 w-full"
                          placeholder={t('storage.backup.passphrasePlaceholder', { min: backupPassphraseMinLength })}
                          aria-describedby="backup-passphrase-help"
                        />
                      </label>
                      <label className="flex min-w-0 flex-col gap-1.5">
                        <span className="t-label-s text-[var(--fg-2)]">{t('storage.backup.confirmPassphrase')}</span>
                        <input
                          type="password"
                          value={backupPassphraseConfirm}
                          onChange={event => setBackupPassphraseConfirm(event.target.value)}
                          autoComplete="new-password"
                          className="md3-input min-h-11 w-full"
                          placeholder={t('storage.backup.confirmPlaceholder')}
                          aria-describedby="backup-passphrase-help"
                        />
                      </label>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <button 
                        onClick={async () => {
                          setIsExporting(true);
                          try {
                            await storageService.exportConversationsText(backupPassphrase);
                            setBackupPassphrase('');
                            setBackupPassphraseConfirm('');
                          } catch (err) {
                            console.error(err);
                            await showAlert({
                              title: t('storage.export.failedTitle'),
                              message: (err as Error).message,
                              tone: 'danger',
                            });
                          } finally {
                            setIsExporting(false);
                          }
                        }}
                        disabled={isExporting || !canExportBackup}
                        className="group flex flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 transition-all hover:bg-[var(--accent-quiet)]"
                      >
                        <div className="rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] p-2 text-[var(--accent)] transition-transform group-hover:scale-105">
                          <Download size={20} strokeWidth={2} />
                        </div>
                        <span className="t-title-s">{t('storage.export.action')}</span>
                      </button>

                      <div className="relative">
                        <input
                          type="file"
                          id="import-dialogues-input"
                          className="hidden"
                          accept={storageService.acceptedConversationFileExtensions}
                          onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            
                            setIsExporting(true);
                            try {
                              const count = await storageService.importConversationsFromFile(file, backupPassphrase);
                              await showAlert({
                                title: t('storage.import.doneTitle'),
                                message: t('storage.import.doneMessage', { count }),
                                tone: 'success',
                              });
                              setBackupPassphrase('');
                              setBackupPassphraseConfirm('');
                              updateEstimate();
                            } catch (err) {
                              console.error(err);
                              await showAlert({
                                title: t('storage.import.failedTitle'),
                                message: (err as Error).message || t('storage.import.failedHint'),
                                tone: 'danger',
                              });
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
                          <span className="t-title-s">{t('storage.import.action')}</span>
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
                  {t('storage.modal.close')}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
};
