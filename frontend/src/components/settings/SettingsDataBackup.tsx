/*
 * 设置 · 数据与备份
 *
 * 「本地旧资料」迁移入口已经移除（当前版本以云端为唯一数据源，不再兼容旧版本数据）。
 * 但云端工作台的备份导出/恢复仍是当前功能，挪到这里保留，避免随旧入口一起失联。
 */

import React, { useRef, useState } from 'react';
import { Download, Upload } from 'lucide-react';
import { useAppDialog } from '../../contexts/DialogContext';
import { api } from '../../workbench/client';
import { downloadApiFile } from '../../lib/download';
import { useT } from '../../i18n';
import { Banner, SettingsGroup, SettingsRow } from './SettingsUI';

export const SettingsDataBackup: React.FC = () => {
  const { t } = useT();
  const { showAlert } = useAppDialog();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<'export' | 'restore' | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const fail = async (e: unknown) => {
    const message = e instanceof Error ? e.message : String(e);
    setError(message);
    await showAlert({
      title: t('settings.data.failed'),
      message,
      tone: 'danger',
    });
  };

  const exportBackup = async () => {
    setBusy('export');
    setNotice('');
    setError('');
    try {
      await downloadApiFile('/api/workbench/backup', 'lawver-workbench-v5.zip');
      setNotice(t('settings.data.exported'));
    } catch (e) {
      await fail(e);
    } finally {
      setBusy(null);
    }
  };

  const restoreBackup = async (file: File) => {
    setBusy('restore');
    setNotice('');
    setError('');
    try {
      const body = new FormData();
      body.append('file', file);
      const result = await api<{ restored: number }>('/backup', 'POST', body, crypto.randomUUID());
      setNotice(t('settings.data.restored', { count: result.restored }));
      // 恢复内容作为新副本写入；通知工作台重拉索引，关闭设置后立即可见。
      window.dispatchEvent(new Event('lawver:workbench-updated'));
    } catch (e) {
      await fail(e);
    } finally {
      setBusy(null);
      if (input.current) input.current.value = '';
    }
  };

  return (
    <>
      <p className="settings-hint">{t('settings.data.hint')}</p>
      {busy && (
        <Banner tone="info">
          {busy === 'export' ? t('settings.data.exporting') : t('settings.data.restoring')}
        </Banner>
      )}
      {notice && <Banner tone="success">{notice}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}
      <SettingsGroup label={t('settings.data.group')}>
        <SettingsRow
          icon={<Download size={17} strokeWidth={2} />}
          title={t('settings.data.exportTitle')}
          description={t('settings.data.exportDesc')}
          onClick={busy ? undefined : () => void exportBackup()}
          disabled={!!busy}
          trailing={<span className="text-[13px] font-medium text-[var(--accent)]">{t('settings.data.exportAction')}</span>}
        />
        <SettingsRow
          icon={<Upload size={17} strokeWidth={2} />}
          title={t('settings.data.restoreTitle')}
          description={t('settings.data.restoreDesc')}
          onClick={busy ? undefined : () => input.current?.click()}
          disabled={!!busy}
          trailing={<span className="text-[13px] font-medium text-[var(--accent)]">{t('settings.data.restoreAction')}</span>}
        />
      </SettingsGroup>
      <input
        ref={input}
        type="file"
        hidden
        accept=".zip"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void restoreBackup(file);
        }}
      />
    </>
  );
};
