/*
 * 模块描述：文件上传进度条，按文件大小自适应显示 KB/MB 进度。
 */

import React from 'react';
import type { WorkspaceFile } from '../types';

const KB = 1024;
const MB = KB * 1024;

const formatNumber = (value: number, unit: 'KB' | 'MB') => {
  if (unit === 'MB') {
    return value >= 10 ? value.toFixed(1) : value.toFixed(2);
  }
  return value >= 100 ? value.toFixed(0) : value.toFixed(1);
};

export const formatFileSizeProgress = (loadedBytes: number, totalBytes: number) => {
  const total = Math.max(totalBytes, 0);
  const loaded = Math.min(Math.max(loadedBytes, 0), total);
  const unit = total >= MB ? 'MB' : 'KB';
  const divisor = unit === 'MB' ? MB : KB;

  return `${formatNumber(loaded / divisor, unit)} / ${formatNumber(total / divisor, unit)} ${unit}`;
};

export const FileUploadProgress: React.FC<{ file: WorkspaceFile; className?: string }> = React.memo(({ file, className = '' }) => {
  const total = Math.max(file.size || 0, 0);
  const progress = total > 0
    ? Math.min(Math.max((file.uploadedBytes || 0) / total, 0), 1)
    : Math.min(Math.max(file.uploadProgress || 0, 0), 1);
  const loaded = total > 0 ? Math.round(total * progress) : 0;
  const percent = Math.round(progress * 100);
  const status = file.isUploading && progress >= 1 ? '正在保存' : '上传中';

  if (!file.isUploading && file.uploadProgress === undefined) {
    return null;
  }

  return (
    <div className={`mt-1.5 min-w-0 ${className}`}>
      <div className="mb-1 flex min-w-0 items-center justify-between gap-2 text-[11px] leading-none text-[var(--fg-3)]">
        <span className="shrink-0">{status}</span>
        <span className="min-w-0 truncate tabular-nums">{formatFileSizeProgress(loaded, total)}</span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-[rgba(20,23,31,0.08)] dark:bg-white/[0.08]"
        role="progressbar"
        aria-label={`${file.name} 上传进度`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div
          className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-150 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
});

FileUploadProgress.displayName = 'FileUploadProgress';
