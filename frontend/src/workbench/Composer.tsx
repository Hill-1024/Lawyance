import React, { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
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
import { SelectField } from "./SelectField";
import { useT } from "../i18n";
import { AnimatedSwitch } from "../components/AnimatedSwitch";
import { CheckBox } from "../components/CheckBox";
import { formatKeys, getBinding, matchKeys, SHORTCUT_IDS } from "../lib/shortcuts";
export type Draft = { text: string; references: Reference[] };
type CandidateKind = "task" | "skill" | "document" | "folder" | "connector";

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
  const { t } = useT();
  const reduceMotion = useReducedMotion();
  // 候选列表按 fixed 定位：它开在输入框正上方，而 .wb-home 是 overflow:auto 的滚动容器，
  // 留在文档流里会被上方内容区裁掉大半。坐标仿照工作台其它菜单（space/thread/overflow）由 JS 算。
  const [popupPos, setPopupPos] = useState<{ left: number; width: number; bottom: number; maxHeight: number } | null>(null);
  const composing = useRef(false),
    start = useRef(-1);
  // kind 是稳定判别值（choose() 与引用类型都按它分支），label 才是给人看的；两者分开，
  // 否则切语言时判断逻辑会跟着文案漂移。
  const options: Array<{ id: string; title: string; text?: string; kind: CandidateKind; label: string }> =
    menu === "/"
      ? templates.map((def) => ({
          id: def.id,
          title: t(def.titleKey),
          text: t(def.textKey),
          kind: "task" as const,
          label: t("workbench.composer.task"),
        }))
      : menu === "$"
        ? skills
            .filter((x) => x.data.published && x.data.enabled !== false)
            .map((x) => ({ ...x, kind: "skill" as const, label: t("workbench.composer.skill") }))
        : [
            ...documents.map((x) => ({ ...x, kind: "document" as const, label: t("workbench.sidebar.fileFallback") })),
            ...(project ? [{ ...project, kind: "folder" as const, label: t("workbench.composer.projectMaterial") }] : []),
            ...connectors
              .filter((x) => x.data.enabled)
              .map((x) => ({ ...x, kind: "connector" as const, label: t("workbench.manage.plugins") })),
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
        menu === "$" ? "skill" : item.kind === "connector" ? "connector" : item.kind === "folder" ? "folder" : "document";
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
          aria-label={t("workbench.composer.candidates")}
          style={{
            left: popupPos.left,
            width: popupPos.width,
            bottom: popupPos.bottom,
            maxHeight: popupPos.maxHeight,
          }}
        >
          <div className="wb-caption">
            {menu === "/"
              ? t("workbench.composer.chooseTask")
              : menu === "$"
                ? t("workbench.composer.chooseSkill")
                : t("workbench.composer.chooseMaterial")}
            <button aria-label={t("workbench.composer.closeCandidates")} onClick={() => setMenu("")}>
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
                <small>{x.label}</small>
              </button>
            ))
          ) : (
            <p>{t("workbench.composer.noMatch")}</p>
          )}
          <small>{t("workbench.composer.candidateHint", { up: formatKeys(getBinding(SHORTCUT_IDS.candidateUp)), down: formatKeys(getBinding(SHORTCUT_IDS.candidateDown)), close: formatKeys(getBinding(SHORTCUT_IDS.overlayClose)) })}</small>
        </div>
      )}
      {!!draft.references.length && (
        <div className="wb-reference-list">
          <small>{t("workbench.composer.references")}</small>
          {draft.references.map((ref, i) => (
            <div className="wb-reference" key={i}>
              <details>
                <summary>
                  {ref.kind === "skill" ? "$" : "@"} {ref.title || ref.id}
                </summary>
                <p>
                  {t("workbench.sidebar.version", { revision: ref.revision || 1 })}
                  {ref.page ? ` · ${t("workbench.composer.page", { page: ref.page })}` : ""}
                </p>
                {ref.text && <blockquote>{ref.text}</blockquote>}
                {ref.kind === "connector" &&
                  connectors
                    .find((x) => x.id === ref.id)
                    ?.data.tools?.map((t: any) => (
                      <CheckBox
                        key={t.name}
                        label={t.name}
                        checked={ref.tools?.includes(t.name) || false}
                        onCheckedChange={(next) =>
                          onChange({
                            ...draft,
                            references: draft.references.map((r, j) =>
                              j === i
                                ? {
                                    ...r,
                                    tools: next
                                      ? [...(r.tools || []), t.name]
                                      : (r.tools || []).filter((n) => n !== t.name),
                                  }
                                : r,
                            ),
                          })
                        }
                      />
                    ))}
              </details>
              <button
                aria-label={t("workbench.composer.removeReference", { title: ref.title })}
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
        aria-label={t("workbench.composer.inputLabel")}
        placeholder={t("workbench.composer.placeholder")}
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
          title={t("workbench.composer.upload")}
          aria-label={t("workbench.composer.upload")}
          onClick={() => file.current?.click()}
        >
          <Paperclip size={17} />
        </button>
        <button
          aria-label={t("workbench.composer.reference")}
          title={t("workbench.composer.referenceHint")}
          onClick={() => open("@")}
        >
          <AtSign size={16} />
          <span>{t("workbench.composer.reference")}</span>
        </button>
        <button
          aria-label={t("workbench.composer.skill")}
          title={t("workbench.composer.skillHint")}
          onClick={() => open("$")}
        >
          <Sparkles size={16} />
          <span>{t("workbench.composer.skill")}</span>
        </button>
        <button
          aria-label={t("workbench.composer.task")}
          title={t("workbench.composer.taskHint")}
          onClick={() => open("/")}
        >
          <Slash size={16} />
          <span>{t("workbench.composer.task")}</span>
        </button>
        <button
          aria-label={t("workbench.composer.taskSettings")}
          aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}
        >
          <ChevronDown size={15} />
        </button>
        <span className="wb-spacer" />
        {running ? (
          <button className="wb-send" aria-label={t("workbench.composer.stop")} onClick={onStop}>
            <Square size={16} />
          </button>
        ) : (
          <button
            className="wb-send"
            aria-label={t("workbench.composer.send")}
            disabled={!draft.text.trim() || disabled}
            onClick={onSend}
          >
            <ArrowUp size={18} />
          </button>
        )}
      </div>
      {/* 展开/收起要有过渡：直接挂载是硬切，输入框高度会瞬间跳一截。
          与庭审作曲区（.wc-options）同一套 motion 手法，reduced-motion 下时长归零。
          内层承载分隔线与留白，动画只作用在最外层高度上，避免边框跟着闪烁。 */}
      <AnimatePresence initial={false}>
        {advanced && (
          <motion.div
            className="wb-advanced"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.16, ease: [0.2, 0, 0, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="wb-advanced-inner">
              <SelectField
                label={t("workbench.composer.taskMode")}
                value={mode}
                onChange={setMode}
                options={[
                  { value: "default", label: t("workbench.composer.taskModeStandard") },
                  { value: "plan_and_solve", label: t("workbench.composer.taskModePlan") },
                ]}
              />
              {/* 复选框换成应用里既有的开关（设置页同款），原生方框与这套 UI 不同源。 */}
              <AnimatedSwitch
                size="sm"
                checked={ocp}
                onCheckedChange={setOcp}
                label={t("workbench.composer.ocp")}
                ariaLabel={t("workbench.composer.ocp")}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
