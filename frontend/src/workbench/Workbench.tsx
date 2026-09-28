import { WorkflowStatusIcon } from "../components/WorkflowStatusIcon";
import { CircleAlert, Pause, User } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Plus,
  Search,
  Folder,
  FolderOpen,
  History,
  MessageSquare,
  FileText,
  ChevronDown,
  Settings,
  Sparkles,
  Menu,
  X,
  Gavel,
  Archive,
  MoreHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import { BrandLockup, BrandMark } from "../components/Brand";
import {
  api,
  cached,
  remember,
  Item,
  Reference,
  withoutTitle,
} from "./client";
import { Composer, Draft } from "./Composer";
import { DocumentPane } from "./DocumentPane";
import { ManageDialog } from "./ManageDialog";
import "./workbench.css";
import { useBackButton } from "../hooks/useBackButton";
import { LayoutToolbar, useWorkspaceLayout } from "./WorkspaceLayout";
import { TextDialog } from "./TextDialog";
const CourtConversation = React.lazy(() => import("./CourtConversation"));

type ThoughtBlock = { key: number; kind: string; label: string; content: string };

const THOUGHT_LABELS: Record<string, string> = {
  reasoning: "Reasoning",
  draft: "Draft",
  tool: "Tool",
  plan: "Plan",
  ocp: "OCP",
  memory: "Memory",
};

// 无需展示给用户的内部信号：正文增量走 live，确认/选择有专门 UI，签名与记忆候选是管线细节。
const HIDDEN_EVENT_TYPES = new Set([
  "content",
  "content_replace",
  "history_trace",
  "memory_sync",
  "thought_signature",
  "memory_candidate",
  "done",
  "user_choice_request",
  "confirmation",
]);

// thought 事件是流式增量：mode=new 开新块，append（以及 reasoning/draft 默认）续写当前块。
// 其余可见事件独立成块；文档/建议事件另有专门按钮，不进时间线。
function aggregateActivity(events: any[]): ThoughtBlock[] {
  const blocks: ThoughtBlock[] = [];
  for (const event of events) {
    if (HIDDEN_EVENT_TYPES.has(event.type)) continue;
    if (event.type === "thought") {
      const kind = THOUGHT_LABELS[event.thought_type] ? event.thought_type : "reasoning";
      const append = event.mode === "append" || kind === "reasoning" || kind === "draft";
      const last = blocks[blocks.length - 1];
      if (append && last && last.kind === kind) {
        last.content += event.content || "";
        continue;
      }
      blocks.push({
        key: blocks.length,
        kind,
        label: THOUGHT_LABELS[kind],
        content: event.content || "",
      });
      continue;
    }
    if (event.type === "document" || event.type === "proposal") continue;
    const content = typeof event.content === "string" ? event.content : "";
    if (!content) continue;
    blocks.push({ key: blocks.length, kind: event.type, label: event.type, content });
  }
  return blocks;
}

