import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { SelectField } from "./SelectField";
import { useT } from "../i18n";
import React, { useState, useRef, useEffect, useLayoutEffect } from "react";
import { Columns2, Rows2, LayoutTemplate, GripVertical, RotateCcw } from "lucide-react";

export type Edge = "left" | "right" | "top" | "bottom";
type Pane = "document" | "agent" | "navigation";
type Layout = { agent: Edge; navigation: "left" | "right"; split: number };
const defaults: Layout = { agent: "right", navigation: "left", split: 35 };
const opposite: Record<Edge, Edge> = { left: "right", right: "left", top: "bottom", bottom: "top" };
export function useWorkspaceLayout(user: string) {
  const { t } = useT();
  const key = "lawver:layout:" + user;
  const [layout, setLayout] = useState<Layout>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "null");
      if (saved && ["left", "right", "top", "bottom"].includes(saved.agent))
        return { ...defaults, ...saved, split: Math.min(65, Math.max(25, Number(saved.split) || 35)) };
    } catch { /* Layout preferences must never block the workspace. */ }
    return defaults;
  });
  const [dragging, setDragging] = useState<Pane>();
  const reduceMotion = useReducedMotion();
  const [activeEdge, setActiveEdge] = useState<Edge>();
  const [bounds, setBounds] = useState<React.CSSProperties>();
  const positions = useRef<Array<{ element: HTMLElement; rect: DOMRect }>>([]);
  useLayoutEffect(() => {
    for (const {element, rect} of positions.current) {
      const next = element.getBoundingClientRect();
      element.animate([{ transform: `translate(${rect.x-next.x}px,${rect.y-next.y}px)`, opacity: .8 }, { transform: 'none', opacity: 1 }], { duration: 220, easing: 'cubic-bezier(.2,.8,.2,1)' });
    }
    positions.current = [];
  }, [layout]);
  function update(patch: Partial<Layout>) {
    if (!reduceMotion && Object.keys(patch).some(k => k !== 'split')) {
      positions.current = Array.from(document.querySelectorAll<HTMLElement>('.wb-sidebar,.wb-document-column,.wb-agent')).map(element => ({element,rect:element.getBoundingClientRect()}));
    }
    // updater 保持纯函数：持久化挪到下面的 effect。拖动分隔条时 layout 每帧都在变，
    // 在 updater 里同步写 localStorage 等于把磁盘写入压进拖动路径（StrictMode 下还会翻倍）。
    setLayout(old => ({ ...old, ...patch }));
  }
  useEffect(() => {
    const timer = setTimeout(() => {
      try { localStorage.setItem(key, JSON.stringify(layout)); } catch { /* In-memory layout still works. */ }
    }, 240);
    return () => clearTimeout(timer);
  }, [key, layout]);
  function dock(edge: Edge) {
    if (dragging === "agent") update({ agent: edge });
    if (dragging === "document") update({ agent: opposite[edge] });
    if (dragging === "navigation" && (edge === "left" || edge === "right")) update({ navigation: edge });
    setDragging(undefined);
    setActiveEdge(undefined);
  }
  function handle(pane: Pane, label: string) {
    return <span className="wb-dock-handle wb-desktop-only" draggable title={t("workbench.layout.dragHint", { label })} aria-label={t("workbench.layout.dragLabel", { label })}
      onDragStart={e => { e.dataTransfer.setData("application/x-lawver-pane", pane); e.dataTransfer.effectAllowed = "move"; const root = e.currentTarget.closest('.wb-app');
        const surface = pane === 'navigation' ? root : root?.querySelector('.wb-body');
        if (root && surface) { const r=root.getBoundingClientRect(), b=surface.getBoundingClientRect(); setBounds({left:b.left-r.left,top:b.top-r.top,width:b.width,height:b.height,right:'auto',bottom:'auto'}); }
        setActiveEdge(undefined); setDragging(pane); }}
      onDragEnd={() => {setDragging(undefined);setActiveEdge(undefined);}}><GripVertical size={16}/></span>;
  }
  /**
   * 分栏改用 flex（不再是 grid）：面板宽度是可动画的 flex-basis，展开/收起才有过渡。
   * 返回容器样式；文档列与会话列的基准宽度见 CSS 的 --wb-doc-basis。
   */
  function splitStyle(agentOpen: boolean): React.CSSProperties {
    const vertical = layout.agent === "top" || layout.agent === "bottom";
    return {
      flexDirection: vertical ? "column" : "row",
      // 文档内层据此钉住排版宽度（cqw），拖动分栏后同步更新。
      "--wb-doc-percent": String(Math.max(25, Math.min(75, 100 - layout.split))),
    } as React.CSSProperties;
  }
  /** 文档列基准宽度（百分比）：会话面板占比的反面，钳在 25%-75%。 */
  const docPercent = Math.max(25, Math.min(75, 100 - layout.split));
  const targets = <AnimatePresence>{dragging && <motion.div key="dock-targets" className="wb-dock-targets" style={bounds} aria-label={t("workbench.layout.dockTargets")}
    initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduceMotion ? 0 : .16}}>
    <AnimatePresence>{activeEdge && <motion.div key={activeEdge} className={`wb-dock-preview ${activeEdge}`}
      initial={{opacity:0,scale:.98}} animate={{opacity:1,scale:1}} exit={{opacity:0}} transition={{duration:reduceMotion ? 0 : .16}}/>}</AnimatePresence>
    {(["left", "right", ...(["agent", "document"].includes(dragging) ? ["top", "bottom"] : [])] as Edge[]).map(edge => <div key={edge} className={`wb-dock-target ${edge} ${activeEdge === edge ? "is-active" : ""}`} data-dock-edge={edge}
      onDragEnter={e => {e.preventDefault();setActiveEdge(edge);}}
      onDragLeave={e => {if (!e.currentTarget.contains(e.relatedTarget as Node)) setActiveEdge(undefined);}}
      onDragOver={e => {e.preventDefault();e.dataTransfer.dropEffect="move";setActiveEdge(edge);}}
      onDrop={e => {e.preventDefault();dock(edge);}}>
      <span>{edge === "top" || edge === "bottom" ? <Rows2 size={16}/> : <Columns2 size={16}/>}{activeEdge === edge ? t("workbench.layout.dropTo") : t("workbench.layout.moveTo")}{({left:t("workbench.layout.left"),right:t("workbench.layout.right"),top:t("workbench.layout.top"),bottom:t("workbench.layout.bottom")} as Record<Edge,string>)[edge]}</span>
    </div>)}
  </motion.div>}</AnimatePresence>;
  return { layout, update, handle, splitStyle, docPercent, targets, reset: () => update(defaults) };
}

