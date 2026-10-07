/*
 * 模块描述：大模型配置档案管理，支持保存多套模型端点并一键热切换到运行时。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckBox } from '../CheckBox';
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
import { useSettingsEdit } from './SettingsEditContext';
import { useAppDialog } from '../../contexts/DialogContext';
import { useT } from '../../i18n';
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
  const { t } = useT();
  const { showAlert, showConfirm } = useAppDialog();
  const reportEdit = useSettingsEdit();
  const [feedback, setFeedback] = useState('');
  const [state, setState] = useState<LlmProfileState | null>(null);
  const [loadError, setLoadError] = useState('');
  const [draft, setDraft] = useState<DraftState | null>(null);
  useEffect(() => {reportEdit('models', draft !== null);}, [draft, reportEdit]);
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
      setLoadError((error as Error).message || t('admin.llmLoadFailed'));
    }
  }, [t]);

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
          title: t('admin.llmModelsEmptyTitle'),
          message: t('admin.llmModelsEmptyMessage'),
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
      await showAlert({ title: t('admin.llmNameRequiredTitle'), message: t('admin.llmNameRequiredMessage'), tone: 'warning' });
      return;
    }
    if (!draft.base_url.trim()) {
      await showAlert({ title: t('admin.llmBaseUrlRequiredTitle'), message: t('admin.llmBaseUrlRequiredMessage'), tone: 'warning' });
      return;
    }
    if (!draft.model.trim()) {
      await showAlert({ title: t('admin.llmModelRequiredTitle'), message: t('admin.llmModelRequiredMessage'), tone: 'warning' });
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
      setFeedback(activated
        ? t('admin.llmSavedActivated', { name })
        : t('admin.llmSavedInactive', { name }));
      void load();
    } catch (error) {
      await showAlert({ title: t('admin.llmSaveFailedTitle'), message: (error as Error).message, tone: 'danger' });
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
      setFeedback(t('admin.llmActivateNotice', { name: profile.name, model: profile.model }));
    } catch (error) {
      await showAlert({ title: t('admin.llmActivateFailedTitle'), message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleDelete = async (profile: LlmProfile) => {
    const confirmed = await showConfirm({
      title: t('admin.llmDeleteConfirmTitle', { name: profile.name }),
      message: t('admin.llmDeleteConfirmMessage'),
      tone: 'danger',
      confirmLabel: t('admin.deleteAction'),
    });
    if (!confirmed) return;
    setBusy(`delete:${profile.id}`);
    try {
      const next = await deleteLlmProfile(profile.id);
      setState(next);
    } catch (error) {
      await showAlert({ title: t('admin.llmDeleteFailedTitle'), message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleClearKey = async (profile: LlmProfile) => {
    const confirmed = await showConfirm({
      title: t('admin.llmClearKeyTitle'),
      message: t('admin.llmClearKeyMessage'),
      tone: 'danger',
      confirmLabel: t('admin.llmClearKeyConfirm'),
    });
    if (!confirmed) return;
    setBusy(`clear:${profile.id}`);
    try {
      await clearLlmProfileSecret(profile.id);
      await load();
    } catch (error) {
      await showAlert({ title: t('admin.llmClearKeyFailedTitle'), message: (error as Error).message, tone: 'danger' });
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
      await showAlert({ title: t('admin.llmSaveFailedTitle'), message: (error as Error).message, tone: 'danger' });
    } finally {
      setBusy('');
    }
  };

  const handleTest = async () => {
    setBusy('test');
    try {
      const result = await testProvider('llm');
      await showAlert({
        title: t('admin.llmTestOkTitle'),
        message: t('admin.llmTestOkMessage', { message: result.message }),
        tone: 'success',
      });
    } catch (error) {
      await showAlert({ title: t('admin.llmTestFailTitle'), message: (error as Error).message, tone: 'danger' });
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
          <RefreshCw size={16} strokeWidth={2} /> {t('admin.llmRetry')}
        </button>
      </div>
    );
  }

  if (!state) {
    return <CenteredSpinner label={t('admin.llmLoading')} />;
  }

  const isBusy = busy !== '';

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {feedback && <div role="status"><Banner tone="success">{feedback}</Banner></div>}
      {/* 当前生效配置 */}
      <section className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-2)]">
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
          <div className="flex min-w-0 gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-on)]">
              <Zap size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="t-title-m">{t('admin.llmActiveModelTitle')}</h2>
                <StatusChip tone={enabled ? 'ok' : 'muted'}>
                  {enabled ? t('admin.llmEnabled') : t('admin.llmDisabled')}
                </StatusChip>
              </div>
              <p className="mt-1 break-all font-mono text-[13px] leading-5 text-[var(--fg-1)]">
                {state.effective.model || t('admin.llmNoModel')}
              </p>
              <p className="mt-0.5 break-all text-[12px] leading-5 text-[var(--fg-3)]">
                {state.effective.source || t('admin.llmEnvDefault')}
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
              {enabled ? t('admin.llmDisableAction') : t('admin.llmEnableAction')}
            </button>
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={isBusy}
              className="md3-btn-tonal lawver-pressable !min-h-11 text-sm disabled:opacity-50"
            >
              {busy === 'test' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2} />}
              {t('admin.llmTestAction')}
            </button>
          </div>
        </div>
        <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-2.5 sm:px-5">
          <p className="text-[12px] leading-5 text-[var(--fg-3)]">
            {t('admin.llmHotSwitchNoteLead')}<strong className="font-medium text-[var(--fg-2)]">{t('admin.llmHotSwitchNoteStrong')}</strong>{t('admin.llmHotSwitchNoteTail')}
          </p>
        </div>
      </section>

      {/* 档案列表 */}
      <section className="min-w-0">
        <div className="mb-2 flex min-w-0 items-end justify-between gap-3 px-1">
          <div className="min-w-0">
            <h2 className="t-label-m font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">
              {t('admin.llmSavedListTitle', { count: state.profiles.length })}
            </h2>
            <p className="mt-1 text-[12px] leading-5 text-[var(--fg-3)]">
              {t('admin.llmSavedListLead')}
            </p>
          </div>
          <button
            type="button"
            onClick={openCreate}
            disabled={isBusy || draft !== null}
            className="md3-btn-filled lawver-pressable !min-h-11 shrink-0 text-sm disabled:opacity-50"
          >
            <Plus size={16} strokeWidth={2.4} /> {t('admin.llmCreateAction')}
          </button>
        </div>

        <div className="min-w-0 divide-y divide-[var(--border-subtle)] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
          {state.profiles.length === 0 ? (
            <EmptyState
              icon={<Sparkles size={22} strokeWidth={2} />}
              title={t("settings.llmProfile.emptyTitle")}
              description={t("settings.llmProfile.emptyDescription")}
              action={(
                <button type="button" onClick={openCreate} className="md3-btn-tonal lawver-pressable text-sm">
                  <Plus size={16} strokeWidth={2.4} /> {t('admin.llmCreateAction')}
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
                      {profile.active && <StatusChip tone="accent">{t('admin.llmInUse')}</StatusChip>}
                      {profile.incomplete && <StatusChip tone="warn">{t('admin.llmIncomplete')}</StatusChip>}
                      {!profile.has_api_key && <StatusChip tone="warn">{t('admin.llmMissingKey')}</StatusChip>}
                      {!profile.enabled && <StatusChip tone="muted">{t('admin.llmDisabled')}</StatusChip>}
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[12px] text-[var(--fg-2)]">
                      {profile.model || t('admin.llmNoModelPlaceholder')}
                    </p>
                    <p className="truncate text-[11px] text-[var(--fg-4)]">
                      {hostOf(profile.base_url) || t('admin.llmNoBaseUrlPlaceholder')}
                    </p>
                    {profile.incomplete && (
                      <p className="mt-1 text-[11px] leading-4 text-[var(--color-warning-500)]">
                        {t('admin.llmIncompleteLead')}
                        {!profile.base_url ? t('admin.llmIncompleteBaseUrl') : ''}
                        {!profile.model ? t('admin.llmIncompleteModel') : ''}
                        {t('admin.llmIncompleteMid')}
                        {state.effective.source
                          ? t('admin.llmIncompleteSource', { source: state.effective.source })
                          : t('admin.llmIncompleteEnv')}
                        {t('admin.llmIncompleteTail')}
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
                        {t('admin.llmActivateButton')}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => openEdit(profile)}
                      disabled={isBusy}
                      className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] disabled:opacity-50"
                      aria-label={t("settings.llmProfile.editNamed", { name: profile.name })}
                      title={t("workbench.manage.edit")}
                    >
                      <Pencil size={16} strokeWidth={2} />
                    </button>
                    {profile.has_api_key && (
                      <button
                        type="button"
                        onClick={() => void handleClearKey(profile)}
                        disabled={isBusy}
                        className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] disabled:opacity-50"
                        aria-label={t("settings.llmProfile.clearKeyNamed", { name: profile.name })}
                        title={t("settings.llmProfile.clearKeyTitle")}
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
                      aria-label={t("settings.llmProfile.deleteNamed", { name: profile.name })}
                      title={t("settings.llmProfile.deleteTitle")}
                    >
                      {busy === `delete:${profile.id}`
                        ? <Loader2 size={15} className="animate-spin" />
                        : <Trash2 size={16} strokeWidth={2} />}
                    </button>
                  </div>
                  {rowBusy && <span className="sr-only">{t("settings.llmProfile.processing")}</span>}
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
            <h2 className="t-title-m">{draft.id ? t('admin.llmEditTitle') : t('admin.llmCreateTitle')}</h2>
          </div>

          <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
              <SettingsField label={t('admin.llmFieldName')} hint={t('admin.llmFieldNameHint')}>
                <input
                  className={fieldInputClass}
                  value={draft.name}
                  placeholder={t('admin.llmFieldNamePlaceholder')}
                  onChange={event => setDraft(prev => (prev ? { ...prev, name: event.target.value } : prev))}
                  autoComplete="off"
                />
              </SettingsField>
              <SettingsField label="Base URL" hint={t('admin.llmFieldBaseUrlHint')}>
                <input
                  className={fieldInputClass}
                  value={draft.base_url}
                  placeholder="https://api.deepseek.com"
                  onChange={event => setDraft(prev => (prev ? { ...prev, base_url: event.target.value } : prev))}
                  autoComplete="off"
                  spellCheck={false}
                />
              </SettingsField>
            </div>

            <SettingsField label={t('admin.llmFieldModel')} hint={t('admin.llmFieldModelHint')}>
              <div className="flex min-w-0 gap-2">
                <input
                  className={`${fieldInputClass} flex-1`}
                  value={draft.model}
                  placeholder="deepseek-v4-pro"
                  onChange={event => setDraft(prev => (prev ? { ...prev, model: event.target.value } : prev))}
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
                  {t('admin.llmModelListAction')}
                </button>
              </div>
            </SettingsField>

            {modelPickerOpen && (
              <div className="min-w-0 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)]">
                <div className="flex min-w-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-3 py-2">
                  <p className="min-w-0 truncate text-[12px] text-[var(--fg-3)]">
                    {models.length > 0
                      ? t('admin.llmModelCount', { count: models.length })
                      : t('admin.llmModelListSource')}
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
                    {t('admin.llmFetchAction')}
                  </button>
                </div>
                {models.length > 0 && (
                  <ul className="md3-scroll max-h-56 divide-y divide-[var(--border-subtle)] overflow-y-auto">
                    {models.map(model => (
                      <li key={model.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setDraft(prev => (prev ? { ...prev, model: model.id } : prev));
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
                  {t('admin.llmKeyUnchanged')}
                </p>
                <button
                  type="button"
                  onClick={() => setShowKeyField(true)}
                  className="md3-btn-text lawver-pressable !min-h-9 shrink-0 !px-3 !text-[12px]"
                >
                  <KeyRound size={13} strokeWidth={2} /> {t('admin.llmChangeKey')}
                </button>
              </div>
            ) : (
              <SettingsField
                label={t('admin.llmFieldApiKey')}
                hint={draft.id ? t('admin.llmApiKeyEditHint') : t('admin.llmApiKeyCreateHint')}
              >
                <input
                  className={fieldInputClass}
                  type="password"
                  value={draft.api_key}
                  placeholder="sk-..."
                  onChange={event => setDraft(prev => (prev ? { ...prev, api_key: event.target.value } : prev))}
                  autoComplete="new-password"
                />
              </SettingsField>
            )}

            {!draft.id && (
              <CheckBox
                className="min-h-11 gap-2.5 text-[13px] text-[var(--fg-2)]"
                label={t('admin.llmActivateOnSave')}
                checked={draft.activate}
                onCheckedChange={checked => setDraft(prev => (prev ? { ...prev, activate: checked } : prev))}
              />
            )}

            <div className="flex min-w-0 flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => setDraft(null)}
                disabled={busy === 'save'}
                className="md3-btn-text lawver-pressable text-sm disabled:opacity-50"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={busy === 'save'}
                className="md3-btn-filled lawver-pressable text-sm disabled:opacity-50"
              >
                {busy === 'save' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} strokeWidth={2.4} />}
                {draft.id ? t('admin.llmSaveEdit') : t('admin.llmSaveCreate')}
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};
