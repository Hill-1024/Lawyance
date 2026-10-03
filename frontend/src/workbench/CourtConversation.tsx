import React, { useEffect, useRef, useState } from 'react';
import { Gavel, Scale, UserRound, BookOpen, ChevronRight, X, Play, Send, Paperclip, SlidersHorizontal, GitBranch, Undo2, CircleAlert, Lock, FileText, Download } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Markdown } from './markdown';
import { useCourtSession } from '../hooks/useCourtSession';
import { useWorkspace } from '../hooks/useWorkspace';
import { useAutoGrowTextarea } from '../hooks/useAutoGrowTextarea';
import { useAppDialog } from '../contexts/DialogContext';
import { buildAttachmentPrompt, stripAttachmentPrompt, stripWorkspacePaths } from '../lib/attachment-prompt';
import { CourtSetup } from '../components/CourtSetup';
import { AnimatedSwitch } from '../components/AnimatedSwitch';
import { WorkflowStatusIcon } from '../components/WorkflowStatusIcon';
import { Reference } from './client';
import { useT } from '../i18n';
import { getBinding, matchKeys, SHORTCUT_IDS } from '../lib/shortcuts';
import './court-conversation.css';
import '../components/court-workspace.css';

export default function CourtConversation({project,selection,onSelect,onCancel,documentReference,onClearReference,dragHandle,onCollapse}: {
  dragHandle?:React.ReactNode; onCollapse?:()=>void;
  project?:string; selection:string; onSelect:(id:string,project?:string)=>void; onCancel:()=>void;
  documentReference?:Reference; onClearReference:()=>void;
}) {
  const court = useCourtSession(true);
  const {currentCourtSession:session,currentCourtId,isInitialized,isRunning} = court;
  const files=useWorkspace(currentCourtId,Boolean(currentCourtId));
  const [dossier,setDossier]=useState<'public'|'private'|null>(null);
  const [options,setOptions]=useState(false),[error,setError]=useState('');
  const reduceMotion=useReducedMotion();
  const {showConfirm}=useAppDialog();
  const {t}=useT();
  // 阶段与角色名随语言切换：放在组件里用 t() 取，模块级常量会停在首次加载的语言。
  const phases: Record<string,string> = {opening:t('workbench.court.phaseOpening'),claim_statement:t('workbench.court.phaseClaim'),prosecution_statement:t('workbench.court.phaseProsecution'),defense_response:t('workbench.court.phaseDefense'),agency_response:t('workbench.court.phaseAgency'),court_inquiry:t('workbench.court.phaseInquiry'),legality_review:t('workbench.court.phaseLegality'),evidence_cross:t('workbench.court.phaseEvidence'),court_debate:t('workbench.court.phaseDebate'),final_statement:t('workbench.court.phaseFinal'),judge_summary:t('workbench.court.phaseSummary'),review:t('workbench.court.phaseReview')};
  const roles = {judge:{label:t('workbench.court.roleJudge'),Icon:Gavel},opponent:{label:t('workbench.court.roleOpponent'),Icon:Scale},reviewer:{label:t('workbench.court.roleReviewer'),Icon:BookOpen},user:{label:t('workbench.court.roleUser'),Icon:UserRound},system:{label:t('workbench.court.roleSystem'),Icon:FileText}};
  const dossierPanel=useRef<HTMLElement>(null);
  // 只在卷宗面板「打开/关闭」时管理焦点；在公开/私密两页之间切换不算重新打开。
  const dossierOpen=dossier!==null;
  useEffect(()=>{if(!dossierOpen)return;const previous=document.activeElement as HTMLElement|null;dossierPanel.current?.querySelector<HTMLButtonElement>('button')?.focus();return()=>{if(previous?.isConnected)previous.focus();};},[dossierOpen]);
  const input=useRef<HTMLInputElement>(null),scroll=useRef<HTMLDivElement>(null),stick=useRef(true);
  const {ref:textarea}=useAutoGrowTextarea(court.composerText);
  const {courtSessions,setCurrentCourtId}=court;
  useEffect(()=>{
    if(isInitialized && selection!=='new' && courtSessions.some(s=>s.id===selection && (!project || s.project_id===project))) setCurrentCourtId(selection);
  },[isInitialized,selection,project,courtSessions,setCurrentCourtId]);
  useEffect(()=>{if(stick.current && scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight;},[session?.public_events,isRunning]);
  const creating=selection==='new';
  async function upload(list:FileList|null) {
    setError('');
    const results=await Promise.allSettled(Array.from(list||[]).map(f=>files.handleFileUpload(f)));
    const failed=results.filter(r=>r.status==='rejected');
    if(failed.length)setError(t('workbench.court.uploadFailed',{count:failed.length}));
    if(input.current)input.current.value='';
  }
  function send() {
    if(!session || session.court_state.trial_over || files.isUploadingFiles)return;
    const quote=documentReference?.text ? `${t('workbench.court.publicQuote',{title:documentReference.title || t('workbench.court.documentFragment'),revision:documentReference.revision})}\n${documentReference.text}` : '';
    const text=[court.composerText.trim(),quote,buildAttachmentPrompt(files.pendingUploads)].filter(Boolean).join('\n\n');
    if(!text)return;
    court.sendUserSpeech(text);files.setPendingUploads([]);onClearReference();
  }
  if(!isInitialized)return <div className="wc-loading" role="status"><WorkflowStatusIcon status="running"/>{t('workbench.court.opening')}</div>;
  if(creating)return <CourtSetup key={project || 'personal'} initialProject={project} onCreate={value=>onSelect(court.createCourtSession(value),value.project_id)} onCancel={onCancel}/>;
  if(!session || session.id!==selection || (project && session.project_id!==project))return <div className="wc-loading">{t('workbench.court.notFound')}<button onClick={onCancel}>{t('workbench.court.backToProject')}</button></div>;
  const state=session.court_state,events=session.public_events,started=events.some(e=>e.speaker!=='system');
  const hasError=Object.values(session.agent_states).some(agent=>agent.status==='error');
  const status=state.trial_over?t('workbench.court.trialOver'):isRunning?court.status || t('workbench.court.preparing'):hasError?court.status || t('workbench.court.turnError'):!started?t('workbench.court.readyToStart'):state.awaiting_user?t('workbench.court.waitingSide',{side:session.user_side}):t('workbench.court.turnDone');
  return <div className="wc-conversation">
    <header className="wc-heading">{dragHandle}<div><h2>{session.title}</h2></div>{/* 可见文字就是可访问名，所以这里**不能**再给 aria-label：全局那条
        「.wb-app button[aria-label]:has(> .lucide:only-child) 统一 32px」会把带文字的按钮也压成
        32px，内容居中溢出，图标戳出按钮左缘、文字溢出右缘。补充说明放 title。 */}
    <button title={t('workbench.court.viewDossierLabel')} aria-pressed={!!dossier} onClick={()=>setDossier(dossier?null:'public')}><BookOpen size={17}/>{t('workbench.court.dossierButton')}</button>{onCollapse&&<button className="wc-collapse wb-desktop-only" aria-label={t('workbench.court.collapse')} onClick={onCollapse}><X size={16}/></button>}</header>
    <div className="wc-stage"><span><Gavel size={15}/>{phases[state.phase]||state.phase}</span><ChevronRight size={13}/><span>{t('workbench.court.perspective',{side:session.user_side})}</span><small>{court.syncError?t('workbench.court.unsynced'):court.isSaving?t('workbench.court.saving'):t('workbench.court.saved')}</small></div>
    {(error||court.syncError)&&<div role="alert" className="wc-error">{error||court.syncError}{court.syncError&&<button onClick={()=>{const blob=new Blob([JSON.stringify({court_sessions:[...court.recoverySessions,...court.courtSessions]})],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='court-recovery.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}><Download size={14}/>{t('workbench.court.exportRecovery')}</button>}</div>}
    <div className="wc-flow" ref={scroll} onScroll={e=>{const el=e.currentTarget;stick.current=el.scrollHeight-el.scrollTop-el.clientHeight<140;}}>
      <div className="wc-material-summary"><FileText size={17}/><div><strong>{t('workbench.court.materialsTitle')}</strong><p>{session.shared_dossier.summary || session.shared_dossier.claims || t('workbench.court.dossierFallback')}</p><button onClick={()=>setDossier('public')}>{t('workbench.court.viewDossier')}<ChevronRight size={13}/></button></div></div>
      {!started && <div className="wc-empty"><h3>{t('workbench.court.emptyTitle')}</h3><p>{t('workbench.court.emptyLead')}</p><button className="wc-primary" disabled={isRunning} onClick={court.runNextTurn}><Play size={15}/>{t('workbench.court.start')}</button></div>}
      {events.filter(e=>e.speaker!=='system').map((event,index,visible)=>{const role=roles[event.speaker]||roles.system;const Icon=role.Icon;return <article className={'wc-message '+(event.speaker==='user'?'is-user':'')} key={event.id}>
        <header><Icon size={17}/><strong>{event.speaker==='user'?session.user_side:role.label}</strong><span>{phases[event.phase]||event.phase}</span></header>
        <div className="wc-message-content"><Markdown>{stripWorkspacePaths(stripAttachmentPrompt(event.content||''))}</Markdown></div>
        {!isRunning&&<footer><button aria-label={t('workbench.court.branchFrom')} onClick={()=>{const id=court.branchFromEvent(session.id,event.id);if(id)onSelect(id,session.project_id);}}><GitBranch size={14}/></button>{index<visible.length-1&&<button aria-label={t('workbench.court.rewindTo')} onClick={async()=>{if(await showConfirm({title:t('workbench.court.rewindConfirm'),message:t('workbench.court.rewindMessage'),confirmLabel:t('workbench.court.rewindAction'),tone:'danger'}))court.rewindToEvent(session.id,event.id);}}><Undo2 size={14}/></button>}</footer>}
      </article>})}
      <div className="wc-status" role="status">{hasError && !isRunning ? <CircleAlert size={14}/> : <WorkflowStatusIcon key={isRunning?'running':'done'} status={isRunning?'running':'done'}/ >}{status}</div>
    </div>
    <footer className="wc-composer-dock">
      <div className="wc-reference-row">{documentReference&&<span><FileText size={14}/>{documentReference.title || t('workbench.court.documentFragment')}<button aria-label={t('workbench.court.removeReference')} onClick={onClearReference}><X size={12}/></button></span>}{files.pendingUploads.map((f,i)=><span key={f.path||i}>{f.kind==='image'&&f.previewUrl?<img className="wc-reference-thumb" src={f.previewUrl} alt={f.name}/>:<Paperclip size={13}/>}{f.name}<button aria-label={t('workbench.court.removeUpload',{name:f.name})} onClick={()=>files.removeUploadedFile(i)}><X size={12}/></button></span>)}</div>
      <div className="wc-composer"><textarea ref={textarea} aria-label={t('workbench.court.speechLabel')} placeholder={state.trial_over?t('workbench.court.speechEnded'):t('workbench.court.speechPlaceholder')} value={court.composerText} disabled={state.trial_over} onChange={e=>court.setComposerText(e.target.value)} onKeyDown={e=>{if(!e.nativeEvent.isComposing && matchKeys(e,getBinding(SHORTCUT_IDS.courtSend))){e.preventDefault();send();}}}/>
        <div className="wc-composer-tools"><button aria-label={t('workbench.court.uploadPublic')} disabled={files.isUploadingFiles||state.trial_over} onClick={()=>input.current?.click()}><Paperclip size={18}/></button><button aria-label={t('workbench.court.options')} aria-expanded={options} onClick={()=>setOptions(!options)}><SlidersHorizontal size={17}/></button><small>{files.isUploadingFiles?t('workbench.court.uploading'):isRunning?t('workbench.court.running'):t('workbench.court.willBePublic')}</small><button className="wc-send" aria-label={t('workbench.court.sendSpeech')} disabled={state.trial_over||files.isUploadingFiles||(!court.composerText.trim()&&!documentReference?.text&&!files.pendingUploads.length)} onClick={send}><Send size={17}/></button></div>
      </div>
      <AnimatePresence>{options&&<motion.div className="wc-options" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} transition={{duration:reduceMotion?0:.16}}><AnimatedSwitch size="sm" label={t('workbench.court.autoAdvance')} checked={session.auto_mode} disabled={state.trial_over} onCheckedChange={court.setAutoMode}/><AnimatedSwitch size="sm" label={t('workbench.court.userAgent')} checked={!!state.user_agent_enabled} disabled={state.trial_over} onCheckedChange={court.setUserAgentMode}/><button disabled={isRunning||state.trial_over} onClick={()=>{court.forceAdvance();court.runNextTurn();}}>{t('workbench.court.advance')}<ChevronRight size={14}/></button></motion.div>}</AnimatePresence>
      <div className="wc-continuation"><span><Lock size={12}/>{t('workbench.court.independentMemory')}</span>{started&&!state.trial_over&&!session.auto_mode&&<button disabled={isRunning||(state.awaiting_user&&!state.user_agent_enabled)} onClick={court.runNextTurn}><Play size={13}/>{started?t('workbench.court.continueRound'):t('workbench.court.start')}</button>}</div>
    </footer>
    <AnimatePresence>{dossier&&<motion.div className="wc-dossier-overlay" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduceMotion?0:.16}} onClick={e=>{if(e.target===e.currentTarget)setDossier(null);}}><section ref={dossierPanel} className="wc-dossier" onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setDossier(null);}if(e.key==='Tab'){const controls=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,textarea,select'));const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}} role="dialog" aria-label={t('workbench.court.dossierLabel')} aria-modal="true"><header><h3>{t('workbench.court.dossierLabel')}</h3><button aria-label={t('workbench.court.closeDossier')} onClick={()=>setDossier(null)}><X size={18}/></button></header><nav><button aria-pressed={dossier==='public'} onClick={()=>setDossier('public')}>{t('workbench.court.publicDossier')}</button><button aria-pressed={dossier==='private'} onClick={()=>setDossier('private')}>{t('workbench.court.privateBrief')}</button></nav><div className="wc-dossier-content">{(dossier==='public'?[[t('workbench.court.dossierSummary'),session.shared_dossier.summary],[t('workbench.court.dossierClaims'),session.shared_dossier.claims],[t('workbench.court.dossierEvidence'),session.shared_dossier.evidence]]:[[t('workbench.court.dossierStrategy'),session.private_brief.strategy],[t('workbench.court.dossierLogic'),session.private_brief.logic_chain],[t('workbench.court.dossierRisk'),session.private_brief.risk_notes]]).map(([label,text])=><section key={label}><h4>{label}</h4><p>{text||t('workbench.court.dossierEmpty')}</p></section>)}{!!session.source_snapshots?.length&&<section><h4>{t('workbench.court.sourceSnapshot')}</h4>{session.source_snapshots.map(source=><p key={source.id}>{source.title}<small>{t('workbench.court.sourceVersion',{revision:source.revision})}{source.truncated?t('workbench.court.sourceSelected'):''}</small></p>)}</section>}</div></section></motion.div>}</AnimatePresence>
    <input ref={input} type="file" multiple hidden onChange={e=>void upload(e.target.files)}/>
  </div>;
}
