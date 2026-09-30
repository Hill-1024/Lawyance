import React, { useEffect, useId, useState } from "react";
import { CheckBox } from "../components/CheckBox";
import { X, Plus, Plug, Sparkles } from "lucide-react";
import { useAppDialog } from "../contexts/DialogContext";
import { useSettingsEdit } from "../components/settings/SettingsEditContext";
import { api, Item } from "./client";
import { fileDB } from "../lib/db";
import { downloadApiFile } from "../lib/download";
import { useT } from "../i18n";
export function ManageDialog({
  tab,
  embedded = false,
  skills,
  connectors,
  projects,
  conversations,
  documents,
  onClose,
  onReload,
  onError,
}: {
  tab: string;
  embedded?: boolean;
  skills: Item[];
  connectors: Item[];
  projects: Item[];
  conversations: Item[];
  documents: Item[];
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
    [locals, setLocals] = useState<any[]>([]),
    [courts, setCourts] = useState<any[]>([]),
    [files, setFiles] = useState<any[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [progress, setProgress] = useState("");
  useEffect(() => {if(embedded) reportEdit("extensions", Boolean(editing));}, [editing, embedded, reportEdit]);
  useEffect(() => {
    if (tab === "trash")
      api<Item[]>("/trash")
        .then(setTrash)
        .catch((e) => onError(e.message));
    if (tab === "migration")
      Promise.all([
        fileDB.getConversations(),
        fileDB.getCourtSessions(),
        fileDB.getAllFiles(),
      ]).then(([c, t, f]) => {
        setLocals(c);
        setCourts(t);
        setFiles(f);
      });
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
        await api("/" + family, "POST", {
          title,
          ...(family === "skills" ? { instructions } : { url, secret }),
        });
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
  async function migrate() {
    setBusy(true);
    try {
      const chosen = locals.filter((c) => selected.includes(c.id));
      const manifest = files
        .filter((f) => selected.includes(f.convId))
        .map((f) => ({
          conversation_id: f.convId,
          name: f.fileName,
          path: f.path,
          available: !!f.blob,
        }));
      const payload = {
        source_id: "browser-" + location.origin,
        conversations: chosen,
        court_sessions: courts,
        files: manifest,
      };
      const hash = Array.from(
        new Uint8Array(
          await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(JSON.stringify(payload)),
          ),
        ),
      )
        .map((x) => x.toString(16).padStart(2, "0"))
        .join("");
      const result = await api(
        "/migrations",
        "POST",
        payload,
        "migration-" + hash,
      );
      setProgress(
        t("workbench.manage.migrated", { sessions: chosen.length, courts: courts.length }),
      );
      for (const f of files.filter((f) => selected.includes(f.convId))) {
        if (!f.blob) continue;
        const body = new FormData();
        body.append("file", f.blob, f.fileName);
        body.append("conversation_id", f.convId);
        body.append("original_path", f.path);
        await api("/migrations/" + result.id + "/files", "POST", body);
      }
      setProgress(t("workbench.manage.migratedDone"));
      onReload();
    } catch (e) {
      setProgress(t("workbench.manage.migratedInterrupted"));
      onError(e.message);
    } finally {
      setBusy(false);
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
            {tab === "migration"
              ? t("workbench.shell.localArchive")
              : tab === "trash"
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
            <h3>{t("workbench.manage.archived")}</h3>
            {[...projects, ...conversations, ...documents]
              .filter((i) => i.data.archived)
              .map((item) => (
                <div className="wb-row" key={item.id}>
                  {item.title}
                  <button
                    onClick={async () => {
                      await api(
                        `/${item.kind === "project" ? "projects" : item.kind === "conversation" ? "conversations" : "documents"}/${item.id}`,
                        "PATCH",
                        { expected_revision: item.revision, archived: false },
                      );
                      onReload();
                    }}
                  >
                    {t("workbench.manage.unarchive")}
                  </button>
                </div>
              ))}
            <h3>{t("workbench.manage.trashGroup")}</h3>
            {trash.map((item) => (
              <div className="wb-row" key={item.id}>
                {item.title}
                <button
                  onClick={async () => {
                    try {
                      await api("/trash/" + item.id + "/restore", "POST");
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
        {tab === "migration" && (
          <>
            <div className="wb-row">
              <button
                onClick={() =>
                  downloadApiFile(
                    "/api/workbench/backup",
                    "lawver-workbench-v5.zip",
                  ).catch((e) => onError(e.message))
                }
              >
                {t("workbench.manage.exportBackup")}
              </button>
              <label className="wb-file-button">
                {t("workbench.manage.restoreV5")}
                <input
                  type="file"
                  hidden
                  accept=".zip"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    setBusy(true);
                    try {
                      const body = new FormData();
                      body.append("file", f);
                      const result = await api(
                        "/backup",
                        "POST",
                        body,
                        crypto.randomUUID(),
                      );
                      setProgress(result.message);
                      onReload();
                    } catch (e) {
                      onError(e.message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                />
              </label>
            </div>
            <p>
              {t("workbench.manage.migrationIntro", { sessions: locals.length, courts: courts.length, attachments: files.length })}
              {t("workbench.manage.migrationSelectHint")}
            </p>
            <a href="/legacy">{t("workbench.manage.legacyLink")}</a>
            <CheckBox
              label={t("workbench.manage.selectAll")}
              checked={selected.length === locals.length && !!locals.length}
              onCheckedChange={(next) =>
                setSelected(next ? locals.map((c) => c.id) : [])
              }
            />
            {locals.map((c) => (
              <label key={c.id}>
                <CheckBox
                  ariaLabel={c.title}
                  checked={selected.includes(c.id)}
                  onCheckedChange={(next) =>
                    setSelected(
                      next
                        ? [...selected, c.id]
                        : selected.filter((id) => id !== c.id),
                    )
                  }
                />
                {t("workbench.manage.sessionMeta", { title: c.title, count: c.messages.length })}
              </label>
            ))}
            <p>{progress}</p>
            <button
              disabled={busy || !selected.length}
              className="wb-primary"
              onClick={migrate}
            >
              {busy ? t("workbench.manage.migrating") : t("workbench.manage.copyToCloud")}
            </button>
            <p>{t("workbench.manage.migrationKeepOpen")}</p>
          </>
        )}
      </section>
    </div>
  );
}
