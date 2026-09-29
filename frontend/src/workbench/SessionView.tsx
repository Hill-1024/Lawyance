import { ChevronDown, CircleAlert, FileText, Pause, X } from "lucide-react";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BrandMark } from "../components/Brand";
import { WorkflowStatusIcon } from "../components/WorkflowStatusIcon";
import { currentActivityLabel, ThoughtBlock } from "./activity";
import { api, Item, Reference } from "./client";

const CourtConversation = React.lazy(() => import("./CourtConversation"));

/** 会话面板：普通会话的头部 + 消息流 + 运行状态，或嵌入式庭审会话。 */
export type SessionViewProps = {
  courtSelection?: string;
  projectId?: string;
  /** 文档窗格是否在显示：决定文案与是否把会话作为停靠面板。 */
  showDoc: boolean;
  conv?: Item;
  messages: any[];
  run?: Item;
  running: boolean;
  live: string;
  events: any[];
  activityBlocks: ThoughtBlock[];
  offline: boolean;
  composer: React.ReactNode;
  scrollRef: React.RefObject<HTMLDivElement>;
  /** 停靠把手：只有并排显示文档时才需要。 */
  dragHandle?: React.ReactNode;
  /** 仅文档模式：庭审视窗也要跟着收起。 */
  courtChatHidden?: boolean;
  courtReference?: Reference;
  onBranch: (messageId: string) => void;
  onOpenDocument: (documentId: string) => void;
  onOpenReference: (referenceId: string) => void;
  onCollapseChat: () => void;
  onSelectCourt: (id: string, projectId?: string) => void;
  onCancelCourt: () => void;
  onClearCourtReference: () => void;
  onError: (message: string) => void;
};

