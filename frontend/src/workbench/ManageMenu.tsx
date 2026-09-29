import { X } from "lucide-react";
import { Item } from "./client";

/** 内容管理弹窗：会话/文档/项目的重命名、收藏、归档、跨空间移动与回收站。 */
export type ManageMenuProps = {
  item: Item;
  projects: Item[];
  onClose: () => void;
  onRename: (item: Item) => void;
  onFavorite: (item: Item) => void;
  onArchive: (item: Item) => void;
  onMove: (item: Item, projectId?: string) => void;
  onDelete: (item: Item) => void;
};

export function ManageMenu({
  item,
  projects,
  onClose,
  onRename,
  onFavorite,
  onArchive,
  onMove,
  onDelete,
}: ManageMenuProps) {
  return (
    <div className="wb-modal-backdrop" onClick={onClose}>
      <section
        className="wb-modal wb-small-modal"
        role="dialog"
        aria-modal="true"
        aria-label="管理内容"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h2>{item.title}</h2>
          <button aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <button onClick={() => onRename(item)}>重命名</button>
        <button onClick={() => onFavorite(item)}>
          {item.data.favorite ? "取消收藏" : "收藏"}
        </button>
        <button onClick={() => onArchive(item)}>
          {item.data.archived ? "取消归档" : "归档"}
        </button>
        {item.kind !== "project" && (
          <label>
            移动到项目
            <select
              value={item.project_id || ""}
              onChange={(event) => onMove(item, event.target.value || undefined)}
            >
              <option value="">个人工作区</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.title}
                </option>
              ))}
            </select>
          </label>
        )}
        <button className="wb-danger" onClick={() => onDelete(item)}>
          移入回收站（保留 30 天）
        </button>
      </section>
    </div>
  );
}
