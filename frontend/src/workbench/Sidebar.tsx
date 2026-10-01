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
import { useT } from "../i18n";
import { SidebarAccount } from "./SidebarAccount";
import type { AccountProfile } from "../services/api";

// 空间菜单 portal 到 body：豁免列表里要有菜单自身的类名。
const SPACE_MENU_SELECTORS = [".wb-space-menu", ".wb-space-pill"] as const;

/** 侧栏：只负责当前工作区的文件、空间切换与底部工具入口。 */
export type SidebarProps = {
  username: string;
  /** 账户资料（uid/自定义 ID/订阅徽标）；未取到时回退显示用户名。 */
  profile: AccountProfile | null;
  /** credits 余额与运维豁免：由 Workbench 抓取（耗尽弹窗与这里共用一份数据）。 */
  credits: { balance: number | null; exempt: boolean } | null;
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
  profile,
  credits,
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
  const { t } = useT();
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number }>();
  // 余额显示在侧栏底部：计费是后台行为，用户至少要有地方看到自己还剩多少。
  // 同一份响应里的套餐决定是否出现 Business 控制台入口。
  usePortalMenuDismiss(menuOpen, () => setMenuOpen(false), { selectors: SPACE_MENU_SELECTORS });
  return (
    <aside data-tour="wb-sidebar" className={"wb-sidebar " + (sidebarOpen ? "is-open" : "")}>
      <div className="wb-brand">
        <Link to="/home" className="wb-brand-link" aria-label={t("workbench.sidebar.home")}>
          <BrandLockup />
        </Link>
        {workspace.handle("navigation", t("workbench.sidebar.files"))}
        <button className="wb-mobile-only" aria-label={t("workbench.shell.closeNav")} onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="wb-space-head">
        <button
          className="wb-space-pill"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          title={t("workbench.sidebar.switchWorkspace")}
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
          <span>{project ? project.title : t("workbench.sidebar.personalWorkspace")}</span>
          <ChevronDown size={14} />
        </button>
        {project && (
          <button aria-label={t("workbench.sidebar.manageProject", { title: project.title })} onClick={() => onManageItem(project)}>
            <MoreHorizontal size={15} />
          </button>
        )}
      </div>
      {menuOpen &&
        createPortal(
          <div
            className="wb-space-menu"
            role="menu"
            aria-label={t("workbench.sidebar.switchWorkspace")}
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
              <span>{t("workbench.sidebar.personalWorkspace")}</span>
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
              <span>{t("workbench.sidebar.newProject")}</span>
            </button>
          </div>,
          document.body,
        )}
      <div className="wb-files-head">
        <span>{t("workbench.sidebar.files")}</span>
        <div className="wb-space-add-wrap">
          <button
            className="wb-space-add"
            aria-label={t("workbench.composer.upload")}
            aria-haspopup="menu"
            title={t("workbench.sidebar.uploadHint")}
            onClick={() => fileInput.current?.click()}
          >
            <Plus size={16} />
          </button>
          <div className="wb-space-add-menu" role="menu" aria-label={t("workbench.sidebar.fileActions")}>
            <button role="menuitem" onClick={() => fileInput.current?.click()}>
              <Upload size={14} />
              {t("workbench.composer.upload")}
            </button>
            <button role="menuitem" onClick={onCreateDocument}>
              <FileText size={14} />
              {t("workbench.sidebar.newDocument")}
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
          aria-label={t("workbench.sidebar.searchFiles")}
          placeholder={t("workbench.sidebar.searchFiles")}
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
                  {(result.data?.format || t("workbench.sidebar.fileFallback")).toUpperCase()} · {t("workbench.sidebar.version", { revision: result.revision })}
                </small>
                <small>{result.excerpt}</small>
              </button>
            ))}
            {!results.length && <p className="wb-space-hint">{t("workbench.sidebar.noMatch")}</p>}
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
                <button aria-label={t("workbench.sidebar.manageProject", { title: item.title })} onClick={() => onManageItem(item)}>
                  <MoreHorizontal size={13} />
                </button>
              </div>
            ))}
            {!docs.length && (
              <p className="wb-space-hint">
                {t("workbench.sidebar.emptyDocs")}
                <button className="wb-space-upload-link" onClick={() => fileInput.current?.click()}>
                  {t("workbench.composer.upload")}
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
            {courtSession ? t("workbench.shell.court") : t("workbench.shell.agent")}
          </button>
        )}
        {offline && <small>{t("workbench.shell.offline")}</small>}
      </div>
      <footer className="wb-nav-footer">
        {profile?.plan === "business" && (
          <button onClick={() => onOpen("/business")}>
            <Building2 size={17} />
            {t("workbench.shell.businessConsole")}
          </button>
        )}
        <button onClick={() => onOpen("/settings/extensions")}>
          <Sparkles size={17} />
          {t("workbench.shell.skillsAndPlugins")}
        </button>
        <button onClick={() => onOpen("migration")}>
          <Archive size={17} />
          {t("workbench.shell.localArchive")}
        </button>
        <div>
          <button aria-label={t("workbench.sidebar.archive")} onClick={() => onOpen("trash")}>
            <Trash2 size={16} />
          </button>
          {/* 图标档（与归档键同款 32px）：底部行要装下 归档+设置+账户 chip，文字档放不下 */}
          <button
            aria-label={t("workbench.shell.settings")}
            title={t("workbench.shell.settings")}
            onClick={() => onOpen("/settings")}
          >
            <Settings size={16} />
          </button>
          <SidebarAccount profile={profile} username={username} onOpen={onOpen} />
          {credits?.balance != null && (
            <span
              className="wb-credits"
              title={t("workbench.sidebar.creditsBalance", { amount: credits.balance.toFixed(2) }) + (credits.exempt ? t("workbench.sidebar.creditsExempt") : "")}
            >
              {credits.exempt ? t("workbench.shell.unlimited") : credits.balance.toFixed(2)}
            </span>
          )}
        </div>
      </footer>
    </aside>
  );
}
