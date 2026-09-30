import {useEffect,useState} from 'react';
import { CheckBox } from "../components/CheckBox";
import { SelectField } from "./SelectField";
import {Folder, MessageSquare, FileText, RefreshCw, Lock} from 'lucide-react';
import {api,Item} from './client';
import { useT } from '../i18n';
export type CourtSource = {id:string;title:string;revision:number;updated_at:string;text:string;truncated:boolean};
export function CourtMaterials({project,onProject,onAuto,onSelect,onReady}:{project:string;onProject:(id:string)=>void;onAuto:(text:string,sources:CourtSource[])=>void;onSelect:(text:string)=>void;onReady:(ready:boolean)=>void}) {
 const { t } = useT();
 const [enabled,setEnabled]=useState(false),[projects,setProjects]=useState<Item[]>([]),[docs,setDocs]=useState<Item[]>([]),[sources,setSources]=useState<CourtSource[]>([]),[selected,setSelected]=useState<string[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0),[omitted,setOmitted]=useState(0);
 useEffect(()=>{let live=true;api('/status').then(async s=>{if(s.enabled){const p=await api<Item[]>('/projects');if(live){setProjects(p);setEnabled(true)}}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
 useEffect(()=>{let live=true;setSelected([]);setSources([]);setDocs([]);setError('');onAuto('',[]);onReady(!project);if(!project)return;
 setLoading(true);
 Promise.all([api('/projects/'+encodeURIComponent(project)+'/court-context'),api<Item[]>('/documents?project_id='+encodeURIComponent(project))]).then(([context,documents])=>{if(!live)return;setDocs(documents);setSources(context.sources);setOmitted(context.omitted);const text=[context.project.desc ? `${t('workbench.court.projectNote')}\n${context.project.desc}` : '',...context.sources.map((s:CourtSource)=>`${t('workbench.court.sessionSource',{title:s.title,revision:s.revision})}${s.truncated?t('workbench.court.sourceSelected'):''}]\n${s.text}`)].filter(Boolean).join('\n\n');onAuto(text,context.sources);onReady(true)}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});
 return()=>{live=false};},[project,refresh]);
 async function collectPublic(){setLoading(true);setError('');try{const values=await Promise.all(selected.filter(id=>docs.some(d=>d.id===id)).map(id=>api<Item>('/documents/'+id)));const nativeText=(node:any):string=>node?.type==='text'?node.text:(node?.content||[]).map(nativeText).join('\n');const pieces=[...sources.filter(s=>selected.includes(s.id)).map(s=>`${t('workbench.court.sessionSourceUnverified',{title:s.title,revision:s.revision})}\n${s.text}`),...values.map(d=>{const text=d.data.text||nativeText(d.data.content);if(!text.trim())throw new Error(t('workbench.court.noExtractableText',{title:d.title}));return `${t('workbench.court.fileSource',{title:d.title,revision:d.revision})}\n${text}`})];const text=pieces.join('\n\n');if(text.length>50000)throw new Error(t('workbench.court.tooLong'));onSelect(text);setSelected([])}catch(e){setError(e.message)}finally{setLoading(false)}}
 if(!enabled && !error)return null;
 return <section className="court-materials"><header><Folder size={18}/><h2>{t('workbench.materials.title')}</h2></header>
 <SelectField label={t('workbench.court.attachProject')} value={project} onChange={onProject} options={[{value:"",label:t('workbench.court.noProject')}, ...projects.map(p=>({value:p.id,label:p.title}))]} />
 {project && <><div className="court-source-status"><Lock size={16}/><span>{loading?t('workbench.court.collecting'):t('workbench.court.collected',{count:sources.length})}{omitted>0?t('workbench.court.collectedMore',{count:omitted}):''}</span><button type="button" aria-label={t('workbench.court.rehydrate')} disabled={loading} onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16}/></button></div><p>{t('workbench.court.autoNote')}</p>
 <details><summary>{t('workbench.court.reviewSources')}</summary><p>{t('workbench.court.reviewHint')}</p>
 {[...sources.map(s=>({...s,kind:'conversation'})),...docs].map(item=><label className="court-source-row" key={item.id}><CheckBox checked={selected.includes(item.id)} onCheckedChange={next=>setSelected(old=>next?[...old,item.id]:old.filter(id=>id!==item.id))} ariaLabel={item.title}/>{item.kind==='conversation'?<MessageSquare size={16}/>:<FileText size={16}/>}<span>{item.title}<small>{item.kind==='conversation'?t('workbench.court.conversationText'):t('workbench.court.projectFile')} · {t('workbench.court.sourceVersion',{revision:item.revision})}</small></span></label>)}
 {sources.map(s=><details key={'preview'+s.id}><summary>{t('workbench.court.preview',{title:s.title})}{s.truncated?t('workbench.court.sourceSelected'):''}</summary><pre>{s.text}</pre></details>)}
 <button type="button" className="md3-btn-tonal" disabled={!selected.length||loading} onClick={collectPublic}>{t('workbench.court.addToEvidence')}</button></details></>}
 {error&&<p role="alert">{error}</p>}
 </section>;
}
