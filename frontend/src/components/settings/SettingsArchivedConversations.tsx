/*
 * 设置 · 已归档的会话
 *
 * 归档会话后它只会从会话列表里收起；此前唯一的恢复入口和回收站挤在侧栏底部的
 * 同一个弹窗里，用户找不到。这里给归档一个显式、可搜索的常驻入口：
 * 按会话名/项目名过滤，行尾可以取消归档或移入回收站（与会话删除同一行为）。
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Archive, ArchiveRestore, MessageSquareText, Search, Trash2 } from 'lucide-react';
import { useAppDialog } from '../../contexts/DialogContext';
import { api, Item, Page } from '../../workbench/client';
import { useT } from '../../i18n';
import { Banner, CenteredSpinner, EmptyState, SettingsGroup, SettingsRow } from './SettingsUI';

type ArchivedConversation = Item & { project_title?: string | null };

const PAGE_SIZE = 200;
// 归档列表用于人工管理，正常规模远小于这个上限；设个硬顶避免游标异常时无限翻页。
const MAX_PAGES = 25;

export const SettingsArchivedConversations: React.FC = () => {
  const { t } = useT();
  const { showAlert, showConfirm } = useAppDialog();
  const [items, setItems] = useState<ArchivedConversation[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const all: ArchivedConversation[] = [];
      let cursor = '';
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const body = await api<Page<ArchivedConversation>>(
          `/archived?kind=conversation&limit=${PAGE_SIZE}` +
            (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''),
        );
        all.push(...body.items);
        if (!body.next_cursor) break;
        cursor = body.next_cursor;
      }
      if (!alive.current) return;
      setItems(all);
      setError('');
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // load 只依赖 api/t，生命周期与当前挂载一致；刻意不把它放进依赖以免每次渲染重拉。
  }, []);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return items;
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        (item.project_title || '').toLowerCase().includes(keyword),
    );
  }, [items, query]);

  const unarchive = async (item: ArchivedConversation) => {
    setBusy(item.id);
    try {
      await api(`/conversations/${item.id}`, 'PATCH', {
        expected_revision: item.revision,
        archived: false,
      });
      if (!alive.current) return;
      setItems((old) => old.filter((entry) => entry.id !== item.id));
      setNotice(t('settings.archived.restored'));
      window.dispatchEvent(new Event('lawver:workbench-updated'));
    } catch (e) {
      await showAlert({
        title: t('settings.archived.actionFailed'),
        message: e instanceof Error ? e.message : String(e),
        tone: 'danger',
      });
    } finally {
      if (alive.current) setBusy('');
    }
  };

  const remove = async (item: ArchivedConversation) => {
    const confirmed = await showConfirm({
      title: t('workbench.manage.trashConfirmTitle'),
      message: t('workbench.manage.trashConfirmMessage', { title: item.title }),
      confirmLabel: t('settings.archived.delete'),
      tone: 'danger',
    });
    if (!confirmed) return;
    setBusy(item.id);
    try {
      // 与会话列表里的删除完全一致：移入回收站，保留 30 天。
      await api(`/conversations/${item.id}`, 'DELETE');
      if (!alive.current) return;
      setItems((old) => old.filter((entry) => entry.id !== item.id));
      setNotice(t('settings.archived.deleted'));
      window.dispatchEvent(new Event('lawver:workbench-updated'));
    } catch (e) {
      await showAlert({
        title: t('settings.archived.actionFailed'),
        message: e instanceof Error ? e.message : String(e),
        tone: 'danger',
      });
    } finally {
      if (alive.current) setBusy('');
    }
  };

  const subtitle = (item: ArchivedConversation) =>
    item.project_title
      ? t('settings.archived.project', { name: item.project_title })
      : t('settings.archived.personal');

  if (loading) return <CenteredSpinner label={t('settings.archived.loading')} />;
  if (error)
    return (
      <Banner tone="danger">
        {error}
        <button className="settings-back" onClick={() => void load()}>
          {t('common.retry')}
        </button>
      </Banner>
    );

  return (
    <>
      <p className="settings-hint">{t('settings.archived.hint')}</p>
      <label className="settings-search">
        <Search size={16} />
        <input
          aria-label={t('settings.archived.searchLabel')}
          placeholder={t('settings.archived.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {!!notice && <Banner tone="success">{notice}</Banner>}
      {!items.length ? (
        <SettingsGroup>
          <EmptyState
            icon={<Archive size={22} />}
            title={t('settings.archived.emptyTitle')}
            description={t('settings.archived.emptyHint')}
          />
        </SettingsGroup>
      ) : !filtered.length ? (
        <SettingsGroup>
          <EmptyState
            icon={<Search size={22} />}
            title={t('settings.archived.noMatchTitle')}
            description={t('settings.archived.noMatchHint')}
          />
        </SettingsGroup>
      ) : (
        <SettingsGroup
          label={t('settings.archived.listLabel')}
          action={
            <span className="text-[12px] text-[var(--fg-3)]">
              {query.trim()
                ? t('settings.archived.filteredCount', {
                    shown: filtered.length,
                    total: items.length,
                  })
                : t('settings.archived.total', { total: items.length })}
            </span>
          }
        >
          {filtered.map((item) => (
            <SettingsRow
              key={item.id}
              icon={<MessageSquareText size={16} />}
              title={item.title}
              description={subtitle(item)}
              stackTrailing
              className={busy === item.id ? 'opacity-60' : ''}
              trailing={
                <>
                  <button
                    type="button"
                    aria-label={t('settings.archived.restoreLabel', { title: item.title })}
                    title={t('settings.archived.restore')}
                    disabled={busy === item.id}
                    onClick={() => void unarchive(item)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)] disabled:opacity-50"
                  >
                    <ArchiveRestore size={16} />
                  </button>
                  <button
                    type="button"
                    aria-label={t('settings.archived.deleteLabel', { title: item.title })}
                    title={t('settings.archived.delete')}
                    disabled={busy === item.id}
                    onClick={() => void remove(item)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.08)] hover:text-[var(--color-danger-500)] disabled:opacity-50"
                  >
                    <Trash2 size={16} />
                  </button>
                </>
              }
            />
          ))}
        </SettingsGroup>
      )}
    </>
  );
};
