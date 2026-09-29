/*
 * 模块描述：开屏公告横幅。登录后拉取一次公告，展示第一条未读；关闭后按公告 id 记住，
 * 不再重复打扰。拉取失败或没有公告时不渲染任何内容。
 */

import React, { useEffect, useState } from 'react';
import { AlertTriangle, Info, X } from 'lucide-react';
import { fetchAnnouncements, type Announcement } from '../services/api';
import '../workbench/workbench.admin.css';

const DISMISS_PREFIX = 'lawver.announcement.dismissed.';

const isDismissed = (id: string): boolean => {
  try {
    return window.localStorage.getItem(DISMISS_PREFIX + id) === '1';
  } catch {
    return false;
  }
};

const rememberDismissed = (id: string) => {
  try {
    window.localStorage.setItem(DISMISS_PREFIX + id, '1');
  } catch {
    // 隐私模式/存储被禁用时忽略：本次会话关闭即可。
  }
};

export const AnnouncementBanner: React.FC = () => {
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAnnouncements()
      .then((data) => {
        if (cancelled) return;
        const next = (data.announcements || []).find((item) => item.id && !isDismissed(item.id));
        if (next) setAnnouncement(next);
      })
      .catch(() => {
        // 公告是锦上添花：读取失败不影响任何主流程。
      });
    return () => { cancelled = true; };
  }, []);

  if (!announcement || hidden) return null;

  const level = announcement.level || 'info';
  const Icon = level === 'info' ? Info : AlertTriangle;

  return (
    <div
      className={`wb-announcement ${level}`}
      role="status"
      aria-live="polite"
      aria-label={`公告：${announcement.title}`}
    >
      <span className="wb-announcement-icon"><Icon size={16} strokeWidth={2} /></span>
      <div className="wb-announcement-body">
        <p className="wb-announcement-title">{announcement.title}</p>
        {announcement.body && <p className="wb-announcement-text">{announcement.body}</p>}
      </div>
      <button
        aria-label="关闭公告"
        onClick={() => {
          rememberDismissed(announcement.id);
          setHidden(true);
        }}
      >
        <X size={15} />
      </button>
    </div>
  );
};
