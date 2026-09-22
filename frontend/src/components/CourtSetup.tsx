/*
 * 模块描述：模拟法庭创建页，分离公开案卷与用户私有作战笔记，引导用户开庭。
 */

import React, { useState } from 'react';
import { Gavel, Landmark, Lock, Scale, ShieldCheck, Sparkles } from 'lucide-react';
import { useTranslation } from '../contexts/LocaleContext';
import type { CourtCaseType, CourtSession } from '../types';

type Translate = ReturnType<typeof useTranslation>;

type CreateInput = {
  case_type: CourtCaseType;
  user_side: string;
  shared_dossier: CourtSession['shared_dossier'];
  private_brief: CourtSession['private_brief'];
};

interface CourtSetupProps {
  onCreate: (input: CreateInput) => void;
  onCancel?: () => void;
}

type SetupForm = {
  case_type: CourtCaseType;
  user_side: string;
  summary: string;
  claims: string;
  evidence: string;
  strategy: string;
  logic_chain: string;
  risk_notes: string;
};

// value 是传给服务端的立场标识，保持中文常量；仅 label / hint 随界面语言变化。
const buildCaseOptions = (t: Translate): Array<{ value: CourtCaseType; label: string; hint: string }> => [
  { value: 'civil', label: t('court.setup.case.civil'), hint: t('court.setup.case.civilHint') },
  { value: 'administrative', label: t('court.setup.case.administrative'), hint: t('court.setup.case.administrativeHint') },
  { value: 'criminal', label: t('court.setup.case.criminal'), hint: t('court.setup.case.criminalHint') }
];

const buildSideOptions = (t: Translate): Record<CourtCaseType, Array<{ value: string; label: string; hint: string }>> => ({
  civil: [
    { value: '原告', label: t('court.setup.side.plaintiff'), hint: t('court.setup.side.plaintiffHint') },
    { value: '被告', label: t('court.setup.side.defendant'), hint: t('court.setup.side.defendantHint') }
  ],
  administrative: [
    { value: '原告（行政相对人）', label: t('court.setup.side.administrativeRelative'), hint: t('court.setup.side.administrativeRelativeHint') },
    { value: '行政机关（被告）', label: t('court.setup.side.administrativeAgency'), hint: t('court.setup.side.administrativeAgencyHint') }
  ],
  criminal: [
    { value: '辩护方', label: t('court.setup.side.defense'), hint: t('court.setup.side.defenseHint') },
    { value: '公诉方', label: t('court.setup.side.prosecution'), hint: t('court.setup.side.prosecutionHint') }
  ]
});

const charCount = (value: string, t: Translate) => {
  const length = value.trim().length;
  return length > 0 ? t('court.setup.charCount', { count: length }) : t('court.setup.charCountEmpty');
};

const SetupField: React.FC<{
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  tone?: 'public' | 'private';
}> = ({ label, hint, value, onChange, rows = 4, tone = 'public' }) => {
  const t = useTranslation();
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-semibold text-[var(--fg-1)]">{label}</span>
        <span
          className={`text-[11px] ${
            tone === 'private' && value.trim()
              ? 'text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
              : 'text-[var(--fg-4)]'
          }`}
        >
          {charCount(value, t)}
        </span>
      </span>
      <textarea
        value={value}
        onChange={event => onChange(event.target.value)}
        rows={rows}
        placeholder={hint}
        className="custom-scrollbar w-full resize-none rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3.5 py-2.5 text-[14px] leading-6 text-[var(--fg-1)] outline-none transition-colors placeholder:text-[var(--fg-4)] focus:border-[var(--accent)] focus:shadow-[0_0_0_1px_var(--accent)]"
      />
    </label>
  );
};

