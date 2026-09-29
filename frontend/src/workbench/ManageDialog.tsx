import React, { useEffect, useId, useState } from "react";
import { X, Plus, Plug, Sparkles } from "lucide-react";
import { useAppDialog } from "../contexts/DialogContext";
import { useSettingsEdit } from "../components/settings/SettingsEditContext";
import { api, Item } from "./client";
import { fileDB } from "../lib/db";
import { downloadApiFile } from "../lib/download";
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
    if (editing && !await showConfirm({title: "放弃未保存的配置？", message: "切换列表会丢弃当前编辑内容。", confirmLabel: "放弃并切换", cancelLabel: "继续编辑", tone: "warning"})) return;
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
        `已迁移 ${chosen.length} 个会话、${courts.length} 个庭审档案。正在上传附件…`,
      );
      for (const f of files.filter((f) => selected.includes(f.convId))) {
        if (!f.blob) continue;
        const body = new FormData();
        body.append("file", f.blob, f.fileName);
        body.append("conversation_id", f.convId);
        body.append("original_path", f.path);
        await api("/migrations/" + result.id + "/files", "POST", body);
      }
      setProgress(
        "会话与可读取附件已复制到云端。原始资料完整保留；缺失附件请在旧资料中核对。",
      );
      onReload();
    } catch (e) {
      setProgress("迁移中断，原始资料未删除。");
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
        aria-label="工作台管理"
      >
        {!embedded && <header>
          <h2>
            {tab === "migration"
              ? "本地旧资料"
              : tab === "trash"
                ? "归档与回收站"
                : "技能与插件"}
          </h2>
          <button aria-label="关闭" onClick={onClose}>
            <X size={20} />
          </button>
        </header>}
        {["skills", "connectors"].includes(tab) && (
          <>
            <nav className="wb-manager-tabs" role="tablist" aria-label="技能与插件分类">
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
                  {value === "skills" ? "技能" : "插件"}
                </button>
              ))}
            </nav>
            <div id={`${sectionId}-panel`} role="tabpanel" aria-labelledby={`${sectionId}-${section}`}>
            {editing ? (
              <>
                <label>
                  名称
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                {section === "skills" ? (
                  <label>
                    技能说明与指令
                    <textarea
                      value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                    />
                  </label>
                ) : (
                  <>
                    <label>
                      HTTPS MCP 地址
                      <input
                        value={url}
                        disabled={!!editing.id}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://example.com/mcp"
                      />
                    </label>
                    <label>
                      API 密钥
                      <input
                        type="password"
                        autoComplete="new-password"
                        value={secret}
                        onChange={(e) => setSecret(e.target.value)}
                        placeholder={
                          editing.data.has_secret
                            ? "已配置；输入新密钥以更新"
                            : "可留空"
                        }
                      />
                    </label>
                    <p>
                      仅支持远程 HTTPS Streamable
                      HTTP。密钥加密存储；插件默认为停用。
                    </p>
                  </>
                )}
                <button
                  disabled={busy || !title.trim()}
                  className="wb-primary"
                  onClick={save}
                >
                  保存{section === "skills" ? "草稿" : ""}
                </button>
                <button onClick={() => setEditing(undefined)}>取消</button>
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
                  {section === "skills" ? "创建技能" : "添加插件"}
                </button>
                {section === "connectors" && connectors.length === 0 && <p className="wb-empty">尚未添加插件。连接远程 MCP 服务后，可在任务中选择使用。</p>}
                {(section === "skills" ? skills : connectors).map((item) => (
                  <div className="wb-row" key={item.id}>
                    <span>
                      {item.title}
                      <small>
                        {item.data.builtin
                          ? "内置技能"
                          : item.data.url ||
                            `版本 ${item.revision} · ${item.data.published ? "已发布" : "草稿"}`}
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
                          测试连接
                        </button>
                      )}
                      {!item.data.builtin && (
                        <>
                          <button onClick={() => edit(item)}>编辑</button>
                          {item.kind === "skill" && (
                            <button
                              onClick={() =>
                                toggle(item, {
                                  published: !item.data.published,
                                })
                              }
                            >
                              {item.data.published ? "撤下" : "发布"}
                            </button>
                          )}
                          <button
                            onClick={() =>
                              toggle(item, { enabled: !item.data.enabled })
                            }
                          >
                            {item.data.enabled ? "停用" : "启用"}
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => {
                          edit({
                            ...item,
                            id: "",
                            title: item.title + " · 副本",
                            data: { ...item.data, builtin: false },
                          });
                        }}
                      >
                        复制
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
            <h3>已归档</h3>
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
                    取消归档
                  </button>
                </div>
              ))}
            <h3>回收站 · 30 天</h3>
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
                  恢复
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
                导出云端备份
              </button>
              <label className="wb-file-button">
                恢复 v5 备份
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
              发现 {locals.length} 个会话、{courts.length} 个庭审记录和{" "}
              {files.length}{" "}
              份本地附件。选择需要迁移的会话；请一起选择同一分支树，以保留完整关系。庭审记录作为原始档案保存。
            </p>
            <a href="/legacy">打开本地旧资料（阅读、导出、旧备份导入）</a>
            <label>
              <input
                type="checkbox"
                checked={selected.length === locals.length && !!locals.length}
                onChange={(e) =>
                  setSelected(e.target.checked ? locals.map((c) => c.id) : [])
                }
              />
              选择所有会话
            </label>
            {locals.map((c) => (
              <label key={c.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, c.id]
                        : selected.filter((id) => id !== c.id),
                    )
                  }
                />
                {c.title} · {c.messages.length} 条消息
              </label>
            ))}
            <p>{progress}</p>
            <button
              disabled={busy || !selected.length}
              className="wb-primary"
              onClick={migrate}
            >
              {busy ? "正在迁移…" : "复制所选资料到云端"}
            </button>
            <p>不会删除本地原始内容；迁移期间请保持页面打开。</p>
          </>
        )}
      </section>
    </div>
  );
}
