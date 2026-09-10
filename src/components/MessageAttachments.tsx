/*
 * 模块描述：消息内附件预览组件，从本地 IndexedDB 取回原图并渲染缩略图与灯箱。
 */

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { FileText, X } from 'lucide-react';
import { fileDB } from '../lib/db';
import type { MessageAttachment } from '../types';

type ResolvedAttachment = MessageAttachment & { url?: string };

const useAttachmentUrls = (conversationId: string | undefined, attachments: MessageAttachment[]) => {
  const [resolved, setResolved] = useState<ResolvedAttachment[]>(attachments);
  // 依赖数组用稳定 key，避免父组件重建数组导致 objectURL 反复创建/释放而闪烁。
  const attachmentKey = attachments.map(a => `${a.kind}:${a.name}:${a.path}`).join('|');

  useEffect(() => {
    let cancelled = false;
    const objectUrls: string[] = [];
    setResolved(attachments);

    if (!conversationId || attachments.length === 0) return;

    (async () => {
      try {
        const files = await fileDB.getFilesByConvId(conversationId);
        if (cancelled) return;
        const next = attachments.map(attachment => {
          if (attachment.kind !== 'image') return attachment;
          const match = files.find(file => file.fileName === attachment.name)
            || files.find(file => file.path === attachment.path);
          if (!match?.blob) return attachment;
          const url = URL.createObjectURL(match.blob);
          objectUrls.push(url);
          return { ...attachment, url };
        });
        if (!cancelled) setResolved(next);
      } catch {
        // 本地缓存缺失时退回文件卡片，不影响消息本身渲染。
      }
    })();

    return () => {
      cancelled = true;
      objectUrls.forEach(url => URL.revokeObjectURL(url));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, attachmentKey]);

  return resolved;
};

export const MessageAttachments: React.FC<{
  conversationId?: string;
  attachments: MessageAttachment[];
}> = ({ conversationId, attachments }) => {
  const resolved = useAttachmentUrls(conversationId, attachments);
  const [lightbox, setLightbox] = useState<ResolvedAttachment | null>(null);

  useEffect(() => {
    if (!lightbox) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [lightbox]);

  if (resolved.length === 0) return null;

  const lightboxLayer = lightbox && typeof document !== 'undefined'
    ? createPortal(
      <div
        className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--bg-overlay)] p-4"
        role="dialog"
        aria-modal="true"
        aria-label={lightbox.name}
        onClick={() => setLightbox(null)}
      >
        <button
          type="button"
          onClick={() => setLightbox(null)}
          className="lawver-pressable absolute right-4 top-[calc(1rem+var(--safe-top))] inline-flex h-11 w-11 items-center justify-center rounded-full bg-[var(--bg-surface)] text-[var(--fg-2)] shadow-[var(--shadow-3)]"
          aria-label="关闭预览"
        >
          <X size={20} strokeWidth={2} />
        </button>
        {lightbox.url ? (
          <img
            src={lightbox.url}
            alt={lightbox.name}
            className="max-h-full max-w-full rounded-[var(--radius-lg)] object-contain shadow-[var(--shadow-5)]"
          />
        ) : (
          <p className="rounded-[var(--radius-lg)] bg-[var(--bg-surface)] px-5 py-4 text-sm text-[var(--fg-2)]">
            本地预览已过期，原文件仍在工作区中。
          </p>
        )}
      </div>,
      document.body,
    )
    : null;

  return (
    <div className="flex flex-wrap justify-end gap-2">
      {lightboxLayer}
      {resolved.map(attachment => (
        attachment.url ? (
          <button
            key={attachment.path}
            type="button"
            onClick={() => setLightbox(attachment)}
            className="lawver-pressable overflow-hidden rounded-[var(--radius-md)] border border-white/25 shadow-[var(--shadow-1)] transition-transform hover:scale-[1.02]"
            aria-label={`查看图片 ${attachment.name}`}
          >
            <img
              src={attachment.url}
              alt={attachment.name}
              className="h-24 w-24 object-cover sm:h-28 sm:w-28"
            />
          </button>
        ) : (
          <span
            key={attachment.path}
            className="flex items-center gap-1.5 rounded-full bg-black/15 px-3 py-1 text-sm"
            title={attachment.name}
          >
            <FileText size={14} strokeWidth={2} />
            <span className="max-w-[200px] truncate">{attachment.name}</span>
          </span>
        )
      ))}
    </div>
  );
};