export const CourtSetup: React.FC<CourtSetupProps> = ({ onCreate, onCancel }) => {
  const t = useTranslation();
  const [form, setForm] = useState<SetupForm>({
    case_type: 'civil',
    user_side: '原告',
    summary: '',
    claims: '',
    evidence: '',
    strategy: '',
    logic_chain: '',
    risk_notes: ''
  });

  const caseOptions = buildCaseOptions(t);
  const sideOptionsByCaseType = buildSideOptions(t);
  const sideOptions = sideOptionsByCaseType[form.case_type];
  const canCreate = [form.summary, form.claims, form.evidence].some(value => value.trim().length > 0);

  const setField = <K extends keyof SetupForm>(key: K, value: SetupForm[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const selectCaseType = (caseType: CourtCaseType) => {
    setForm(prev => ({
      ...prev,
      case_type: caseType,
      user_side: sideOptionsByCaseType[caseType][0].value
    }));
  };

  const handleSubmit = () => {
    if (!canCreate) return;
    onCreate({
      case_type: form.case_type,
      user_side: form.user_side.trim() || '用户方',
      shared_dossier: {
        summary: form.summary.trim(),
        claims: form.claims.trim(),
        evidence: form.evidence.trim()
      },
      private_brief: {
        strategy: form.strategy.trim(),
        logic_chain: form.logic_chain.trim(),
        risk_notes: form.risk_notes.trim()
      }
    });
  };

  return (
    <div className="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto bg-[var(--bg-app)]">
      <div className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-12">
        {/* 引导语 */}
        <div className="flex items-start gap-3 sm:gap-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--accent-quiet)] text-[var(--accent)] sm:h-12 sm:w-12">
            <Gavel size={22} strokeWidth={2} className="sm:size-6" />
          </span>
          <div className="min-w-0">
            <h1 className="t-headline-s">{t('court.setup.title')}</h1>
            <p className="mt-1.5 text-[14px] leading-6 text-[var(--fg-3)]">
              {t('court.setup.intro')}
            </p>
          </div>
        </div>

        {/* 案件类型 */}
        <section className="mt-8">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">{t('court.setup.caseType')}</h2>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {caseOptions.map(option => {
              const active = form.case_type === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => selectCaseType(option.value)}
                  className={`lawver-pressable flex flex-col items-center gap-1 rounded-[var(--radius-md)] border px-3 py-3 transition-colors ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent-quiet)]'
                      : 'border-[var(--border-default)] bg-[var(--bg-surface)] hover:border-[var(--border-strong)]'
                  }`}
                >
                  <span className={`text-[15px] font-semibold ${active ? 'text-[var(--accent)]' : 'text-[var(--fg-1)]'}`}>
                    {option.label}
                  </span>
                  <span className="text-[11px] text-[var(--fg-3)]">{option.hint}</span>
                </button>
              );
            })}
          </div>
        </section>

        {/* 用户立场 */}
        <section className="mt-6">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">{t('court.setup.side')}</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {sideOptions.map(option => {
              const active = form.user_side === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setField('user_side', option.value)}
                  className={`lawver-pressable flex items-center gap-3 rounded-[var(--radius-md)] border px-4 py-3 text-left transition-colors ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent-quiet)]'
                      : 'border-[var(--border-default)] bg-[var(--bg-surface)] hover:border-[var(--border-strong)]'
                  }`}
                >
                  <span
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                      active ? 'bg-[var(--accent)] text-[var(--accent-on)]' : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
                    }`}
                  >
                    <Scale size={17} strokeWidth={2} />
                  </span>
                  <span className="min-w-0">
                    <span className={`block text-[14px] font-semibold ${active ? 'text-[var(--accent)]' : 'text-[var(--fg-1)]'}`}>
                      {option.label}
                    </span>
                    <span className="block text-[12px] text-[var(--fg-3)]">{option.hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* 公开案卷 */}
        <section className="mt-6 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
              <Landmark size={18} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-[var(--fg-1)]">{t('court.setup.dossier.title')}</h2>
              <p className="text-[12px] leading-5 text-[var(--fg-3)]">{t('court.setup.dossier.hint')}</p>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            <SetupField
              label={t('court.setup.field.summary')}
              hint={t('court.setup.field.summaryHint')}
              value={form.summary}
              onChange={value => setField('summary', value)}
              rows={5}
            />
            <SetupField
              label={t('court.setup.field.claims')}
              hint={t('court.setup.field.claimsHint')}
              value={form.claims}
              onChange={value => setField('claims', value)}
            />
            <SetupField
              label={t('court.setup.field.evidence')}
              hint={t('court.setup.field.evidenceHint')}
              value={form.evidence}
              onChange={value => setField('evidence', value)}
            />
          </div>
        </section>

        {/* 私有作战笔记 */}
        <section className="mt-4 rounded-[var(--radius-lg)] border border-[rgba(44,118,112,0.22)] bg-[rgba(44,118,112,0.05)] p-4 sm:p-5">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[rgba(44,118,112,0.14)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
              <Lock size={17} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-[var(--fg-1)]">{t('court.setup.notes.title')}</h2>
              <p className="flex items-center gap-1.5 text-[12px] leading-5 text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
                <ShieldCheck size={13} strokeWidth={2} className="shrink-0" />
                {t('court.setup.notes.hint')}
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            <SetupField
              tone="private"
              label={t('court.setup.field.strategy')}
              hint={t('court.setup.field.strategyHint')}
              value={form.strategy}
              onChange={value => setField('strategy', value)}
              rows={4}
            />
            <SetupField
              tone="private"
              label={t('court.setup.field.logicChain')}
              hint={t('court.setup.field.logicChainHint')}
              value={form.logic_chain}
              onChange={value => setField('logic_chain', value)}
            />
            <SetupField
              tone="private"
              label={t('court.setup.field.riskNotes')}
              hint={t('court.setup.field.riskNotesHint')}
              value={form.risk_notes}
              onChange={value => setField('risk_notes', value)}
            />
          </div>
        </section>

        {/* 操作：吸底常驻。表单在移动端接近两屏高，主操作不能靠滚动去找；
            「未填写」提示同时移入操作栏——按钮禁用时正是最需要看到它的时刻。 */}
        <div className="sticky bottom-0 z-10 -mx-4 mt-7 border-t border-[var(--border-subtle)] bg-[var(--bg-app)] px-4 pb-[calc(0.75rem+var(--safe-bottom))] pt-3 sm:-mx-8 sm:px-8">
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
            <p className="flex items-center gap-1.5 text-[12px] text-[var(--fg-3)]">
              <Sparkles size={13} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
              {canCreate ? t('court.setup.ready') : t('court.setup.notReady')}
            </p>
            <div className="flex items-center justify-end gap-2">
              {onCancel && (
                <button onClick={onCancel} className="md3-btn-text lawver-pressable">
                  {t('court.setup.cancel')}
                </button>
              )}
              <button
                onClick={handleSubmit}
                disabled={!canCreate}
                className="md3-btn-filled lawver-pressable min-w-[7.5rem]"
              >
                <Gavel size={18} strokeWidth={2} />
                {t('court.setup.submit')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