export function LayoutToolbar({ workspace }: { workspace: ReturnType<typeof useWorkspaceLayout> }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const presets = [
    { name: t("workbench.layout.presetDocumentFirst"), edge: "right" as Edge, Icon: Columns2 },
    { name: t("workbench.layout.presetAgentLeft"), edge: "left" as Edge, Icon: Columns2 },
    { name: t("workbench.layout.presetStacked"), edge: "bottom" as Edge, Icon: Rows2 },
  ];
  return <div className="wb-layout-picker wb-desktop-only" onBlur={e => {if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false);}}>
    <button aria-expanded={open} aria-controls="workspace-layout-options" onClick={() => setOpen(!open)}><LayoutTemplate size={16}/>{t("workbench.shell.workspaceLayout")}</button>
    <AnimatePresence>{open && <motion.div initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:reduceMotion ? 0 : .14}} className="wb-layout-options" id="workspace-layout-options" onKeyDown={e => {if(e.key === "Escape") {e.stopPropagation();setOpen(false);}}}>
      <strong>{t("workbench.layout.title")}</strong><p>{t("workbench.layout.hint")}</p>
      {presets.map(({name,edge,Icon}) => <button key={name} aria-pressed={workspace.layout.agent === edge} onClick={() => {workspace.update({agent:edge,split:edge === "bottom" ? 45 : 35}); setOpen(false);}}><Icon size={18}/>{name}</button>)}
      <SelectField label={t("workbench.layout.agentPosition")} value={workspace.layout.agent} onChange={value=>workspace.update({agent:value as Edge})} options={Object.entries({left:t("workbench.layout.left"),right:t("workbench.layout.right"),top:t("workbench.layout.top"),bottom:t("workbench.layout.bottom")}).map(([value,label])=>({value,label}))} />
      <SelectField label={t("workbench.layout.navigation")} value={workspace.layout.navigation} onChange={value=>workspace.update({navigation:value as "left"|"right"})} options={[{value:"left",label:t("workbench.layout.left")},{value:"right",label:t("workbench.layout.right")}]} />
      <button onClick={() => {workspace.reset();setOpen(false);}}><RotateCcw size={16}/>{t("workbench.layout.reset")}</button>
    </motion.div>}</AnimatePresence>
  </div>;
}
