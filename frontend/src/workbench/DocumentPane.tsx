import React, { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { SelectField } from "./SelectField";
import { useT } from "../i18n";
import { createPortal } from "react-dom";
import { Link as RouterLink } from "react-router-dom";
import { useReducedMotion } from "motion/react";
import { useEditor, useEditorState, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TableKit } from "@tiptap/extension-table";
import Image from "@tiptap/extension-image";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";
import Placeholder from "@tiptap/extension-placeholder";
import { Node, Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  Quote,
  FilePlus2,
  ImagePlus,
  Link,
  Bold,
  Italic,
  Strikethrough,
  Highlighter,
  List,
  ListOrdered,
  Table,
  Undo,
  Redo,
  Download,
  History,
  ZoomIn,
  ZoomOut,
  RotateCw,
  Scan,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  MoreHorizontal,
  Check,
  X,
  Loader2,
  CircleAlert,
} from "lucide-react";
import { TextDialog } from "./TextDialog";
import { usePortalMenuDismiss } from "./usePortalMenu";

// 「更多操作」菜单 portal 到 body：自身类名必须列入豁免，否则鼠标按下菜单项时菜单已被卸载。
const OVERFLOW_MENU_SELECTORS = [".wb-overflow-menu", ".wb-overflow"] as const;
import {
  api,
  binary,
  cached,
  remember,
  download,
  Item,
  Reference,
  Conflict,
} from "./client";
const PageBreak = Node.create({
  name: "pageBreak",
  group: "block",
  atom: true,
  parseHTML: () => [{ tag: "hr[data-page-break]" }],
  renderHTML: () => ["hr", { "data-page-break": "true" }],
});

/* Inline change-proposal preview: strike the original text in place and render
   the proposed replacement right after it as a widget — purely decorative until
   the proposal is accepted. Ambiguous (multi-match) proposals stay card-only. */
const inlineKey = new PluginKey("wb-inline-proposals");
function inlineDecorations(doc: any, items: any[]) {
  const hits: { id: string; from: number; to: number; after: string }[] = [];
  const counts = new Map<string, number>();
  doc.descendants((node: any, pos: number) => {
    if (!node.isTextblock || !node.childCount) return;
    const text = node.textContent;
    for (const item of items) {
      const before = String(item.data.before || "");
      if (!before) continue;
      const at = text.indexOf(before);
      if (at >= 0) {
        counts.set(item.id, (counts.get(item.id) || 0) + 1);
        hits.push({
          id: item.id,
          from: pos + 1 + at,
          to: pos + 1 + at + before.length,
          after: String(item.data.after || ""),
        });
      }
    }
  });
  const decorations: any[] = [];
  const positions: Record<string, number> = {};
  for (const hit of hits) {
    if (counts.get(hit.id) !== 1) continue;
    positions[hit.id] = hit.from;
    decorations.push(Decoration.inline(hit.from, hit.to, { class: "wb-inline-before" }));
    decorations.push(
      Decoration.widget(
        hit.to,
        () => {
          const el = document.createElement("ins");
          el.className = "wb-inline-after";
          el.textContent = hit.after;
          return el;
        },
        { side: 1, key: hit.id },
      ),
    );
  }
  return { decorations: DecorationSet.create(doc, decorations), positions };
}
const InlineProposals = Extension.create({
  name: "inlineProposals",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: inlineKey,
        state: {
          init: () => ({
            items: [] as any[],
            decorations: DecorationSet.empty,
            positions: {} as Record<string, number>,
          }),
          apply(tr, value, _old, newState) {
            const meta = tr.getMeta(inlineKey);
            const items = meta ? meta.items : value.items;
            if (!items.length)
              return { items, decorations: DecorationSet.empty, positions: {} };
            if (meta || tr.docChanged)
              return { items, ...inlineDecorations(newState.doc, items) };
            return {
              items,
              decorations: value.decorations.map(tr.mapping, tr.doc),
              positions: value.positions,
            };
          },
        },
        props: {
          decorations(state) {
            return inlineKey.getState(state)?.decorations;
          },
        },
      }),
    ];
  },
});

type SaveStatus = "saved" | "restoredDraft" | "unsaved" | "offlineDraft" | "cacheFailed" | "saving" | "saveFailed" | "cloudAdopted";

