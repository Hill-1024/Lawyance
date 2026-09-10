/*
 * 模块描述：大模型配置档案管理，支持保存多套模型端点并一键热切换到运行时。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronDown,
  Gauge,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Star,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  activateLlmProfile,
  clearLlmProfileSecret,
  deleteLlmProfile,
  fetchLlmModels,
  getLlmProfiles,
  saveLlmProfile,
  testProvider,
  updateSettings,
  getSettings,
  type AppSettings,
  type LlmModel,
  type LlmProfile,
  type LlmProfileState,
} from '../../services/api';
import { useAppDialog } from '../../contexts/DialogContext';
import {
  Banner,
  CenteredSpinner,
  EmptyState,
  SettingsField,
  StatusChip,
  fieldInputClass,
} from './SettingsUI';

const hostOf = (baseUrl: string) => {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl.replace(/^https?:\/\//, '').split('/')[0] || baseUrl;
  }
};

type DraftState = {
  id?: string;
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  activate: boolean;
};

const emptyDraft = (): DraftState => ({
  name: '',
  base_url: '',
  model: '',
  api_key: '',
  activate: true,
});

export const LlmProfileManager: React.FC = () => {
  const { showAlert, showConfirm } = useAppDialog();
  const [state, setState] = useState<LlmProfileState | null>(null);
  const [loadError, setLoadError] = useState('');
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [busy, setBusy] = useState('');
  const [models, setModels] = useState<LlmModel[]>([]);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [showKeyField, setShowKeyField] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [settingsSnapshot, setSettingsSnapshot] = useState<AppSettings | null>(null);

  const load = useCallback(async () => {
    setLoadError('');
    try {
      const [profileState, settings] = await Promise.all([
        getLlmProfiles(),
        getSettings().catch(() => null),
      ]);
      setState(profileState);
      setSettingsSnapshot(settings);
      const llm = settings?.providers?.llm;
      setEnabled(Boolean(llm?.enabled));
    } catch (error) {
      setLoadError((error as Error).message || '读取模型档案失败');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const activeProfile = useMemo(
    () => state?.profiles.find(profile => profile.active) || null,
    [state],
  );

  const refreshModels = async () => {
    setBusy('models');
    try {
      const next = await fetchLlmModels();
      setModels(next);
      if (next.length === 0) {
        await showAlert({
          title: '没有取到模型列表',
          message: '当前生效的 Base URL 与 API Key 未能返回 /models 列表，可以直接手动填写模型名称。',
          tone: 'warning',
        });
      }
    } finally {
      setBusy('');
    }
  };

  const openCreate = () => {
    setDraft({ ...emptyDraft(), base_url: activeProfile?.base_url || '' });
    setShowKeyField(true);
    setModelPickerOpen(false);
  };

  const openEdit = (profile: LlmProfile) => {
    setDraft({
      id: profile.id,
      name: profile.name,
      base_url: profile.base_url,
      model: profile.model,
      api_key: '',
      activate: false,
    });
    setShowKeyField(false);
    setModelPickerOpen(false);
  };

  const handleSave = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      await showAlert({ title: '请填写档案名称', message: '档案名称用于在列表中区分不同模型。', tone: 'warning' });
      return;
    }
    if (!draft.base_url.trim()) {
      await showAlert({ title: '请填写 Base URL', message: '例如 https://api.deepseek.com', tone: 'warning' });
      return;
    }
    if (!draft.model.trim()) {
      await showAlert({ title: '请填写模型名称', message: '可以从模型列表中选择，也可以手动输入。', tone: 'warning' });
      return;
    }
    setBusy('save');
    const name = draft.name.trim();
    try {
      const next = await saveLlmProfile({
        id: draft.id,
        name,
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
        api_key: draft.api_key.trim() || undefined,
        enabled: true,
        activate: draft.activate,
      });
      setState(next);
      setDraft(null);
      // 以后端返回的实际活动档案为准，避免"未勾选自动切换却提示已切换"。
      const activeName = next.profiles.find(profile => profile.id === next.active)?.name;
      const activated = activeName === name;
      await showAlert({
        title: draft.id ? '档案已更新' : '档案已保存',
        message: activated
          ? `已切换到「${name}」，后续对话立即使用该模型，无需重启服务。`
          : `「${name}」已保存，在列表中点击「切换使用」即可生效。`,
        tone: 'success',
      });
      void load();
    } catch (error) {
      await showAlert({ title: '保存失败', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleActivate = async (profile: LlmProfile) => {
    if (profile.active) return;
    setBusy(`activate:${profile.id}`);
    try {
      const next = await activateLlmProfile(profile.id);
      setState(next);
      await showAlert({
        title: '已切换模型',
        message: `当前使用「${profile.name}」(${profile.model})，下一轮对话立即生效。`,
        tone: 'success',
      });
    } catch (error) {
      await showAlert({ title: '切换失败', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleDelete = async (profile: LlmProfile) => {
    const confirmed = await showConfirm({
      title: `删除「${profile.name}」？`,
      message: '该档案保存的模型端点与 API Key 会被一并移除，正在进行的对话不受影响。',
      tone: 'danger',
      confirmLabel: '删除',
    });
    if (!confirmed) return;
    setBusy(`delete:${profile.id}`);
    try {
      const next = await deleteLlmProfile(profile.id);
      setState(next);
    } catch (error) {
      await showAlert({ title: '删除失败', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleClearKey = async (profile: LlmProfile) => {
    const confirmed = await showConfirm({
      title: '清除该档案的 API Key？',
      message: '清除后该档案需要重新填写 Key 才能调用模型。',
      tone: 'danger',
      confirmLabel: '清除',
    });
    if (!confirmed) return;
    setBusy(`clear:${profile.id}`);
    try {
      await clearLlmProfileSecret(profile.id);
      await load();
    } catch (error) {
      await showAlert({ title: '清除失败', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const toggleProviderEnabled = async (next: boolean) => {
    setBusy('toggle');
    setEnabled(next);
    try {
      const result = await updateSettings({
        providers: { ...(settingsSnapshot?.providers || {}), llm: { enabled: next } },
      });
      setSettingsSnapshot(result);
    } catch (error) {
      setEnabled(!next);
      await showAlert({ title: '保存失败', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleTest = async () => {
    setBusy('test');
    try {
      const result = await testProvider('llm');
      await showAlert({
        title: '配置完整',
        message: `${result.message}。实际可用性取决于服务商与网络，可在对话中验证。`,
        tone: 'success',
      });
    } catch (error) {
      await showAlert({ title: '检测未通过', message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  if (loadError) {
    return (
      <div className="min-w-0">
        <Banner tone="danger">{loadError}</Banner>
        <button
          type="button"
          onClick={() => void load()}
          className="md3-btn-tonal lawver-pressable mt-3"
        >
          <RefreshCw size={16} strokeWidth={2} /> 重试
        </button>
      </div>
    );
  }

  if (!state) {
    return <CenteredSpinner label="正在读取模型档案…" />;
  }

  const isBusy = busy !== '';

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {/* 当前生效配置 */}
      <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
          <div className="flex min-w-0 gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
              <Zap size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="t-title-m">当前生效模型</h2>
                <StatusChip tone={enabled ? 'ok' : 'muted'}>
                  {enabled ? '已启用' : '已停用'}
                </StatusChip>
              </div>
              <p className="mt-1 break-all font-mono text-[13px] leading-5 text-[var(--fg-1)]">
                {state.effective.model || '未配置模型'}
              </p>
              <p className="mt-0.5 break-all text-[12px] leading-5 text-[var(--fg-3)]">
                {state.effective.source || '环境变量默认'}
                {state.effective.base_url ? ` · ${hostOf(state.effective.base_url)}` : ''}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void toggleProviderEnabled(!enabled)}
              disabled={isBusy}
              className="md3-btn-tonal lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {busy === 'toggle' ? <Loader2 size={15} className="animate-spin" /> : <Gauge size={15} strokeWidth={2} />}
              {enabled ? '停用 LLM' : '启用 LLM'}
            </button>
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={isBusy}
              className="md3-btn-tonal lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {busy === 'test' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2} />}
              检测配置
            </button>
          </div>
        </div>
        <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-2.5 sm:px-5">
          <p className="text-[12px] leading-5 text-[var(--fg-3)]">
            切换档案会立即写入运行时配置，<strong className="font-medium text-[var(--fg-2)]">无需重启服务</strong>；
            对话、OCP 审查与标题生成都会使用新的模型。
          </p>
        </div>
      </section>

      {/* 档案列表 */}
      <section className="min-w-0">
        <div className="mb-2 flex min-w-0 items-end justify-between gap-3 px-1">
          <div className="min-w-0">
            <h2 className="t-label-m font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">
              已保存的模型 ({state.profiles.length})
            </h2>
            <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">
              保存多套端点后可直接切换，不必重复填写地址与密钥。
            </p>
          </div>
          <button
            type="button"
            onClick={openCreate}
            disabled={isBusy || draft !== null}
            className="md3-btn-filled lawver-pressable !min-h-11 shrink-0 text-sm disabled:opacity-50"
          >
            <Plus size={16} strokeWidth={2.4} /> 新增配置
          </button>
        </div>

        <div className="min-w-0 divide-y divide-[var(--border-subtle)] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
          {state.profiles.length === 0 ? (
            <EmptyState
              icon={<Sparkles size={22} strokeWidth={2} />}
              title="还没有保存的模型配置"
              description="新增一套配置后即可在多个模型之间一键切换。"
              action={(
                <button type="button" onClick={openCreate} className="md3-btn-tonal lawver-pressable text-sm">
                  <Plus size={16} strokeWidth={2.4} /> 新增配置
                </button>
              )}
            />
          ) : (
            state.profiles.map(profile => {
              const rowBusy = busy.endsWith(profile.id);
              return (
                <div
                  key={profile.id}
                  className={`flex min-w-0 flex-col gap-3 px-4 py-3.5 transition-colors sm:flex-row sm:items-center sm:px-5 ${
                    profile.active ? 'bg-[var(--accent-quiet)]' : 'hover:bg-[var(--bg-surface-2)]'
                  }`}
                >
                  <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] ${
                    profile.active
                      ? 'bg-[var(--accent)] text-[var(--accent-on)]'
                      : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
                  }`}>
                    {profile.active ? <Star size={18} strokeWidth={2.2} /> : <Sparkles size={18} strokeWidth={2} />}
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate text-[14px] font-semibold text-[var(--fg-1)]">{profile.name}</span>
                      {profile.active && <StatusChip tone="accent">使用中</StatusChip>}
                      {profile.incomplete && <StatusChip tone="warn">配置不完整</StatusChip>}
                      {!profile.has_api_key && <StatusChip tone="warn">缺少 Key</StatusChip>}
                      {!profile.enabled && <StatusChip tone="muted">已停用</StatusChip>}
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[12px] text-[var(--fg-2)]">
                      {profile.model || '（未填写模型）'}
                    </p>
                    <p className="truncate text-[11px] text-[var(--fg-4)]">
                      {hostOf(profile.base_url) || '（未填写 Base URL）'}
                    </p>
                    {profile.incomplete && (
                      <p className="mt-1 text-[11px] leading-4 text-[var(--color-warning-500)]">
                        该档案缺少{!profile.base_url ? ' Base URL' : ''}{!profile.model ? ' 模型名称' : ''}，
                        当前实际使用{state.effective.source ? `「${state.effective.source}」` : '环境变量配置'}，
                        补齐后「切换使用」才会生效。
                      </p>
                    )}
                  </div>

                  <div className="flex min-w-0 flex-wrap items-center gap-1.5 sm:shrink-0">
                    {!profile.active && (
                      <button
                        type="button"
                        onClick={() => void handleActivate(profile)}
                        disabled={isBusy}
                        className="md3-btn-tonal lawver-pressable !min-h-11 !px-3.5 text-[13px] disabled:opacity-50"
                      >
                        {busy === `activate:${profile.id}`
                          ? <Loader2 size={14} className="animate-spin" />
                          : <Zap size={14} strokeWidth={2} />}
                        切换使用
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => openEdit(profile)}
                      disabled={isBusy}
                      className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] disabled:opacity-50"
                      aria-label={`编辑 ${profile.name}`}
                      title="编辑"
                    >
                      <Pencil size={16} strokeWidth={2} />
                    </button>
                    {profile.has_api_key && (
                      <button
                        type="button"
                        onClick={() => void handleClearKey(profile)}
                        disabled={isBusy}
                        className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] disabled:opacity-50"
                        aria-label={`清除 ${profile.name} 的 API Key`}
                        title="清除 API Key"
                      >
                        {busy === `clear:${profile.id}`
                          ? <Loader2 size={15} className="animate-spin" />
                          : <KeyRound size={16} strokeWidth={2} />}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void handleDelete(profile)}
                      disabled={isBusy}
                      className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] disabled:opacity-50"
                      aria-label={`删除 ${profile.name}`}
                      title="删除"
                    >
                      {busy === `delete:${profile.id}`
                        ? <Loader2 size={15} className="animate-spin" />
                        : <Trash2 size={16} strokeWidth={2} />}
                    </button>
                  </div>
                  {rowBusy && <span className="sr-only">处理中</span>}
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* 内联编辑器：避免为简单表单弹出模态框 */}
      {draft && (
        <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--accent)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
          <div className="flex min-w-0 items-center gap-3 border-b border-[var(--border-subtle)] px-4 py-3.5 sm:px-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
              {draft.id ? <Pencil size={17} strokeWidth={2} /> : <Plus size={18} strokeWidth={2.4} />}
            </span>
            <h2 className="t-title-m">{draft.id ? '编辑模型配置' : '新增模型配置'}</h2>
          </div>

          <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
              <SettingsField label="档案名称" hint="用于在列表中区分，例如「主力 · DeepSeek」">
                <input
                  className={fieldInputClass}
                  value={draft.name}
                  placeholder="主力模型"
                  onChange={event => setDraft({ ...draft, name: event.target.value })}
                  autoComplete="off"
                />
              </SettingsField>
              <SettingsField label="Base URL" hint="OpenAI 兼容端点，需包含 /v1 等路径前缀">
                <input
                  className={fieldInputClass}
                  value={draft.base_url}
                  placeholder="https://api.deepseek.com"
                  onChange={event => setDraft({ ...draft, base_url: event.target.value })}
                  autoComplete="off"
                  spellCheck={false}
                />
              </SettingsField>
            </div>

            <SettingsField label="模型名称" hint="可手动输入，或从端点拉取可用模型">
              <div className="flex min-w-0 gap-2">
                <input
                  className={`${fieldInputClass} flex-1`}
                  value={draft.model}
                  placeholder="deepseek-v4-pro"
                  onChange={event => setDraft({ ...draft, model: event.target.value })}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button
                  type="button"
                  onClick={() => setModelPickerOpen(open => !open)}
                  className="md3-btn-tonal lawver-pressable !min-h-11 shrink-0 !px-3.5 text-sm"
                  aria-expanded={modelPickerOpen}
                >
                  <ChevronDown size={16} strokeWidth={2} className={`transition-transform ${modelPickerOpen ? 'rotate-180' : ''}`} />
                  列表
                </button>
              </div>
            </SettingsField>

            {modelPickerOpen && (
              <div className="min-w-0 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)]">
                <div className="flex min-w-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-3 py-2">
                  <p className="min-w-0 truncate text-[12px] text-[var(--fg-3)]">
                    {models.length > 0
                      ? `当前生效端点返回 ${models.length} 个模型`
                      : '列表来自当前生效的端点与 Key'}
                  </p>
                  <button
                    type="button"
                    onClick={() => void refreshModels()}
                    disabled={busy === 'models'}
                    className="md3-btn-text lawver-pressable !min-h-9 !px-2.5 !text-[12px] disabled:opacity-50"
                  >
                    {busy === 'models'
                      ? <Loader2 size={13} className="animate-spin" />
                      : <RefreshCw size={13} strokeWidth={2} />}
                    拉取
                  </button>
                </div>
                {models.length > 0 && (
                  <ul className="md3-scroll max-h-56 divide-y divide-[var(--border-subtle)] overflow-y-auto">
                    {models.map(model => (
                      <li key={model.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setDraft({ ...draft, model: model.id });
                            setModelPickerOpen(false);
                          }}
                          className="lawver-pressable flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] text-[var(--fg-1)] transition-colors hover:bg-[var(--accent-quiet)]"
                        >
                          <span className="min-w-0 flex-1 truncate font-mono">{model.id}</span>
                          {model.owned_by && (
                            <span className="shrink-0 text-[11px] text-[var(--fg-4)]">{model.owned_by}</span>
                          )}
                          {draft.model === model.id && <Check size={15} strokeWidth={2.4} className="text-[var(--accent)]" />}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {draft.id && !showKeyField ? (
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2.5">
                <p className="min-w-0 text-[12px] text-[var(--fg-3)]">
                  API Key 保持不变；如需更换请点击右侧按钮。
                </p>
                <button
                  type="button"
                  onClick={() => setShowKeyField(true)}
                  className="md3-btn-text lawver-pressable !min-h-9 shrink-0 !px-3 !text-[12px]"
                >
                  <KeyRound size={13} strokeWidth={2} /> 更换 Key
                </button>
              </div>
            ) : (
              <SettingsField
                label="API Key"
                hint={draft.id ? '留空则不覆盖已保存的 Key' : '只保存在服务端 data/secrets.json，不会回传到前端'}
              >
                <input
                  className={fieldInputClass}
                  type="password"
                  value={draft.api_key}
                  placeholder="sk-..."
                  onChange={event => setDraft({ ...draft, api_key: event.target.value })}
                  autoComplete="new-password"
                />
              </SettingsField>
            )}

            {!draft.id && (
              <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[13px] text-[var(--fg-2)]">
                <input
                  type="checkbox"
                  checked={draft.activate}
                  onChange={event => setDraft({ ...draft, activate: event.target.checked })}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
                保存后立即切换使用
              </label>
            )}

            <div className="flex min-w-0 flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => setDraft(null)}
                disabled={busy === 'save'}
                className="md3-btn-text lawver-pressable text-sm disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={busy === 'save'}
                className="md3-btn-filled lawver-pressable text-sm disabled:opacity-50"
              >
                {busy === 'save' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2.4} />}
                {draft.id ? '保存修改' : '保存配置'}
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};
