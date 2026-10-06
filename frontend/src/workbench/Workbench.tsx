import { motion } from "motion/react";
import React, { useEffect, useEffectEvent, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Plus,
  Search,
  Folder,
  History,
  MessageSquare,
  FileText,
  ChevronDown,
  Columns2,
  Maximize2,
  Minimize2,
  Link2,
  PenLine,
  RefreshCw,
  Star,
  Settings,
  Sparkles,
  X,
  Gavel,
  Archive,
  MoreHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import {
  api,
  cached,
  remember,
  Item,
  Reference,
  withoutTitle,
} from "./client";
import { aggregateActivity } from "./activity";
import { Composer, Draft } from "./Composer";
import { DocumentPane } from "./DocumentPane";
import { Sidebar } from "./Sidebar";
import { useSuggestions } from "./useSuggestions";
import { UpgradeNudgeGate } from "./UpgradeNudgeGate";
import {
  fetchAccountProfile,
  fetchMyCredits,
  type AccountProfile,
} from "../services/api";
import { useWorkbenchIndex } from "./useWorkbenchIndex";
import { HistoryMenu } from "./HistoryMenu";
import { HomeView } from "./HomeView";
import { ManageDialog } from "./ManageDialog";
import { ManageMenu } from "./ManageMenu";
import "./workbench.css";
import { getBinding, matchKeys, SHORTCUT_IDS } from "../lib/shortcuts";
import { useBackButton } from "../hooks/useBackButton";
import { useWorkspaceLayout } from "./WorkspaceLayout";
import { describeError } from "../lib/errors";
import { useT } from "../i18n";
import { SessionView } from "./SessionView";
import { TextDialog } from "./TextDialog";
import { TabMenuItem, TabStrip } from "./TabStrip";
import {
  PERSONAL,
  TabBook,
  TabRef,
  ensureTab,
  findTab,
  loadTabs,
  patchTab,
  purgeTabs,
  moveTabToSpace,
  removeTab,
  saveTabs,
  spaceKey,
  tabKey,
  tabTitle,
  tabsOf,
  withTabs,
} from "./tabs";

export default function Workbench({ username }: { username: string }) {
  const [textDialog, setTextDialog] = useState<{
    title: string;
    initial?: string;
    withDescription?: boolean;
    submit: (s: string, desc?: string) => void | Promise<void>;
  }>();
  const workspace = useWorkspaceLayout(username);
  const [error, setError] = useState("");
  // 子组件与各处 catch 报上来的原始错误统一过一遍翻译：浏览器网络层抛的是英文原文，
  // 界面只该显示中文。也把它交给子组件的 onError，避免每个调用点各写一遍。
  const reportError = React.useCallback((value: unknown) => setError(describeError(value)), []);
  const {
    projects,
    conversations,
    documents,
    skills,
    connectors,
    courtItems,
    offline,
    reload,
  } = useWorkbenchIndex(username, setError);
  const { t } = useT();
  const suggestions = useSuggestions();
  // credits 耗尽时的升级提示：仅非 max/business、非运维豁免账号；localStorage 冷却门
  // ——勾选「不再提醒」永久关闭，否则 14 天只提醒一次，不高频打扰。
  const [nudgeOpen, setNudgeOpen] = useState(false);
  const navigate = useNavigate(),
    location = useLocation(),
    routeUuid = useParams().uuid,
    [params] = useSearchParams();
  // 账户资料（侧栏底部头像/徽标）：挂载时取一次；路径变化（含从设置页回来）时刷新，
  // 这样改完自定义 ID/头像不需要刷新整页。
  const [accountProfile, setAccountProfile] = useState<AccountProfile | null>(null);
  // credits 余额：侧栏显示与耗尽弹窗共用一份数据；余额会被后台任务扣减，
  // 挂载与路径变化时刷新一次即可，不必轮询。
  const [credits, setCredits] = useState<{ balance: number | null; exempt: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void fetchAccountProfile().then((data) => {
      if (!cancelled) setAccountProfile(data);
    });
    void fetchMyCredits()
      .then((data) => {
        if (!cancelled) {
          setCredits({
            balance: typeof data.credits === "number" ? data.credits : null,
            exempt: Boolean(data.exempt),
          });
        }
      })
      .catch(() => undefined);
    const onProfileUpdated = (event: Event) => {
      const detail = (event as CustomEvent<AccountProfile>).detail;
      if (detail) setAccountProfile(detail);
    };
    // 设置弹窗开着时背景路径不变（/home），pathname effect 不会重跑；
    // 设置页保存成功后会广播新资料，这里直接吃。
    window.addEventListener("lawver:profile-updated", onProfileUpdated);
    return () => {
      cancelled = true;
      window.removeEventListener("lawver:profile-updated", onProfileUpdated);
    };
  }, [location.pathname]);
  // 路径即状态：/home、/project/:uuid、/conversation/:uuid、/court/:uuid。
  const isCourtPath = location.pathname.startsWith("/court/");
  const isConversationPath = location.pathname.startsWith("/conversation/");
  const isProjectPath = location.pathname.startsWith("/project/");
  const courtSelection = isCourtPath ? routeUuid : undefined;
  const [courtReference,setCourtReference] = useState<Reference>();
  const [projectId, setProjectId] = useState<string>(),
    [conv, setConv] = useState<Item>(),
    [doc, setDoc] = useState<Item>(),
    [draft, setDraft] = useState<Draft>({ text: "", references: [] }),
    [run, setRun] = useState<Item>(),
    [events, setEvents] = useState<any[]>([]),
    [live, setLive] = useState("");
  // 标签页：一个空间一套（个人工作区/项目），文档状态跟随标签而不是全局。
  const [tabBook, setTabBook] = useState<TabBook>(() => loadTabs(username));
  const [tabRuns, setTabRuns] = useState<
    Record<string, { id: string; status: string; unseen?: boolean }>
  >({});
  const [notice, setNotice] = useState(""),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<any[]>(),
    [sidebar, setSidebar] = useState(false),
    [mobile, setMobile] = useState("会话"),
    [dialog, setDialog] = useState(""),
    [menu, setMenu] = useState<Item>(),
    [projectFilter, setProjectFilter] = useState("全部" as "全部" | "最近"),
    [history, setHistory] = useState(false),
    [appDrag, setAppDrag] = useState(false),
    [agentVisible, setAgentVisible] = useState(true),
    [mode, setMode] = useState("default"),
    [ocp, setOcp] = useState(true),
    [uploading, setUploading] = useState(false),
    [resizing, setResizing] = useState(false);
  const dragDepth = useRef(0),
    sideFile = useRef<HTMLInputElement>(null),
    historyButton = useRef<HTMLButtonElement>(null);
  const active = useRef<string>(undefined),
    draftKey = conv?.id || "new:" + String(projectId),
    draftReady = useRef(""),
    draftValue = useRef(draft),
    // 贴底跟随：true 时流式输出会把消息区钉在底部；用户上翻即脱钩。
    stick = useRef(true),
    // 刚发送的运行落在哪个会话：路由同步触发 loadConversation 时据此贴底而不是恢复存档位置。
    followRun = useRef<string>(undefined),
    scroll = useRef<HTMLDivElement>(null);
  // 只在这里维护 active.current：它标记「当前会话身份」，用于丢弃过期的会话加载。
  // 曾经在渲染期写 active.current = conv?.id，任何一次无关重渲染都会把正在加载的会话判成过期，
  // 于是会话状态与标签一起丢掉。
  draftValue.current = draft;
  // run 的渲染期镜像：异步回调里判断「此刻的运行」要用最新值，不能用闭包捕获的旧值。
  const runValue = useRef<Item>(undefined);
  runValue.current = run;
  // 活动标签由路由决定：/conversation/:id、/court/:id，其余路径都是该空间的「新会话」标签。
  const documentCache = useRef<Record<string, Item>>({}),
    activeKeyRef = useRef("");
  const space = spaceKey(projectId),
    spaceTabs = tabsOf(tabBook, space),
    activeTabKey =
      isConversationPath && routeUuid
        ? tabKey({ kind: "conversation", id: routeUuid })
        : isCourtPath && routeUuid && routeUuid !== "new"
          ? tabKey({ kind: "court", id: routeUuid })
          : tabKey({ kind: "new", id: "" }),
    activeTab = findTab(tabBook, space, activeTabKey),
    // 主区内容由活跃标签决定：新会话标签永远显示首页，会话标签显示会话，
    // 哪怕上一个会话的任务还在跑（进度与完成由标签徽标提示）。
    activeIsSession = isConversationPath || isCourtPath || (!!activeTab && activeTab.kind !== "new"),
    showDoc = !!doc && !activeTab?.docHidden,
    fullScreen = !!activeTab?.doc && !!activeTab?.docHidden;
  // 运行状态的写入发生在异步回调里，用一个 ref 读「此刻」的当前标签。
  activeKeyRef.current = activeTabKey;
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
      collapseDocument();
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
  // 首页问候语按本地时间走，避免固定文案显得像模板。
  const greeting = (() => {
      const hour = new Date().getHours();
      if (hour < 6) return t("workbench.home.greetingNight");
      if (hour < 11) return t("workbench.home.greetingMorning");
      if (hour < 13) return t("workbench.home.greetingNoon");
      if (hour < 18) return t("workbench.home.greetingAfternoon");
      return t("workbench.home.greetingEvening");
    })(),
    recentSessions = [
      ...spaceConversations.map((item) => ({
        tab: { kind: "conversation", id: item.id } as TabRef,
        item,
      })),
      ...spaceCourts.map((item) => ({
        tab: { kind: "court", id: item.id } as TabRef,
        item,
      })),
    ]
      .sort((a, b) => new Date(b.item.updated_at).getTime() - new Date(a.item.updated_at).getTime())
      .slice(0, 6);

  function createDocument() {
    api<Item>("/documents", "POST", {
      title: t("workbench.manage.untitledDocument"),
      project_id: projectId,
    })
      .then((d) => {
        saved(d);
        openDocument(d);
      })
      .catch((e) => reportError(e));
  }
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  // 路由是空间/会话/庭审的唯一事实源：路径变化时同步内部状态并加载会话。
  // 只有庭审路径才读 ?project=，其余路径上它变化不触发同步。
  const pathname = location.pathname;
  const courtProject = isCourtPath ? params.get("project") || "" : "";
  // 加载会话要读此刻的 conv / run / offline 等状态，但只应由路由变化触发。
  const loadRouteConversation = useEffectEvent((id: string) => {
    void loadConversation(id);
  });
  useEffect(() => {
    if (isProjectPath && routeUuid) {
      setProjectId(routeUuid);
      setTabBook((book) => ensureTab(book, spaceKey(routeUuid), { kind: "new", id: "" }));
    } else if (isCourtPath) {
      setCourtReference(undefined);
      setSidebar(false);
      setMobile("会话");
      setAgentVisible(true);
      if (courtProject) setProjectId(courtProject);
    } else if (pathname === "/home") {
      setProjectId(undefined);
      setTabBook((book) => ensureTab(book, PERSONAL, { kind: "new", id: "" }));
    }
    if (isConversationPath && routeUuid) loadRouteConversation(routeUuid);
  }, [pathname, routeUuid, courtProject, isProjectPath, isCourtPath, isConversationPath]);
  // 浏览器返回离开会话路径时清掉会话态，让空间首页正常显示。
  // 进行中的任务保留会话态（完成时轮询会刷新它）：这是导航那一刻的判断，任务结束本身不触发清理。
  const releaseConversation = useEffectEvent(() => {
    if (!running) setConv(undefined);
  });
  // pathname 是触发条件：每次导航都重新判断一次。
  useEffect(() => {
    if (!isConversationPath && !courtSelection) releaseConversation();
  }, [pathname, isConversationPath, courtSelection]);
  // 草稿按 draftKey 读取；key 已经变了（或组件卸载）时丢弃这次读取结果。
  useEffect(() => {
    let canceled = false;
    draftReady.current = "";
    setDraft({ text: "", references: [] });
    cached<Draft>(username, "draft:" + draftKey).then((d) => {
      if (canceled) return;
      setDraft(d || { text: "", references: [] });
      draftReady.current = draftKey;
    });
    return () => {
      canceled = true;
    };
  }, [draftKey, username]);
  function updateDraft(d: Draft) {
    setDraft(d);
    if (draftReady.current === draftKey)
      remember(username, "draft:" + draftKey, d).catch(() =>
        setError(t("workbench.shell.draftCacheFailed")),
      );
  }
  useEffect(() => {
    if (!query) {
      setResults(undefined);
      return;
    }
    const timer = setTimeout(
      () =>
        api<any[]>(
          "/search?kind=document&space=" +
            encodeURIComponent(projectId || "personal") +
            "&q=" +
            encodeURIComponent(query),
        )
          .then(setResults)
          .catch((e) => reportError(e)),
      180,
    );
    return () => clearTimeout(timer);
  }, [query, projectId, reportError]);
  // 运行状态只有这一个写入口：终止状态且该标签不是当前标签时留下未读标记。
  function recordRun(key: string, id: string, status: string) {
    const terminal = !["queued", "running", "waiting_confirmation"].includes(status);
    setTabRuns((prev) => ({
      ...prev,
      [key]: {
        id,
        status,
        unseen: prev[key]?.unseen || (terminal && key !== activeKeyRef.current),
      },
    }));
  }
  // 轮询的生命周期只跟「哪个运行、是否还在跑」走：运行对象每轮都会换新，状态也会在活跃态之间切换
  // （running ⇄ waiting_confirmation），这些都不该重启轮询、清空已收到的事件。
  const runId = run?.id;
  // 运行挂在会话上而不是视图上：换标签只暂停轮询，标签徽标由后台轮询跟进。
  const runConversation = run?.parent_id;
  // 下面几个 effect event 在轮询回调里按「此刻」读取状态：
  // 运行途中切换文档、切换语言都不重启轮询，也不会用到轮询开始时的旧值。
  const trackRunStart = useEffectEvent(() => {
    if (run) recordRun("conversation:" + run.parent_id, run.id, run.data.status);
  });
  const applyRunEvent = useEffectEvent((event: any) => {
    if (!["document", "proposal"].includes(event.type)) return;
    reload();
    // 只刷新此刻打开的那篇文档。请求回来时用户若已换了文档，只更新缓存，不把窗格切回去。
    if (event.type === "proposal" && doc?.id === event.content.document_id)
      api<Item>("/documents/" + doc.id)
        .then((d) => {
          documentCache.current[d.id] = d;
          setDoc((current) => (current?.id === d.id ? d : current));
        })
        .catch(() => {});
  });
  const notifyPollInterrupted = useEffectEvent(() =>
    setNotice(t("workbench.session.connectInterrupted")),
  );
  useEffect(() => {
    if (!runId || !running) return;
    let canceled = false,
      last = 0;
    const owner = "conversation:" + runConversation;
    let output = "";
    setLive("");
    setEvents([]);
    trackRunStart();
    async function poll() {
      try {
        const data = await api(`/runs/${runId}/events?after=${last}`);
        if (canceled) return;
        for (const event of data.events) {
          last = event.seq;
          if (event.type === "content") output += event.content;
          if (event.type === "content_replace") output = event.content;
          applyRunEvent(event);
        }
        setLive(output);
        setEvents((e) => [...e, ...data.events].slice(-500));
        if (!data.has_more) {
          setRun(data.run);
          recordRun(owner, runId, data.run.data.status);
        }
        if (
          !data.has_more &&
          !["queued", "running", "waiting_confirmation"].includes(
            data.run.data.status,
          )
        ) {
          if (active.current === data.run.parent_id) {
            const c = await api<Item>("/conversations/" + data.run.parent_id);
            remember(username, "conversation:" + c.id, c);
            // 等待期间用户可能已切到别的会话：只在它仍是当前会话时替换视图。
            if (active.current === c.id) {
              setConv(c);
              setLive("");
            }
          }
          reload();
          return;
        }
        setTimeout(poll, data.has_more ? 50 : 1500);
      } catch {
        if (!canceled) {
          notifyPollInterrupted();
          setTimeout(poll, 2500);
        }
      }
    }
    poll();
    return () => {
      canceled = true;
    };
  }, [runId, runConversation, running, reload, username]);
  // 终态任务补拉一次事件：让「查看执行过程」在重新进入会话后仍能展开，不触发额外刷新。
  const hasEvents = events.length > 0;
  useEffect(() => {
    if (!runId || running || hasEvents) return;
    let canceled = false;
    api<{ events: any[] }>(`/runs/${runId}/events?after=0`)
      .then((data) => {
        if (!canceled && data.events?.length)
          setEvents((prev) => (prev.length ? prev : data.events.slice(-500)));
      })
      .catch(() => {});
    return () => {
      canceled = true;
    };
  }, [runId, running, hasEvents]);
  // 后台标签的运行跟进：低频拉状态，完成或失败时在该标签上留一个未读标记。
  const activeRunKey = run ? "conversation:" + run.parent_id : "";
  const backgroundRuns = Object.entries(tabRuns).filter(
    ([key, entry]) =>
      key !== activeTabKey &&
      key !== activeRunKey &&
      ["queued", "running", "waiting_confirmation"].includes(entry.status),
  );
  const hasBackgroundRuns = backgroundRuns.length > 0;
  // 每次 tick 读此刻的后台运行列表：列表内容变化（含换了运行 id）不必重置计时器，也不会拉到旧 id。
  const pollBackgroundRuns = useEffectEvent(() => {
    for (const [key, entry] of backgroundRuns)
      api<Item>("/runs/" + entry.id)
        .then((attached) => recordRun(key, entry.id, attached.data.status))
        .catch(() => {});
  });
  useEffect(() => {
    if (!hasBackgroundRuns) return;
    const timer = setInterval(() => pollBackgroundRuns(), 5000);
    return () => clearInterval(timer);
  }, [hasBackgroundRuns]);
  useEffect(() => {
    // 回到该标签即视为已读。
    setTabRuns((prev) =>
      prev[activeTabKey]?.unseen
        ? { ...prev, [activeTabKey]: { ...prev[activeTabKey], unseen: false } }
        : prev,
    );
  }, [activeTabKey]);
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
      setProjectId(c.project_id || undefined);
      setSidebar(false);
      setMobile("会话");
      setTabBook((book) =>
        ensureTab(book, spaceKey(c.project_id || undefined), {
          kind: "conversation",
          id: c.id,
        }),
      );
      // 重新进入同一会话时不要清掉进行中的任务，否则会掐断流式轮询。
      if (!run || run.parent_id !== id) {
        setLive("");
        setRun(undefined);
        setEvents([]);
      }
      const runId = c.data.messages?.at(-1)?.run_id;
      if (runId && !offline)
        api<Item>("/runs/" + runId)
          .then((attached) => {
            // 慢响应到达时用户可能已切到别的会话，或已在本会话发起新运行：
            // 过期的补拉不得覆盖当前 run，否则轮询与流式展示被冻结。
            if (active.current !== id) return;
            const current = runValue.current;
            if (current && current.parent_id === id && current.id !== attached.id) return;
            setRun(attached);
            // 只有真正采纳 attached 时才登记：保住 current 的话，把 tabRuns 覆盖成
            // 过期 attached.id 会让该标签在后台轮询里跟踪错对象，丢未读标记。
            recordRun("conversation:" + id, attached.id, attached.data.status);
          })
          .catch(() => {});
      const position = await cached<number>(username, "scroll:" + id);
      requestAnimationFrame(() => {
        if (!scroll.current) return;
        // 首页发起新会话会立刻换路径、触发这次加载：贴底看运行，不恢复（不存在的）存档位置。
        if (followRun.current === id) {
          followRun.current = undefined;
          scroll.current.scrollTop = scroll.current.scrollHeight;
        } else scroll.current.scrollTop = position || 0;
      });
    } catch (e) {
      reportError(e);
    }
  }
  // UI 入口只负责改路径；会话加载由路由同步 effect 驱动 loadConversation。
  function openConversation(id: string) {
    navigate("/conversation/" + encodeURIComponent(id));
  }
  // 打开文档 = 把文档挂到当前标签上；没有文档标签条，一个标签同时只显示一篇。
  function attachDocument(d: Item) {
    documentCache.current[d.id] = d;
    setDoc(d);
    setTabBook((book) => patchTab(book, space, activeTabKey, { doc: d.id, docHidden: undefined }));
    setMobile("文档");
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
      attachDocument(d);
      setProjectId(d.project_id || undefined);
      setSidebar(false);
    } catch (e) {
      reportError(e);
    }
  }
  function saved(d: Item) {
    attachDocument(d);
    remember(username, "document:" + d.id, d);
    reload();
  }
  // 进入某个空间的首页时取一次工作建议；缓存按空间隔离，换台不重复请求。
  // 是否已缓存是读取时的判断，缓存本身变化不触发加载。
  const loadSuggestions = useEffectEvent((target: string) => {
    if (!suggestions.loaded(target)) void suggestions.load(target, false);
  });
  useEffect(() => {
    if (isConversationPath || isCourtPath) return;
    loadSuggestions(space);
  }, [space, isConversationPath, isCourtPath]);
  // 标签切换即换文档：目标标签有文档就取回（内存命中优先），没有就清空文档窗格。
  // 标签簿按读取时的最新值查；它的其他变化（排序、新开标签、挂文档）不触发换文档。
  const documentOfTab = useEffectEvent(
    (targetSpace: string, key: string) => findTab(tabBook, targetSpace, key)?.doc,
  );
  useEffect(() => {
    const wanted = documentOfTab(space, activeTabKey);
    if (!wanted) {
      setDoc(undefined);
      return;
    }
    const known = documentCache.current[wanted];
    if (known) {
      setDoc(known);
      return;
    }
    let canceled = false;
    (async () => {
      try {
        let d: Item;
        try {
          d = await api<Item>("/documents/" + wanted);
        } catch (e) {
          d = await cached<Item>(username, "document:" + wanted);
          if (!d) throw e;
        }
        if (canceled) return;
        documentCache.current[d.id] = d;
        setDoc(d);
      } catch {
        if (!canceled) setDoc(undefined);
      }
    })();
    return () => {
      canceled = true;
    };
  }, [space, activeTabKey, username]);
  // 当前路由指向的会话是否已被删除，只在索引列表刷新后判断，路由变化本身不触发：
  // 刚新建的会话在索引刷新前还不在列表里，不能当成已删除。
  const leaveDeletedSession = useEffectEvent((alive: (tab: TabRef) => boolean) => {
    if ((!isConversationPath && !isCourtPath) || !routeUuid || routeUuid === "new") return;
    if (!alive({ kind: isCourtPath ? "court" : "conversation", id: routeUuid }))
      navigate(projectId ? "/project/" + encodeURIComponent(projectId) : "/home");
  });
  // 会话/庭审被删除后剔除残留标签；当前标签被清掉时把路由带回空间首页。
  useEffect(() => {
    if (!conversations.length && !courtItems.length) return;
    const alive = (tab: TabRef) =>
      tab.kind === "court"
        ? courtItems.some((item) => item.id === tab.id)
        : conversations.some((item) => item.id === tab.id);
    setTabBook((book) => {
      let next = book;
      for (const name of Object.keys(book)) next = purgeTabs(next, name, alive);
      return next;
    });
    leaveDeletedSession(alive);
  }, [conversations, courtItems]);
  useEffect(() => {
    saveTabs(username, tabBook);
  }, [username, tabBook]);
  // 标签即会话入口：已打开的会话只聚焦既有标签，绝不开第二个。
  function activateTab(tab: TabRef) {
    if (tab.kind === "conversation") openConversation(tab.id);
    else if (tab.kind === "court") openCourt(projectId, tab.id);
    else navigate(projectId ? "/project/" + encodeURIComponent(projectId) : "/home");
  }
  /**
   * 在标签里选一个会话（历史菜单、首页最近会话）：
   * 未打开的会话由当前标签接管（标签留在原位、换掉它显示的会话），
   * 已打开的会话直接跳到它所在的标签，绝不重复开标签。
   */
  function pickSession(tab: TabRef) {
    const existing = spaceTabs.find((item) => tabKey(item) === tabKey(tab));
    if (existing) {
      activateTab(existing);
      return;
    }
    // 接管 = 换掉当前标签记录的会话；文档跟随会话，所以顺带清掉原文档。
    setTabBook((book) =>
      withTabs(
        book,
        space,
        tabsOf(book, space).map((item) =>
          tabKey(item) === activeTabKey ? { kind: tab.kind, id: tab.id } : item,
        ),
      ),
    );
    if (tab.kind === "court") openCourt(projectId, tab.id);
    else openConversation(tab.id);
  }
  function closeTab(tab: TabRef) {
    const key = tabKey(tab);
    const list = tabsOf(tabBook, space);
    const index = list.findIndex((item) => tabKey(item) === key);
    const neighbour = list[index + 1] || list[index - 1];
    setTabBook((book) => removeTab(book, space, key));
    if (key === activeTabKey) {
      if (neighbour) activateTab(neighbour);
      else navigate(space === PERSONAL ? "/home" : "/project/" + encodeURIComponent(space));
    }
  }
  function closeOtherTabs(tab: TabRef) {
    const keep = tabKey(tab);
    setTabBook((book) =>
      withTabs(
        book,
        space,
        tabsOf(book, space).filter((item) => tabKey(item) === keep),
      ),
    );
    if (keep !== activeTabKey) activateTab(tab);
  }
  function copyTabLink(tab: TabRef) {
    const path =
      tab.kind === "court"
        ? "/court/" +
          encodeURIComponent(tab.id) +
          (space === PERSONAL ? "" : "?project=" + encodeURIComponent(space))
        : "/conversation/" + encodeURIComponent(tab.id);
    const link = new URL(path, window.location.origin).href;
    navigator.clipboard
      ?.writeText(link)
      .then(() => setNotice(t("workbench.shell.linkCopied")))
      .catch(() => setNotice(t("workbench.shell.linkCopyFailed", { link })));
  }
  // 会话全屏 ⇄ 并排：收起文档窗格但保持文档打开，侧栏文件选中态随之清除。
  function toggleScreen() {
    if (!activeTab?.doc) return;
    const next = !activeTab.docHidden;
    setTabBook((book) => patchTab(book, space, activeTabKey, { docHidden: next || undefined }));
    setMobile(next ? "会话" : "文档");
  }
  function collapseDocument() {
    setTabBook((book) => patchTab(book, space, activeTabKey, { docHidden: true }));
    setMobile("会话");
  }
  function openDocumentById(id: string) {
    const known =
      documentCache.current[id] || documents.find((item) => item.id === id);
    if (known) void openDocument(known);
  }
  function removeItem(item: Item) {
    const family =
      item.kind === "project"
        ? "projects"
        : item.kind === "document"
          ? "documents"
          : "conversations";
    return api("/" + family + "/" + item.id, "DELETE")
      .then(() => {
        if (doc?.id === item.id) setDoc(undefined);
        if (conv?.id === item.id) setConv(undefined);
        if (item.kind === "conversation")
          setTabBook((book) => removeTab(book, space, tabKey({ kind: "conversation", id: item.id })));
        setMenu(undefined);
        reload();
      })
      .catch((e) => reportError(e));
  }
  function renameItem(item: Item) {
    setTextDialog({
      title: t("workbench.manage.newName"),
      initial: item.title,
      submit: (title) => {
        void mutate(item, { title });
        setTextDialog(undefined);
      },
    });
    setMenu(undefined);
  }
  // 归档与删除一样关掉标签：归档表示「不再在当前范围里出现」。
  function archiveItem(item: Item) {
    const archived = !item.data.archived;
    void mutate(item, { archived }).then(() => {
      if (archived && item.kind === "conversation")
        setTabBook((book) =>
          removeTab(book, space, tabKey({ kind: "conversation", id: item.id })),
        );
    });
  }
  function applySuggestion(item: { title: string; prompt: string }) {
    updateDraft({
      ...draftValue.current,
      text: draftValue.current.text.trim()
        ? draftValue.current.text + "\n" + item.prompt
        : item.prompt,
    });
    requestAnimationFrame(() =>
      document.querySelector<HTMLTextAreaElement>('[data-tour="wb-composer"] textarea')?.focus(),
    );
  }
  function openHistory() {
    setHistory(true);
  }
  function tabMenuItems(tab: TabRef): TabMenuItem[] {
    const item =
      tab.kind === "new"
        ? undefined
        : (tab.kind === "court" ? courtItems : conversations).find(
            (entry) => entry.id === tab.id,
          );
    const items: TabMenuItem[] = [];
    if (item && item.kind === "conversation") {
      items.push({ label: t("workbench.manage.rename"), icon: <PenLine size={14} />, onSelect: () => renameItem(item) });
      items.push({
        label: item.data.favorite ? t("workbench.manage.unfavorite") : t("workbench.manage.favorite"),
        icon: <Star size={14} />,
        onSelect: () => void mutate(item, { favorite: !item.data.favorite }),
      });
      items.push({
        label: item.data.archived ? t("workbench.manage.unarchive") : t("workbench.manage.archive"),
        icon: <Archive size={14} />,
        onSelect: () => archiveItem(item),
      });
    }
    if (tab.kind !== "new")
      items.push({
        label: t("workbench.tabs.copyLink"),
        icon: <Link2 size={14} />,
        onSelect: () => copyTabLink(tab),
      });
    items.push({ label: t("workbench.tabs.closeTab"), icon: <X size={14} />, onSelect: () => closeTab(tab) });
    items.push({
      label: t("workbench.tabs.closeOthers"),
      icon: <Minimize2 size={14} />,
      onSelect: () => closeOtherTabs(tab),
    });
    if (item && item.kind === "conversation")
      items.push({
        label: t("workbench.manage.trash"),
        icon: <Trash2 size={14} />,
        danger: true,
        onSelect: () => void removeItem(item),
      });
    return items;
  }
  // 快捷键监听只注册一次；按下时用此刻的空间新建会话。
  const newSessionFromShortcut = useEffectEvent(() => quick(projectId));
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (matchKeys(e, getBinding(SHORTCUT_IDS.sessionNew))) {
        e.preventDefault();
        newSessionFromShortcut();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  // 新建会话 = 打开该空间的「新会话」标签，不关闭当前标签。
  function quick(pid?: string) {
    active.current = undefined;
    setDoc(undefined);
    setConv(undefined);
    setRun(undefined);
    setLive("");
    setEvents([]);
    setProjectId(pid);
    setMobile("会话");
    setSidebar(false);
    setTabBook((book) => ensureTab(book, spaceKey(pid), { kind: "new", id: "" }));
    navigate(pid ? "/project/" + encodeURIComponent(pid) : "/home");
  }
  // 庭审是独立路径；项目上下文用 query 携带（新建庭审时定位所属空间）。
  function openCourt(pid: string | undefined, id = "new") {
    if (id !== "new")
      setTabBook((book) => ensureTab(book, spaceKey(pid), { kind: "court", id }));
    navigate("/court/" + encodeURIComponent(id) + (pid ? "?project=" + encodeURIComponent(pid) : ""));
  }
  function createProject() {
    setTextDialog({
      title: t("workbench.sidebar.newProject"),
      withDescription: true,
      submit: async (title, desc) => {
        try {
          const p = await api<Item>("/projects", "POST", { title, desc });
          setTextDialog(undefined);
          await reload();
          quick(p.id);
        } catch (e) {
          reportError(e);
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
      setTabBook((book) =>
        ensureTab(book, spaceKey(projectId), { kind: "conversation", id: c.id }),
      );
      setConv(await api("/conversations/" + c.id));
      setRun(r);
      recordRun("conversation:" + c.id, r.id, r.data.status);
      setAgentVisible(true);
      // 用户刚发的消息和运行都长在消息流末尾：立即贴底，否则长会话里发起的运行根本看不见。
      stick.current = true;
      followRun.current = c.id;
      requestAnimationFrame(() => {
        const el = scroll.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
      // 会话已落地，把地址换成可分享的会话路径（replace，避免返回键绕回首页草稿）。
      navigate("/conversation/" + encodeURIComponent(c.id), { replace: true });
      reload();
    } catch (e) {
      reportError(e);
    }
  }
  async function upload(files: File[]) {
    setUploading(true);
    // 逐文件处理：一个文件失败不该把剩下的静默丢掉，也要逐条给出原因——
    // 批量选中的文件里混一个超限的，其余合法文件全不上传，用户会以为「都传过了」。
    const failures: string[] = [];
    const renamed: string[] = [];
    let uploaded = 0;
    for (const f of files) {
      const body = new FormData();
      body.append("file", f);
      if (projectId) body.append("project_id", projectId);
      try {
        const d = await api<Item>("/documents/upload", "POST", body);
        uploaded += 1;
        if (d.title !== f.name) renamed.push(`${f.name} → ${d.title}`);
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
      } catch (e) {
        failures.push(`${f.name}：${describeError(e, t("workbench.shell.uploadFailed"))}`);
      }
    }
    if (uploaded) await reload();
    setUploading(false);
    if (!failures.length) {
      // 成功必须清掉上一次的失败横幅：否则「重试成功」之后界面还挂着 Failed to fetch，
      // 用户会以为没传上去，再传一遍。
      setError("");
      setNotice(
        (projectId
          ? t("workbench.shell.uploadedReferenced")
          : t("workbench.shell.uploadedWorkspace")) +
          (renamed.length ? t("workbench.shell.renamedNote", { names: renamed.join("；") }) : ""),
      );
      return;
    }
    setError(
      uploaded
        ? t("workbench.shell.uploadPartial", { ok: uploaded, failed: failures.length, list: failures.join("；") })
        : t("workbench.shell.uploadFailedWithList", { list: failures.join("；") }),
    );
  }
  function reference(r: Reference, action: "add" | "ask" | "rewrite" | "explain" = "add") {
    if(courtSelection) {if(!r.text){setNotice(t("workbench.shell.selectTextForCourt"));return;}setCourtReference(r);setAgentVisible(true);setMobile("会话");return;}
    updateDraft({
      ...draft,
      references: [...draft.references, r],
      text:
        action === "add"
          ? draft.text
          : (draft.text ? draft.text + "\n" : "") +
            (action === "rewrite"
              ? t("workbench.shell.promptRewrite")
              : action === "explain"
                ? t("workbench.shell.promptExplain")
                : t("workbench.shell.promptAsk")),
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
      reportError(e);
    }
  }
  const composer = (
    <Composer
      draft={draft}
      onChange={updateDraft}
      onSend={send}
      onStop={() =>
        api("/runs/" + run.id + "/stop", "POST").catch((e) =>
          reportError(e),
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
  // 没有消息时的兜底空数组也要保持引用稳定，否则下面的钉底 effect 每次渲染都会重跑。
  const convMessages = conv?.data.messages;
  const messages = React.useMemo(() => convMessages || [], [convMessages]);
  const activityBlocks = React.useMemo(() => aggregateActivity(events), [events]);
  // 距底 140px 内算「在底部」（与庭审会话同一阈值）：发送即视为在底部，上翻即脱钩。
  const trackStick = React.useCallback(() => {
    const el = scroll.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  }, []);
  // 流式钉底：只在运行中且用户本就在底部附近时跟随，回看历史不被打扰。
  React.useEffect(() => {
    if (!running || !stick.current) return;
    const el = scroll.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [running, live, activityBlocks, messages]);
  const chat = (
    <SessionView
      courtSelection={courtSelection}
      projectId={projectId}
      showDoc={showDoc}
      courtChatHidden={showDoc && !agentVisible}
      conv={conv}
      messages={messages}
      run={run}
      running={running}
      live={live}
      events={events}
      activityBlocks={activityBlocks}
      offline={offline}
      composer={composer}
      scrollRef={scroll}
      onMessagesScroll={trackStick}
      dragHandle={workspace.handle("agent", courtSelection ? t("workbench.history.groupCourt") : t("workbench.shell.agent"))}
      courtReference={courtReference}
      onBranch={(messageId) =>
        api<Item>(`/conversations/${conv.id}/branch`, "POST", {
          message_id: messageId,
          title: conv.title + t("workbench.manage.branchSuffix"),
        })
          .then((c) => {
            reload();
            openConversation(c.id);
          })
          .catch((e) => reportError(e))
      }
      onOpenDocument={openDocumentById}
      onOpenReference={(referenceId) => {
        const known = documents.find((item) => item.id === referenceId);
        if (known) void openDocument(known);
      }}
      onCollapseChat={() => setAgentVisible(false)}
      onSelectCourt={(id, pid) => openCourt(pid, id)}
      onCancelCourt={() => quick(projectId)}
      onClearCourtReference={() => setCourtReference(undefined)}
      onError={reportError}
    />
  );
  return (
    <div
      className={"wb-app " + (showDoc ? "has-document" : "") + " mobile-" + mobile}
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
      <Sidebar
        username={username}
        profile={accountProfile}
        credits={credits}
        sidebarOpen={sidebar}
        project={project}
        projects={projects}
        offline={offline}
        agentCollapsed={!agentVisible}
        courtSession={!!courtSelection}
        query={query}
        results={results}
        docs={spaceDocs}
        activeDocId={doc?.id}
        showDoc={showDoc}
        fileInput={sideFile}
        workspace={workspace}
        onClose={() => setSidebar(false)}
        onSwitchSpace={(pid) => {
          setDoc(undefined);
          quick(pid);
        }}
        onManageItem={setMenu}
        onCreateProject={createProject}
        onUpload={upload}
        onCreateDocument={createDocument}
        onQuery={setQuery}
        onOpenFile={(item) => void openDocument(item)}
        onRestoreAgent={() => setAgentVisible(true)}
        onOpen={(view) => (view.startsWith("/") ? navigate(view) : setDialog(view))}
      />
      {sidebar && (
        <button
          className="wb-sidebar-shade"
          aria-label={t("workbench.shell.closeNav")}
          onClick={() => setSidebar(false)}
        />
      )}
      <main className="wb-main">
        <div className="wb-sheet">
        <TabStrip
          space={space}
          tabs={spaceTabs}
          activeKey={activeTabKey}
          titleOf={(tab) => tabTitle(tab, conversations, courtItems)}
          runs={tabRuns}
          menuItems={tabMenuItems}
          onActivate={activateTab}
          onClose={closeTab}
          onReorder={(next) => setTabBook((book) => withTabs(book, space, next))}
          onCreate={() => quick(projectId)}
          onCreateCourt={() => navigate("/court/new")}
          onNav={() => setSidebar(true)}
          chrome={
            <>
              <HistoryMenu
                conversations={spaceConversations}
                courts={spaceCourts}
                currentConvId={conv?.id}
                currentCourtId={courtSelection}
                open={history}
                buttonRef={historyButton}
                onToggle={setHistory}
                onOpenConversation={(id) => pickSession({ kind: "conversation", id })}
                onOpenCourt={(id) => pickSession({ kind: "court", id })}
                onNewSession={() => quick(projectId)}
                onNewCourt={() => navigate("/court/new")}
              />
              <button
                className="wb-tabstrip-action"
                aria-label={fullScreen ? t("workbench.tabs.fullscreenOff") : t("workbench.tabs.fullscreenOn")}
                aria-pressed={fullScreen}
                title={fullScreen ? t("workbench.tabs.fullscreenOff") : t("workbench.tabs.fullscreenOnHint")}
                disabled={!activeTab?.doc}
                onClick={toggleScreen}
              >
                {fullScreen ? <Columns2 size={16} /> : <Maximize2 size={16} />}
              </button>
            </>
          }
        />
        {(error || notice || uploading) && (
          <div className={"wb-banner " + (error ? "error" : "")} role="status">
            <span>{error || (uploading ? t("workbench.shell.uploading") : notice)}</span>
            <button
              aria-label={t("workbench.shell.closeNotice")}
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
          className={
            "wb-body" + (doc ? " wb-docked" : "") + (resizing ? " is-resizing" : "")
          }
          data-agent-position={workspace.layout.agent}
          style={doc ? workspace.splitStyle(showDoc && agentVisible) : undefined}
        >
          {doc && (
              <motion.section
                className="wb-document-column"
                initial={{ flexBasis: "0%", opacity: 0 }}
                animate={{
                  // 三种状态：并排 = 按分栏比例；仅文档 = 占满；会话全屏 = 收起到 0
                  flexBasis: !showDoc
                    ? "0%"
                    : agentVisible
                      ? workspace.docPercent + "%"
                      : "100%",
                  opacity: showDoc ? 1 : 0,
                }}
                transition={
                  resizing
                    ? { duration: 0 }
                    : { duration: 0.38, ease: [0.22, 0.9, 0.24, 1] }
                }
                aria-hidden={!showDoc}
              >
                <div className="wb-doc-heading">
                  {workspace.handle("document", t("workbench.shell.document"))}
                  <FileText size={15} />
                  <span className="wb-doc-title">{doc.title}</span>
                  <button
                    className="wb-doc-collapse"
                    aria-label={t("workbench.shell.collapseDoc")}
                    title={t("workbench.shell.collapseDocHint")}
                    onClick={collapseDocument}
                  >
                    <Minimize2 size={15} />
                  </button>
                </div>
                <DocumentPane
                  key={doc.id}
                  document={doc}
                  user={username}
                  onSaved={saved}
                  onReference={reference}
                  onError={reportError}
                />
              </motion.section>
          )}
          {doc && showDoc && agentVisible && (
                  <div
                    className="wb-resizer"
                    role="separator"
                    aria-label={t("workbench.layout.resizeAgent")}
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
                    onPointerDown={e => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      setResizing(true);
                    }}
                    onPointerUp={() => setResizing(false)}
                    onPointerCancel={() => setResizing(false)}
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
          )}
          {/* 右侧内容（会话或首页）：仅文档模式下隐藏但保持挂载，滚动位置与庭审状态不丢。 */}
          <div
            className="wb-right-pane"
            style={doc && showDoc && !agentVisible ? { display: "none" } : undefined}
          >
          {courtSelection || activeIsSession ? (
            chat
          ) : (
            <HomeView
              project={project}
              greeting={greeting}
              suggestions={suggestions.itemsFor(space)}
              suggestionsLoading={suggestions.loading(space)}
              recentSessions={recentSessions}
              projects={projects}
              projectFilter={projectFilter}
              composer={composer}
              onFilter={setProjectFilter}
              onRefreshSuggestions={() => void suggestions.load(space, true)}
              onApplySuggestion={applySuggestion}
              onOpenSession={pickSession}
              onManageItem={setMenu}
              onOpenHistory={openHistory}
              onOpenProject={quick}
              onNewProject={createProject}
            />
          )}
          </div>
        </div>
        </div>
      </main>
      {appDrag && (
        <div className="wb-drop-overlay" aria-hidden="true">
          <strong>{t("workbench.shell.dropToUpload", { target: project?.title || t("workbench.sidebar.personalWorkspace") })}</strong>
        </div>
      )}
      {workspace.targets}
      <UpgradeNudgeGate
        plan={accountProfile?.plan}
        balance={credits?.balance ?? null}
        exempt={Boolean(credits?.exempt)}
        open={nudgeOpen}
        onOpen={() => setNudgeOpen(true)}
        onClose={(options) => setNudgeOpen(false)}
      />
      {menu && (
        <ManageMenu
          item={menu}
          projects={projects}
          onClose={() => setMenu(undefined)}
          onRename={(item) => renameItem(item)}
          onFavorite={(item) => {
            setMenu(undefined);
            void mutate(item, { favorite: !item.data.favorite });
          }}
          onArchive={(item) => {
            setMenu(undefined);
            archiveItem(item);
          }}
          onMove={(item, target) => {
            // 标签跟着会话走：移动到别的空间时把标签一并挪过去。
            if (item.kind === "conversation")
              setTabBook((book) =>
                moveTabToSpace(
                  book,
                  spaceKey(item.project_id),
                  spaceKey(target),
                  tabKey({ kind: "conversation", id: item.id }),
                ),
              );
            void mutate(item, { project_id: target || null });
          }}
          onDelete={(item) => {
            setMenu(undefined);
            void removeItem(item);
          }}
        />
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
          onError={reportError}
        />
      )}
    </div>
  );
}
