/*
 * 模块描述：本地持久化数据变更事件，供导入/清理后刷新已挂载的状态 Hook。
 */

export interface LocalStorageDataChangeDetail {
  source: 'import';
  conversationIds?: string[];
  courtSessionIds?: string[];
}

const LOCAL_STORAGE_DATA_CHANGED_EVENT = 'lawver:local-storage-data-changed';

export const notifyLocalStorageDataChanged = (detail: LocalStorageDataChangeDetail) => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<LocalStorageDataChangeDetail>(
    LOCAL_STORAGE_DATA_CHANGED_EVENT,
    { detail }
  ));
};

export const addLocalStorageDataChangeListener = (
  handler: (detail: LocalStorageDataChangeDetail) => void | Promise<void>
) => {
  if (typeof window === 'undefined') return () => undefined;

  const listener = (event: Event) => {
    handler((event as CustomEvent<LocalStorageDataChangeDetail>).detail);
  };

  window.addEventListener(LOCAL_STORAGE_DATA_CHANGED_EVENT, listener);
  return () => window.removeEventListener(LOCAL_STORAGE_DATA_CHANGED_EVENT, listener);
};
