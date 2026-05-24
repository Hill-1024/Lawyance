/*
 * 模块描述：模拟法庭创建页，分离公开案卷与用户私有作战笔记，引导用户开庭。
 */

import React, { useState } from 'react';
import { Gavel, Landmark, Lock, Scale, ShieldCheck, Sparkles } from 'lucide-react';
import type { CourtCaseType, CourtSession } from '../types';

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

const CASE_OPTIONS: Array<{ value: CourtCaseType; label: string; hint: string }> = [
  { value: 'civil', label: '民事', hint: '原告 / 被告' },
  { value: 'administrative', label: '行政', hint: '相对人 / 行政机关' },
  { value: 'criminal', label: '刑事', hint: '公诉 / 辩护' }
];

const SIDE_OPTIONS_BY_CASE_TYPE: Record<CourtCaseType, Array<{ value: string; label: string; hint: string }>> = {
  civil: [
    { value: '原告', label: '原告', hint: '提出诉讼请求' },
    { value: '被告', label: '被告', hint: '抗辩并反驳请求' }
  ],
  administrative: [
    { value: '原告（行政相对人）', label: '行政相对人', hint: '起诉行政行为一方' },
    { value: '行政机关（被告）', label: '行政机关', hint: '被诉机关一方' }
  ],
  criminal: [
    { value: '辩护方', label: '辩护方', hint: '为被告人辩护' },
    { value: '公诉方', label: '公诉方', hint: '指控与举证一方' }
  ]
};

const charCount = (value: string) => {
  const length = value.trim().length;
  return length > 0 ? `${length} 字` : '未填写';
};

const SetupField: React.FC<{
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  tone?: 'public' | 'private';
}> = ({ label, hint, value, onChange, rows = 4, tone = 'public' }) => (
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
        {charCount(value)}
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

export const CourtSetup: React.FC<CourtSetupProps> = ({ onCreate, onCancel }) => {
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

  const sideOptions = SIDE_OPTIONS_BY_CASE_TYPE[form.case_type];
  const canCreate = [form.summary, form.claims, form.evidence].some(value => value.trim().length > 0);

  const setField = <K extends keyof SetupForm>(key: K, value: SetupForm[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const selectCaseType = (caseType: CourtCaseType) => {
    setForm(prev => ({
      ...prev,
      case_type: caseType,
      user_side: SIDE_OPTIONS_BY_CASE_TYPE[caseType][0].value
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
      <div className="mx-auto w-full max-w-2xl px-5 py-8 sm:px-8 sm:py-12">
        {/* 引导语 */}
        <div className="flex items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--accent-quiet)] text-[var(--accent)]">
            <Gavel size={24} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h1 className="t-headline-s">开启一场模拟法庭</h1>
            <p className="mt-1.5 text-[14px] leading-6 text-[var(--fg-3)]">
              你出庭代理一方，法官与对方律师由相互独立、记忆隔离的 AI 出演。一场完整庭审会压力测试你的论证链，提前暴露漏洞与庭上突发情况。
            </p>
          </div>
        </div>

        {/* 案件类型 */}
        <section className="mt-8">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">案件类型</h2>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {CASE_OPTIONS.map(option => {
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
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">你出庭代理</h2>
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
        <section className="mt-6 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-1)]">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
              <Landmark size={18} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-[var(--fg-1)]">公开案卷</h2>
              <p className="text-[12px] leading-5 text-[var(--fg-3)]">法官与对方律师都会读到这部分——只写双方都已知的事实。</p>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            <SetupField
              label="案情与争议焦点"
              hint="简述案件事实经过、双方争议的核心问题"
              value={form.summary}
              onChange={value => setField('summary', value)}
              rows={5}
            />
            <SetupField
              label="诉求 / 指控"
              hint="原告诉讼请求、公诉指控或被诉行政行为"
              value={form.claims}
              onChange={value => setField('claims', value)}
            />
            <SetupField
              label="公开证据线索"
              hint="已进入庭审、双方都知道的证据与材料"
              value={form.evidence}
              onChange={value => setField('evidence', value)}
            />
          </div>
        </section>

        {/* 私有作战笔记 */}
        <section className="mt-4 rounded-[var(--radius-lg)] border border-[rgba(44,118,112,0.22)] bg-[rgba(44,118,112,0.05)] p-5">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[rgba(44,118,112,0.14)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
              <Lock size={17} strokeWidth={2} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-[var(--fg-1)]">你的作战笔记</h2>
              <p className="flex items-center gap-1.5 text-[12px] leading-5 text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
                <ShieldCheck size={13} strokeWidth={2} className="shrink-0" />
                仅你与复盘员可见 · 法官和对方律师永远看不到
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            <SetupField
              tone="private"
              label="庭审策略"
              hint="你打算怎么打这场庭、想达成什么"
              value={form.strategy}
              onChange={value => setField('strategy', value)}
              rows={4}
            />
            <SetupField
              tone="private"
              label="证据链与推理路径"
              hint="你的核心论证链条、想让法庭采信的逻辑"
              value={form.logic_chain}
              onChange={value => setField('logic_chain', value)}
            />
            <SetupField
              tone="private"
              label="担心的漏洞与突发情况"
              hint="你自己也没把握的环节，复盘员会重点检验"
              value={form.risk_notes}
              onChange={value => setField('risk_notes', value)}
            />
          </div>
        </section>

        {/* 操作 */}
        <div className="mt-7 flex items-center justify-between gap-3">
          <p className="flex items-center gap-1.5 text-[12px] text-[var(--fg-3)]">
            <Sparkles size={13} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
            默认中国法语境
          </p>
          <div className="flex items-center gap-2">
            {onCancel && (
              <button onClick={onCancel} className="md3-btn-text lawver-pressable">
                取消
              </button>
            )}
            <button
              onClick={handleSubmit}
              disabled={!canCreate}
              className="md3-btn-filled lawver-pressable"
            >
              <Gavel size={18} strokeWidth={2} />
              开庭
            </button>
          </div>
        </div>
        {!canCreate && (
          <p className="mt-2 text-right text-[12px] text-[var(--fg-4)]">请至少填写一项公开案卷信息</p>
        )}
      </div>
    </div>
  );
};
