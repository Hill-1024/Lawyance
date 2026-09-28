/*
 * 模块描述：模拟法庭创建页，分离公开案卷与用户私有作战笔记，引导用户开庭。
 */

import { useAppDialog } from '../contexts/DialogContext';
import { CourtMaterials, CourtSource } from '../workbench/CourtMaterials';
import React, { useState } from 'react';
import { Gavel, Landmark, Lock, Scale, ShieldCheck, Sparkles } from 'lucide-react';
import type { CourtCaseType, CourtSession } from '../types';

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

export const CourtSetup: React.FC<CourtSetupProps> = ({ onCreate, onCancel, initialProject = "" }) => {
  const {showConfirm} = useAppDialog();
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
        logic_chain: [form.logic_chain.trim(), autoNotes ? "【同项目会话备庭资料 · 仅私有】\n" + autoNotes : ""].filter(Boolean).join("\n\n"),
        risk_notes: form.risk_notes.trim()
      }
    });
  };

  return <div className="court-setup court-setup-modern custom-scrollbar">
    <div className="court-setup-content">
      <header className="court-welcome"><span><Gavel size={22}/></span><div><h1>在这里，准备你的下一次出庭。</h1><p>整理案卷，选择立场，与法官和对方律师展开一场模拟对话。</p></div></header>
      <div className="court-role-config">
        <label>案件类型<select aria-label="案件类型" value={form.case_type} onChange={e=>selectCaseType(e.target.value as CourtCaseType)}>{CASE_OPTIONS.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
        <label>我的立场<select aria-label="我的立场" value={form.user_side} onChange={e=>setField('user_side',e.target.value)}>{sideOptions.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
      </div>
      <nav className="court-preparation-tabs" aria-label="庭审准备">
        <button aria-pressed={tab==='public'} onClick={()=>setTab('public')}><Landmark size={16}/>公开案卷</button>
        <button aria-pressed={tab==='private'} onClick={()=>setTab('private')}><Lock size={16}/>私有备庭</button>
        <button aria-pressed={tab==='sources'} onClick={()=>setTab('sources')}><Scale size={16}/>项目材料 <small>{sources.length}</small></button>
      </nav>
      <section className="court-preparation-pane" hidden={tab!=='public'}>
        <p className="court-scope-note">法官与对方律师均可阅读。请确认这里的事实和证据可以公开。</p>
        <SetupField label="案情与争议焦点" hint="案件经过、核心争议，以及需要法庭查明的事实…" value={form.summary} onChange={v=>setField('summary',v)} rows={5}/>
        <SetupField label="诉求 / 指控" hint="你希望获得什么裁判结果？" value={form.claims} onChange={v=>setField('claims',v)} rows={3}/>
        <SetupField label="公开证据线索" hint="列出已公开的证据，或从项目材料中选择加入。" value={form.evidence} onChange={v=>setField('evidence',v)} rows={3}/>
      </section>
      <section className="court-preparation-pane" hidden={tab!=='private'}>
        <p className="court-scope-note"><ShieldCheck size={16}/>仅供我方代理与复盘员使用，不向法官和对方提供。</p>
        <SetupField label="庭审策略" hint="你的应对方案与谈判空间" value={form.strategy} onChange={v=>setField('strategy',v)} rows={3}/>
        <SetupField label="证据链与推理路径" hint="核心论证与事实之间的联系" value={form.logic_chain} onChange={v=>setField('logic_chain',v)} rows={3}/>
        <SetupField label="担心的漏洞与突发情况" hint="希望在模拟中重点检验的薄弱环节" value={form.risk_notes} onChange={v=>setField('risk_notes',v)} rows={3}/>
        {autoNotes && <details className="court-auto-notes"><summary>已自动收集的私有备庭资料 · {sources.length} 个会话</summary><textarea aria-label="自动收集的私有备庭资料" value={autoNotes} onChange={e=>setAutoNotes(e.target.value)} rows={8}/></details>}
      </section>
      <div hidden={tab!=='sources'}>        <CourtMaterials onReady={setMaterialsReady} project={project} onProject={async id=>{if(Object.entries(form).some(([key,value])=>!['case_type','user_side'].includes(key)&&value.trim()) && !await showConfirm({title:'切换庭审项目？',message:'已填写的案卷和私有笔记将清空，重新收集新项目材料。',confirmLabel:'切换项目',cancelLabel:'继续编辑'}))return;setProject(id);setForm(prev=>({...prev,summary:'',claims:'',evidence:'',strategy:'',logic_chain:'',risk_notes:''}));}} onAuto={(text,sources)=>{setAutoNotes(text);setSources(sources);}} onSelect={text => setForm(prev => ({...prev, evidence: [prev.evidence, text].filter(Boolean).join("\n\n")}))} /></div>
    </div>
    <footer className="court-setup-actions"><span>{canCreate ? '准备就绪 · 创建后由你决定何时开始' : '填写至少一项公开案卷信息后即可创建'}</span><div>{onCancel && <button onClick={onCancel}>取消</button>}<button className="court-primary" disabled={!canCreate} onClick={handleSubmit}><Gavel size={16}/>创建庭审会话</button></div></footer>
  </div>;
};
