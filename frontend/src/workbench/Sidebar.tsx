import {
  Archive,
  Building2,
  ChevronDown,
  FileText,
  Folder,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  User,
  X,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { BrandLockup } from "../components/Brand";
import { fetchMyCredits } from "../services/api";
import { Item } from "./client";
import { LayoutToolbar, useWorkspaceLayout } from "./WorkspaceLayout";
import { usePortalMenuDismiss } from "./usePortalMenu";

// 空间菜单 portal 到 body：豁免列表里要有菜单自身的类名。
const SPACE_MENU_SELECTORS = [".wb-space-menu", ".wb-space-pill"] as const;

/** 侧栏：只负责当前工作区的文件、空间切换与底部工具入口。 */
export type SidebarProps = {
  username: string;
  sidebarOpen: boolean;
  project?: Item;
  projects: Item[];
  offline: boolean;
  agentCollapsed: boolean;
  courtSession: boolean;
  query: string;
  results?: any[];
  docs: Item[];
  /** 当前标签正在显示的文档：决定文件行的选中态。 */
  activeDocId?: string;
  showDoc: boolean;
  fileInput: React.RefObject<HTMLInputElement>;
  workspace: ReturnType<typeof useWorkspaceLayout>;
  onClose: () => void;
  onSwitchSpace: (projectId?: string) => void;
  onManageItem: (item: Item) => void;
  onCreateProject: () => void;
  onUpload: (files: File[]) => void;
  onCreateDocument: () => void;
  onQuery: (value: string) => void;
  onOpenFile: (item: Item) => void;
  onRestoreAgent: () => void;
  onOpen: (view: string) => void;
};

export function Sidebar({
  username,
  sidebarOpen,
  project,
  projects,
  offline,
  agentCollapsed,
  courtSession,
  query,
  results,
  docs,
  activeDocId,
  showDoc,
  fileInput,
  workspace,
  onClose,
  onSwitchSpace,
  onManageItem,
  onCreateProject,
  onUpload,
  onCreateDocument,
  onQuery,
  onOpenFile,
  onRestoreAgent,
  onOpen,
}: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number }>();
  // 余额显示在侧栏底部：计费是后台行为，用户至少要有地方看到自己还剩多少。
  // 同一份响应里的套餐决定是否出现 Business 控制台入口。
  const [credits, setCredits] = useState<number | null>(null);
  const [exempt, setExempt] = useState(false);
  const [plan, setPlan] = useState("");
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchMyCredits()
        .then((data) => {
          if (cancelled || !data) return;
          setCredits(typeof data.credits === "number" ? data.credits : null);
          setExempt(Boolean(data.exempt));
          setPlan(data.plan || "");
        })
        .catch(() => undefined);
    load();
    // 余额会被后台任务扣减，切标签或完成任务后刷新一次即可，不必轮询。
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 120000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
  usePortalMenuDismiss(menuOpen, () => setMenuOpen(false), { selectors: SPACE_MENU_SELECTORS });
  return (
    <aside data-tour="wb-sidebar" className={"wb-sidebar " + (sidebarOpen ? "is-open" : "")}>
      <div className="wb-brand">
        <Link to="/home" className="wb-brand-link" aria-label="回到工作台首页">
          <BrandLockup />
        </Link>
        {workspace.handle("navigation", "文件")}
        <button className="wb-mobile-only" aria-label="关闭导航" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="wb-space-head">
        <button
          className="wb-space-pill"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          title="切换工作区"
          onClick={(e) => {
            if (!menuOpen) {
              const r = e.currentTarget.getBoundingClientRect();
              const width = Math.min(240, window.innerWidth - 16);
              setMenuPos({
                top: Math.min(r.bottom + 6, window.innerHeight - 160),
                left: Math.max(
                  8,
                  Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 8),
                ),
              });
            }
            setMenuOpen(!menuOpen);
          }}
        >
          {project ? <Folder size={15} /> : <User size={15} />}
          <span>{project ? project.title : "个人工作区"}</span>
          <ChevronDown size={14} />
        </button>
        {project && (
          <button aria-label={"管理 " + project.title} onClick={() => onManageItem(project)}>
            <MoreHorizontal size={15} />
          </button>
        )}
      </div>
      {menuOpen &&
        createPortal(
          <div
            className="wb-space-menu"
            role="menu"
            aria-label="切换工作区"
            style={{ position: "fixed", top: menuPos?.top, left: menuPos?.left }}
          >
            <button
              role="menuitem"
              className={!project ? "selected" : ""}
              onClick={() => {
                setMenuOpen(false);
                onSwitchSpace(undefined);
              }}
            >
              <User size={14} />
              <span>个人工作区</span>
            </button>
            {projects
              .filter((item) => !item.data.archived)
              .map((item) => (
                <button
                  key={item.id}
                  role="menuitem"
                  className={project?.id === item.id ? "selected" : ""}
                  onClick={() => {
                    setMenuOpen(false);
                    onSwitchSpace(item.id);
                  }}
                >
                  <Folder size={14} />
                  <span>{item.title}</span>
                </button>
              ))}
            <div className="wb-space-menu-sep" />
            <button
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onCreateProject();
              }}
            >
              <Plus size={14} />
              <span>创建项目</span>
            </button>
          </div>,
          document.body,
        )}
      <div className="wb-files-head">
        <span>文件</span>
        <div className="wb-space-add-wrap">
          <button
            className="wb-space-add"
            aria-label="上传文件"
            aria-haspopup="menu"
            title="上传文件（悬停可选新建文档）"
            onClick={() => fileInput.current?.click()}
          >
            <Plus size={16} />
          </button>
          <div className="wb-space-add-menu" role="menu" aria-label="文件操作">
            <button role="menuitem" onClick={() => fileInput.current?.click()}>
              <Upload size={14} />
              上传文件
            </button>
            <button role="menuitem" onClick={onCreateDocument}>
              <FileText size={14} />
              新建文档
            </button>
          </div>
        </div>
      </div>
      <input
        ref={fileInput}
        type="file"
        hidden
        multiple
        accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
        onChange={(e) => {
          onUpload(Array.from(e.target.files || []));
          e.target.value = "";
        }}
      />
      <label className="wb-search">
        <Search size={16} />
        <input
          aria-label="搜索文件"
          placeholder="搜索文件"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
      </label>
      <div className="wb-nav-scroll">
        {results ? (
          <div className="wb-search-results">
            {results.map((result) => (
              <button
                key={result.id}
                onClick={() => {
                  onOpenFile(result);
                  onQuery("");
                }}
              >
                <span>{result.title}</span>
                <small>
                  {(result.data?.format || "文件").toUpperCase()} · 版本 {result.revision}
                </small>
                <small>{result.excerpt}</small>
              </button>
            ))}
            {!results.length && <p className="wb-space-hint">没有匹配的文件。</p>}
          </div>
        ) : (
          <>
            {docs.map((item) => (
              <div
                className={
                  "wb-space-row" + (showDoc && activeDocId === item.id ? " selected" : "")
                }
                key={item.id}
              >
                <button onClick={() => onOpenFile(item)}>
                  <FileText size={14} />
                  <span>{item.title}</span>
                </button>
                <button aria-label={"管理 " + item.title} onClick={() => onManageItem(item)}>
                  <MoreHorizontal size={13} />
                </button>
              </div>
            ))}
            {!docs.length && (
              <p className="wb-space-hint">
                暂无文件，拖到页面任意位置即可上传，或
                <button className="wb-space-upload-link" onClick={() => fileInput.current?.click()}>
                  上传文件
                </button>
              </p>
            )}
          </>
        )}
      </div>
      <div className="wb-sidebar-tools">
        <LayoutToolbar workspace={workspace} />
        {showDoc && agentCollapsed && (
          <button className="wb-desktop-only" onClick={onRestoreAgent}>
            <Sparkles size={16} />
            {courtSession ? "庭审" : "Agent"}
          </button>
        )}
        {offline && <small>离线</small>}
      </div>
      <footer className="wb-nav-footer">
        {plan === "business" && (
          <button onClick={() => onOpen("/business")}>
            <Building2 size={17} />
            Business 控制台
          </button>
        )}
        <button onClick={() => onOpen("/settings/extensions")}>
          <Sparkles size={17} />
          技能与插件
        </button>
        <button onClick={() => onOpen("migration")}>
          <Archive size={17} />
          本地旧资料
        </button>
        <div>
          <button aria-label="归档与回收站" onClick={() => onOpen("trash")}>
            <Trash2 size={16} />
          </button>
          <button onClick={() => onOpen("/settings")}>
            <Settings size={16} />
            设置
          </button>
          <span>{username}</span>
          {credits !== null && (
            <span
              className="wb-credits"
              title={`credits 余额 ${credits.toFixed(2)}${exempt ? "（运维账号不限）" : ""}`}
            >
              {exempt ? "不限" : credits.toFixed(2)}
            </span>
          )}
        </div>
      </footer>
    </aside>
  );
}
