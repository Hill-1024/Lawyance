/*
 * 模块描述：设置页的「操作快捷键」面板与帮助页共用的快捷键速查。
 *
 * 改键在这里完成：行内录制下一次按键，Esc 取消；同作用域内撞键直接拒绝。
 * 全部按键来自 lib/shortcuts 注册表，界面只显示格式化后的按键，不出现原始串。
 */

import React, { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Keyboard, RotateCcw, X } from 'lucide-react';
import { Banner, SettingsGroup, SettingsRow, StatusChip } from './SettingsUI';
import {
  SCOPE_LABELS,
  SHORTCUTS,
  findConflict,
  formatKeys,
  getBinding,
  getOverrides,
  resetAll,
  resetBinding,
  setBinding,
  specFromEvent,
  subscribe,
  type ShortcutDef,
} from '../../lib/shortcuts';

const keyCapClass =
  'inline-flex min-h-6 items-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-inset)] px-1.5 font-mono text-[11px] leading-5 text-[var(--fg-2)]';

const smallButtonClass = 'md3-btn-text lawver-pressable !min-h-8 !px-2 !text-[12px]';

/** 按键胶囊：统一由 formatKeys 渲染，界面里不出现 "mod+n" 这类原始串。 */
export const ShortcutKeys: React.FC<{ spec: string; className?: string }> = ({ spec, className = '' }) => (
  <span className={`${keyCapClass} ${className}`}>{formatKeys(spec)}</span>
);

const groupOf = (defs: readonly ShortcutDef[]) => {
  const groups: Array<[string, ShortcutDef[]]> = [];
  for (const def of defs) {
    const bucket = groups.find(([label]) => label === def.group);
    if (bucket) bucket[1].push(def);
    else groups.push([def.group, [def]]);
  }
  return groups;
};

/** 帮助页的只读速查：与设置页同源。 */
export const ShortcutCheatSheet: React.FC = () => {
  const overrides = useSyncExternalStore(subscribe, getOverrides);
  const rows = useMemo(
    () => SHORTCUTS.map(def => ({ def, keys: overrides[def.id] || def.defaultKeys })),
    [overrides],
  );
  return (
    <SettingsGroup label="键盘快捷键" hint="绑定保存在当前设备，可在「操作快捷键」里修改。">
      {rows.map(({ def, keys }) => (
        <SettingsRow
          key={def.id}
          dense
          icon={<Keyboard size={17} strokeWidth={2} />}
          title={def.label}
          description={SCOPE_LABELS[def.scope]}
          trailing={<ShortcutKeys spec={keys} />}
        />
      ))}
    </SettingsGroup>
  );
};

/** 操作快捷键面板：改键、单条恢复默认、全部恢复默认。 */
export const SettingsShortcuts: React.FC = () => {
  const overrides = useSyncExternalStore(subscribe, getOverrides);
  const [recording, setRecording] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const groups = useMemo(() => groupOf(SHORTCUTS), []);
  const hasOverrides = Object.keys(overrides).length > 0;

  // 录制期间在捕获阶段拦截按键：既不让 Esc 关掉设置，也不让新键触发别的动作。
  useEffect(() => {
    if (!recording) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        setRecording('');
        setError('');
        return;
      }
      const spec = specFromEvent(event);
      // 只按了修饰键：继续等真正的按键。
      if (!spec) return;
      event.preventDefault();
      event.stopPropagation();
      const conflict = findConflict(recording, spec);
      if (conflict) {
        setError(`「${formatKeys(spec)}」已用于「${conflict.label}」，请换一组按键或先恢复默认。`);
        return;
      }
      const label = SHORTCUTS.find(item => item.id === recording)?.label || recording;
      if (!setBinding(recording, spec)) {
        setError('这组按键不可用，请换一组。');
        return;
      }
      setRecording('');
      setError('');
      setNotice(`「${label}」已改为 ${formatKeys(spec)}。`);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [recording]);

  return (
    <>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <p className="settings-hint">绑定保存在当前设备，只影响本机的按键行为；改键后立即生效。</p>
        <button
          type="button"
          className={smallButtonClass}
          disabled={!hasOverrides}
          onClick={() => {
            resetAll();
            setRecording('');
            setError('');
            setNotice('全部快捷键已恢复默认。');
          }}
        >
          <RotateCcw size={14} strokeWidth={2} />
          全部恢复默认
        </button>
      </div>
      {error && <Banner tone="danger">{error}</Banner>}
      {notice && !error && <div role="status"><Banner tone="success">{notice}</Banner></div>}

      {groups.map(([group, defs]) => (
        <SettingsGroup key={group} label={group}>
          {defs.map(def => {
            const active = recording === def.id;
            const overridden = overrides[def.id] !== undefined;
            return (
              <SettingsRow
                key={def.id}
                dense
                icon={<Keyboard size={17} strokeWidth={2} />}
                title={def.label}
                description={active ? '请按下新的按键组合，按 Esc 取消。' : SCOPE_LABELS[def.scope]}
                trailing={
                  active ? (
                    <>
                      <span className="text-[12px] text-[var(--accent)]">等待按键…</span>
                      <button
                        type="button"
                        className={smallButtonClass}
                        onClick={() => {
                          setRecording('');
                          setError('');
                        }}
                      >
                        <X size={14} strokeWidth={2} />
                        取消
                      </button>
                    </>
                  ) : (
                    <>
                      {overridden && <StatusChip tone="accent">已改键</StatusChip>}
                      <ShortcutKeys spec={getBinding(def.id)} />
                      <button
                        type="button"
                        className={smallButtonClass}
                        onClick={() => {
                          setNotice('');
                          setError('');
                          setRecording(def.id);
                        }}
                      >
                        改键
                      </button>
                      <button
                        type="button"
                        className={smallButtonClass}
                        disabled={!overridden}
                        onClick={() => {
                          resetBinding(def.id);
                          setNotice(`「${def.label}」已恢复默认。`);
                          setError('');
                        }}
                      >
                        恢复默认
                      </button>
                    </>
                  )
                }
              />
            );
          })}
        </SettingsGroup>
      ))}
    </>
  );
};
