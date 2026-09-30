import { Gavel, MessageSquare, MoreHorizontal, Plus, RefreshCw } from "lucide-react";
import { useT } from "../i18n";
import React from "react";
import { Item } from "./client";
import { TabRef, tabKey } from "./tabs";

export type SuggestionItem = { title: string; prompt: string };
export type RecentSession = { tab: TabRef; item: Item };

/** 空白首页（新会话标签的内容）：问候语 → 工作建议 → 输入框 → 最近会话 → 项目陈列。 */
export type HomeViewProps = {
  project?: Item;
  greeting: string;
  suggestions: SuggestionItem[];
  suggestionsLoading: boolean;
  recentSessions: RecentSession[];
  projects: Item[];
  projectFilter: "全部" | "最近";
  composer: React.ReactNode;
  onFilter: (filter: "全部" | "最近") => void;
  onRefreshSuggestions: () => void;
  onApplySuggestion: (suggestion: SuggestionItem) => void;
  onOpenSession: (tab: TabRef) => void;
  /** 行内「管理」：打开与侧栏同一个管理菜单（重命名/收藏/归档/移入回收站）。 */
  onManageItem: (item: Item) => void;
  onOpenHistory: () => void;
  onOpenProject: (projectId: string) => void;
  onNewProject: () => void;
};

export function HomeView({
  project,
  greeting,
  suggestions,
  suggestionsLoading,
  recentSessions,
  projects,
  projectFilter,
  composer,
  onFilter,
  onRefreshSuggestions,
  onApplySuggestion,
  onOpenSession,
  onManageItem,
  onOpenHistory,
  onOpenProject,
  onNewProject,
}: HomeViewProps) {
  const { t } = useT();
  const visibleProjects = projectFilter === "最近"
    ? projects
        .filter((item) => !item.data.archived)
        .slice()
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 6)
    : projects.filter((item) => !item.data.archived);
  return (
    <section className="wb-home">
      {project ? (
        <header className="wb-project-head">
          <h1>{project.title}</h1>
          {project.data.desc && <p className="wb-project-description">{project.data.desc}</p>}
        </header>
      ) : (
        <div className="wb-home-hero">
          <h1>{greeting}，今天先处理哪件事？</h1>
          <p>从左侧选择文件，或直接描述你要完成的工作。</p>
        </div>
      )}
      <div className="wb-home-suggest">
        <div className="wb-home-suggest-head">
          <span>{t("workbench.home.suggestions")}</span>
          <button
            className="wb-home-refresh"
            onClick={onRefreshSuggestions}
            disabled={suggestionsLoading}
            title={t("workbench.home.refreshSuggestionsHint")}
          >
            <RefreshCw size={13} />
            {t("workbench.home.refreshSuggestions")}
          </button>
        </div>
        <div className="wb-home-chips" aria-busy={suggestionsLoading}>
          {suggestionsLoading
            ? [0, 1, 2].map((index) => (
                <span key={index} className="wb-home-chip is-loading" aria-hidden="true" />
              ))
            : suggestions.map((item) => (
                <button
                  key={item.title}
                  className="wb-home-chip"
                  title={item.prompt}
                  onClick={() => onApplySuggestion(item)}
                >
                  {item.title}
                </button>
              ))}
        </div>
      </div>
      {composer}
      <section className="wb-home-recent">
        <header>
          <h2>{t("workbench.home.recentSessions")}</h2>
          {!!recentSessions.length && (
            <button className="wb-mini-action" onClick={onOpenHistory}>
              {t("workbench.home.openHistory")}
            </button>
          )}
        </header>
        {recentSessions.map(({ tab, item }) => (
          <div className="wb-file-row" key={tabKey(tab)}>
            <button className="wb-file-row-main" onClick={() => onOpenSession(tab)}>
              {tab.kind === "court" ? <Gavel size={17} /> : <MessageSquare size={17} />}
              <span>
                {item.title}
                <small>
                  {new Date(item.updated_at).toDateString() === new Date().toDateString()
                    ? t("workbench.home.today")
                    : new Date(item.updated_at).toLocaleDateString()}
                </small>
              </span>
            </button>
            {/* 悬停才露面，与侧栏文件行、标签关闭键同一档；此前这一行只有打开、没有管理入口。 */}
            <button
              className="wb-file-row-manage"
              aria-label={t("workbench.home.manage", { title: item.title })}
              onClick={() => onManageItem(item)}
            >
              <MoreHorizontal size={14} />
            </button>
          </div>
        ))}
        {!recentSessions.length && <p className="wb-empty-hint">{t("workbench.home.emptySessions")}</p>}
      </section>
      {!project && (
        <section className="wb-home-projects">
          <header className="wb-projects-head">
            <div className="wb-projects-title-row">
              <h2 className="wb-projects-title">{t("workbench.home.projects")}</h2>
              <div className="wb-projects-filter">
                <button
                  className={projectFilter === "全部" ? "active" : ""}
                  onClick={() => onFilter("全部")}
                >
                  全部
                </button>
                <button
                  className={projectFilter === "最近" ? "active" : ""}
                  onClick={() => onFilter("最近")}
                >
                  最近
                </button>
              </div>
            </div>
            <button
              data-tour="wb-new-project"
              className="wb-primary wb-projects-new"
              onClick={onNewProject}
            >
              <Plus size={15} />
              {t("workbench.home.newProject")}
            </button>
          </header>
          <div className="wb-project-cards">
            {visibleProjects.map((item, index) => (
              <button
                key={item.id}
                className="wb-project-card"
                style={{ "--i": index } as React.CSSProperties}
                onClick={() => onOpenProject(item.id)}
              >
                <strong>{item.title}</strong>
                {item.data.desc && <small className="wb-project-card-desc">{item.data.desc}</small>}
                <span className="wb-project-card-meta">
                  最后修改{" "}
                  {new Date(item.updated_at).toLocaleDateString("zh-CN", {
                    month: "numeric",
                    day: "numeric",
                  })}{" "}
                  {new Date(item.updated_at).toLocaleTimeString("zh-CN", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </button>
            ))}
            {!projects.filter((item) => !item.data.archived).length && (
              <p className="wb-empty-hint">
                还没有项目，点击右上角「新建项目」开始归拢你的材料。
              </p>
            )}
          </div>
        </section>
      )}
    </section>
  );
}
