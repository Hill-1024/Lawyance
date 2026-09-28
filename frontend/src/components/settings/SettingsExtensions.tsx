import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ManageDialog } from '../../workbench/ManageDialog';
import { api, type Item } from '../../workbench/client';
import { Banner, CenteredSpinner } from './SettingsUI';
import '../../workbench/workbench.css';
export function SettingsExtensions() {
  const [data, setData] = useState<{skills:Item[];connectors:Item[]}>();
  const [error,setError] = useState('');
  const [enabled,setEnabled] = useState<boolean>();
  // 切二级页会立刻卸载本组件，而这两个请求还在飞；不判存活就会在卸载后 setState。
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const load = useCallback(async () => {
    try {
      const status = await api<{enabled:boolean}>('/status');
      if (!alive.current) return;
      setEnabled(status.enabled);
      if(!status.enabled) return;
      const [skills,connectors] = await Promise.all([api<Item[]>('/skills'),api<Item[]>('/connectors')]);
      if (!alive.current) return;
      setData({skills,connectors}); setError('');
    } catch(e) {if (alive.current) setError((e as Error).message);}
  },[]);
  useEffect(() => {alive.current = true; void load();},[load]);
  if(error && !data) return <Banner tone="danger">{error}<button className="settings-back" onClick={() => void load()}>重试</button></Banner>;
  if(enabled === false) return <Banner>该账号尚未启用云端工作台，技能与插件管理将在启用后提供。</Banner>;
  if(!data) return <CenteredSpinner label="正在读取技能与插件…"/>;
  return <><p className="settings-hint">管理可用能力；每次任务仍需明确选择要使用的技能或插件。</p>{error && <Banner tone="danger">{error}</Banner>}<div className="wb-app wb-settings-extensions"><ManageDialog embedded tab="skills" skills={data.skills} connectors={data.connectors} projects={[]} conversations={[]} documents={[]} onClose={() => {}} onReload={() => {void load();window.dispatchEvent(new Event('lawver:extensions-updated'));}} onError={setError}/></div></>;
}
