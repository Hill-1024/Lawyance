import React, { useEffect, useRef, useState } from 'react';
import { Gavel, Scale, UserRound, BookOpen, ChevronRight, X, Play, Send, Paperclip, SlidersHorizontal, GitBranch, Undo2, CircleAlert, Lock, FileText, Download } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCourtSession } from '../hooks/useCourtSession';
import { useWorkspace } from '../hooks/useWorkspace';
import { useAutoGrowTextarea } from '../hooks/useAutoGrowTextarea';
import { useAppDialog } from '../contexts/DialogContext';
import { buildAttachmentPrompt, stripAttachmentPrompt, stripWorkspacePaths } from '../lib/attachment-prompt';
import { CourtSetup } from '../components/CourtSetup';
import { WorkflowStatusIcon } from '../components/WorkflowStatusIcon';
import { Reference } from './client';
import { getBinding, matchKeys, SHORTCUT_IDS } from '../lib/shortcuts';
import './court-conversation.css';
import '../components/court-workspace.css';

const phases: Record<string,string> = {opening:'开庭',claim_statement:'诉辩陈述',prosecution_statement:'宣读起诉',defense_response:'答辩回应',agency_response:'机关答辩',court_inquiry:'法庭调查',legality_review:'合法性审查',evidence_cross:'举证质证',court_debate:'法庭辩论',final_statement:'最后陈述',judge_summary:'法庭意见',review:'庭后复盘'};
const roles = {judge:{label:'法官',Icon:Gavel},opponent:{label:'对方代理',Icon:Scale},reviewer:{label:'复盘员',Icon:BookOpen},user:{label:'我方',Icon:UserRound},system:{label:'庭审记录',Icon:FileText}};
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
  const dossierPanel=useRef<HTMLElement>(null);
  useEffect(()=>{if(!dossier)return;const previous=document.activeElement as HTMLElement|null;dossierPanel.current?.querySelector<HTMLButtonElement>('button')?.focus();return()=>{if(previous?.isConnected)previous.focus();};},[Boolean(dossier)]);
  const input=useRef<HTMLInputElement>(null),scroll=useRef<HTMLDivElement>(null),stick=useRef(true);
  const {ref:textarea}=useAutoGrowTextarea(court.composerText);
  useEffect(()=>{
    if(isInitialized && selection!=='new' && court.courtSessions.some(s=>s.id===selection && (!project || s.project_id===project))) court.setCurrentCourtId(selection);
  },[isInitialized,selection,project,court.courtSessions,court.setCurrentCourtId]);
  useEffect(()=>{if(stick.current && scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight;},[session?.public_events,isRunning]);
  const creating=selection==='new';
  async function upload(list:FileList|null) {
    setError('');
    const results=await Promise.allSettled(Array.from(list||[]).map(f=>files.handleFileUpload(f)));
    const failed=results.filter(r=>r.status==='rejected');
    if(failed.length)setError(`${failed.length} 份材料上传失败，请重试。`);
    if(input.current)input.current.value='';
  }
  function send() {
    if(!session || session.court_state.trial_over || files.isUploadingFiles)return;
    const quote=documentReference?.text ? `【公开引用：${documentReference.title || '文档片段'} · 版本 ${documentReference.revision}】\n${documentReference.text}` : '';
    const text=[court.composerText.trim(),quote,buildAttachmentPrompt(files.pendingUploads)].filter(Boolean).join('\n\n');
    if(!text)return;
    court.sendUserSpeech(text);files.setPendingUploads([]);onClearReference();
  }
  if(!isInitialized)return <div className="wc-loading" role="status"><WorkflowStatusIcon status="running"/>正在打开庭审会话…</div>;
  if(creating)return <CourtSetup key={project || 'personal'} initialProject={project} onCreate={value=>onSelect(court.createCourtSession(value),value.project_id)} onCancel={onCancel}/>;
  if(!session || session.id!==selection || (project && session.project_id!==project))return <div className="wc-loading">庭审未找到或正在同步。<button onClick={onCancel}>返回项目</button></div>;
  const state=session.court_state,events=session.public_events,started=events.some(e=>e.speaker!=='system');
  const hasError=Object.values(session.agent_states).some(agent=>agent.status==='error');
  const status=state.trial_over?'庭审已结束':isRunning?court.status || '正在准备发言':hasError?court.status || '本轮执行遇到问题，请重试':!started?'案卷已就绪，等待开始':state.awaiting_user?`等待${session.user_side}陈述`:'本轮完成，可以继续';
  return <div className="wc-conversation">
    <header className="wc-heading">{dragHandle}<div><h2>{session.title}</h2></div><button aria-label="查看庭审案卷" aria-pressed={!!dossier} onClick={()=>setDossier(dossier?null:'public')}><BookOpen size={17}/>案卷</button>{onCollapse&&<button className="wc-collapse wb-desktop-only" aria-label="收起模拟庭审" onClick={onCollapse}><X size={16}/></button>}</header>
    <div className="wc-stage"><span><Gavel size={15}/>{phases[state.phase]||state.phase}</span><ChevronRight size={13}/><span>{session.user_side}视角</span><small>{court.syncError?'未同步':court.isSaving?'保存中…':'已保存'}</small></div>
    {(error||court.syncError)&&<div role="alert" className="wc-error">{error||court.syncError}{court.syncError&&<button onClick={()=>{const blob=new Blob([JSON.stringify({court_sessions:[...court.recoverySessions,...court.courtSessions]})],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='court-recovery.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}><Download size={14}/>导出恢复副本</button>}</div>}
    <div className="wc-flow" ref={scroll} onScroll={e=>{const el=e.currentTarget;stick.current=el.scrollHeight-el.scrollTop-el.clientHeight<140;}}>
      <div className="wc-material-summary"><FileText size={17}/><div><strong>本次庭审材料</strong><p>{session.shared_dossier.summary || session.shared_dossier.claims || '已整理公开案卷'}</p><button onClick={()=>setDossier('public')}>查看案卷与来源<ChevronRight size={13}/></button></div></div>
      {!started && <div className="wc-empty"><h3>从法官的第一句发问开始。</h3><p>公开案卷已就绪。你的私有备庭笔记仅供我方代理与复盘员使用。</p><button className="wc-primary" disabled={isRunning} onClick={court.runNextTurn}><Play size={15}/>开始庭审</button></div>}
      {events.filter(e=>e.speaker!=='system').map((event,index,visible)=>{const role=roles[event.speaker]||roles.system;const Icon=role.Icon;return <article className={'wc-message '+(event.speaker==='user'?'is-user':'')} key={event.id}>
        <header><Icon size={17}/><strong>{event.speaker==='user'?session.user_side:role.label}</strong><span>{phases[event.phase]||event.phase}</span></header>
        <div className="wc-message-content"><Markdown remarkPlugins={[remarkGfm]}>{stripWorkspacePaths(stripAttachmentPrompt(event.content||''))}</Markdown></div>
        {!isRunning&&<footer><button aria-label="从这条发言创建分支" onClick={()=>{const id=court.branchFromEvent(session.id,event.id);if(id)onSelect(id,session.project_id);}}><GitBranch size={14}/></button>{index<visible.length-1&&<button aria-label="撤回到这条发言" onClick={async()=>{if(await showConfirm({title:'撤回到这条发言？',message:'之后的公开记录和角色记忆将被清除。',confirmLabel:'撤回',tone:'danger'}))court.rewindToEvent(session.id,event.id);}}><Undo2 size={14}/></button>}</footer>}
      </article>})}
      <div className="wc-status" role="status">{hasError && !isRunning ? <CircleAlert size={14}/> : <WorkflowStatusIcon key={isRunning?'running':'done'} status={isRunning?'running':'done'}/ >}{status}</div>
    </div>
    <footer className="wc-composer-dock">
      <div className="wc-reference-row">{documentReference&&<span><FileText size={14}/>{documentReference.title || '文档片段'}<button aria-label="移除文档引用" onClick={onClearReference}><X size={12}/></button></span>}{files.pendingUploads.map((f,i)=><span key={f.path||i}><Paperclip size={13}/>{f.name}<button aria-label={'移除 '+f.name} onClick={()=>files.removeUploadedFile(i)}><X size={12}/></button></span>)}</div>
      <div className="wc-composer"><textarea ref={textarea} aria-label="庭审发言" placeholder={state.trial_over?'本场庭审已结束':'陈述观点，或就刚才的发言提出回应…'} value={court.composerText} disabled={state.trial_over} onChange={e=>court.setComposerText(e.target.value)} onKeyDown={e=>{if(!e.nativeEvent.isComposing && matchKeys(e,getBinding(SHORTCUT_IDS.courtSend))){e.preventDefault();send();}}}/>
        <div className="wc-composer-tools"><button aria-label="上传公开材料" disabled={files.isUploadingFiles||state.trial_over} onClick={()=>input.current?.click()}><Paperclip size={18}/></button><button aria-label="庭审选项" aria-expanded={options} onClick={()=>setOptions(!options)}><SlidersHorizontal size={17}/></button><small>{files.isUploadingFiles?'正在上传…':isRunning?'发言中，输入将作为插话':'发送内容将进入公开庭审'}</small><button className="wc-send" aria-label="发送庭审发言" disabled={state.trial_over||files.isUploadingFiles||(!court.composerText.trim()&&!documentReference?.text&&!files.pendingUploads.length)} onClick={send}><Send size={17}/></button></div>
      </div>
      <AnimatePresence>{options&&<motion.div className="wc-options" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} transition={{duration:reduceMotion?0:.16}}><label><input type="checkbox" checked={session.auto_mode} disabled={state.trial_over} onChange={e=>court.setAutoMode(e.target.checked)}/>自动推进</label><label><input type="checkbox" checked={!!state.user_agent_enabled} disabled={state.trial_over} onChange={e=>court.setUserAgentMode(e.target.checked)}/>我方 AI 代理</label><button disabled={isRunning||state.trial_over} onClick={()=>{court.forceAdvance();court.runNextTurn();}}>推进阶段<ChevronRight size={14}/></button></motion.div>}</AnimatePresence>
      <div className="wc-continuation"><span><Lock size={12}/>各方角色独立记忆</span>{started&&!state.trial_over&&!session.auto_mode&&<button disabled={isRunning||(state.awaiting_user&&!state.user_agent_enabled)} onClick={court.runNextTurn}><Play size={13}/>{started?'继续下一轮':'开始庭审'}</button>}</div>
    </footer>
    <AnimatePresence>{dossier&&<motion.div className="wc-dossier-overlay" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduceMotion?0:.16}} onClick={e=>{if(e.target===e.currentTarget)setDossier(null);}}><section ref={dossierPanel} className="wc-dossier" onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setDossier(null);}if(e.key==='Tab'){const controls=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,textarea,select'));const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}} role="dialog" aria-label="庭审案卷" aria-modal="true"><header><h3>庭审案卷</h3><button aria-label="关闭庭审案卷" onClick={()=>setDossier(null)}><X size={18}/></button></header><nav><button aria-pressed={dossier==='public'} onClick={()=>setDossier('public')}>公开案卷</button><button aria-pressed={dossier==='private'} onClick={()=>setDossier('private')}>私有备庭</button></nav><div className="wc-dossier-content">{(dossier==='public'?[['案情与争议',session.shared_dossier.summary],['诉求 / 指控',session.shared_dossier.claims],['公开证据',session.shared_dossier.evidence]]:[['庭审策略',session.private_brief.strategy],['证据链与推理',session.private_brief.logic_chain],['风险与薄弱环节',session.private_brief.risk_notes]]).map(([label,text])=><section key={label}><h4>{label}</h4><p>{text||'未填写'}</p></section>)}{!!session.source_snapshots?.length&&<section><h4>材料来源 · 创建时快照</h4>{session.source_snapshots.map(source=><p key={source.id}>{source.title}<small>版本 {source.revision}{source.truncated?' · 节选':''}</small></p>)}</section>}</div></section></motion.div>}</AnimatePresence>
    <input ref={input} type="file" multiple hidden onChange={e=>void upload(e.target.files)}/>
  </div>;
}
