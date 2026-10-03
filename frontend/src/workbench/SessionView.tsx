import { ChevronDown, CircleAlert, FileText, Pause, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import React from "react";
import { Markdown } from "./markdown";
import { BrandMark } from "../components/Brand";
import { WorkflowStatusIcon } from "../components/WorkflowStatusIcon";
import { currentActivityLabel, ThoughtBlock } from "./activity";
import { useT } from "../i18n";
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
  /** 消息区滚动回调：宿主用它维护「贴底跟随」判定。 */
  onMessagesScroll?: React.UIEventHandler<HTMLDivElement>;
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
  onMessagesScroll,
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
  // 全部 hook 都放在庭审早退之前、无条件调用：Workbench 在庭审与普通会话之间切换时
  // 复用的是同一个 SessionView 实例，早退后再调 hook 会让两种渲染的 hook 数量不一致。
  // 生产构建里 React 不会报错，表现为从庭审切回会话时下面这些状态被悄悄重置。
  const { t } = useT();
  // 执行过程挂在「Lawver」标签行右侧：状态本身就是开关标签，展开后时间线出现在标签行下方。
  const [timelineOpen, setTimelineOpen] = React.useState(false);
  const reduceMotion = useReducedMotion();
  React.useEffect(() => {
    if (running) setTimelineOpen(true);
  }, [running]);
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
              {t("workbench.court.opening")}
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
  const RUN_TEXT: Record<string, string> = {
    queued: t("workbench.session.runQueued"),
    running: t("workbench.session.runRunning"),
    waiting_confirmation: t("workbench.session.runWaiting"),
    completed: t("workbench.session.runCompleted"),
    failed: t("workbench.session.runFailed"),
    interrupted: t("workbench.session.runInterrupted"),
    stopped: t("workbench.session.runStopped"),
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
  /*
   * 失败反馈的兜底：运行失败的终态写在 run 上（后端会带上 error 文案），
   * 但重新进入会话时前端不一定还持有那个 run 对象——此时用「最后一条消息是用户的、
   * 而且没有任务在跑」来判断上一轮没有收尾，至少让用户知道该重发。
   */
  const runFailed = run?.data.status === "failed" || run?.data.status === "interrupted";
  const stalled = !running && !run && messages.length > 0 && messages[messages.length - 1]?.role === "user";
  const failureNotice = runFailed
    ? run?.data.error || t("workbench.session.runFailedFallback")
    : stalled
      ? t("workbench.session.runStalled")
      : "";
  const runBadge = run ? (
    hasTimeline || run.data.error ? (
      <button
        className="wb-run-badge"
        aria-expanded={timelineOpen}
        title={timelineOpen ? t("workbench.session.collapseRun") : t("workbench.session.viewRun")}
        onClick={() => setTimelineOpen((open) => !open)}
      >
        {RUN_ICON(run.data.status)}
        {running && hasTimeline
          ? currentActivityLabel(activityBlocks)
          : hasTimeline
            ? RUN_TEXT[run.data.status] + " · " + (timelineOpen ? t("workbench.session.collapseThought") : t("workbench.session.viewThought"))
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
  // 展开/收起走高度过渡（与输入框高级面板、庭审选项同一手法）：直接挂载是硬切，
  // 一大段思考内容会瞬间把下面的消息顶走。
  const timeline = (
    <AnimatePresence initial={false}>
      {timelineOpen && run && (hasTimeline || run.data.error) ? (
        <motion.div
          className="wb-thought-list"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.2, ease: [0.2, 0, 0, 1] }}
          style={{ overflow: "hidden" }}
        >
          {run.data.error && <p className="wb-thought-error">{run.data.error}</p>}
          {activityBlocks.map((block) => (
            <div key={block.key} className={"wb-thought-block is-" + block.kind}>
              <small>{block.label}</small>
              <div className="wb-thought-copy">
                <Markdown>{block.content}</Markdown>
              </div>
            </div>
          ))}
          {events
            .filter((event) => event.type === "document")
            .map((event) => (
              <div key={event.seq}>
                <button onClick={() => onOpenDocument(event.content.document_id)}>
                  <FileText size={15} />
                  {event.content.title || t("workbench.session.openDocument")}
                </button>
              </div>
            ))}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );

  return (
    <section className={"wb-chat " + (showDoc ? "wb-agent" : "")}>
      <header className="wb-chat-heading">
        {showDoc && dragHandle}
        <div>
          <small>{showDoc ? t("workbench.session.headingDoc") : t("workbench.session.headingChat")}</small>
          <h2>{conv?.title || t("workbench.session.untitled")}</h2>
        </div>
        <div className="wb-thread-tools">
          {showDoc && (
            <button
              className="wb-desktop-only"
              aria-label={t("workbench.session.collapseChat")}
              title={t("workbench.session.collapseChat")}
              onClick={onCollapseChat}
            >
              <X size={17} />
            </button>
          )}
        </div>
      </header>
      <div className="wb-messages" ref={scrollRef} onScroll={onMessagesScroll}>
        {!messages.length && !running && (
          <div className="wb-chat-empty">
            <BrandMark className="wb-empty-brand" />
            <h3>{showDoc ? t("workbench.session.emptyDoc") : t("workbench.session.emptyChat")}</h3>
            <p>
              {showDoc
                ? t("workbench.session.emptyDocLead")
                : t("workbench.session.emptyChatLead")}
            </p>
          </div>
        )}
        {messages.map((message: any) => (
          <article key={message.id} className={"wb-message " + message.role}>
            <div className="wb-message-label">
              <span className="wb-role">{message.role === "user" ? t("workbench.session.you") : t("workbench.session.assistant")}</span>
              {/*
                徽标与时间线是「当前 run」的附属品：运行期间挂在下方的 live/待响应文章上，
                落到消息上只发生在 run 终态之后（含历史回看）。不挡 running 的话，
                旧回复与流式文章会各挂一份同状态徽标。
              */}
              {runBadge && !running && message.role === "assistant" && message.id === lastAssistantId && runBadge}
              <button className="wb-branch" title={t("workbench.session.branch")} onClick={() => onBranch(message.id)}>
                {t("workbench.session.branchShort")}
              </button>
            </div>
            {timeline && !running && message.role === "assistant" && message.id === lastAssistantId && timeline}
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
            <Markdown>{message.content}</Markdown>
          </article>
        ))}
        {/*
          运行期文章：live 有正文就流式渲染；还没流出正文时也不能整块缺席——
          否则发出消息到首 token 之间会话区一片空白，徽标与时间线也无处安放。
        */}
        {(live || running) && (
          <article className={"wb-message assistant" + (live ? "" : " is-pending")}>
            <div className="wb-message-label">
              <span className="wb-role">Lawver</span>
              {runBadge}
            </div>
            {timeline}
            {live && <Markdown>{live}</Markdown>}
          </article>
        )}
        {run?.data.status === "waiting_confirmation" && (
          <div className="wb-confirmation">
            <strong>{t("workbench.session.toolRequest")}</strong>
            <p>{run.data.confirmation?.tool}</p>
            <pre>{JSON.stringify(run.data.confirmation?.arguments, null, 2)}</pre>
            <p>{t("workbench.session.toolConfirm")}</p>
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
                  {allow ? t("workbench.session.allowOnce") : t("workbench.session.deny")}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {/* 失败提示挂在会话层，不挂在消息里：失败路径不产出 assistant 消息，徽标与
          「任务未完成」就永远没有落点，用户只看到自己那条消息，以为发送成功了。
          这里的「查看执行过程」很关键：失败时活动块与错误详情都在时间线里，
          而徽标挂在 assistant 消息上，失败路径永远没有那个落点。 */}
      {failureNotice && (
        <div className="wb-run-failure" role="status">
          <CircleAlert size={16} />
          <div>
            <strong>{t("workbench.session.runFailed")}</strong>
            <p>{failureNotice}</p>
          </div>
          {run && (hasTimeline || !!run.data.error) && (
            <button
              className="wb-quiet"
              aria-expanded={timelineOpen}
              onClick={() => setTimelineOpen((open) => !open)}
            >
              {timelineOpen ? t("workbench.session.collapseRun") : t("workbench.session.viewRun")}
              <ChevronDown size={12} className={timelineOpen ? "is-open" : ""} aria-hidden="true" />
            </button>
          )}
        </div>
      )}
      {runFailed && !lastAssistantId && <div className="wb-run-thought">{timeline}</div>}
      <div className="wb-composer-wrap">
        {composer}
        <small className="wb-disclaimer">
          {offline
            ? t("workbench.composer.offlineHint")
            : t("workbench.composer.disclaimer")}
        </small>
      </div>
    </section>
  );
}
