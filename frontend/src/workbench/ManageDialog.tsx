import React, { useEffect, useEffectEvent, useId, useState } from "react";
import { X, Plus, Plug, Sparkles } from "lucide-react";
import { useAppDialog } from "../contexts/DialogContext";
import { useSettingsEdit } from "../components/settings/SettingsEditContext";
import { api, Item, Page } from "./client";
import { useT } from "../i18n";
export function ManageDialog({
  tab,
  embedded = false,
  skills,
  connectors,
  onClose,
  onReload,
  onError,
}: {
  tab: string;
  embedded?: boolean;
  skills: Item[];
  connectors: Item[];
  onClose: () => void;
  onReload: () => void;
  onError: (s: string) => void;
}) {
  const { showConfirm } = useAppDialog();
  const { t } = useT();
  const sectionId = useId();
  const reportEdit = useSettingsEdit();
  const [section, setSection] = useState(tab),
    [editing, setEditing] = useState<Item>(),
    [title, setTitle] = useState(""),
    [instructions, setInstructions] = useState(""),
    [url, setUrl] = useState(""),
    [secret, setSecret] = useState(""),
    [busy, setBusy] = useState(false),
    [trash, setTrash] = useState<Item[]>([]),
    [archived, setArchived] = useState<Item[]>([]);
  useEffect(() => {if(embedded) reportEdit("extensions", Boolean(editing));}, [editing, embedded, reportEdit]);
  // 报错是「拉取之后要做的事」，不是重新拉取的理由：onError 放进 effect event，切页签才重拉。
  const reportLoadError = useEffectEvent((message: string) => onError(message));
  useEffect(() => {
    if (tab === "trash") {
      // 归档列表必须单独取：常规分页已排除归档条目，内存索引里看不到旧会话。
      api<Item[]>("/trash")
        .then(setTrash)
        .catch((e) => reportLoadError(e.message));
      api<Page>("/archived?limit=200")
        .then((page) => setArchived(page.items))
        .catch((e) => reportLoadError(e.message));
    }
  }, [tab]);
  async function switchSection(next: string) {
    if (next === section) return;
    if (editing && !await showConfirm({title: t("workbench.manage.discardTitle"), message: t("workbench.manage.discardMessage"), confirmLabel: t("workbench.manage.discardConfirm"), cancelLabel: t("workbench.manage.discardCancel"), tone: "warning"})) return;
    setSection(next);
    setEditing(undefined);
  }
  function edit(item: Item) {
    setEditing(item);
    setTitle(item.title);
    setInstructions(item.data.instructions || "");
    setUrl(item.data.url || "");
    setSecret("");
  }
  async function save() {
    setBusy(true);
    try {
      const family = section === "connectors" ? "connectors" : "skills";
      if (editing.id)
        await api(`/${family}/${editing.id}`, "PATCH", {
          expected_revision: editing.revision,
          title,
          ...(family === "skills"
            ? { instructions, published: false }
            : secret
              ? { secret }
              : {}),
        });
      else
        // 后端对创建类 POST 强制 Idempotency-Key：每次保存动作生成一个，失败重试复用同一动作的 key。
        await api("/" + family, "POST", {
          title,
          ...(family === "skills" ? { instructions } : { url, secret }),
        }, crypto.randomUUID());
      setEditing(undefined);
      onReload();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(item: Item, patch: any) {
    try {
      await api(
        `/${item.kind === "skill" ? "skills" : "connectors"}/${item.id}`,
        "PATCH",
        { expected_revision: item.revision, ...patch },
      );
      onReload();
    } catch (e) {
      onError(e.message);
    }
  }
  const dismiss = embedded || busy ? undefined : onClose;
  return (
    <div
      className={embedded ? "wb-settings-manager" : "wb-modal-backdrop"}
      onMouseDown={dismiss ? (e) => { if (e.target === e.currentTarget) dismiss(); } : undefined}
      onKeyDown={dismiss ? (e) => { if (e.key === "Escape") { e.stopPropagation(); dismiss(); } } : undefined}
    >
      <section
        className="wb-modal"
        role={embedded ? undefined : "dialog"}
        aria-modal={embedded ? undefined : true}
        aria-label={t("workbench.manage.workbenchLabel")}
      >
        {!embedded && <header>
          <h2>
            {tab === "trash"
              ? t("workbench.sidebar.archive")
              : t("workbench.shell.skillsAndPlugins")}
          </h2>
          <button aria-label={t("common.close")} onClick={onClose}>
            <X size={20} />
          </button>
        </header>}
        {["skills", "connectors"].includes(tab) && (
          <>
            <nav className="wb-manager-tabs" role="tablist" aria-label={t("workbench.manage.sectionLabel")}>
              {(["skills", "connectors"] as const).map((value) => (
                <button
                  key={value}
                  id={`${sectionId}-${value}`}
                  role="tab"
                  aria-selected={section === value}
                  aria-controls={`${sectionId}-panel`}
                  tabIndex={section === value ? 0 : -1}
                  onClick={() => { void switchSection(value); }}
                  onKeyDown={(event) => {
                    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                    event.preventDefault();
                    const next = event.key === "Home" ? "skills" : event.key === "End" ? "connectors" : value === "skills" ? "connectors" : "skills";
                    void switchSection(next);
                    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
                    buttons?.[next === "skills" ? 0 : 1]?.focus();
                  }}
                >
                  {value === "skills" ? <Sparkles size={18} /> : <Plug size={18} />}
                  {value === "skills" ? t("workbench.manage.skills") : t("workbench.manage.plugins")}
                </button>
              ))}
            </nav>
            <div id={`${sectionId}-panel`} role="tabpanel" aria-labelledby={`${sectionId}-${section}`}>
            {editing ? (
              <>
                <label>
                  {t("workbench.manage.name")}
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                {section === "skills" ? (
                  <label>
                    {t("workbench.manage.skillInstruction")}
                    <textarea
                      value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                    />
                  </label>
                ) : (
                  <>
                    <label>
                      {t("workbench.manage.mcpUrl")}
                      <input
                        value={url}
                        disabled={!!editing.id}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://example.com/mcp"
                      />
                    </label>
                    <label>
                      {t("workbench.manage.apiKey")}
                      <input
                        type="password"
                        autoComplete="new-password"
                        value={secret}
                        onChange={(e) => setSecret(e.target.value)}
                        placeholder={
                          editing.data.has_secret
                            ? t("workbench.manage.keyConfigured")
                            : t("workbench.manage.keyOptional")
                        }
                      />
                    </label>
                    <p>{t("workbench.manage.connectorHint")}</p>
                  </>
                )}
                <button
                  disabled={busy || !title.trim()}
                  className="wb-primary"
                  onClick={save}
                >
                  {section === "skills" ? t("workbench.manage.saveDraft") : t("common.save")}
                </button>
                <button onClick={() => setEditing(undefined)}>{t("common.cancel")}</button>
              </>
            ) : (
              <>
                <button
                  onClick={() =>
                    edit({
                      id: "",
                      kind: section === "skills" ? "skill" : "connector",
                      title: "",
                      revision: 1,
                      data: {},
                    } as Item)
                  }
                >
                  <Plus size={16} />
                  {section === "skills" ? t("workbench.manage.createSkill") : t("workbench.manage.addConnector")}
                </button>
                {section === "connectors" && connectors.length === 0 && <p className="wb-empty">{t("workbench.manage.emptyPlugins")}</p>}
                {(section === "skills" ? skills : connectors).map((item) => (
                  <div className="wb-row" key={item.id}>
                    <span>
                      {item.title}
                      <small>
                        {item.data.builtin
                          ? t("workbench.manage.builtinSkill")
                          : item.data.url ||
                            t("workbench.manage.versionLine", { revision: item.revision, state: item.data.published ? t("workbench.manage.published") : t("workbench.manage.draft") })}
                      </small>
                      {item.data.last_error && (
                        <small>{item.data.last_error}</small>
                      )}
                    </span>
                    <div>
                      {item.kind === "connector" && (
                        <button
                          disabled={busy}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              await api(
                                "/connectors/" + item.id + "/test",
                                "POST",
                              );
                              onReload();
                            } catch (e) {
                              onError(e.message);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          {t("workbench.manage.testConnection")}
                        </button>
                      )}
                      {!item.data.builtin && (
                        <>
                          <button onClick={() => edit(item)}>{t("workbench.manage.edit")}</button>
                          {item.kind === "skill" && (
                            <button
                              onClick={() =>
                                toggle(item, {
                                  published: !item.data.published,
                                })
                              }
                            >
                              {item.data.published ? t("workbench.manage.unpublish") : t("workbench.manage.publish")}
                            </button>
                          )}
                          <button
                            onClick={() =>
                              toggle(item, { enabled: !item.data.enabled })
                            }
                          >
                            {item.data.enabled ? t("workbench.manage.disable") : t("workbench.manage.enable")}
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => {
                          edit({
                            ...item,
                            id: "",
                            title: item.title + t("workbench.manage.copySuffix"),
                            data: { ...item.data, builtin: false },
                          });
                        }}
                      >
                        {t("workbench.manage.duplicate")}
                      </button>
                    </div>
                  </div>
                ))}
              </>
            )}
            </div>
          </>
        )}
        {tab === "trash" && (
          <>
            <h3>
              {t("workbench.manage.archived")}
              {archived.length ? ` · ${archived.length}` : ""}
            </h3>
            {/* 归档不是删除：这里必须始终有出口，否则用户点完归档会觉得会话丢了。 */}
            {!archived.length && (
              <p className="wb-empty">{t("workbench.manage.emptyArchived")}</p>
            )}
            {archived.map((item) => (
              <div className="wb-row" key={item.id}>
                <span>
                  {item.title}
                  <small>
                    {item.kind === "project"
                      ? t("workbench.manage.kindProject")
                      : item.kind === "conversation"
                        ? t("workbench.manage.kindConversation")
                        : t("workbench.manage.kindDocument")}
                  </small>
                </span>
                <button
                  onClick={async () => {
                    try {
                      await api(
                        `/${item.kind === "project" ? "projects" : item.kind === "conversation" ? "conversations" : "documents"}/${item.id}`,
                        "PATCH",
                        { expected_revision: item.revision, archived: false },
                      );
                      setArchived(
                        (await api<Page>("/archived?limit=200")).items,
                      );
                      onReload();
                    } catch (e) {
                      onError(e.message);
                    }
                  }}
                >
                  {t("workbench.manage.unarchive")}
                </button>
              </div>
            ))}
            <h3>
              {t("workbench.manage.trashGroup")}
              {trash.length ? ` · ${trash.length}` : ""}
            </h3>
            {!trash.length && <p className="wb-empty">{t("workbench.manage.emptyTrash")}</p>}
            {trash.map((item) => (
              <div className="wb-row" key={item.id}>
                {item.title}
                <button
                  onClick={async () => {
                    try {
                      await api("/trash/" + item.id + "/restore", "POST", undefined, crypto.randomUUID());
                      setTrash(await api("/trash"));
                      onReload();
                    } catch (e) {
                      onError(e.message);
                    }
                  }}
                >
                  {t("workbench.manage.restore")}
                </button>
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  );
}
