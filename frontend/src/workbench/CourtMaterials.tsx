import {useEffect,useState} from 'react';
import { CheckBox } from "../components/CheckBox";
import { SelectField } from "./SelectField";
import {Folder, MessageSquare, FileText, RefreshCw, Lock} from 'lucide-react';
import {api,Item} from './client';
export type CourtSource = {id:string;title:string;revision:number;updated_at:string;text:string;truncated:boolean};
export function CourtMaterials({project,onProject,onAuto,onSelect,onReady}:{project:string;onProject:(id:string)=>void;onAuto:(text:string,sources:CourtSource[])=>void;onSelect:(text:string)=>void;onReady:(ready:boolean)=>void}) {
 const [enabled,setEnabled]=useState(false),[projects,setProjects]=useState<Item[]>([]),[docs,setDocs]=useState<Item[]>([]),[sources,setSources]=useState<CourtSource[]>([]),[selected,setSelected]=useState<string[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0),[omitted,setOmitted]=useState(0);
 useEffect(()=>{let live=true;api('/status').then(async s=>{if(s.enabled){const p=await api<Item[]>('/projects');if(live){setProjects(p);setEnabled(true)}}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
 useEffect(()=>{let live=true;setSelected([]);setSources([]);setDocs([]);setError('');onAuto('',[]);onReady(!project);if(!project)return;
 setLoading(true);
 Promise.all([api('/projects/'+encodeURIComponent(project)+'/court-context'),api<Item[]>('/documents?project_id='+encodeURIComponent(project))]).then(([context,documents])=>{if(!live)return;setDocs(documents);setSources(context.sources);setOmitted(context.omitted);const text=[context.project.desc ? `【项目说明 · 待核对】\n${context.project.desc}` : '',...context.sources.map((s:CourtSource)=>`【会话：${s.title} · 版本 ${s.revision}${s.truncated?' · 节选':''}】\n${s.text}`)].filter(Boolean).join('\n\n');onAuto(text,context.sources);onReady(true)}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});
 return()=>{live=false};},[project,refresh]);
 async function collectPublic(){setLoading(true);setError('');try{const values=await Promise.all(selected.filter(id=>docs.some(d=>d.id===id)).map(id=>api<Item>('/documents/'+id)));const nativeText=(node:any):string=>node?.type==='text'?node.text:(node?.content||[]).map(nativeText).join('\n');const pieces=[...sources.filter(s=>selected.includes(s.id)).map(s=>`【会话：${s.title} · 版本 ${s.revision} · 内容待核验】\n${s.text}`),...values.map(d=>{const text=d.data.text||nativeText(d.data.content);if(!text.trim())throw new Error(`${d.title} 没有可提取正文，请先整理扫描件`);return `【${d.title} · 版本 ${d.revision}】\n${text}`})];const text=pieces.join('\n\n');if(text.length>50000)throw new Error('公开材料超过 50,000 字，请减少选择');onSelect(text);setSelected([])}catch(e){setError(e.message)}finally{setLoading(false)}}
 if(!enabled && !error)return null;
 return <section className="court-materials"><header><Folder size={18}/><h2>项目与备庭材料</h2></header>
 <SelectField label="所属项目" value={project} onChange={onProject} options={[{value:"",label:"不关联项目 · 本地独立庭审"}, ...projects.map(p=>({value:p.id,label:p.title}))]} />
 {project && <><div className="court-source-status"><Lock size={16}/><span>{loading?'正在整理同项目会话…':`已收集 ${sources.length} 个会话到私有备庭材料`}{omitted>0?`，另有 ${omitted} 个会话未收录`:''}</span><button type="button" aria-label="重新收集项目会话" disabled={loading} onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16}/></button></div><p>自动收集的是会话原文，AI 分析仍需核验。只在创建时收集；后续会话不会悄悄改变本场庭审。</p>
 <details><summary>核对来源，选择可公开的材料</summary><p>勾选并加入后，法官与模拟对方都能阅读。未选择的会话只进入私有笔记。</p>
 {[...sources.map(s=>({...s,kind:'conversation'})),...docs].map(item=><label className="court-source-row" key={item.id}><CheckBox checked={selected.includes(item.id)} onCheckedChange={next=>setSelected(old=>next?[...old,item.id]:old.filter(id=>id!==item.id))} ariaLabel={item.title}/>{item.kind==='conversation'?<MessageSquare size={16}/>:<FileText size={16}/>}<span>{item.title}<small>{item.kind==='conversation'?'会话原文':'项目文件'} · 版本 {item.revision}</small></span></label>)}
 {sources.map(s=><details key={'preview'+s.id}><summary>预览：{s.title}{s.truncated?'（节选）':''}</summary><pre>{s.text}</pre></details>)}
 <button type="button" className="md3-btn-tonal" disabled={!selected.length||loading} onClick={collectPublic}>将所选内容加入公开证据线索</button></details></>}
 {error&&<p role="alert">{error}</p>}
 </section>;
}
