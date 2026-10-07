/*
 * 模块描述：模拟法庭创建页，分离公开案卷与用户私有作战笔记，引导用户开庭。
 */

import { useAppDialog } from '../contexts/DialogContext';
import { SelectField } from "../workbench/SelectField";
import { CourtMaterials, CourtSource } from '../workbench/CourtMaterials';
import React, { useState } from 'react';
import { Gavel, Landmark, Lock, Scale, ShieldCheck, Sparkles } from 'lucide-react';
import type { CourtCaseType, CourtSession } from '../types';
import { useT, type Translator } from '../i18n';

type CreateInput = {
  project_id?: string;
  source_snapshots?: CourtSession["source_snapshots"];
  case_type: CourtCaseType;
  user_side: string;
  shared_dossier: CourtSession['shared_dossier'];
  private_brief: CourtSession['private_brief'];
};

interface CourtSetupProps {
  onCreate: (input: CreateInput) => void;
  onCancel?: () => void;
  initialProject?: string;
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

const charCount = (value: string, t: Translator) => {
  const length = value.trim().length;
  return length > 0 ? t('courtSetup.charCountFilled', { count: length }) : t('courtSetup.charCountEmpty');
};

const SetupField: React.FC<{
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  tone?: 'public' | 'private';
}> = ({ label, hint, value, onChange, rows = 4, tone = 'public' }) => {
  const { t } = useT();
  return (
  <label className="flex min-w-0 flex-col gap-1.5">
    <span className="flex items-baseline justify-between gap-3">
      <span className="text-[13px] font-semibold text-[var(--fg-1)]">{label}</span>
      <span
        className={`text-[11px] ${
          tone === 'private' && value.trim()
            ? 'text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
            // 计数是功能性提示不是装饰：--fg-4 只有 2.5:1，提到 --fg-2 保证可读。
            : 'text-[var(--fg-2)]'
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

export const CourtSetup: React.FC<CourtSetupProps> = ({ onCreate, onCancel, initialProject = "" }) => {
  const {showConfirm} = useAppDialog();
  const { t } = useT();
  // 案件类型/立场的 value 会随创建请求发给后端，属于事实值，任何语言下都不变；只翻译标签与提示。
  const CASE_OPTIONS: Array<{ value: CourtCaseType; label: string; hint: string }> = [
    { value: 'civil', label: t('courtSetup.caseCivil'), hint: t('courtSetup.caseCivilHint') },
    { value: 'administrative', label: t('courtSetup.caseAdministrative'), hint: t('courtSetup.caseAdministrativeHint') },
    { value: 'criminal', label: t('courtSetup.caseCriminal'), hint: t('courtSetup.caseCriminalHint') },
  ];
  const SIDE_OPTIONS_BY_CASE_TYPE: Record<CourtCaseType, Array<{ value: string; label: string; hint: string }>> = {
    civil: [
      { value: '原告', label: t('courtSetup.sidePlaintiff'), hint: t('courtSetup.sidePlaintiffHint') },
      { value: '被告', label: t('courtSetup.sideDefendant'), hint: t('courtSetup.sideDefendantHint') },
    ],
    administrative: [
      { value: '原告（行政相对人）', label: t('courtSetup.sideCitizen'), hint: t('courtSetup.sideCitizenHint') },
      { value: '行政机关（被告）', label: t('courtSetup.sideAgency'), hint: t('courtSetup.sideAgencyHint') },
    ],
    criminal: [
      { value: '辩护方', label: t('courtSetup.sideDefense'), hint: t('courtSetup.sideDefenseHint') },
      { value: '公诉方', label: t('courtSetup.sideProsecution'), hint: t('courtSetup.sideProsecutionHint') },
    ],
  };
  const [tab,setTab] = useState<"public"|"private"|"sources">("public");
  const [project,setProject] = useState(initialProject);
  const [materialsReady,setMaterialsReady] = useState(!initialProject);
  const [autoNotes,setAutoNotes] = useState("");
  const [sources,setSources] = useState<CourtSource[]>([]);
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
  const canCreate = (!project || materialsReady) && [form.summary, form.claims, form.evidence].some(value => value.trim().length > 0);

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
      project_id: project || undefined,
      source_snapshots: sources.map(({text,...source})=>source),
      case_type: form.case_type,
      user_side: form.user_side.trim() || '用户方',
      shared_dossier: {
        summary: form.summary.trim(),
        claims: form.claims.trim(),
        evidence: form.evidence.trim()
      },
      private_brief: {
        strategy: form.strategy.trim(),
        logic_chain: [form.logic_chain.trim(), autoNotes ? t('courtSetup.autoNotesHeader') + "\n" + autoNotes : ""].filter(Boolean).join("\n\n"),
        risk_notes: form.risk_notes.trim()
      }
    });
  };

  return <div className="court-setup court-setup-modern custom-scrollbar">
    <div className="court-setup-content">
      <header className="court-welcome"><span><Gavel size={22}/></span><div><h1>{t('courtSetup.welcomeTitle')}</h1><p>{t('courtSetup.welcomeLead')}</p></div></header>
      <div className="court-role-config">
        <SelectField label={t('courtSetup.caseType')} value={form.case_type} options={CASE_OPTIONS} onChange={v=>selectCaseType(v as CourtCaseType)} />
        <SelectField label={t('courtSetup.mySide')} value={form.user_side} options={sideOptions} onChange={v=>setField('user_side',v)} />
      </div>
      <nav className="court-preparation-tabs" aria-label={t('courtSetup.preparation')}>
        <button aria-pressed={tab==='public'} onClick={()=>setTab('public')}><Landmark size={16}/>{t('workbench.court.publicDossier')}</button>
        <button aria-pressed={tab==='private'} onClick={()=>setTab('private')}><Lock size={16}/>{t('workbench.court.privateBrief')}</button>
        <button aria-pressed={tab==='sources'} onClick={()=>setTab('sources')}><Scale size={16}/>{t('courtSetup.projectMaterials')} <small>{sources.length}</small></button>
      </nav>
      <section className="court-preparation-pane" hidden={tab!=='public'}>
        <p className="court-scope-note">{t('courtSetup.publicScopeNote')}</p>
        <SetupField label={t('courtSetup.summaryLabel')} hint={t('courtSetup.summaryHint')} value={form.summary} onChange={v=>setField('summary',v)} rows={5}/>
        <SetupField label={t('courtSetup.claimsLabel')} hint={t('courtSetup.claimsHint')} value={form.claims} onChange={v=>setField('claims',v)} rows={3}/>
        <SetupField label={t('courtSetup.evidenceLabel')} hint={t('courtSetup.evidenceHint')} value={form.evidence} onChange={v=>setField('evidence',v)} rows={3}/>
      </section>
      <section className="court-preparation-pane" hidden={tab!=='private'}>
        <p className="court-scope-note"><ShieldCheck size={16}/>{t('courtSetup.privateScopeNote')}</p>
        <SetupField label={t('courtSetup.strategyLabel')} hint={t('courtSetup.strategyHint')} value={form.strategy} onChange={v=>setField('strategy',v)} rows={3}/>
        <SetupField label={t('courtSetup.logicLabel')} hint={t('courtSetup.logicHint')} value={form.logic_chain} onChange={v=>setField('logic_chain',v)} rows={3}/>
        <SetupField label={t('courtSetup.riskLabel')} hint={t('courtSetup.riskHint')} value={form.risk_notes} onChange={v=>setField('risk_notes',v)} rows={3}/>
        {autoNotes && <details className="court-auto-notes"><summary>{t('courtSetup.autoNotesSummary',{count:sources.length})}</summary><textarea aria-label={t('courtSetup.autoNotesLabel')} value={autoNotes} onChange={e=>setAutoNotes(e.target.value)} rows={8}/></details>}
      </section>
      <div hidden={tab!=='sources'}>        <CourtMaterials onReady={setMaterialsReady} project={project} onProject={async id=>{if(Object.entries(form).some(([key,value])=>!['case_type','user_side'].includes(key)&&value.trim()) && !await showConfirm({title:t('courtSetup.switchProjectTitle'),message:t('courtSetup.switchProjectMessage'),confirmLabel:t('courtSetup.switchProjectConfirm'),cancelLabel:t('courtSetup.switchProjectCancel')}))return;setProject(id);setForm(prev=>({...prev,summary:'',claims:'',evidence:'',strategy:'',logic_chain:'',risk_notes:''}));}} onAuto={(text,sources)=>{setAutoNotes(text);setSources(sources);}} onSelect={text => setForm(prev => ({...prev, evidence: [prev.evidence, text].filter(Boolean).join("\n\n")}))} /></div>
    </div>
    <footer className="court-setup-actions"><span>{canCreate ? t('courtSetup.readyNote') : t('courtSetup.needMoreNote')}</span><div>{onCancel && <button onClick={onCancel}>{t('common.cancel')}</button>}<button className="court-primary" disabled={!canCreate} onClick={handleSubmit}><Gavel size={16}/>{t('courtSetup.create')}</button></div></footer>
  </div>;
};
