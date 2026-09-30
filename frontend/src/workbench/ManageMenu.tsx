import { X } from "lucide-react";
import { SelectField } from "./SelectField";
import { useT } from "../i18n";
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
  const { t } = useT();
  return (
    <div className="wb-modal-backdrop" onClick={onClose}>
      <section
        className="wb-modal wb-small-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("workbench.manage.dialogLabel")}
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h2>{item.title}</h2>
          <button aria-label={t("common.close")} onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <button onClick={() => onRename(item)}>{t("workbench.manage.rename")}</button>
        <button onClick={() => onFavorite(item)}>
          {item.data.favorite ? t("workbench.manage.unfavorite") : t("workbench.manage.favorite")}
        </button>
        <button onClick={() => onArchive(item)}>
          {item.data.archived ? t("workbench.manage.unarchive") : t("workbench.manage.archive")}
        </button>
        {item.kind !== "project" && (
          <SelectField
            label={t("workbench.manage.moveToProject")}
            value={item.project_id || ""}
            onChange={(value) => onMove(item, value || undefined)}
            options={[
              { value: "", label: t("workbench.sidebar.personalWorkspace") },
              ...projects.map((project) => ({ value: project.id, label: project.title })),
            ]}
          />
        )}
        <button className="wb-danger" onClick={() => onDelete(item)}>
          {t("workbench.manage.trash")}
        </button>
      </section>
    </div>
  );
}
