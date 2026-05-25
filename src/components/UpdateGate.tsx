/*
 * 模块描述：Android 强制更新门禁，负责版本检测、下载进度和安装引导。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { AlertTriangle, Download, RefreshCw, ShieldCheck } from 'lucide-react';
import { apiUrl } from '../services/api';
import { isNativeAndroid } from '../lib/platform';
import {
  LawverUpdater,
  type AndroidReleaseManifest,
  type DownloadProgress,
} from '../lib/lawverUpdater';

const MANIFEST_PATH = '/api/releases/android/latest';

type GateState = 'checking' | 'ready' | 'required';
type UpdatePhase = 'idle' | 'downloading' | 'downloaded' | 'permission' | 'installing';

const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '未知大小';
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

const errorMessage = (error: unknown) => {
  const raw = error as { code?: string; message?: string };
  const message = raw?.message || String(error || '');
  if (raw?.code === 'RATE_LIMIT' || /429|rate limit|频繁/i.test(message)) {
    return '下载请求过于频繁，请稍后重试。';
  }
  if (/sha|checksum|hash|校验/i.test(message)) {
    return '更新包校验失败，请重新下载。';
  }
  if (/permission|unknown app|install/i.test(message)) {
    return '需要允许 Lawver 安装未知应用后继续。';
  }
  return message || '更新失败，请稍后重试。';
};

export const UpdateGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [gateState, setGateState] = useState<GateState>(() => (isNativeAndroid() ? 'checking' : 'ready'));
  const [manifest, setManifest] = useState<AndroidReleaseManifest | null>(null);
  const [localVersion, setLocalVersion] = useState({ versionName: '', versionCode: 0 });
  const [phase, setPhase] = useState<UpdatePhase>('idle');
  const [progress, setProgress] = useState<DownloadProgress>({ receivedBytes: 0, totalBytes: 0, percent: 0 });
  const [downloadedPath, setDownloadedPath] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isNativeAndroid()) {
      setGateState('ready');
      return;
    }

    let cancelled = false;
    const checkUpdate = async () => {
      try {
        const info = await CapacitorApp.getInfo();
        const currentCode = Number(info.build || 0);
        const latest = await LawverUpdater.checkForUpdate({ manifestUrl: apiUrl(MANIFEST_PATH) });
        if (cancelled) return;
        setLocalVersion({ versionName: info.version || '', versionCode: currentCode });
        if (Number(latest.versionCode) > currentCode) {
          setManifest(latest);
          setGateState('required');
        } else {
          setGateState('ready');
        }
      } catch (e) {
        console.warn('[Update] Version check failed, continuing with cached app.', e);
        if (!cancelled) setGateState('ready');
      }
    };

    checkUpdate();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isNativeAndroid()) return undefined;
    let handle: { remove: () => Promise<void> } | undefined;
    LawverUpdater.addListener('downloadProgress', next => {
      setProgress({
        receivedBytes: Number(next.receivedBytes || 0),
        totalBytes: Number(next.totalBytes || 0),
        percent: Math.max(0, Math.min(100, Number(next.percent || 0))),
      });
    }).then(listener => {
      handle = listener;
    });

    return () => {
      handle?.remove().catch(console.error);
    };
  }, []);

  const latestLabel = useMemo(() => {
    if (!manifest) return '';
    return `${manifest.versionName} (${manifest.versionCode})`;
  }, [manifest]);

  const installDownloadedApk = useCallback(async (filePath: string) => {
    setError('');
    setPhase('installing');
    try {
      const result = await LawverUpdater.installApk({ filePath });
      if (result.needsPermission) {
        setPhase('permission');
        setError('请允许 Lawver 安装未知应用，返回后继续安装。');
        await LawverUpdater.openInstallPermissionSettings();
        return;
      }
      setPhase('installing');
    } catch (e) {
      setPhase('downloaded');
      setError(errorMessage(e));
    }
  }, []);

  const startDownload = useCallback(async () => {
    if (!manifest) return;
    setError('');
    setDownloadedPath('');
    setProgress({ receivedBytes: 0, totalBytes: manifest.size || 0, percent: 0 });
    setPhase('downloading');

    try {
      const result = await LawverUpdater.downloadApk({
        url: manifest.apkUrl,
        fileName: `Lawver-${manifest.versionName}.apk`,
        sha256: manifest.sha256,
      });
      setProgress({ receivedBytes: result.size, totalBytes: result.size, percent: 100 });
      setDownloadedPath(result.filePath);
      setPhase('downloaded');
      await installDownloadedApk(result.filePath);
    } catch (e) {
      setPhase('idle');
      setError(errorMessage(e));
    }
  }, [installDownloadedApk, manifest]);

  const continueInstall = useCallback(() => {
    if (!downloadedPath) return;
    installDownloadedApk(downloadedPath);
  }, [downloadedPath, installDownloadedApk]);

  if (gateState === 'ready') {
    return <>{children}</>;
  }

  const isChecking = gateState === 'checking';
  const progressLabel = progress.totalBytes > 0
    ? `${formatBytes(progress.receivedBytes)} / ${formatBytes(progress.totalBytes)}`
    : formatBytes(manifest?.size || 0);
  const actionDisabled = isChecking || phase === 'downloading' || phase === 'installing';

  return (
    <div className="fixed inset-0 z-[1000] flex min-h-[100dvh] items-center justify-center bg-[var(--bg-app)] px-4 py-[max(24px,var(--safe-top))] text-[var(--fg-1)]">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="lawver-update-title"
        className="w-full max-w-[430px] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-4)]"
      >
        <div className="border-b border-[var(--border-subtle)] px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
              {isChecking ? <RefreshCw className="h-5 w-5 animate-spin" /> : <ShieldCheck className="h-5 w-5" />}
            </div>
            <div className="min-w-0">
              <h1 id="lawver-update-title" className="t-title-m truncate">
                {isChecking ? '正在检查版本' : '需要更新 Lawver'}
              </h1>
              <p className="mt-1 text-[13px] leading-5 text-[var(--fg-3)]">
                {isChecking ? '正在确认 Android 客户端是否为最新版本。' : '当前版本无法继续使用，请安装最新版本。'}
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4 px-5 py-5">
          {!isChecking && manifest && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-3">
                <div className="text-xs text-[var(--fg-3)]">当前版本</div>
                <div className="mt-1 break-words font-medium text-[var(--fg-1)]">
                  {localVersion.versionName || '未知'} ({localVersion.versionCode || 0})
                </div>
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-3">
                <div className="text-xs text-[var(--fg-3)]">最新版本</div>
                <div className="mt-1 break-words font-medium text-[var(--fg-1)]">{latestLabel}</div>
              </div>
            </div>
          )}

          {!isChecking && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 text-xs text-[var(--fg-3)]">
                <span>{phase === 'downloading' ? '正在下载' : '更新包'}</span>
                <span className="font-mono">{progress.percent}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-[var(--radius-pill)] bg-[var(--bg-inset)]">
                <div
                  className="h-full rounded-[var(--radius-pill)] bg-[var(--accent)] transition-[width] duration-300"
                  style={{ width: `${phase === 'idle' ? 0 : progress.percent}%` }}
                />
              </div>
              <div className="text-xs leading-5 text-[var(--fg-3)]">{progressLabel}</div>
            </div>
          )}

          {error && (
            <div className="flex gap-2 rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.28)] bg-[rgba(176,70,62,0.08)] px-3 py-3 text-sm leading-5 text-[var(--color-danger-500)]">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {!isChecking && (
            <div className="flex flex-col gap-2">
              {phase === 'permission' ? (
                <button
                  type="button"
                  onClick={continueInstall}
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-on)] shadow-[var(--shadow-2)] transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <ShieldCheck className="h-4 w-4" />
                  授权后继续安装
                </button>
              ) : (
                <button
                  type="button"
                  onClick={phase === 'downloaded' && downloadedPath ? continueInstall : startDownload}
                  disabled={actionDisabled}
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-on)] shadow-[var(--shadow-2)] transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {phase === 'downloading' || phase === 'installing'
                    ? <RefreshCw className="h-4 w-4 animate-spin" />
                    : <Download className="h-4 w-4" />}
                  {phase === 'downloading' ? '正在下载' : phase === 'installing' ? '正在唤起安装' : '下载并安装'}
                </button>
              )}
              <p className="text-center text-xs leading-5 text-[var(--fg-3)]">
                下载文件将保存到系统默认下载目录。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