export function SessionView({
  courtSelection,
  projectId,
  showDoc,
  conv,
  messages,
  run,
  running,
  live,
  events,
  activityBlocks,
  offline,
  composer,
  scrollRef,
  dragHandle,
  courtChatHidden,
  courtReference,
  onBranch,
  onOpenDocument,
  onOpenReference,
  onCollapseChat,
  onSelectCourt,
  onCancelCourt,
  onClearCourtReference,
  onError,
}: SessionViewProps) {
  if (courtSelection)
    return (
      <section
        key="court"
        style={courtChatHidden ? { display: "none" } : undefined}
        className={"wb-chat wb-court-session " + (showDoc ? "wb-agent" : "")}
      >
        <React.Suspense
          fallback={
            <div className="wb-empty-hint" role="status">
              正在打开庭审会话…
            </div>
          }
        >
          <CourtConversation
            key="court-session"
            dragHandle={showDoc ? dragHandle : undefined}
            onCollapse={showDoc ? onCollapseChat : undefined}
            project={projectId}
            selection={courtSelection}
            onSelect={onSelectCourt}
            onCancel={onCancelCourt}
            documentReference={courtReference}
            onClearReference={onClearCourtReference}
          />
        </React.Suspense>
      </section>
    );
  // 执行过程挂在「Lawver」标签行右侧：状态本身就是开关标签，展开后时间线出现在标签行下方。
  const [timelineOpen, setTimelineOpen] = React.useState(false);
  React.useEffect(() => {
    if (running) setTimelineOpen(true);
  }, [running]);
  const RUN_TEXT: Record<string, string> = {
    queued: "等待执行",
    running: "正在处理材料",
    waiting_confirmation: "等待你的确认",
    completed: "任务已完成",
    failed: "任务未完成",
    interrupted: "任务已中断",
    stopped: "已停止",
  };
  const RUN_ICON = (status: string) =>
    status === "completed" ? (
      <WorkflowStatusIcon status="done" />
    ) : ["queued", "running"].includes(status) ? (
      <WorkflowStatusIcon status="running" />
    ) : status === "failed" ? (
      <CircleAlert size={14} />
    ) : (
      <Pause size={14} />
    );
  const lastAssistantId = [...messages].reverse().find((m: any) => m.role === "assistant")?.id;
  const hasTimeline = activityBlocks.length > 0;
  const runBadge = run ? (
    hasTimeline || run.data.error ? (
      <button
        className="wb-run-badge"
        aria-expanded={timelineOpen}
        title={timelineOpen ? "收起执行过程" : "查看执行过程"}
        onClick={() => setTimelineOpen((open) => !open)}
      >
        {RUN_ICON(run.data.status)}
        {running && hasTimeline
          ? currentActivityLabel(activityBlocks)
          : hasTimeline
            ? RUN_TEXT[run.data.status] + " · " + (timelineOpen ? "收起思考过程" : "查看思考过程")
            : RUN_TEXT[run.data.status]}
        <ChevronDown size={12} className="wb-run-chevron" />
      </button>
    ) : (
      <span className="wb-run-badge is-static">
        {RUN_ICON(run.data.status)}
        {RUN_TEXT[run.data.status]}
      </span>
    )
  ) : null;
  // 时间线：只在展开且确有内容时出现；错误信息也在这里交代。
  const timeline =
    timelineOpen && run && (hasTimeline || run.data.error) ? (
      <div className="wb-thought-list">
        {run.data.error && <p className="wb-thought-error">{run.data.error}</p>}
        {activityBlocks.map((block) => (
          <div key={block.key} className={"wb-thought-block is-" + block.kind}>
            <small>{block.label}</small>
            <div className="wb-thought-copy">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.content}</ReactMarkdown>
            </div>
          </div>
        ))}
        {events
          .filter((event) => event.type === "document")
          .map((event) => (
            <div key={event.seq}>
              <button onClick={() => onOpenDocument(event.content.document_id)}>
                <FileText size={15} />
                {event.content.title || "打开文档"}
              </button>
            </div>
          ))}
      </div>
    ) : null;

  return (
    <section className={"wb-chat " + (showDoc ? "wb-agent" : "")}>
      <header className="wb-chat-heading">
        {showDoc && dragHandle}
        <div>
          <small>{showDoc ? "与文档一起思考" : "当前会话"}</small>
          <h2>{conv?.title || "新的开始"}</h2>
        </div>
        <div className="wb-thread-tools">
          {showDoc && (
            <button
              className="wb-desktop-only"
              aria-label="收起对话，仅看文档"
              title="收起对话，仅看文档"
              onClick={onCollapseChat}
            >
              <X size={17} />
            </button>
          )}
        </div>
      </header>
      <div className="wb-messages" ref={scrollRef}>
        {!messages.length && !running && (
          <div className="wb-chat-empty">
            <BrandMark className="wb-empty-brand" />
            <h3>{showDoc ? "让思考与文档同行" : "从一个问题开始"}</h3>
            <p>
              {showDoc
                ? "选择文档片段，即可提问、解释或提出修改建议。"
                : "引用材料，选择技能，描述你希望完成的工作。"}
            </p>
          </div>
        )}
        {messages.map((message: any) => (
          <article key={message.id} className={"wb-message " + message.role}>
            <div className="wb-message-label">
              <span className="wb-role">{message.role === "user" ? "你" : "Lawver"}</span>
              {runBadge && message.role === "assistant" && message.id === lastAssistantId && runBadge}
              <button className="wb-branch" title="从此处分支" onClick={() => onBranch(message.id)}>
                分支
              </button>
            </div>
            {timeline && message.role === "assistant" && message.id === lastAssistantId && timeline}
            {message.references?.length > 0 && (
              <div className="wb-message-refs">
                {message.references.map((reference: any, index: number) => (
                  <button key={index} onClick={() => onOpenReference(reference.id)}>
                    {reference.kind === "skill" ? "$" : "@"} {reference.title} · v
                    {reference.revision}
                  </button>
                ))}
              </div>
            )}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </article>
        ))}
        {live && (
          <article className="wb-message assistant">
            <div className="wb-message-label">
              <span className="wb-role">Lawver</span>
              {runBadge}
            </div>
            {timeline}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{live}</ReactMarkdown>
          </article>
        )}
        {run?.data.status === "waiting_confirmation" && (
          <div className="wb-confirmation">
            <strong>插件请求执行工具</strong>
            <p>{run.data.confirmation?.tool}</p>
            <pre>{JSON.stringify(run.data.confirmation?.arguments, null, 2)}</pre>
            <p>确认后将把上述参数发送给外部插件，可能产生外部变更。</p>
            <div className="wb-confirmation-actions">
              {[false, true].map((allow) => (
                <button
                  key={String(allow)}
                  className={allow ? "wb-primary" : "wb-quiet"}
                  onClick={() =>
                    api(`/runs/${run.id}/confirmation`, "POST", {
                      call_id: run.data.confirmation.id,
                      allow,
                    }).catch((e) => onError(e.message))
                  }
                >
                  {allow ? "允许本次调用" : "拒绝"}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="wb-composer-wrap">
        {composer}
        <small className="wb-disclaimer">
          {offline
            ? "离线可编辑草稿；联网后请主动发送。"
            : "法律意见需结合事实核验 · 仅使用本次明确引用的资料"}
        </small>
      </div>
    </section>
  );
}
