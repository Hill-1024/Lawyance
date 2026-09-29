import React, { useState, useRef, useEffect } from "react";
import {
  ArrowUp,
  Square,
  Paperclip,
  AtSign,
  Sparkles,
  Slash,
  X,
  ChevronDown,
} from "lucide-react";
import { Item, Reference, templates } from "./client";
import { formatKeys, getBinding, matchKeys, SHORTCUT_IDS } from "../lib/shortcuts";
export type Draft = { text: string; references: Reference[] };
export function Composer({
  draft,
  onChange,
  onSend,
  onStop,
  onUpload,
  documents,
  skills,
  connectors,
  project,
  running,
  disabled,
  mode,
  setMode,
  ocp,
  setOcp,
}: {
  draft: Draft;
  onChange: (d: Draft) => void;
  onSend: () => void;
  onStop: () => void;
  onUpload: (f: File[]) => void;
  documents: Item[];
  skills: Item[];
  connectors: Item[];
  project?: Item;
  running: boolean;
  disabled?: boolean;
  mode: string;
  setMode: (v: string) => void;
  ocp: boolean;
  setOcp: (v: boolean) => void;
}) {
  const input = useRef<HTMLTextAreaElement>(null),
    file = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null),
    popup = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState(""),
    [query, setQuery] = useState(""),
    [index, setIndex] = useState(0),
    [advanced, setAdvanced] = useState(false);
  // 候选列表按 fixed 定位：它开在输入框正上方，而 .wb-home 是 overflow:auto 的滚动容器，
  // 留在文档流里会被上方内容区裁掉大半。坐标仿照工作台其它菜单（space/thread/overflow）由 JS 算。
  const [popupPos, setPopupPos] = useState<{ left: number; width: number; bottom: number; maxHeight: number } | null>(null);
  const composing = useRef(false),
    start = useRef(-1);
  const options =
    menu === "/"
      ? templates.map((t) => ({ ...t, type: "任务" }))
      : menu === "$"
        ? skills
            .filter((x) => x.data.published && x.data.enabled !== false)
            .map((x) => ({ ...x, type: "技能" }))
        : [
            ...documents.map((x) => ({ ...x, type: "文件" })),
            ...(project ? [{ ...project, type: "项目资料" }] : []),
            ...connectors
              .filter((x) => x.data.enabled)
              .map((x) => ({ ...x, type: "插件" })),
          ];
  const candidates = options
    .filter((x) => x.title.toLowerCase().includes(query.toLowerCase()))
    .slice(0, 12);
  useEffect(() => {
    if (!menu) {
      setPopupPos(null);
      return;
    }
    let frame = 0;
    const place = () => {
      frame = 0;
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = window.visualViewport;
      const width = viewport?.width ?? window.innerWidth;
      const height = viewport?.height ?? window.innerHeight;
      const offsetTop = viewport?.offsetTop ?? 0;
      const box = Math.min(rect.width, width - 24);
      setPopupPos({
        left: Math.max(12, Math.min(rect.left, width - box - 12)),
        width: box,
        bottom: height + offsetTop - rect.top + 8,
        maxHeight: Math.max(140, rect.top - offsetTop - 24),
      });
    };
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(place);
    };
    place();
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, { capture: true, passive: true });
    window.visualViewport?.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("scroll", schedule, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, { capture: true });
      window.visualViewport?.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("scroll", schedule);
    };
  }, [menu]);
  useEffect(() => {
    if (input.current) {
      input.current.style.height = "auto";
      input.current.style.height =
        Math.min(input.current.scrollHeight, 220) + "px";
    }
  }, [draft.text]);
  function open(symbol: string) {
    start.current = -1;
    setMenu(symbol);
    setQuery("");
    setIndex(0);
    input.current?.focus();
  }
  function choose(item: any) {
    let text = draft.text;
    if (start.current >= 0) {
      const end = input.current?.selectionStart ?? text.length;
      text = text.slice(0, start.current) + text.slice(end);
    }
    if (menu === "/")
      onChange({ ...draft, text: text + (text ? "\n" : "") + item.text });
    else {
      const kind =
        menu === "$"
          ? "skill"
          : item.type === "插件"
            ? "connector"
            : item.type === "项目资料"
              ? "folder"
              : "document";
      onChange({
        text,
        references: [
          ...draft.references,
          {
            kind,
            id: item.id,
            revision: item.revision,
            title: item.title,
            ...(kind === "connector" ? { tools: [] } : {}),
          },
        ],
      });
    }
    setMenu("");
    setQuery("");
    start.current = -1;
    input.current?.focus();
  }
  function update(text: string, caret: number) {
    onChange({ ...draft, text });
    if (composing.current) return;
    const match = text.slice(0, caret).match(/(?:^|\s)([/@$])([^\s/@$]*)$/);
    if (match) {
      start.current = caret - match[1].length - match[2].length;
      setMenu(match[1]);
      setQuery(match[2]);
      setIndex(0);
    } else setMenu("");
  }
  return (
    <div
      ref={root}
      data-tour="wb-composer"
      className="wb-composer"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        onUpload(Array.from(e.dataTransfer.files));
      }}
    >
      {menu && popupPos && (
        <div
          ref={popup}
          className="wb-candidates"
          role="listbox"
          aria-label="引用候选"
          style={{
            left: popupPos.left,
            width: popupPos.width,
            bottom: popupPos.bottom,
            maxHeight: popupPos.maxHeight,
          }}
        >
          <div className="wb-caption">
            {menu === "/"
              ? "选择任务，编辑后发送"
              : menu === "$"
                ? "选择已发布技能"
                : "选择本次使用的资料或插件"}
            <button aria-label="关闭候选" onClick={() => setMenu("")}>
              <X size={14} />
            </button>
          </div>
          {candidates.length ? (
            candidates.map((x, i) => (
              <button
                key={x.id}
                className={index === i ? "selected" : ""}
                role="option"
                aria-selected={index === i}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(x)}
              >
                <span>{x.title}</span>
                <small>{x.type}</small>
              </button>
            ))
          ) : (
            <p>没有匹配项</p>
          )}
          <small>{formatKeys(getBinding(SHORTCUT_IDS.candidateUp))} {formatKeys(getBinding(SHORTCUT_IDS.candidateDown))} 选择 · Enter / Tab 确认 · {formatKeys(getBinding(SHORTCUT_IDS.overlayClose))} 关闭</small>
        </div>
      )}
      {!!draft.references.length && (
        <div className="wb-reference-list">
          <small>本次引用</small>
          {draft.references.map((ref, i) => (
            <div className="wb-reference" key={i}>
              <details>
                <summary>
                  {ref.kind === "skill" ? "$" : "@"} {ref.title || ref.id}
                </summary>
                <p>
                  版本 {ref.revision || 1}
                  {ref.page ? ` · 第 ${ref.page} 页` : ""}
                </p>
                {ref.text && <blockquote>{ref.text}</blockquote>}
                {ref.kind === "connector" &&
                  connectors
                    .find((x) => x.id === ref.id)
                    ?.data.tools?.map((t: any) => (
                      <label key={t.name}>
                        <input
                          type="checkbox"
                          checked={ref.tools?.includes(t.name) || false}
                          onChange={(e) =>
                            onChange({
                              ...draft,
                              references: draft.references.map((r, j) =>
                                j === i
                                  ? {
                                      ...r,
                                      tools: e.target.checked
                                        ? [...(r.tools || []), t.name]
                                        : (r.tools || []).filter(
                                            (n) => n !== t.name,
                                          ),
                                    }
                                  : r,
                              ),
                            })
                          }
                        />
                        {t.name}
                      </label>
                    ))}
              </details>
              <button
                aria-label={`移除 ${ref.title}`}
                onClick={() =>
                  onChange({
                    ...draft,
                    references: draft.references.filter((_, j) => j !== i),
                  })
                }
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <textarea
        ref={input}
        value={draft.text}
        aria-label="输入任务"
        placeholder="描述你的法律问题，或用 @ 引用材料…"
        disabled={disabled}
        onChange={(e) => update(e.target.value, e.target.selectionStart)}
        onCompositionStart={() => (composing.current = true)}
        onCompositionEnd={(e) => {
          composing.current = false;
          update(e.currentTarget.value, e.currentTarget.selectionStart);
        }}
        onPaste={(e) => {
          const files = Array.from(e.clipboardData.files) as File[];
          if (files.length) {
            e.preventDefault();
            onUpload(files);
          }
        }}
        onKeyDown={(e) => {
          if (
            composing.current ||
            e.nativeEvent.isComposing ||
            e.keyCode === 229
          )
            return;
          if (menu) {
            if (matchKeys(e, getBinding(SHORTCUT_IDS.candidateDown))) {
              e.preventDefault();
              setIndex(
                (index + 1 + Math.max(1, candidates.length)) %
                  Math.max(1, candidates.length),
              );
            } else if (matchKeys(e, getBinding(SHORTCUT_IDS.candidateUp))) {
              e.preventDefault();
              setIndex(
                (index - 1 + Math.max(1, candidates.length)) %
                  Math.max(1, candidates.length),
              );
            } else if (
              (e.key === "Enter" || e.key === "Tab") &&
              candidates[index]
            ) {
              e.preventDefault();
              choose(candidates[index]);
            } else if (matchKeys(e, getBinding(SHORTCUT_IDS.overlayClose))) {
              e.preventDefault();
              setMenu("");
            }
            if (e.key === "Enter") e.preventDefault();
            return;
          }
          if (matchKeys(e, getBinding(SHORTCUT_IDS.composerSend))) {
            e.preventDefault();
            if (!running) onSend();
            return;
          }
          // 换行是浏览器的默认行为；这里显式放行，让绑定可读也可改。
          if (matchKeys(e, getBinding(SHORTCUT_IDS.composerNewline))) return;
        }}
      />
      <div className="wb-composer-actions">
        <input
          ref={file}
          type="file"
          multiple
          hidden
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
          onChange={(e) => {
            onUpload(Array.from(e.target.files || []));
            e.target.value = "";
          }}
        />
        <button
          title="上传文件"
          aria-label="上传文件"
          onClick={() => file.current?.click()}
        >
          <Paperclip size={17} />
        </button>
        <button
          aria-label="引用"
          title="引用材料（@）"
          onClick={() => open("@")}
        >
          <AtSign size={16} />
          <span>引用</span>
        </button>
        <button
          aria-label="技能"
          title="选择技能（$）"
          onClick={() => open("$")}
        >
          <Sparkles size={16} />
          <span>技能</span>
        </button>
        <button
          aria-label="任务"
          title="任务模板（/）"
          onClick={() => open("/")}
        >
          <Slash size={16} />
          <span>任务</span>
        </button>
        <button
          aria-label="任务设置"
          aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}
        >
          <ChevronDown size={15} />
        </button>
        <span className="wb-spacer" />
        {running ? (
          <button className="wb-send" aria-label="停止生成" onClick={onStop}>
            <Square size={16} />
          </button>
        ) : (
          <button
            className="wb-send"
            aria-label="发送任务"
            disabled={!draft.text.trim() || disabled}
            onClick={onSend}
          >
            <ArrowUp size={18} />
          </button>
        )}
      </div>
      {advanced && (
        <div className="wb-advanced">
          <label>
            任务模式
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="default">标准</option>
              <option value="plan_and_solve">规划与执行</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={ocp}
              onChange={(e) => setOcp(e.target.checked)}
            />
            高级输出审查
          </label>
        </div>
      )}
    </div>
  );
}