export function DocumentPane({
  document: doc,
  user,
  onSaved,
  onReference,
  onError,
}: {
  document: Item;
  user: string;
  onSaved: (d: Item) => void;
  onReference: (r: Reference, action?: string) => void;
  onError: (s: string) => void;
}) {
  const { t } = useT();
  const reduceMotion = useReducedMotion();
  const [linkDialog, setLinkDialog] = useState(false);
  const [overflow, setOverflow] = useState(false);
  const [overflowPos, setOverflowPos] = useState<{ top: number; right: number }>();
  // 保存状态存"码"不存文案：图标与分支判断都按码走，切语言不影响逻辑。
  const [status, setStatus] = useState<SaveStatus>("saved"),
    [conflict, setConflict] = useState<Item>(),
    [versions, setVersions] = useState<any[]>(),
    [proposals, setProposals] = useState<Item[]>([]),
    [font, setFont] = useState(17),
    [sel, setSel] = useState<{ text: string; x: number; y: number }>(),
    [selMenu, setSelMenu] = useState(false);
  const reading = useRef<HTMLDivElement>(null),
    paneRef = useRef<HTMLElement>(null),
    selRange = useRef<{ from: number; to: number } | undefined>(undefined),
    winRange = useRef<Range | undefined>(undefined),
    selTick = useRef(0);
  const latest = useRef(doc),
    timer = useRef<ReturnType<typeof setTimeout>>(null),
    serial = useRef(Promise.resolve()),
    alive = useRef(true),
    dirty = useRef(false),
    blocked = useRef(false),
    editorRef = useRef<any>(null);
  /*
   * dirty 是 ref（保存链路里要读到最新值，且改动频繁不想每次重渲染），但渲染期读 ref 不会触发
   * 重渲染：底部「全部拒绝 / 全部接受 / 恢复此版本」的 disabled 会停在第一次编辑之前的状态。
   * 用一份 state 镜像它，两个都写。
   */
  const [isDirty, setIsDirty] = useState(false);
  const markDirty = (value: boolean) => {
    dirty.current = value;
    setIsDirty(value);
  };
  const scrollSave = useRef<ReturnType<typeof setTimeout>>(null);
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Highlight,
      TableKit,
      Image.configure({ allowBase64: true }),
      PageBreak,
      Placeholder.configure({ placeholder: t("workbench.doc.editorPlaceholder") }),
      InlineProposals,
    ],
    content: doc.data.content || {
      type: "doc",
      content: [{ type: "paragraph" }],
    },
    editable: doc.data.format === "native",
    onUpdate: ({ editor }) => schedule(editor.getJSON()),
    onSelectionUpdate: () => nativeSelection(),
  });
  const ui = useEditorState({
    editor,
    selector: ({ editor }) => ({
      bold: editor?.isActive("bold") ?? false,
      italic: editor?.isActive("italic") ?? false,
      underline: editor?.isActive("underline") ?? false,
      strike: editor?.isActive("strike") ?? false,
      highlight: editor?.isActive("highlight") ?? false,
      bullet: editor?.isActive("bulletList") ?? false,
      ordered: editor?.isActive("orderedList") ?? false,
      heading: editor?.isActive("heading")
        ? String(editor.getAttributes("heading").level)
        : "p",
      undo: editor?.can().undo() ?? false,
      redo: editor?.can().redo() ?? false,
      chars: editor?.state.doc.textContent.length ?? 0,
    }),
  });
  editorRef.current = editor;
  const native = doc.data.format === "native";
  const pending = useMemo(
    () => proposals.filter((p) => p.data.status === "pending"),
    [proposals],
  );
  // effect 里的异步回调报错走这里：总是调用最新的 onError，又不让它成为 effect 的依赖。
  const reportError = useEffectEvent((message: string) => onError(message));
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
      if (scrollSave.current) clearTimeout(scrollSave.current);
      // 排队中的帧会在卸载后调 setSel / setSelMenu，必须取消。
      if (selTick.current) cancelAnimationFrame(selTick.current);
    };
  }, []);
  // 父组件推来新版本：记为最新已知版本，并拉取它的修改建议。
  // 比已知版本还旧的 props（保存回执先到、旧数据后到）直接忽略。
  useEffect(() => {
    if (doc.revision < latest.current.revision) return;
    latest.current = doc;
    api<Item[]>(`/change-proposals?document_id=${doc.id}`)
      .then(setProposals)
      .catch((e) => reportError(e.message));
  }, [doc]);
  // 编辑器内容跟随最新版本；本地有未保存改动时不覆盖。
  // 依赖上一个 effect 先更新 latest（同一组件的 effect 按声明顺序执行），所以必须放在它后面。
  useEffect(() => {
    if (!editor || dirty.current || doc.data.format !== "native") return;
    if (doc.revision < latest.current.revision) return;
    if (JSON.stringify(editor.getJSON()) !== JSON.stringify(doc.data.content))
      editor.commands.setContent(doc.data.content, { emitUpdate: false });
  }, [doc, editor]);
  useEffect(() => {
    if (!editor) return;
    const items = native ? pending : [];
    editor.view.dispatch(editor.state.tr.setMeta(inlineKey, { items }));
  }, [editor, pending, native]);
  usePortalMenuDismiss(overflow, () => setOverflow(false), { selectors: OVERFLOW_MENU_SELECTORS });
  useEffect(() => {
    cached<number>(user, "doc-position:" + doc.id).then((p) => {
      if (reading.current) reading.current.scrollTop = p || 0;
    });
  }, [doc.id, user]);
  // 本地草稿与云端不一致时恢复草稿。比较用的是读到草稿那一刻的最新 doc，
  // 打开后云端若已前进，会按冲突处理，而不是拿旧版本号去覆盖保存。
  const restoreDraft = useEffectEvent((draft: any) => {
    if (
      !draft?.content ||
      JSON.stringify(draft.content) === JSON.stringify(doc.data.content)
    )
      return;
    markDirty(true);
    editorRef.current?.commands.setContent(draft.content, {
      emitUpdate: false,
    });
    setStatus("restoredDraft");
    if (draft.revision !== doc.revision) {
      blocked.current = true;
      setConflict(doc);
    } else schedule(draft.content);
  });
  // 组件按 doc.id 挂载（父组件 key={doc.id}），所以这里每份文档只跑一次。
  useEffect(() => {
    cached<any>(user, "doc-draft:" + doc.id).then((d) => restoreDraft(d));
  }, [doc.id, user]);
  function schedule(content: any) {
    markDirty(true);
    setStatus(navigator.onLine ? "unsaved" : "offlineDraft");
    remember(user, "doc-draft:" + doc.id, {
      revision: latest.current.revision,
      content,
    }).catch(() => setStatus("cacheFailed"));
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      serial.current = serial.current.then(async () => {
        if (blocked.current || !navigator.onLine) return;
        setStatus("saving");
        try {
          const d = await api<Item>(`/documents/${doc.id}/content`, "PUT", {
            expected_revision: latest.current.revision,
            content,
          });
          latest.current = d;
          if (
            JSON.stringify(editorRef.current?.getJSON()) ===
            JSON.stringify(content)
          ) {
            markDirty(false);
            await remember(user, "doc-draft:" + doc.id, null);
            if (alive.current) setStatus("saved");
          }
          if (alive.current) onSaved(d);
        } catch (e) {
          if (e instanceof Conflict && e.current) {
            blocked.current = true;
            setConflict(e.current);
          }
          if (alive.current) setStatus("saveFailed");
        }
      });
    }, 800);
  }
  // 网络恢复后补存。走 effect event 才能用到最新的 schedule（及其中的 onSaved 等 props），
  // 监听器本身只需注册一次。
  const resumeSave = useEffectEvent(() => {
    const ed = editorRef.current;
    if (dirty.current && ed) schedule(ed.getJSON());
  });
  useEffect(() => {
    const online = () => resumeSave();
    window.addEventListener("online", online);
    return () => window.removeEventListener("online", online);
  }, []);

  /* Selection popover: native docs use ProseMirror coords, previews use the
     window selection range; both land in pane-relative coordinates. */
  function placeSel(text: string, clientX: number, topEdge: number, bottomEdge: number) {
    const pane = paneRef.current?.getBoundingClientRect();
    if (!pane) return;
    const width = 172,
      height = 44,
      margin = 8;
    let left = clientX - width / 2;
    left = Math.max(margin, Math.min(left, pane.width - width - margin));
    let top = topEdge - pane.top - height - 8;
    if (top < 52) top = bottomEdge - pane.top + 8;
    setSel({ text, x: left, y: Math.max(52, Math.min(top, pane.height - height - margin)) });
  }
  function nativeSelection() {
    const ed = editorRef.current;
    if (!ed || doc.data.format !== "native") return;
    const { from, to } = ed.state.selection;
    const text = ed.state.doc.textBetween(from, to, "\n");
    if (!text.trim()) {
      selRange.current = undefined;
      setSel(undefined);
      setSelMenu(false);
      return;
    }
    selRange.current = { from, to };
    const a = ed.view.coordsAtPos(from),
      b = ed.view.coordsAtPos(to);
    placeSel(
      text,
      (a.left + b.left) / 2,
      Math.min(a.top, b.top),
      Math.max(a.bottom, b.bottom),
    );
  }
  function repositionSel() {
    if (!sel) return;
    if (native && selRange.current && editorRef.current) {
      const { from, to } = selRange.current;
      const a = editorRef.current.view.coordsAtPos(from),
        b = editorRef.current.view.coordsAtPos(to);
      placeSel(
        sel.text,
        (a.left + b.left) / 2,
        Math.min(a.top, b.top),
        Math.max(a.bottom, b.bottom),
      );
    } else if (winRange.current) {
      const r = winRange.current.getBoundingClientRect();
      placeSel(sel.text, r.left + r.width / 2, r.top, r.bottom);
    }
  }
  function selected(action: string) {
    if (!sel) return;
    onReference(
      {
        kind: "selection",
        id: doc.id,
        revision: latest.current.revision,
        title: doc.title,
        text: sel.text,
        anchor: native ? selRange.current : undefined,
      },
      action,
    );
    setSel(undefined);
    setSelMenu(false);
  }
  function locate(id: string) {
    const ed = editorRef.current;
    if (!ed) return;
    const pos = inlineKey.getState(ed.view.state)?.positions?.[id];
    if (pos == null) return;
    const dom = ed.view.domAtPos(pos);
    const el =
      dom.node.nodeType === 1
        ? (dom.node as HTMLElement)
        : dom.node.parentElement;
    el?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
  }
  const openVersions = () =>
    api<any[]>(`/documents/${doc.id}/versions`)
      .then(setVersions)
      .catch((e) => onError(e.message));
  async function decision(p: Item, action: "accept" | "reject") {
    try {
      if (dirty.current) throw new Error(t("workbench.doc.saveBeforeReview"));
      const result = await api(
        `/change-proposals/${p.id}/decision`,
        "POST",
        { action, expected_revision: latest.current.revision },
        crypto.randomUUID(),
      );
      onSaved(result.document);
      setProposals(await api(`/change-proposals?document_id=${doc.id}`));
    } catch (e) {
      onError(e.message);
    }
  }
  async function batch(action: "accept" | "reject") {
    for (const p of proposals.filter((x) => x.data.status === "pending")) {
      try {
        const result = await api(
          `/change-proposals/${p.id}/decision`,
          "POST",
          { action, expected_revision: latest.current.revision },
          crypto.randomUUID(),
        );
        latest.current = result.document;
        onSaved(result.document);
      } catch (e) {
        onError(e.message);
        break;
      }
    }
    setProposals(await api(`/change-proposals?document_id=${doc.id}`));
  }
  const statusText: Record<SaveStatus, string> = {
    saved: t("workbench.doc.statusSaved"),
    restoredDraft: t("workbench.doc.statusRestoredDraft"),
    unsaved: t("workbench.doc.statusUnsaved"),
    offlineDraft: t("workbench.doc.statusOfflineDraft"),
    cacheFailed: t("workbench.doc.statusCacheFailed"),
    saving: t("workbench.doc.statusSaving"),
    saveFailed: t("workbench.doc.statusSaveFailed"),
    cloudAdopted: t("workbench.doc.statusCloudAdopted"),
  };
  const saveIcon = !native ? null : status === "saving" ? (
    <Loader2 size={13} className="wb-spin" />
  ) : status === "saveFailed" ? (
    <CircleAlert size={13} />
  ) : status === "saved" || status === "restoredDraft" || status === "cloudAdopted" ? (
    <Check size={13} />
  ) : null;
  return (
    <section className="wb-document-pane" ref={paneRef}>
      <header className="wb-document-toolbar">
        {native && editor && (
          <>
            <div className="wb-toolbar-group">
              <button
                title={t("workbench.doc.undo")}
                aria-label={t("workbench.doc.undo")}
                disabled={!ui?.undo}
                onClick={() => editor.chain().focus().undo().run()}
              >
                <Undo />
              </button>
              <button
                title={t("workbench.doc.redo")}
                aria-label={t("workbench.doc.redo")}
                disabled={!ui?.redo}
                onClick={() => editor.chain().focus().redo().run()}
              >
                <Redo />
              </button>
            </div>
            <div className="wb-toolbar-group">
              <SelectField
                className="wb-heading-select"
                aria-label={t("workbench.doc.paragraphFormat")}
                value={ui?.heading || "p"}
                onChange={(value) =>
                  value === "p"
                    ? editor.chain().focus().setParagraph().run()
                    : editor
                        .chain()
                        .focus()
                        .toggleHeading({ level: +value as 1 | 2 | 3 })
                        .run()
                }
                options={[
                  { value: "p", label: t("workbench.doc.paragraphBody") },
                  { value: "1", label: t("workbench.doc.paragraphH1") },
                  { value: "2", label: t("workbench.doc.paragraphH2") },
                  { value: "3", label: t("workbench.doc.paragraphH3") },
                ]}
              />
              <button
                title={t("workbench.doc.bold")}
                aria-label={t("workbench.doc.bold")}
                aria-pressed={ui?.bold}
                onClick={() => editor.chain().focus().toggleBold().run()}
              >
                <Bold />
              </button>
              <button
                title={t("workbench.doc.italic")}
                aria-label={t("workbench.doc.italic")}
                aria-pressed={ui?.italic}
                onClick={() => editor.chain().focus().toggleItalic().run()}
              >
                <Italic />
              </button>
              <button
                title={t("workbench.doc.underline")}
                aria-label={t("workbench.doc.underline")}
                aria-pressed={ui?.underline}
                onClick={() => editor.chain().focus().toggleUnderline().run()}
              >
                <u className="wb-u-glyph">U</u>
              </button>
              <button
                title={t("workbench.doc.strike")}
                aria-label={t("workbench.doc.strike")}
                aria-pressed={ui?.strike}
                onClick={() => editor.chain().focus().toggleStrike().run()}
              >
                <Strikethrough />
              </button>
              <button
                title={t("workbench.doc.highlight")}
                aria-label={t("workbench.doc.highlight")}
                aria-pressed={ui?.highlight}
                onClick={() => editor.chain().focus().toggleHighlight().run()}
              >
                <Highlighter />
              </button>
            </div>
            <div className="wb-toolbar-group">
              <button
                title={t("workbench.doc.bulletList")}
                aria-label={t("workbench.doc.bulletList")}
                aria-pressed={ui?.bullet}
                onClick={() => editor.chain().focus().toggleBulletList().run()}
              >
                <List />
              </button>
              <button
                title={t("workbench.doc.orderedList")}
                aria-label={t("workbench.doc.orderedList")}
                aria-pressed={ui?.ordered}
                onClick={() =>
                  editor.chain().focus().toggleOrderedList().run()
                }
              >
                <ListOrdered />
              </button>
              <button
                title={t("workbench.doc.insertTable")}
                aria-label={t("workbench.doc.insertTable")}
                onClick={() =>
                  editor
                    .chain()
                    .focus()
                    .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
                    .run()
                }
              >
                <Table />
              </button>
              <button
                title={t("workbench.doc.blockquote")}
                aria-label={t("workbench.doc.blockquote")}
                onClick={() => editor.chain().focus().toggleBlockquote().run()}
              >
                <Quote />
              </button>
            </div>
            <div className="wb-toolbar-group">
              <label className="wb-file-button wb-image-upload" title={t("workbench.doc.insertImage")}>
                <ImagePlus aria-hidden="true" />
                <span className="sr-only">{t("workbench.doc.insertImage")}</span>
                <input
                  type="file"
                  aria-label={t("workbench.doc.insertImage")}
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    if (f.size > 4 * 1024 * 1024) {
                      onError(t("workbench.doc.imageTooLarge"));
                      return;
                    }
                    const reader = new FileReader();
                    reader.onload = () =>
                      editor
                        .chain()
                        .focus()
                        .setImage({ src: String(reader.result) })
                        .run();
                    reader.readAsDataURL(f);
                  }}
                />
              </label>
              <button
                title={t("workbench.doc.insertLink")}
                aria-label={t("workbench.doc.insertLink")}
                onClick={() => setLinkDialog(true)}
              >
                <Link />
              </button>
              <button
                title={t("workbench.doc.insertPageBreak")}
                aria-label={t("workbench.doc.insertPageBreak")}
                onClick={() =>
                  editor.chain().focus().insertContent({ type: "pageBreak" }).run()
                }
              >
                <FilePlus2 />
              </button>
            </div>
          </>
        )}
        {!native && <span className="wb-format-badge">{doc.data.format?.toUpperCase()}</span>}
        <span className="wb-spacer" />
        <div className="wb-toolbar-group">
          {["docx", "txt", "md"].includes(doc.data.format) && (
            <button
              className="wb-text-action"
              onClick={() =>
                api<Item>(`/documents/${doc.id}/editable-copy`, "POST")
                  .then(onSaved)
                  .catch((e) => onError(e.message))
              }
            >
              <FilePlus2 size={15} />
              {t("workbench.doc.createEditCopy")}
            </button>
          )}
          <button
            className="wb-text-action"
            onClick={() =>
              download(doc.id, doc.title, native).catch((e) =>
                onError(e.message),
              )
            }
          >
            <Download size={15} />
            {native ? t("workbench.doc.exportWord") : t("workbench.doc.downloadOriginal")}
          </button>
          <div className="wb-overflow">
            <button
              title={t("workbench.doc.moreDocActions")}
              aria-label={t("workbench.doc.moreDocActions")}
              aria-expanded={overflow}
              onClick={(e) => {
                if (!overflow) {
                  const r = e.currentTarget.getBoundingClientRect();
                  setOverflowPos({
                    top: r.bottom + 6,
                    right: window.innerWidth - r.right,
                  });
                }
                setOverflow(!overflow);
              }}
            >
              <MoreHorizontal />
            </button>
            {overflow &&
              createPortal(
                <div
                  className="wb-overflow-menu"
                  role="menu"
                  aria-label={t("workbench.doc.moreDocActions")}
                  style={{
                    position: "fixed",
                    top: overflowPos?.top,
                    right: overflowPos?.right,
                  }}
                >
                  <button role="menuitem" onClick={() => { setOverflow(false); openVersions(); }}>
                    <History size={15} />
                    {t("workbench.doc.versionHistory")}
                  </button>
                  <SelectField
                    label={t("workbench.doc.fontSize")}
                    value={String(font)}
                    onChange={(value) => setFont(+value)}
                    options={[15, 17, 19, 22].map((n) => ({ value: String(n), label: String(n) }))}
                  />
                </div>,
                document.body,
              )}
          </div>
        </div>
      </header>
      {doc.data.conversion_notice && (
        <p className="wb-notice">{doc.data.conversion_notice}</p>
      )}
      {conflict && (
        <div className="wb-conflict">
          <strong>{t("workbench.doc.conflictTitle")}</strong>
          <p>{t("workbench.doc.conflictLead", { revision: conflict.revision })}</p>
          <details>
            <summary>{t("workbench.doc.viewCloud")}</summary>
            <pre>{JSON.stringify(conflict.data.content, null, 2)}</pre>
          </details>
          <button
            onClick={async () => {
              try {
                const copy = await api<Item>("/documents", "POST", {
                  title: doc.title + t("workbench.doc.conflictCopySuffix"),
                  project_id: doc.project_id,
                  content: editor.getJSON(),
                });
                blocked.current = false;
                markDirty(false);
                await remember(user, "doc-draft:" + doc.id, null);
                setConflict(undefined);
                onSaved(copy);
              } catch (e) {
                onError(e.message);
              }
            }}
          >
            {t("workbench.doc.saveCopy")}
          </button>
          <button
            onClick={() => {
              editor.commands.setContent(conflict.data.content, {
                emitUpdate: false,
              });
              latest.current = conflict;
              markDirty(false);
              blocked.current = false;
              remember(user, "doc-draft:" + doc.id, null);
              setConflict(undefined);
              onSaved(conflict);
              setStatus("cloudAdopted");
            }}
          >
            {t("workbench.doc.useCloudVersion")}
          </button>
        </div>
      )}
      <div
        ref={reading}
        onScroll={(e) => {
          // 滚动每帧都在触发。以前每次都写一次 IndexedDB，长文档拖动滚动条会持续打满磁盘。
          const top = e.currentTarget.scrollTop;
          if (scrollSave.current) clearTimeout(scrollSave.current);
          scrollSave.current = setTimeout(() => {
            remember(user, "doc-position:" + doc.id, top).catch(() => {});
          }, 240);
          if (!sel) return;
          cancelAnimationFrame(selTick.current);
          selTick.current = requestAnimationFrame(repositionSel);
        }}
        className="wb-document-scroll"
        style={{ "--document-font-size": font + "px" } as React.CSSProperties}
        onMouseUp={() => {
          if (native) return;
          const s = window.getSelection();
          const text = s?.toString() || "";
          if (!s?.rangeCount || !text.trim()) {
            winRange.current = undefined;
            setSel(undefined);
            setSelMenu(false);
            return;
          }
          const range = s.getRangeAt(0);
          winRange.current = range;
          const r = range.getBoundingClientRect();
          placeSel(text, r.left + r.width / 2, r.top, r.bottom);
        }}
      >
        {native ? (
          <article className="wb-paper">
            <EditorContent editor={editor} />
          </article>
        ) : (
          <OriginalPreview
            user={user}
            doc={doc}
            onRegion={(r) => onReference(r, "ask")}
            onError={onError}
          />
        )}
      </div>
      {sel && (
        <div
          className={"wb-select-pop" + (selMenu ? " open" : "")}
          style={
            { "--sel-x": sel.x + "px", "--sel-y": sel.y + "px" } as React.CSSProperties
          }
          role="toolbar"
          aria-label={t("workbench.doc.selActions")}
        >
          <button
            className="wb-select-primary"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => selected("add")}
          >
            <Quote size={13} />
            {t("workbench.doc.referenceToSession")}
          </button>
          <button
            className="wb-select-more"
            aria-label={t("workbench.doc.moreActions")}
            aria-expanded={selMenu}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setSelMenu(!selMenu)}
          >
            <ChevronDown size={14} />
          </button>
          {selMenu && (
            <div className="wb-select-menu" role="menu" aria-label={t("workbench.doc.moreActions")}>
              {([
                ["ask", t("workbench.shell.refAsk")],
                ["rewrite", t("workbench.shell.refRewrite")],
                ["explain", t("workbench.shell.refExplain")],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  role="menuitem"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => selected(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {!!pending.length && (
        <aside className="wb-review" aria-label={t("workbench.doc.reviewPanel")}>
          <header>
            <strong>{t("workbench.doc.reviewTitle", { count: pending.length })}</strong>
            <span className="wb-spacer" />
            <button
              className="wb-batch-reject"
              disabled={isDirty}
              onClick={() => batch("reject")}
            >
              <X size={13} />
              {t("workbench.doc.rejectAll")}
            </button>
            <button
              className="wb-batch-accept"
              disabled={isDirty}
              onClick={() => batch("accept")}
            >
              <Check size={13} />
              {t("workbench.doc.acceptAll")}
            </button>
          </header>
          <div className="wb-review-list">
            {pending.map((p) => (
              <div key={p.id} className="wb-review-card">
                <button
                  className="wb-review-locate"
                  title={t("workbench.doc.locateInText")}
                  onClick={() => locate(p.id)}
                >
                  <span>{p.data.reason}</span>
                </button>
                <del>{p.data.before}</del>
                <ins>{p.data.after}</ins>
                <footer>
                  <small>{t("workbench.doc.basedOnRevision", { revision: p.data.base_revision })}</small>
                  <RouterLink to={"/conversation/" + p.data.conversation_id}>{t("workbench.doc.relatedSession")}</RouterLink>
                  <span className="wb-spacer" />
                  <button className="wb-quiet" onClick={() => decision(p, "reject")}>
                    {t("workbench.doc.reject")}
                  </button>
                  <button className="wb-primary" onClick={() => decision(p, "accept")}>
                    {t("workbench.doc.accept")}
                  </button>
                </footer>
              </div>
            ))}
          </div>
        </aside>
      )}
      <footer className="wb-doc-status">
        <span>{native ? t("workbench.doc.charsCount", { count: ui?.chars ?? 0 }) : (doc.data.format || "").toUpperCase()}</span>
        <span className="wb-save-state" role="status">
          {saveIcon}
          {native ? statusText[status] : t("workbench.doc.originalReadonly")}
        </span>
      </footer>
      {linkDialog && (
        <TextDialog
          title={t("workbench.doc.linkTitle")}
          onClose={() => setLinkDialog(false)}
          onSubmit={(href) => {
            if (!/^https?:\/\//.test(href)) {
              onError(t("workbench.doc.invalidLink"));
              return;
            }
            editor.chain().focus().setLink({ href }).run();
            setLinkDialog(false);
          }}
        />
      )}
      {versions && (
        <div
          className="wb-modal-backdrop"
          onMouseDown={(e) => { if (e.target === e.currentTarget) setVersions(undefined); }}
          onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setVersions(undefined); } }}
        >
          <section
            className="wb-modal"
            role="dialog"
            aria-modal="true"
            aria-label={t("workbench.doc.versionHistory")}
          >
            <header>
              <h2>{t("workbench.doc.versionHistory")}</h2>
              <button onClick={() => setVersions(undefined)}>{t("common.close")}</button>
            </header>
            <p>{t("workbench.doc.restoreNote")}</p>
            {versions.map((v) => (
              <div className="wb-row" key={v.revision}>
                <span>
                  {t("workbench.doc.versionLabel", { revision: v.revision })}
                  <small>{new Date(v.created_at).toLocaleString()}</small>
                </span>
                <button
                  disabled={doc.data.format !== "native" || isDirty}
                  onClick={async () => {
                    try {
                      const d = await api<Item>(
                        `/documents/${doc.id}/restore-version`,
                        "POST",
                        {
                          expected_revision: latest.current.revision,
                          revision: v.revision,
                        },
                      );
                      onSaved(d);
                      setVersions(undefined);
                    } catch (e) {
                      onError(e.message);
                    }
                  }}
                >
                  {t("workbench.doc.restoreVersion")}
                </button>
              </div>
            ))}
          </section>
        </div>
      )}
    </section>
  );
}
function OriginalPreview({
  doc,
  user,
  onRegion,
  onError,
}: {
  doc: Item;
  user: string;
  onRegion: (r: Reference) => void;
  onError: (s: string) => void;
}) {
  const { t } = useT();
  const container = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null),
    textLayer = useRef<HTMLDivElement>(null),
    viewport = useRef<any>(undefined);
  const [pdf, setPdf] = useState<any>(),
    [page, setPage] = useState(1),
    [zoom, setZoom] = useState(1),
    [rotation, setRotation] = useState(0),
    [url, setUrl] = useState(""),
    [boxMode, setBoxMode] = useState(false),
    [box, setBox] = useState<number[]>(),
    [search, setSearch] = useState("");
  const origin = useRef<number[]>(undefined);
  const format = doc.data.format;
  const reportError = useEffectEvent((message: string) => onError(message));
  const reportRenderFailure = useEffectEvent(() =>
    onError(t("workbench.doc.pdfRenderFailed")),
  );
  useEffect(() => {
    let cleanup = () => {},
      cancelled = false;
    binary(doc.id)
      .then(async (b) => {
        await remember(user, "blob:" + doc.id, b);
        return b;
      })
      .catch(async (e) => {
        const b = await cached<Blob>(user, "blob:" + doc.id);
        if (!b) throw e;
        return b;
      })
      .then(async (blob) => {
        const u = URL.createObjectURL(blob);
        cleanup = () => URL.revokeObjectURL(u);
        if (cancelled) {
          cleanup();
          return;
        }
        setUrl(u);
        if (format === "pdf") {
          const lib = await import("pdfjs-dist");
          lib.GlobalWorkerOptions.workerSrc = new URL(
            "pdfjs-dist/build/pdf.worker.min.mjs",
            import.meta.url,
          ).toString();
          const task = lib.getDocument({ data: await blob.arrayBuffer() });
          const p = await task.promise;
          if (cancelled) {
            task.destroy();
            return;
          }
          setPdf(p);
          const prior = cleanup;
          cleanup = () => {
            prior();
            task.destroy();
          };
        } else if (format === "docx") {
          const { renderAsync } = await import("docx-preview");
          if (container.current)
            await renderAsync(blob, container.current, undefined, {
              inWrapper: true,
              ignoreWidth: true,
              renderAltChunks: false,
            });
        }
      })
      .catch((e) => reportError(e.message));
    return () => {
      cancelled = true;
      cleanup();
    };
  }, [doc.id, format, user]);
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let task: any,
      layer: any,
      cancelled = false;
    (async () => {
      const p = await pdf.getPage(page);
      if (cancelled) return;
      const width = container.current?.clientWidth || 700;
      const base = p.getViewport({ scale: 1, rotation });
      const v = p.getViewport({
        scale: Math.min(1.5, (width - 32) / base.width) * zoom,
        rotation,
      });
      viewport.current = v;
      const c = canvas.current;
      c.width = v.width * devicePixelRatio;
      c.height = v.height * devicePixelRatio;
      c.style.width = v.width + "px";
      c.style.height = v.height + "px";
      task = p.render({
        canvasContext: c.getContext("2d"),
        canvas: c,
        viewport: v,
        transform: [devicePixelRatio, 0, 0, devicePixelRatio, 0, 0],
      });
      await task.promise;
      if (cancelled) return;
      const lib = await import("pdfjs-dist");
      const el = textLayer.current;
      el.innerHTML = "";
      el.style.width = v.width + "px";
      el.style.height = v.height + "px";
      el.style.setProperty("--scale-factor", String(v.scale));
      layer = new lib.TextLayer({
        textContentSource: await p.getTextContent(),
        container: el,
        viewport: v,
      });
      await layer.render();
    })().catch((e) => {
      if (e.name !== "RenderingCancelledException" && !cancelled)
        reportRenderFailure();
    });
    return () => {
      cancelled = true;
      task?.cancel();
      layer?.cancel();
    };
  }, [pdf, page, zoom, rotation]);
  async function find() {
    if (!pdf || !search.trim()) return;
    for (let i = 0; i < pdf.numPages; i++) {
      const n = ((page + i) % pdf.numPages) + 1;
      const p = await pdf.getPage(n);
      const text = await p.getTextContent();
      if (
        text.items
          .map((x: any) => x.str || "")
          .join("")
          .includes(search)
      ) {
        setPage(n);
        return;
      }
    }
    onError(t("workbench.doc.noMatchText"));
  }
  function point(e: React.PointerEvent) {
    const b = e.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - b.left) / b.width)),
      Math.max(0, Math.min(1, (e.clientY - b.top) / b.height)),
    ];
  }
  function finish(e: React.PointerEvent) {
    if (!boxMode || !origin.current) return;
    const a = origin.current,
      b = point(e);
    origin.current = undefined;
    let r = [
      Math.min(a[0], b[0]),
      Math.min(a[1], b[1]),
      Math.max(a[0], b[0]),
      Math.max(a[1], b[1]),
    ];
    if (doc.data.format === "pdf") {
      const unrotate = (x: number, y: number) =>
        rotation === 90
          ? [y, 1 - x]
          : rotation === 180
            ? [1 - x, 1 - y]
            : rotation === 270
              ? [1 - y, x]
              : [x, y];
      const p = unrotate(r[0], r[1]),
        q = unrotate(r[2], r[3]);
      r = [
        Math.min(p[0], q[0]),
        Math.min(p[1], q[1]),
        Math.max(p[0], q[0]),
        Math.max(p[1], q[1]),
      ];
    }
    onRegion({
      kind: "region",
      id: doc.id,
      revision: doc.revision,
      title: doc.title,
      page,
      rect: r,
      rotation,
    });
    setBoxMode(false);
    setBox(undefined);
  }
  return (
    <>
      {doc.data.format === "pdf" && (
        <div className="wb-preview-controls">
          <button
            aria-label={t("workbench.doc.prevPage")}
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <span>
            {page} / {pdf?.numPages || "…"}
          </span>
          <button
            aria-label={t("workbench.doc.nextPage")}
            disabled={!pdf || page === pdf.numPages}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight size={16} />
          </button>
          <button
            aria-label={t("workbench.doc.zoomOut")}
            onClick={() => setZoom(Math.max(0.5, zoom - 0.2))}
          >
            <ZoomOut size={16} />
          </button>
          <button
            aria-label={t("workbench.doc.zoomIn")}
            onClick={() => setZoom(Math.min(3, zoom + 0.2))}
          >
            <ZoomIn size={16} />
          </button>
          <button aria-label={t("workbench.doc.rotatePage")} onClick={() => setRotation((rotation + 90) % 360)}>
            <RotateCw size={16} />
          </button>
          <input
            aria-label={t("workbench.doc.searchPdf")}
            placeholder={t("workbench.doc.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && find()}
          />
          <button className="wb-text-action" onClick={find}>
            {t("workbench.doc.find")}
          </button>
          <button
            className={"wb-text-action wb-box-toggle" + (boxMode ? " selected" : "")}
            aria-pressed={boxMode}
            onClick={() => setBoxMode(!boxMode)}
          >
            <Scan size={15} />
            {t("workbench.doc.selectRegionAsk")}
          </button>
        </div>
      )}
      <div ref={container} className="wb-original">
        {["pdf", "image"].includes(doc.data.format) && (
          <div
            className={"wb-page-surface " + (boxMode ? "select-region" : "")}
            onPointerDown={(e) => {
              if (boxMode) {
                e.currentTarget.setPointerCapture(e.pointerId);
                origin.current = point(e);
                setBox([...origin.current, ...origin.current]);
              }
            }}
            onPointerMove={(e) => {
              if (origin.current) setBox([...origin.current, ...point(e)]);
            }}
            onPointerUp={finish}
          >
            {doc.data.format === "pdf" ? (
              <>
                <canvas ref={canvas} />
                <div className="textLayer" ref={textLayer} />
              </>
            ) : (
              <img src={url} alt={doc.title} />
            )}{" "}
            {box && (
              <div
                className="wb-region"
                style={{
                  left: Math.min(box[0], box[2]) * 100 + "%",
                  top: Math.min(box[1], box[3]) * 100 + "%",
                  width: Math.abs(box[2] - box[0]) * 100 + "%",
                  height: Math.abs(box[3] - box[1]) * 100 + "%",
                }}
              />
            )}
          </div>
        )}
        {["txt", "md"].includes(doc.data.format) && (
          <pre className="wb-paper">{doc.data.text}</pre>
        )}
        {doc.data.format === "image" && (
          <button
            className={"wb-text-action wb-box-toggle" + (boxMode ? " selected" : "")}
            onClick={() => setBoxMode(!boxMode)}
          >
            <Scan size={15} />
            {t("workbench.doc.selectRegionAsk")}
          </button>
        )}
      </div>
    </>
  );
}