// 运行中状态行旁的一句话进度（对齐 legacy 的措辞）。
function currentActivityLabel(blocks: ThoughtBlock[]): string {
  const block = blocks[blocks.length - 1];
  if (!block) return "";
  if (block.kind === "tool") {
    const match = block.content.match(/执行:\s*`([^`]+)`/);
    if (match) return "正在执行 " + match[1];
    if (block.content.includes("工具执行完毕")) return "正在生成最终回复";
    return "正在调用工具";
  }
  if (block.kind === "draft") return "正在拟定回答初稿";
  if (block.kind === "plan") return "正在规划执行步骤";
  if (block.kind === "ocp") return "正在审查输出";
  return "正在分析问题";
}
export default function Workbench({ username }: { username: string }) {
  const [textDialog, setTextDialog] = useState<{
    title: string;
    initial?: string;
    withDescription?: boolean;
    submit: (s: string, desc?: string) => void | Promise<void>;
  }>();
  const workspace = useWorkspaceLayout(username);
  const reduceMotion = useReducedMotion();
  const navigate = useNavigate(),
    location = useLocation(),
    routeUuid = useParams().uuid,
    [params] = useSearchParams();
  // 路径即状态：/home、/project/:uuid、/conversation/:uuid、/court/:uuid。
  const isCourtPath = location.pathname.startsWith("/court/");
  const isConversationPath = location.pathname.startsWith("/conversation/");
  const isProjectPath = location.pathname.startsWith("/project/");
  const courtSelection = isCourtPath ? routeUuid : undefined;
  const [courtReference,setCourtReference] = useState<Reference>();
  const [courtItems,setCourtItems] = useState<Item[]>([]);
  const [projects, setProjects] = useState<Item[]>([]),
    [conversations, setConversations] = useState<Item[]>([]),
    [documents, setDocuments] = useState<Item[]>([]),
    [skills, setSkills] = useState<Item[]>([]),
    [connectors, setConnectors] = useState<Item[]>([]);
  const [projectId, setProjectId] = useState<string>(),
    [conv, setConv] = useState<Item>(),
    [doc, setDoc] = useState<Item>(),
    [tabs, setTabs] = useState<Item[]>([]),
    [draft, setDraft] = useState<Draft>({ text: "", references: [] }),
    [run, setRun] = useState<Item>(),
    [events, setEvents] = useState<any[]>([]),
    [live, setLive] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<any[]>(),
    [sidebar, setSidebar] = useState(false),
    [mobile, setMobile] = useState("会话"),
    [dialog, setDialog] = useState(""),
    [menu, setMenu] = useState<Item>(),
    [spaceTab, setSpaceTab] = useState("会话" as "会话" | "文件"),
    [spaceMenu, setSpaceMenu] = useState(false),
    [spaceMenuPos, setSpaceMenuPos] = useState<{ top: number; left: number }>(),
    [projectFilter, setProjectFilter] = useState("全部" as "全部" | "最近"),
    [history, setHistory] = useState(false),
    [historyPos, setHistoryPos] = useState<{ top: number; left: number }>(),
    [appDrag, setAppDrag] = useState(false),
    [agentVisible, setAgentVisible] = useState(true),
    [mode, setMode] = useState("default"),
    [ocp, setOcp] = useState(true),
    [offline, setOffline] = useState(!navigator.onLine),
    [uploading, setUploading] = useState(false);
  const dragDepth = useRef(0),
    sideFile = useRef<HTMLInputElement>(null);
  const active = useRef<string>(undefined),
    draftKey = conv?.id || "new:" + String(projectId),
    draftReady = useRef(""),
    draftValue = useRef(draft),
    scroll = useRef<HTMLDivElement>(null);
  active.current = conv?.id;
  draftValue.current = draft;
  useBackButton(() => {
    if (textDialog) {
      setTextDialog(undefined);
      return true;
    }
    if (dialog) {
      setDialog("");
      return true;
    }
    if (menu) {
      setMenu(undefined);
      return true;
    }
    if (sidebar) {
      setSidebar(false);
      return true;
    }
    if (mobile !== "会话") {
      setMobile("会话");
      return true;
    }
    if (doc) {
      setDoc(undefined);
      return true;
    }
    return false;
  });
  const project = projects.find((p) => p.id === projectId),
    running =
      !!run &&
      ["queued", "running", "waiting_confirmation"].includes(run.data.status),
    projectDocs = documents.filter(
      (d) => (d.project_id || undefined) === projectId && !d.data.archived,
    ),
    spaceDocs = project
      ? projectDocs
      : documents.filter((d) => !d.project_id && !d.data.archived),
    spaceConversations = conversations.filter(
      (c) => (c.project_id || undefined) === projectId && !c.data.archived,
    ),
    spaceCourts = courtItems.filter((c) => c.project_id === projectId);
  function createDocument() {
    api<Item>("/documents", "POST", {
      title: "未命名文档",
      project_id: projectId,
    })
      .then((d) => {
        saved(d);
        openDocument(d);
      })
      .catch((e) => setError(e.message));
  }
  useEffect(() => {
    if (!spaceMenu) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest?.(".wb-space-menu, .wb-space-pill")) setSpaceMenu(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setSpaceMenu(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [spaceMenu]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!history) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest?.(".wb-thread-history")) setHistory(false);
    };    const esc = (e: KeyboardEvent) => e.key === "Escape" && setHistory(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [history]);
  useEffect(() => {const refresh = () => {void reload();}; window.addEventListener("lawver:extensions-updated", refresh); return () => window.removeEventListener("lawver:extensions-updated", refresh);}, []);
  async function reload() {
    try {
      const [p, c, d, s, k, courts] = await Promise.all([
        api<Item[]>("/projects"),
        api<Item[]>("/conversations"),
        api<Item[]>("/documents"),
        api<Item[]>("/skills"),
        api<Item[]>("/connectors"),
        api<Item[]>("/courts"),
      ]);
      setProjects(p);
      setCourtItems(courts);
      setConversations(c);
      setDocuments(d);
      setSkills(s);
      setConnectors(k);
      await remember(username, "index", { p, c, d, s, k, courts });
      setOffline(false);
    } catch (e) {
      const cache = await cached<any>(username, "index");
      if (cache) {
        setProjects(cache.p);
        setCourtItems(cache.courts || []);
        setConversations(cache.c);
        setDocuments(cache.d);
        setSkills(cache.s);
        setConnectors(cache.k);
        setOffline(true);
      } else setError(e.message);
    }
  }
  useEffect(() => {
    reload();
    const online = () => {
        setOffline(false);
        reload();
      },
      off = () => setOffline(true);
    window.addEventListener("online", online);
    const courtsUpdated = (event:Event) => {
      const detail=(event as CustomEvent<{user:string;items:Item[]}>).detail;
      if(detail?.user !== username || !detail.items?.length)return;
      setCourtItems(old=>{const next=new Map(old.map(item=>[item.id,item]));for(const item of detail.items)next.set(item.id,item);return [...next.values()];});
    };
    window.addEventListener("lawver:courts-updated", courtsUpdated);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("lawver:courts-updated", courtsUpdated);
      window.removeEventListener("offline", off);
    };
  }, [username]);
  // 路由是空间/会话/庭审的唯一事实源：路径变化时同步内部状态并加载会话。
  const routeSpaceKey = location.pathname + "|" + (routeUuid || "") + "|" + (isCourtPath ? params.get("project") || "" : "");
  useEffect(() => {
    if (isProjectPath && routeUuid) {
      setProjectId(routeUuid);
    } else if (isCourtPath) {
      setCourtReference(undefined);
      setSidebar(false);
      setMobile("会话");
      setAgentVisible(true);
      const contextProject = params.get("project");
      if (contextProject) setProjectId(contextProject);
    } else if (location.pathname === "/home") {
      setProjectId(undefined);
    }
    if (isConversationPath && routeUuid) {
      void loadConversation(routeUuid);
    }
  }, [routeSpaceKey]);
  // 浏览器返回离开会话路径时清掉会话态，让空间首页正常显示（进行中的任务保留）。
  useEffect(() => {
    if (!isConversationPath && !courtSelection && !running) setConv(undefined);
  }, [location.pathname]);
  useEffect(() => {
    draftReady.current = "";
    setDraft({ text: "", references: [] });
    const key = draftKey;
    cached<Draft>(username, "draft:" + key).then((d) => {
      if (key === (active.current || "new:" + String(projectId))) {
        setDraft(d || { text: "", references: [] });
        draftReady.current = key;
      }
    });
  }, [draftKey]);
  function updateDraft(d: Draft) {
    setDraft(d);
    if (draftReady.current === draftKey)
      remember(username, "draft:" + draftKey, d).catch(() =>
        setError("草稿缓存失败，请保留输入内容"),
      );
  }
  useEffect(() => {
    if (!query) {
      setResults(undefined);
      return;
    }
    const timer = setTimeout(
      () =>
        api<any[]>("/search?q=" + encodeURIComponent(query))
          .then(setResults)
          .catch((e) => setError(e.message)),
      180,
    );
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (!run || !running) return;
    let canceled = false,
      last = 0;
    const id = run.id;
    let output = "";
    setLive("");
    setEvents([]);
    async function poll() {
      try {
        const data = await api(`/runs/${id}/events?after=${last}`);
        if (canceled) return;
        for (const event of data.events) {
          last = event.seq;
          if (event.type === "content") output += event.content;
          if (event.type === "content_replace") output = event.content;
          if (["document", "proposal"].includes(event.type)) {
            reload();
            if (
              event.type === "proposal" &&
              doc?.id === event.content.document_id
            )
              api<Item>("/documents/" + doc.id).then(setDoc);
          }
        }
        setLive(output);
        setEvents((e) => [...e, ...data.events].slice(-500));
        if (!data.has_more) setRun(data.run);
        if (
          !data.has_more &&
          !["queued", "running", "waiting_confirmation"].includes(
            data.run.data.status,
          )
        ) {
          if (active.current === data.run.parent_id) {
            const c = await api<Item>("/conversations/" + data.run.parent_id);
            setConv(c);
            remember(username, "conversation:" + c.id, c);
            setLive("");
          }
          reload();
          return;
        }
        setTimeout(poll, data.has_more ? 50 : 1500);
      } catch (e) {
        if (!canceled) {
          setNotice("连接中断，正在恢复任务状态…");
          setTimeout(poll, 2500);
        }
      }
    }
    poll();
    return () => {
      canceled = true;
    };
  }, [run?.id, running]);
  async function loadConversation(id: string) {
    try {
      if (scroll.current && conv)
        remember(username, "scroll:" + conv.id, scroll.current.scrollTop);
      active.current = id;
      let c: Item;
      try {
        c = await api<Item>("/conversations/" + id);
        remember(username, "conversation:" + id, c);
      } catch (e) {
        c = await cached<Item>(username, "conversation:" + id);
        if (!c) throw e;
      }
      if (active.current !== id) return;
      setConv(c);
      if (doc && doc.project_id !== c.project_id) setDoc(undefined);
      setProjectId(c.project_id || undefined);
      setSidebar(false);
      setMobile("会话");
      // 重新进入同一会话时不要清掉进行中的任务，否则会掐断流式轮询。
      if (!run || run.parent_id !== id) {
        setLive("");
        setRun(undefined);
        setEvents([]);
      }
      const runId = c.data.messages?.at(-1)?.run_id;
      if (runId && !offline)
        api<Item>("/runs/" + runId)
          .then(setRun)
          .catch(() => {});
      const position = await cached<number>(username, "scroll:" + id);
      requestAnimationFrame(() => {
        if (scroll.current) scroll.current.scrollTop = position || 0;
      });
    } catch (e) {
      setError(e.message);
    }
  }
  // UI 入口只负责改路径；会话加载由路由同步 effect 驱动 loadConversation。
  function openConversation(id: string) {
    navigate("/conversation/" + encodeURIComponent(id));
  }
  async function openDocument(item: Item) {
    try {
      let d: Item;
      try {
        d = await api<Item>("/documents/" + item.id);
        remember(username, "document:" + item.id, d);
      } catch (e) {
        d = await cached<Item>(username, "document:" + item.id);
        if (!d) throw e;
      }
      setDoc(d);
      setTabs((t) =>
        t.some((x) => x.id === d.id)
          ? t.map((x) => (x.id === d.id ? d : x))
          : [...t, d],
      );
      setProjectId(d.project_id || undefined);
      setMobile("文档");
      setSidebar(false);
    } catch (e) {
      setError(e.message);
    }
  }
  function saved(d: Item) {
    setDoc(d);
    setTabs((t) =>
      t.some((x) => x.id === d.id)
        ? t.map((x) => (x.id === d.id ? d : x))
        : [...t, d],
    );
    remember(username, "document:" + d.id, d);
    reload();
  }
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        quick(projectId);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [projectId]);
  function quick(pid?: string) {
    if (doc && (doc.project_id || undefined) !== pid) setDoc(undefined);
    setConv(undefined);
    setRun(undefined);
    setLive("");
    setEvents([]);
    setProjectId(pid);
    setMobile("会话");
    setSidebar(false);
    navigate(pid ? "/project/" + encodeURIComponent(pid) : "/home");
  }
  // 庭审是独立路径；项目上下文用 query 携带（新建庭审时定位所属空间）。
  function openCourt(pid: string | undefined, id = "new") {
    navigate("/court/" + encodeURIComponent(id) + (pid ? "?project=" + encodeURIComponent(pid) : ""));
  }
  function createProject() {
    setTextDialog({
      title: "创建项目",
      withDescription: true,
      submit: async (title, desc) => {
        try {
          const p = await api<Item>("/projects", "POST", { title, desc });
          setTextDialog(undefined);
          await reload();
          quick(p.id);
        } catch (e) {
          setError(e.message);
        }
      },
    });
  }
  async function send() {
    if (!draft.text.trim() || running || offline) return;
    try {
      const fingerprint = JSON.stringify({ draft, mode, ocp, projectId });
      let pending = await cached<{ fingerprint: string; key: string }>(
        username,
        "pending:" + draftKey,
      );
      if (pending?.fingerprint !== fingerprint) {
        pending = { fingerprint, key: crypto.randomUUID() };
        await remember(username, "pending:" + draftKey, pending);
      }
      let c = conv;
      if (!c) {
        c = await api<Item>(
          "/conversations",
          "POST",
          { title: draft.text.slice(0, 40), project_id: projectId },
          pending.key + "-conversation",
        );
        active.current = c.id;
      }
      const r = await api<Item>(
        "/runs",
        "POST",
        {
          conversation_id: c.id,
          message: draft.text,
          references: withoutTitle(draft.references),
          mode,
          use_ocp: ocp,
        },
        pending.key,
      );
      await remember(username, "pending:" + draftKey, null);
      await remember(username, "draft:" + draftKey, {
        text: "",
        references: [],
      });
      await remember(username, "draft:" + c.id, { text: "", references: [] });
      setDraft({ text: "", references: [] });
      setConv(await api("/conversations/" + c.id));
      setRun(r);
      setAgentVisible(true);
      // 会话已落地，把地址换成可分享的会话路径（replace，避免返回键绕回首页草稿）。
      navigate("/conversation/" + encodeURIComponent(c.id), { replace: true });
      reload();
    } catch (e) {
      setError(e.message);
    }
  }
  async function upload(files: File[]) {
    setUploading(true);
    try {
      for (const f of files) {
        const body = new FormData();
        body.append("file", f);
        if (projectId) body.append("project_id", projectId);
        const d = await api<Item>("/documents/upload", "POST", body);
        updateDraft({
          ...draftValue.current,
          references: [
            ...draftValue.current.references,
            {
              kind: "document",
              id: d.id,
              revision: d.revision,
              title: d.title,
            },
          ],
        });
      }
      await reload();
      setNotice(
        projectId
          ? "文件已上传，并加入本次引用"
          : "文件已存入个人工作区，可在管理菜单移动进项目",
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }
  function reference(r: Reference, action = "加入引用") {
    if(courtSelection) {if(!r.text){setNotice("请划选文档文字，作为本次庭审的公开引用。");return;}setCourtReference(r);setAgentVisible(true);setMobile("会话");return;}
    updateDraft({
      ...draft,
      references: [...draft.references, r],
      text:
        action === "加入引用"
          ? draft.text
          : (draft.text ? draft.text + "\n" : "") +
            (action === "改写"
              ? "请修改所引用的片段，并提出可审阅的修改建议。"
              : action === "解释"
                ? "请解释所引用的片段。"
                : "关于所引用的内容："),
    });
    setAgentVisible(true);
    setMobile("会话");
  }
  async function mutate(item: Item, patch: any) {
    try {
      const family =
        item.kind === "project"
          ? "projects"
          : item.kind === "conversation"
            ? "conversations"
            : "documents";
      await api("/" + family + "/" + item.id, "PATCH", {
        expected_revision: item.revision,
        ...patch,
      });
      setMenu(undefined);
      reload();
    } catch (e) {
      setError(e.message);
    }
  }
  const composer = (
    <Composer
      draft={draft}
      onChange={updateDraft}
      onSend={send}
      onStop={() =>
        api("/runs/" + run.id + "/stop", "POST").catch((e) =>
          setError(e.message),
        )
      }
      onUpload={upload}
      documents={projectDocs}
      skills={skills}
      connectors={connectors}
      project={project}
      running={running}
      disabled={uploading}
      mode={mode}
      setMode={setMode}
      ocp={ocp}
      setOcp={setOcp}
    />
  );
  const messages = conv?.data.messages || [];
  const activityBlocks = React.useMemo(() => aggregateActivity(events), [events]);
  const chat = courtSelection ? <section key="court" style={doc && !agentVisible ? {display:"none"} : undefined} className={"wb-chat wb-court-session " + (doc ? "wb-agent" : "")}>

    <React.Suspense fallback={<div className="wb-empty-hint" role="status">正在打开庭审会话…</div>}><CourtConversation key="court-session" dragHandle={doc ? workspace.handle("agent","模拟庭审") : undefined} onCollapse={doc ? ()=>setAgentVisible(false) : undefined} project={projectId} selection={courtSelection} onSelect={(id,pid)=>openCourt(pid,id)} onCancel={()=>quick(projectId)} documentReference={courtReference} onClearReference={()=>setCourtReference(undefined)}/></React.Suspense>
  </section> : (
    <section
      className={"wb-chat " + (doc ? "wb-agent" : "")}
    >
      <header className="wb-chat-heading">
        {doc && workspace.handle("agent", "Agent")}
        <div>
          <small>{doc ? "与文档一起思考" : "当前会话"}</small>
          <h2>{conv?.title || "新的开始"}</h2>
        </div>
        <div className="wb-thread-tools">
          <div className="wb-thread-history">
            <button
              aria-label="会话历史"
              aria-expanded={history}
              onClick={(e) => {
                if (!history) {
                  const r = e.currentTarget.getBoundingClientRect();
                  const width = Math.min(300, window.innerWidth - 16);
                  setHistoryPos({
                    top: r.bottom + 6,
                    left: Math.max(
                      8,
                      Math.min(
                        r.left + r.width / 2 - width / 2,
                        window.innerWidth - width - 8,
                      ),
                    ),
                  });
                }
                setHistory(!history);
              }}
            >
              <History size={15} />
              <ChevronDown size={12} />
            </button>
            {history &&
              createPortal(
                <div
                  className="wb-thread-menu"
                  role="menu"
                  aria-label="会话历史"
                  style={{ position: "fixed", top: historyPos?.top, left: historyPos?.left }}
                >
                  {spaceConversations.map((c) => (
                    <button
                      key={c.id}
                      role="menuitem"
                      className={conv?.id === c.id ? "selected" : ""}
                      onClick={() => {
                        setHistory(false);
                        openConversation(c.id);
                      }}
                    >
                      <MessageSquare size={14} />
                      <span>{c.title}</span>
                      <small>
                        {new Date(c.updated_at).toDateString() === new Date().toDateString()
                          ? "今天"
                          : new Date(c.updated_at).toLocaleDateString()}
                      </small>
                    </button>
                  ))}
                  {!!spaceCourts.length && <small className="wb-thread-group">模拟庭审</small>}
                  {spaceCourts.map((c) => (
                    <button
                      key={c.id}
                      role="menuitem"
                      className={courtSelection === c.id ? "selected" : ""}
                      onClick={() => {
                        setHistory(false);
                        openCourt(projectId, c.id);
                      }}
                    >
                      <Gavel size={14} />
                      <span>{c.title}</span>
                    </button>
                  ))}
                  {!spaceConversations.length && !spaceCourts.length && (
                    <p className="wb-space-hint">还没有会话，发送第一条消息即开始。</p>
                  )}
                  <button
                    role="menuitem"
                    onClick={() => {
                      setHistory(false);
                      quick(projectId);
                    }}
                  >
                    <Plus size={14} />
                    新建会话
                  </button>
                </div>,
                document.body,
              )}
          </div>
          <button className="wb-text-action" onClick={() => quick(projectId)}>
            <Plus size={14} />
            新会话
          </button>
          {doc && (
            <button
              className="wb-desktop-only"
              aria-label="收起 Agent"
              onClick={() => setAgentVisible(false)}
            >
              <X size={17} />
            </button>
          )}
        </div>
      </header>
      <div className="wb-messages" ref={scroll}>
        {!messages.length && !running && (
          <div className="wb-chat-empty">
            <BrandMark className="wb-empty-brand" />
            <h3>{doc ? "让思考与文档同行" : "从一个问题开始"}</h3>
            <p>
              {doc
                ? "选择文档片段，即可提问、解释或提出修改建议。"
                : "引用材料，选择技能，描述你希望完成的工作。"}
            </p>
          </div>
        )}
        {messages.map((m: any) => (
          <article key={m.id} className={"wb-message " + m.role}>
            <div className="wb-message-label">
              {m.role === "user" ? "你" : "Lawver"}
              <button
                title="从此处分支"
                onClick={() =>
                  api<Item>(`/conversations/${conv.id}/branch`, "POST", {
                    message_id: m.id,
                    title: conv.title + " · 分支",
                  })
                    .then((c) => {
                      reload();
                      openConversation(c.id);
                    })
                    .catch((e) => setError(e.message))
                }
              >
                分支
              </button>
            </div>
            {m.references?.length > 0 && (
              <div className="wb-message-refs">
                {m.references.map((r: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => {
                      const d = documents.find((d) => d.id === r.id);
                      if (d) openDocument(d);
                    }}
                  >
                    {r.kind === "skill" ? "$" : "@"} {r.title} · v{r.revision}
                  </button>
                ))}
              </div>
            )}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {m.content}
            </ReactMarkdown>
          </article>
        ))}
        {live && (
          <article className="wb-message assistant">
            <div className="wb-message-label">Lawver</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{live}</ReactMarkdown>
          </article>
        )}
        {run && (
          <div className="wb-run-status">
            {run.data.status === "completed" ? <WorkflowStatusIcon status="done"/> : ["queued", "running"].includes(run.data.status) ? <WorkflowStatusIcon status="running"/> : run.data.status === "failed" ? <CircleAlert size={14}/> : <Pause size={14}/>}
            {
              (
                {
                  queued: "等待执行",
                  running: "正在处理材料",
                  waiting_confirmation: "等待你的确认",
                  completed: "任务已完成",
                  failed: "任务未完成",
                  interrupted: "任务已中断",
                  stopped: "已停止",
                } as any
              )[run.data.status]
            }
            {run.data.error && <p>{run.data.error}</p>}
            {running && activityBlocks.length > 0 && (
              <p className="wb-run-current">{currentActivityLabel(activityBlocks)}</p>
            )}
            {!!activityBlocks.length && (
              <details className="wb-run-events" open={running ? true : undefined}>
                <summary>查看执行过程</summary>
                <div className="wb-thought-list">
                  {activityBlocks.map((block) => (
                    <div key={block.key} className={"wb-thought-block is-" + block.kind}>
                      <small>{block.label}</small>
                      <div className="wb-thought-copy">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {block.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  ))}
                </div>
                {events
                  .filter((e) => e.type === "document")
                  .map((e) => (
                    <div key={e.seq}>
                      <button
                        onClick={() =>
                          openDocument({ id: e.content.document_id } as Item)
                        }
                      >
                        <FileText size={15} />
                        {e.content.title || "打开文档"}
                      </button>
                    </div>
                  ))}
              </details>
            )}
          </div>
        )}
        {run?.data.status === "waiting_confirmation" && (
          <div className="wb-confirmation">
            <strong>插件请求执行工具</strong>
            <p>{run.data.confirmation?.tool}</p>
            <pre>
              {JSON.stringify(run.data.confirmation?.arguments, null, 2)}
            </pre>
            <p>确认后将把上述参数发送给外部插件，可能产生外部变更。</p>
            <div className="wb-confirmation-actions">
              {[false, true].map((allow) => (
                <button
                  key={String(allow)}
                  className={allow ? "wb-primary" : "wb-quiet"}
                  onClick={() =>
                    api(`/runs/${run.id}/confirmation`, "POST", {
                      call_id: run.data.confirmation.id,
                      allow,
                    }).catch((e) => setError(e.message))
                  }
                >
                  {allow ? "允许本次调用" : "拒绝"}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="wb-composer-wrap">
        {composer}
        <small className="wb-disclaimer">
          {offline
            ? "离线可编辑草稿；联网后请主动发送。"
            : "法律意见需结合事实核验 · 仅使用本次明确引用的资料"}
        </small>
      </div>
    </section>
  );
  return (
    <div
      className={"wb-app " + (doc ? "has-document" : "") + " mobile-" + mobile}
      data-navigation={workspace.layout.navigation}
      onDragEnter={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setAppDrag(true);
      }}
      onDragLeave={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (!dragDepth.current) setAppDrag(false);
      }}
      onDragOver={(e) => {
        if (dragDepth.current) e.preventDefault();
      }}
      onDrop={(e) => {
        dragDepth.current = 0;
        setAppDrag(false);
        if (!e.dataTransfer.types.includes("Files") || e.defaultPrevented)
          return;
        e.preventDefault();
        const files = Array.from(e.dataTransfer.files);
        if (files.length) void upload(files);
      }}
    >
      <aside data-tour="wb-sidebar" className={"wb-sidebar " + (sidebar ? "is-open" : "")}>
        <div className="wb-brand">
          <Link to="/home" className="wb-brand-link" aria-label="回到工作台首页">
            <BrandLockup />
          </Link>
          {workspace.handle("navigation", "项目导航")}
          <button
            className="wb-mobile-only"
            aria-label="关闭导航"
            onClick={() => setSidebar(false)}
          >
            <X size={18} />
          </button>
        </div>
        <div className="wb-space-head">
          <button
            className="wb-space-pill"
            aria-haspopup="menu"
            aria-expanded={spaceMenu}
            title="切换工作区"
            onClick={(e) => {
              if (!spaceMenu) {
                const r = e.currentTarget.getBoundingClientRect();
                const width = Math.min(240, window.innerWidth - 16);
                setSpaceMenuPos({
                  top: Math.min(r.bottom + 6, window.innerHeight - 160),
                  left: Math.max(
                    8,
                    Math.min(
                      r.left + r.width / 2 - width / 2,
                      window.innerWidth - width - 8,
                    ),
                  ),
                });
              }
              setSpaceMenu(!spaceMenu);
            }}
          >
            {project ? <Folder size={15} /> : <User size={15} />}
            <span>{project ? project.title : "个人工作区"}</span>
            <ChevronDown size={14} />
          </button>
          {project && (
            <button aria-label={"管理 " + project.title} onClick={() => setMenu(project)}>
              <MoreHorizontal size={15} />
            </button>
          )}
        </div>
        {spaceMenu &&
          createPortal(
            <div
              className="wb-space-menu"
              role="menu"
              aria-label="切换工作区"
              style={{ position: "fixed", top: spaceMenuPos?.top, left: spaceMenuPos?.left }}
            >
              <button
                role="menuitem"
                className={!project ? "selected" : ""}
                onClick={() => {
                  setSpaceMenu(false);
                  setDoc(undefined);
                  quick(undefined);
                }}
              >
                <User size={14} />
                <span>个人工作区</span>
              </button>
              {projects
                .filter((p) => !p.data.archived)
                .map((p) => (
                  <button
                    key={p.id}
                    role="menuitem"
                    className={project?.id === p.id ? "selected" : ""}
                    onClick={() => {
                      setSpaceMenu(false);
                      setDoc(undefined);
                      quick(p.id);
                    }}
                  >
                    <Folder size={14} />
                    <span>{p.title}</span>
                  </button>
                ))}
              <div className="wb-space-menu-sep" />
              <button
                role="menuitem"
                onClick={() => {
                  setSpaceMenu(false);
                  createProject();
                }}
              >
                <Plus size={14} />
                <span>创建项目</span>
              </button>
            </div>,
            document.body,
          )}
        <div className="wb-space-tabs" role="tablist" aria-label="切换会话与文件">
          {(["会话", "文件"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={spaceTab === t}
              className="wb-space-tab"
              onClick={() => setSpaceTab(t)}
            >
              {t}
            </button>
          ))}
          <span className="wb-spacer" />
          {spaceTab === "文件" ? (
            <div className="wb-space-add-wrap">
              <button
                className="wb-space-add"
                aria-label="上传文件"
                aria-haspopup="menu"
                title="上传文件（悬停可选新建文档）"
                onClick={() => sideFile.current?.click()}
              >
                <Plus size={16} />
              </button>
              <div className="wb-space-add-menu" role="menu" aria-label="文件操作">
                <button role="menuitem" onClick={() => sideFile.current?.click()}>
                  <Upload size={14} />
                  上传文件
                </button>
                <button role="menuitem" onClick={createDocument}>
                  <FileText size={14} />
                  新建文档
                </button>
              </div>
            </div>
          ) : (
            <button
              className="wb-space-add"
              aria-label="新建会话"
              title="新建会话"
              onClick={() => quick(projectId)}
            >
              <Plus size={16} />
            </button>
          )}
        </div>
        <input
          ref={sideFile}
          type="file"
          hidden
          multiple
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
          onChange={(e) => {
            upload(Array.from(e.target.files || []));
            e.target.value = "";
          }}
        />
        <label className="wb-search">
          <Search size={16} />
          <input
            aria-label="搜索项目、会话与文件"
            placeholder="搜索工作内容"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="wb-nav-scroll">
          {results ? (
            <div className="wb-search-results">
              {results.map((r) => (
                <button
                  key={r.id}
                  onClick={() => {
                    r.kind === "document"
                      ? openDocument(r)
                      : r.kind === "conversation"
                        ? openConversation(r.id)
                        : quick(r.id);
                    setQuery("");
                  }}
                >
                  <span>{r.title}</span>
                  <small>
                    {projects.find((p) => p.id === r.project_id)?.title ||
                      "个人工作区"}{" "}
                    · {r.kind}
                  </small>
                  <small>{r.excerpt}</small>
                </button>
              ))}
            </div>
          ) : (
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={spaceTab}
                className="wb-space-list"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
                transition={{ duration: 0.16, ease: [0.2, 0, 0, 1] }}
              >
                {spaceTab === "文件" ? (
                  <>
                    {spaceDocs.map((d) => (
                      <div
                        className={"wb-space-row" + (doc?.id === d.id ? " selected" : "")}
                        key={d.id}
                      >
                        <button onClick={() => openDocument(d)}>
                          <FileText size={14} />
                          <span>{d.title}</span>
                        </button>
                        <button aria-label={"管理 " + d.title} onClick={() => setMenu(d)}>
                          <MoreHorizontal size={13} />
                        </button>
                      </div>
                    ))}
                    {!spaceDocs.length && (
                      <p className="wb-space-hint">
                        暂无文件，拖到页面任意位置即可上传，或
                        <button className="wb-space-upload-link" onClick={() => sideFile.current?.click()}>
                          上传文件
                        </button>
                      </p>
                    )}
                  </>
                ) : (
                  <>
                    {spaceConversations.map((c) => (
                      <div
                        className={"wb-space-row" + (conv?.id === c.id ? " selected" : "")}
                        key={c.id}
                      >
                        <button onClick={() => openConversation(c.id)}>
                          <MessageSquare size={14} />
                          <span>{c.title}</span>
                        </button>
                        <button aria-label={"管理 " + c.title} onClick={() => setMenu(c)}>
                          <MoreHorizontal size={13} />
                        </button>
                      </div>
                    ))}
                    {spaceCourts.map((c) => (
                      <div
                        className={"wb-space-row" + (courtSelection === c.id ? " selected" : "")}
                        key={c.id}
                      >
                        <button
                          aria-current={courtSelection === c.id ? "page" : undefined}
                          onClick={() => openCourt(projectId, c.id)}
                        >
                          <Gavel size={14} />
                          <span>{c.title}</span>
                        </button>
                      </div>
                    ))}
                    {!spaceConversations.length && !spaceCourts.length && (
                      <p className="wb-space-hint">发送第一条消息，开启会话。</p>
                    )}
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          )}
        </div>
        <div className="wb-sidebar-tools">
          <LayoutToolbar workspace={workspace} />
          {doc && !agentVisible && <button className="wb-desktop-only" onClick={()=>setAgentVisible(true)}><Sparkles size={16}/>{courtSelection ? "庭审" : "Agent"}</button>}
          {offline && <small>离线</small>}
        </div>
        <footer className="wb-nav-footer">
          <button onClick={() => navigate("/settings/extensions")}>
            <Sparkles size={17} />
            技能与插件
          </button>

          <button onClick={() => setDialog("migration")}>
            <Archive size={17} />
            本地旧资料
          </button>
          <div>
            <button
              aria-label="归档与回收站"
              onClick={() => setDialog("trash")}
            >
              <Trash2 size={16} />
            </button>
            <button onClick={() => navigate("/settings")}>
              <Settings size={16} />
              设置
            </button>
            <span>{username}</span>
          </div>
        </footer>
      </aside>
      {sidebar && (
        <button
          className="wb-sidebar-shade"
          aria-label="关闭导航"
          onClick={() => setSidebar(false)}
        />
      )}
      <main className="wb-main">
        <nav className="wb-mobile-tabs">
          <button data-tour="wb-nav-toggle" aria-label="打开导航" onClick={()=>setSidebar(true)}><Menu size={19}/></button>
          {["会话", "文档"].map((p) => (
            <button
              className={mobile === p ? "selected" : ""}
              key={p}
              aria-current={mobile === p ? "page" : undefined}
              onClick={() => {
                setMobile(p);
                if (p === "会话") setAgentVisible(true);
              }}
              disabled={p === "文档" && !doc}
            >
              {p}
            </button>
          ))}
        </nav>
        {(error || notice || uploading) && (
          <div className={"wb-banner " + (error ? "error" : "")} role="status">
            <span>{error || (uploading ? "正在上传并提取文件…" : notice)}</span>
            <button
              aria-label="关闭提示"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={14} />
            </button>
          </div>
        )}
        <div
          className={"wb-body" + (doc ? " wb-docked" : "")}
          data-agent-position={workspace.layout.agent}
          style={doc ? workspace.grid(agentVisible) : undefined}
        >
          {doc ? (
            <>
              <section className="wb-document-column">
                <nav className="wb-tabs">
                  {workspace.handle("document", "文档") }
                  {tabs.map((t) => (
                    <div
                      key={t.id}
                      className={t.id === doc.id ? "selected" : ""}
                    >
                      <button onClick={() => openDocument(t)}>
                        <FileText size={14} />
                        {t.title}
                      </button>
                      <button
                        aria-label={"关闭 " + t.title}
                        onClick={() => {
                          setTabs(tabs.filter((x) => x.id !== t.id));
                          if (doc.id === t.id)
                            setDoc(tabs.find((x) => x.id !== t.id));
                        }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </nav>
                <DocumentPane
                  key={doc.id}
                  document={doc}
                  user={username}
                  onSaved={saved}
                  onReference={reference}
                  onError={setError}
                />
              </section>
              {agentVisible && (
                <>
                  <div
                    className="wb-resizer"
                    role="separator"
                    aria-label="调整 Agent 面板大小"
                    aria-orientation={workspace.layout.agent === "top" || workspace.layout.agent === "bottom" ? "horizontal" : "vertical"}
                    aria-valuemin={25} aria-valuemax={65} aria-valuenow={workspace.layout.split}
                    tabIndex={0}
                    onKeyDown={e => {
                      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
                      e.preventDefault();
                      const leading = workspace.layout.agent === "left" || workspace.layout.agent === "top";
                      const forward = e.key === "ArrowRight" || e.key === "ArrowDown";
                      workspace.update({split:Math.max(25,Math.min(65,workspace.layout.split + (leading === forward ? 2 : -2)))});
                    }}
                    onPointerDown={e => e.currentTarget.setPointerCapture(e.pointerId)}
                    onPointerMove={e => {
                      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
                      const parent = e.currentTarget.parentElement!;
                      const documentRect = parent.querySelector(".wb-document-column")!.getBoundingClientRect();
                      const agentRect = parent.querySelector(".wb-agent")!.getBoundingClientRect();
                      const vertical = workspace.layout.agent === "top" || workspace.layout.agent === "bottom";
                      const start = vertical ? Math.min(documentRect.top,agentRect.top) : Math.min(documentRect.left,agentRect.left);
                      const total = vertical ? documentRect.height+agentRect.height : documentRect.width+agentRect.width;
                      let split = ((vertical ? e.clientY : e.clientX)-start)/total*100;
                      if (workspace.layout.agent === "right" || workspace.layout.agent === "bottom") split=100-split;
                      workspace.update({split:Math.max(25,Math.min(65,split))});
                    }}
                  />
                  {!courtSelection && chat}
                </>
              )}
            </>
          ) : courtSelection || conv || running ? (
            courtSelection ? null : chat
          ) : (
            <section className="wb-home">
              {project && (
                <header className="wb-project-head">
                  <h1>{project.title}</h1>
                  {project.data.desc && <p className="wb-project-description">{project.data.desc}</p>}
                </header>
              )}
              {composer}
              {!project ? (
                <section className="wb-home-projects">
                  <header className="wb-projects-head">
                    <div className="wb-projects-title-row">
                      <h2 className="wb-projects-title">项目</h2>
                      <div className="wb-projects-filter">
                        <button
                          className={projectFilter === "全部" ? "active" : ""}
                          onClick={() => setProjectFilter("全部")}
                        >
                          全部
                        </button>
                        <button
                          className={projectFilter === "最近" ? "active" : ""}
                          onClick={() => setProjectFilter("最近")}
                        >
                          最近
                        </button>
                      </div>
                    </div>
                    <button data-tour="wb-new-project" className="wb-primary wb-projects-new" onClick={createProject}>
                      <Plus size={15} />
                      新建项目
                    </button>
                  </header>
                  <div className="wb-project-cards">
                    {(projectFilter === "最近"
                      ? projects
                          .filter((p) => !p.data.archived)
                          .slice()
                          .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
                          .slice(0, 6)
                      : projects.filter((p) => !p.data.archived)
                    ).map((p, i) => (
                      <button
                        key={p.id}
                        className="wb-project-card"
                        style={{ "--i": i } as React.CSSProperties}
                        onClick={() => {
                          quick(p.id);
                          setDoc(undefined);
                        }}
                      >
                        <strong>{p.title}</strong>
                        {p.data.desc && <small className="wb-project-card-desc">{p.data.desc}</small>}
                        <span className="wb-project-card-meta">
                          最后修改 {new Date(p.updated_at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}{" "}
                          {new Date(p.updated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </button>
                    ))}
                    {!projects.filter((p) => !p.data.archived).length && (
                      <p className="wb-empty-hint">还没有项目，点击右上角「新建项目」开始归拢你的材料。</p>
                    )}
                  </div>
                </section>
              ) : (
                <div className="wb-home-sections">
                  <section>
                    <header>
                      <h2>项目文件</h2>
                      <button className="wb-mini-action" onClick={createDocument}>
                        <Plus size={14} />
                        新建文档
                      </button>
                    </header>
                    {projectDocs.slice(0, 5).map((d) => (
                      <button
                        className="wb-file-row"
                        key={d.id}
                        onClick={() => openDocument(d)}
                      >
                        <FileText size={17} />
                        <span>
                          {d.title}
                          <small>
                            {d.data.format?.toUpperCase()} · 版本 {d.revision}
                          </small>
                        </span>
                      </button>
                    ))}
                    {!projectDocs.length && (
                      <div className="wb-files-empty wb-home-empty">
                        <FolderOpen size={26} />
                        <strong>暂无项目文件</strong>
                        <p>拖拽文件到页面任意位置，或</p>
                        <label className="wb-files-upload">
                          <Upload size={14} />
                          上传材料
                          <input
                            type="file"
                            hidden
                            multiple
                            accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                            onChange={(e) => {
                              upload(Array.from(e.target.files || []));
                              e.target.value = "";
                            }}
                          />
                        </label>
                      </div>
                    )}
                  </section>
                  <section>
                    <header>
                      <h2>会话</h2>
                      <div className="wb-section-actions">
                        <button className="wb-mini-action" onClick={() => quick(projectId)}>
                          <Plus size={14} />
                          新建会话
                        </button>
                        <button className="wb-mini-action" onClick={() => openCourt(projectId)}>
                          <Gavel size={14} />
                          新建庭审
                        </button>
                      </div>
                    </header>
                    {spaceConversations.slice(0, 5).map((c) => (
                      <button
                        className="wb-file-row"
                        key={c.id}
                        onClick={() => openConversation(c.id)}
                      >
                        <MessageSquare size={17} />
                        <span>
                          {c.title}
                          <small>
                            {new Date(c.updated_at).toLocaleDateString()}
                          </small>
                        </span>
                      </button>
                    ))}
                    {spaceCourts.slice(0, 3).map((c) => (
                      <button
                        className="wb-file-row"
                        key={c.id}
                        onClick={() => openCourt(projectId, c.id)}
                      >
                        <Gavel size={17} />
                        <span>
                          {c.title}
                          <small>
                            {new Date(c.updated_at).toLocaleDateString()}
                          </small>
                        </span>
                      </button>
                    ))}
                    {!spaceConversations.length && !spaceCourts.length && (
                      <p className="wb-empty-hint">
                        发送第一条消息，开启会话。
                      </p>
                    )}
                  </section>
                </div>
              )}
            </section>
          )}
          {courtSelection && chat}
        </div>
      </main>
      {appDrag && (
        <div className="wb-drop-overlay" aria-hidden="true">
          <strong>松开，上传到「{project?.title || "个人工作区"}」</strong>
        </div>
      )}
      {workspace.targets}
      {menu && (
        <div className="wb-modal-backdrop" onClick={() => setMenu(undefined)}>
          <section
            className="wb-modal wb-small-modal"
            role="dialog"
            aria-modal="true"
            aria-label="管理内容"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <h2>{menu.title}</h2>
              <button aria-label="关闭" onClick={() => setMenu(undefined)}>
                <X size={18} />
              </button>
            </header>
            <button
              onClick={() => {
                // 必须同时收起菜单：否则两个 .wb-modal-backdrop 同处一档，谁在上只由 DOM 顺序决定，
                // 而且下层的菜单遮罩还挂着「点一下关掉」的行为。
                setTextDialog({
                  title: "新名称",
                  initial: menu.title,
                  submit: (title) => {
                    mutate(menu, { title });
                    setTextDialog(undefined);
                  },
                });
                setMenu(undefined);
              }}
            >
              重命名
            </button>
            <button
              onClick={() => mutate(menu, { favorite: !menu.data.favorite })}
            >
              {menu.data.favorite ? "取消收藏" : "收藏"}
            </button>
            <button
              onClick={() => mutate(menu, { archived: !menu.data.archived })}
            >
              {menu.data.archived ? "取消归档" : "归档"}
            </button>
            {menu.kind !== "project" && (
              <label>
                移动到项目
                <select
                  value={menu.project_id || ""}
                  onChange={(e) =>
                    mutate(menu, { project_id: e.target.value || null })
                  }
                >
                  <option value="">个人工作区</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              className="wb-danger"
              onClick={async () => {
                try {
                  await api(
                    `/${menu.kind === "project" ? "projects" : menu.kind === "document" ? "documents" : "conversations"}/${menu.id}`,
                    "DELETE",
                  );
                  if (doc?.id === menu.id) setDoc(undefined);
                  if (conv?.id === menu.id) setConv(undefined);
                  setMenu(undefined);
                  reload();
                } catch (e) {
                  setError(e.message);
                }
              }}
            >
              移入回收站（保留 30 天）
            </button>
          </section>
        </div>
      )}
      {textDialog && (
        <TextDialog
          title={textDialog.title}
          initial={textDialog.initial}
          withDescription={textDialog.withDescription}
          onSubmit={textDialog.submit}
          onClose={() => setTextDialog(undefined)}
        />
      )}
      {dialog && (
        <ManageDialog
          tab={dialog}
          skills={skills}
          connectors={connectors}
          projects={projects}
          conversations={conversations}
          documents={documents}
          onClose={() => setDialog("")}
          onReload={reload}
          onError={setError}
        />
      )}
    </div>
  );
}
