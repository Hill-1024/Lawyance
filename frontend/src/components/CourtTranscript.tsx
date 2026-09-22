/*
 * 模块描述：模拟法庭庭审记录，按发言时间线渲染多方发言、阶段分隔与流式状态。
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  ChevronDown,
  Gavel,
  GitBranch,
  History,
  Landmark,
  Play,
  Scale,
  ScrollText,
  Undo2,
  UserRound,
  X
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import type { CourtPublicEvent, CourtSession, CourtSpeaker } from '../types';
import { HoverInfo } from './HoverInfo';
import { useAppDialog } from '../contexts/DialogContext';
import { useTranslation } from '../contexts/LocaleContext';
import { stripAttachmentPrompt, stripWorkspacePaths } from '../lib/attachment-prompt';

type Translate = ReturnType<typeof useTranslation>;

const buildPhaseLabels = (t: Translate): Record<string, string> => ({
  opening: t('court.transcript.phase.opening'),
  claim_statement: t('court.transcript.phase.claimStatement'),
  prosecution_statement: t('court.transcript.phase.prosecutionStatement'),
  defense_response: t('court.transcript.phase.defenseResponse'),
  agency_response: t('court.transcript.phase.agencyResponse'),
  court_inquiry: t('court.transcript.phase.courtInquiry'),
  legality_review: t('court.transcript.phase.legalityReview'),
  evidence_cross: t('court.transcript.phase.evidenceCross'),
  court_debate: t('court.transcript.phase.courtDebate'),
  final_statement: t('court.transcript.phase.finalStatement'),
  judge_summary: t('court.transcript.phase.judgeSummary'),
  review: t('court.transcript.phase.review')
});

export const phaseLabel = (phase: string, t: Translate) => buildPhaseLabels(t)[phase] || phase || t('court.transcript.phaseFallback');

type SpeakerMeta = {
  label: string;
  role: string;
  icon: React.ElementType;
  avatarClass: string;
  iconClass: string;
  nameClass: string;
};

export const buildSpeakerMeta = (t: Translate): Record<CourtSpeaker, SpeakerMeta> => ({
  judge: {
    label: t('court.transcript.speaker.judge'),
    role: t('court.transcript.speaker.judgeRole'),
    icon: Gavel,
    avatarClass: 'bg-[var(--accent-quiet)]',
    iconClass: 'text-[var(--accent)]',
    nameClass: 'text-[var(--brand-primary-700)] dark:text-[var(--accent)]'
  },
  opponent: {
    label: t('court.transcript.speaker.opponent'),
    role: t('court.transcript.speaker.opponentRole'),
    icon: Scale,
    avatarClass: 'bg-[rgba(184,132,42,0.14)]',
    iconClass: 'text-[var(--color-warning-500)]',
    nameClass: 'text-[var(--color-warning-500)]'
  },
  reviewer: {
    label: t('court.transcript.speaker.reviewer'),
    role: t('court.transcript.speaker.reviewerRole'),
    icon: BrainCircuit,
    avatarClass: 'bg-[rgba(44,118,112,0.14)]',
    iconClass: 'text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]',
    nameClass: 'text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
  },
  user: {
    label: t('court.transcript.speaker.user'),
    role: t('court.transcript.speaker.userRole'),
    icon: UserRound,
    avatarClass: 'bg-[var(--accent)]',
    iconClass: 'text-[var(--accent-on)]',
    nameClass: 'text-[var(--fg-1)]'
  },
  system: {
    label: t('court.transcript.speaker.system'),
    role: t('court.transcript.speaker.systemRole'),
    icon: Landmark,
    avatarClass: 'bg-[var(--bg-inset)]',
    iconClass: 'text-[var(--fg-3)]',
    nameClass: 'text-[var(--fg-3)]'
  }
});

const courtSanitizeSchema: any = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames || []), 'sup', 'sub'],
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a || []), 'href', 'title'],
    code: [...(defaultSchema.attributes?.code || []), ['className', /^language-[\w-]+$/]],
    sup: [],
    sub: []
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto']
  }
};

const markdownComponents: any = {
  a(props: any) {
    const { node, ...rest } = props;
    return <a target="_blank" rel="noopener noreferrer" {...rest} />;
  }
};

/**
 * 展示用文本：剥掉内部工作区路径与附件说明块。
 * 事件原始 content 保留路径（各角色据此调用 image_reader 等工具读取材料），
 * 但用户不应在庭审记录里看到 TEMP/... 这类内部路径。
 */
const toDisplayContent = (content?: string): string => {
  if (!content) return '';
  return stripWorkspacePaths(stripAttachmentPrompt(content));
};

const CourtMarkdown: React.FC<{ content?: string; compact?: boolean; className?: string }> = ({
  content,
  compact = false,
  className = ''
}) => (
  <div className={`message-copy prose dark:prose-invert w-full max-w-none break-words ${compact ? '!text-[13px] !leading-6' : ''} ${className}`}>
    <Markdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, courtSanitizeSchema]]}
      components={markdownComponents}
    >
      {toDisplayContent(content)}
    </Markdown>
  </div>
);

const TypingDots: React.FC = () => (
  <span className="flex items-center gap-1">
    <span className="lawver-bloom-dot h-1.5 w-1.5 rounded-full bg-[var(--fg-3)]" />
    <span className="lawver-bloom-dot h-1.5 w-1.5 rounded-full bg-[var(--fg-3)]" />
    <span className="lawver-bloom-dot h-1.5 w-1.5 rounded-full bg-[var(--fg-3)]" />
  </span>
);

const PhaseDivider: React.FC<{ phase: string }> = ({ phase }) => {
  const t = useTranslation();
  return (
    <div className="flex items-center gap-3 py-1" role="separator">
      <span className="h-px flex-1 bg-[var(--border-subtle)]" />
      <span className="flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-1 text-[12px] font-medium tracking-[0.04em] text-[var(--fg-3)] shadow-[var(--shadow-1)]">
        <Landmark size={13} strokeWidth={2} className="text-[var(--accent)]" />
        {phaseLabel(phase, t)}
      </span>
      <span className="h-px flex-1 bg-[var(--border-subtle)]" />
    </div>
  );
};

const SystemNotice: React.FC<{ event: CourtPublicEvent }> = ({ event }) => {
  const isError = /出错|失败|错误|异常/.test(event.content);
  return (
    <div className="flex justify-center py-0.5">
      <span
        className={`inline-flex max-w-full items-center gap-1.5 rounded-full px-3 py-1 text-[12px] leading-5 ${
          isError
            ? 'bg-[var(--color-danger-100)] text-[var(--color-danger-500)]'
            : 'bg-[var(--bg-inset)] text-[var(--fg-3)]'
        }`}
      >
        {isError && <AlertTriangle size={12} strokeWidth={2} className="shrink-0" />}
        <span className="truncate">{event.content}</span>
      </span>
    </div>
  );
};

const CourtMessage: React.FC<{
  event: CourtPublicEvent;
  userSideLabel: string;
  isStreaming: boolean;
  isLast: boolean;
  onRewind?: (eventId: string) => void;
  onBranch?: (eventId: string) => void;
}> = ({ event, userSideLabel, isStreaming, isLast, onRewind, onBranch }) => {
  const { showConfirm } = useAppDialog();
  const t = useTranslation();

  if (event.speaker === 'system') {
    return <SystemNotice event={event} />;
  }

  const speakerMeta = buildSpeakerMeta(t);
  const meta = speakerMeta[event.speaker] || speakerMeta.system;
  const Icon = meta.icon;
  const isUser = event.speaker === 'user';
  const name = isUser ? userSideLabel || t('court.transcript.speaker.user') : meta.label;
  const isInterjection = event.type === 'interjection';
  const hasContent = Boolean(event.content && event.content.trim());

  // 流式期间禁止操作正在写入的条目，避免半截撤回/分支。撤回到最后一条无意义。
  const canBranch = Boolean(onBranch) && !isStreaming;
  const canRewind = Boolean(onRewind) && !isStreaming && !isLast;

  const handleRewind = async () => {
    if (!onRewind) return;
    const confirmed = await showConfirm({
      title: t('court.transcript.rewind.title'),
      message: t('court.transcript.rewind.message'),
      tone: 'danger',
      confirmLabel: t('court.transcript.rewind.confirm'),
    });
    if (confirmed) onRewind(event.id);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.2, 0, 0, 1] }}
      className={`group flex max-w-full gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      <span
        className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full shadow-[var(--shadow-1)] ${meta.avatarClass} ${meta.iconClass}`}
      >
        <Icon size={17} strokeWidth={2} />
      </span>

      <div className={`flex min-w-0 flex-col gap-1.5 ${isUser ? 'items-end' : 'w-full items-start'}`}>
        <div className={`flex items-center gap-2 px-0.5 ${isUser ? 'flex-row-reverse' : ''}`}>
          <span className={`text-[13px] font-semibold ${meta.nameClass}`}>{name}</span>
          <span className="text-[12px] text-[var(--fg-4)]">{meta.role}</span>
          {isInterjection && (
            <span className="rounded-full bg-[var(--accent-quiet)] px-2 py-0.5 text-[11px] font-medium text-[var(--accent)]">
              {t('court.transcript.interjection')}
            </span>
          )}
          {isUser && event.by_user_agent && (
            <span
              title={t('court.transcript.agentGenerated')}
              className="inline-flex items-center gap-1 rounded-full bg-[rgba(44,118,112,0.14)] px-2 py-0.5 text-[11px] font-medium text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]"
            >
              <Bot size={10} strokeWidth={2} />
              {t('court.transcript.aiAgent')}
            </span>
          )}
          {isStreaming && hasContent && <TypingDots />}
        </div>

        {isUser ? (
          <div className="w-fit max-w-full rounded-[24px_8px_24px_24px] bg-[var(--accent)] px-4 py-2.5 text-[var(--accent-on)] shadow-[var(--shadow-1)]">
            <CourtMarkdown content={event.content} compact className="court-markdown-on-accent" />
          </div>
        ) : (
          <div className="w-full rounded-[8px_24px_24px_24px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 shadow-[var(--shadow-1)]">
            {hasContent ? (
              <CourtMarkdown content={event.content} />
            ) : (
              <div className="flex h-6 items-center">
                <TypingDots />
              </div>
            )}
          </div>
        )}

        {(canRewind || canBranch) && (
          <div className={`flex items-center gap-0.5 px-0.5 opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:focus-within:opacity-100 ${isUser ? 'self-end' : 'self-start'}`}>
            {canRewind && (
              <HoverInfo label={t('court.transcript.rewind.hint')} placement="top">
                <button
                  onClick={handleRewind}
                  className="lawver-pressable inline-flex h-7 w-7 items-center justify-center rounded-full text-[var(--fg-4)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
                  aria-label={t('court.transcript.rewind.action')}
                >
                  <Undo2 size={13} strokeWidth={2} />
                </button>
              </HoverInfo>
            )}
            {canBranch && (
              <HoverInfo label={t('court.transcript.branch.hint')} placement="top">
                <button
                  onClick={() => onBranch?.(event.id)}
                  className="lawver-pressable inline-flex h-7 w-7 items-center justify-center rounded-full text-[var(--fg-4)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--brand-tertiary-700)] dark:hover:bg-white/[0.06] dark:hover:text-[#8ecdc7]"
                  aria-label={t('court.transcript.branch.hint')}
                >
                  <GitBranch size={13} strokeWidth={2} />
                </button>
              </HoverInfo>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
};

const latestSpeechBySpeaker = (events: CourtPublicEvent[]) => {
  const latest: Partial<Record<CourtSpeaker, CourtPublicEvent>> = {};
  events.forEach(event => {
    if (event.speaker !== 'system') {
      latest[event.speaker] = event;
    }
  });
  return latest;
};

const lastHumanSpeaker = (events: CourtPublicEvent[]): CourtSpeaker | null => {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const speaker = events[index].speaker;
    if (speaker !== 'system') return speaker;
  }
  return null;
};

const resolvePartySeats = (session: CourtSession, t: Translate) => {
  const userSide = session.user_side || t('court.transcript.speaker.userRole');
  const userIsRight = /被告|辩护|行政机关/.test(userSide) && !/原告/.test(userSide);
  const leftTitle = session.case_type === 'criminal' ? t('court.transcript.seat.prosecution') : t('court.transcript.seat.plaintiff');
  const rightTitle = session.case_type === 'criminal' ? t('court.transcript.seat.defense') : t('court.transcript.seat.defendant');
  const opponentLabel = session.case_type === 'criminal'
    ? (userIsRight ? t('court.transcript.party.prosecution') : t('court.transcript.party.defense'))
    : (userIsRight ? t('court.transcript.party.plaintiff') : t('court.transcript.party.defendant'));

  const left = userIsRight
    ? { speaker: 'opponent' as CourtSpeaker, title: leftTitle, participant: opponentLabel }
    : { speaker: 'user' as CourtSpeaker, title: leftTitle, participant: userSide };
  const right = userIsRight
    ? { speaker: 'user' as CourtSpeaker, title: rightTitle, participant: userSide }
    : { speaker: 'opponent' as CourtSpeaker, title: rightTitle, participant: opponentLabel };

  return { left, right };
};

const CourtSeat: React.FC<{
  speaker: CourtSpeaker;
  title: string;
  participant: string;
  event?: CourtPublicEvent;
  active: boolean;
  align?: 'center' | 'left' | 'right';
}> = ({ speaker, title, participant, event, active, align = 'left' }) => {
  const t = useTranslation();
  const speakerMeta = buildSpeakerMeta(t);
  const meta = speakerMeta[speaker] || speakerMeta.system;
  const Icon = meta.icon;
  const textAlign = align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left';
  const bubbleRadius = align === 'right' ? 'rounded-[8px_8px_24px_8px]' : align === 'center' ? 'rounded-[8px_8px_24px_24px]' : 'rounded-[8px_8px_8px_24px]';
  const isUser = speaker === 'user';

  return (
    <section
      className={`min-w-0 rounded-[var(--radius-md)] border bg-[var(--bg-surface)] p-3.5 shadow-[var(--shadow-1)] transition-colors ${
        active ? 'border-[var(--accent)] ring-1 ring-[var(--accent-quiet)]' : 'border-[var(--border-subtle)]'
      }`}
    >
      <div className={`flex items-center gap-3 ${align === 'right' ? 'flex-row-reverse' : ''} ${align === 'center' ? 'justify-center' : ''}`}>
        <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${meta.avatarClass} ${meta.iconClass}`}>
          <Icon size={18} strokeWidth={2} />
        </span>
        <div className={`min-w-0 ${textAlign}`}>
          <div className="text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">{title}</div>
          <div className={`truncate text-[14px] font-semibold ${speaker === 'user' ? 'text-[var(--fg-1)]' : meta.nameClass}`}>
            {participant}
          </div>
        </div>
      </div>

      <div
        className={`mt-3 min-h-[104px] border px-4 py-3 ${bubbleRadius} ${
          isUser
            ? 'border-transparent bg-[var(--accent)] text-[var(--accent-on)]'
            : 'border-[var(--border-subtle)] bg-[var(--bg-inset)] text-[var(--fg-1)]'
        }`}
      >
        {event?.content?.trim() ? (
          <CourtMarkdown content={event.content} compact={speaker !== 'judge'} className={isUser ? 'court-markdown-on-accent' : ''} />
        ) : (
          <p className={`text-[13px] leading-6 ${isUser ? 'text-[var(--accent-on)] opacity-80' : 'text-[var(--fg-4)]'}`}>
            {t('court.transcript.awaitingSpeech')}
          </p>
        )}
      </div>
    </section>
  );
};

const CourtroomStage: React.FC<{ session: CourtSession; isRunning: boolean }> = ({ session, isRunning }) => {
  const t = useTranslation();
  const latest = useMemo(() => latestSpeechBySpeaker(session.public_events), [session.public_events]);
  const activeSpeaker = useMemo(() => lastHumanSpeaker(session.public_events), [session.public_events]);
  const seats = useMemo(() => resolvePartySeats(session, t), [session, t]);
  const reviewerEvent = latest.reviewer;

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[linear-gradient(180deg,var(--bg-surface),var(--bg-app))] p-3 shadow-[var(--shadow-1)] sm:p-4">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto w-full max-w-xl">
          <CourtSeat
            speaker="judge"
            title={t('court.transcript.seat.bench')}
            participant={t('court.transcript.speaker.judge')}
            event={latest.judge}
            active={activeSpeaker === 'judge'}
            align="center"
          />
        </div>

        <div className="mx-auto my-4 h-px w-2/3 bg-[var(--border-subtle)]" aria-hidden="true" />

        <div className="grid gap-4 lg:grid-cols-2">
          <CourtSeat
            speaker={seats.left.speaker}
            title={seats.left.title}
            participant={seats.left.participant}
            event={latest[seats.left.speaker]}
            active={activeSpeaker === seats.left.speaker}
            align="left"
          />
          <CourtSeat
            speaker={seats.right.speaker}
            title={seats.right.title}
            participant={seats.right.participant}
            event={latest[seats.right.speaker]}
            active={activeSpeaker === seats.right.speaker}
            align="right"
          />
        </div>

        {reviewerEvent && (
          <div className="mx-auto mt-4 w-full max-w-2xl">
            <CourtSeat
              speaker="reviewer"
              title={t('court.transcript.seat.review')}
              participant={t('court.transcript.reviewerName')}
              event={reviewerEvent}
              active={activeSpeaker === 'reviewer'}
              align="center"
            />
          </div>
        )}
      </div>
    </div>
  );
};

const HistoryDrawer: React.FC<{
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}> = ({ open, onClose, children }) => {
  const t = useTranslation();
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="court-history-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            key="court-history-drawer"
            initial={{ x: '100%', opacity: 0.8 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0.8 }}
            transition={{ duration: 0.24, ease: [0.2, 0, 0, 1] }}
            className="fixed right-0 top-0 z-50 flex h-full w-[min(92vw,460px)] flex-col border-l border-[var(--border-subtle)] bg-[var(--bg-app)] shadow-[var(--shadow-4)]"
            role="dialog"
            aria-modal="true"
            aria-label={t('court.transcript.history.label')}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-subtle)] px-4 py-3 sm:px-5 sm:py-4">
              <div>
                <h3 className="t-title-m text-[15px]">{t('court.transcript.history.title')}</h3>
                <p className="text-[12px] text-[var(--fg-3)]">{t('court.transcript.history.subtitle')}</p>
              </div>
              <button
                onClick={onClose}
                className="lawver-pressable rounded-full p-2 text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
                aria-label={t('court.transcript.history.close')}
              >
                <X size={19} strokeWidth={2} />
              </button>
            </div>
            <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 py-4 sm:px-4 sm:py-5">
              {children}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
};

const RecapCard: React.FC<{ summary: string }> = ({ summary }) => {
  const t = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-inset)]">
      <button
        onClick={() => setOpen(value => !value)}
        className="lawver-pressable flex w-full items-center gap-2 px-3.5 py-2.5 text-left"
      >
        <ScrollText size={15} strokeWidth={2} className="shrink-0 text-[var(--fg-3)]" />
        <span className="flex-1 text-[13px] font-medium text-[var(--fg-2)]">{t('court.transcript.recap')}</span>
        <ChevronDown
          size={15}
          strokeWidth={2}
          className={`shrink-0 text-[var(--fg-3)] transition-transform duration-200 ${open ? '-rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="border-t border-[var(--border-subtle)] px-3.5 py-3">
          <CourtMarkdown content={summary} compact />
        </div>
      )}
    </div>
  );
};

const StartHero: React.FC<{ session: CourtSession; onStart: () => void; canStart: boolean }> = ({
  session,
  onStart,
  canStart
}) => {
  const t = useTranslation();
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-6 py-12 text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--accent-quiet)] text-[var(--accent)]">
        <Gavel size={30} strokeWidth={2} />
      </span>
      <h2 className="t-headline-s mt-5">{t('court.transcript.start.title')}</h2>
      <p className="mt-2 max-w-md text-[14px] leading-6 text-[var(--fg-3)]">
        {t('court.transcript.start.introPrefix')}<span className="font-medium text-[var(--fg-2)]">{session.user_side}</span>
        {t('court.transcript.start.introSuffix')}
      </p>
      {session.shared_dossier.summary && (
        <div className="mt-5 w-full max-w-md rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 text-left shadow-[var(--shadow-1)]">
          <div className="mb-1 text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-3)]">{t('court.transcript.start.summaryLabel')}</div>
          <p className="line-clamp-4 text-[13px] leading-6 text-[var(--fg-2)]">{session.shared_dossier.summary}</p>
        </div>
      )}
      <button onClick={onStart} disabled={!canStart} className="md3-btn-filled lawver-pressable mt-6">
        <Play size={18} strokeWidth={2} />
        {t('court.transcript.start.button')}
      </button>
    </div>
  );
};

interface CourtTranscriptProps {
  session: CourtSession;
  isRunning: boolean;
  status: string | null;
  /** 发言区实际高度：输入框增高会压缩记录区，贴底时需要跟着补偿。 */
  composerHeight?: number;
  onStart: () => void;
  onRewind?: (eventId: string) => void;
  onBranch?: (eventId: string) => void;
}

export const CourtTranscript: React.FC<CourtTranscriptProps> = ({ session, isRunning, status, composerHeight = 0, onStart, onRewind, onBranch }) => {
  const t = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const lastSignatureRef = useRef('');
  const [historyOpen, setHistoryOpen] = useState(false);

  const events = session.public_events;
  const hasStarted = useMemo(() => events.some(event => event.speaker !== 'system'), [events]);
  const lastEvent = events[events.length - 1];
  const signature = `${events.length}:${lastEvent?.id || ''}:${lastEvent?.content.length || 0}:${isRunning ? 1 : 0}:${Math.round(composerHeight)}`;

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || lastSignatureRef.current === signature) return;
    lastSignatureRef.current = signature;
    if (stickRef.current) {
      container.scrollTo({ top: container.scrollHeight });
    }
  }, [signature]);

  const rows = useMemo(() => {
    const items: React.ReactNode[] = [];
    let renderedPhase = '';
    events.forEach((event, index) => {
      if (event.phase && event.phase !== renderedPhase) {
        items.push(<PhaseDivider key={`phase-${event.id}`} phase={event.phase} />);
        renderedPhase = event.phase;
      }
      const isLast = index === events.length - 1;
      const isStreaming = isRunning && isLast && event.speaker !== 'system';
      items.push(
        <CourtMessage
          key={event.id}
          event={event}
          userSideLabel={session.user_side}
          isStreaming={isStreaming}
          isLast={isLast}
          onRewind={onRewind}
          onBranch={onBranch}
        />
      );
    });
    return items;
  }, [events, isRunning, session.user_side, onRewind, onBranch]);

  return (
    <div
      ref={scrollRef}
      onScroll={event => {
        const el = event.currentTarget;
        stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
      }}
      className="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto bg-[var(--bg-app)]"
    >
      {!hasStarted ? (
        <StartHero session={session} onStart={onStart} canStart={!isRunning && !session.court_state.trial_over} />
      ) : (
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-3 py-4 sm:px-6 sm:py-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="md3-chip md3-chip-primary w-fit">{phaseLabel(session.court_state.phase, t)}</div>
              <p className="mt-1 text-[13px] text-[var(--fg-3)]">{t('court.transcript.stageHint')}</p>
            </div>
            <button onClick={() => setHistoryOpen(true)} className="md3-btn-tonal lawver-pressable">
              <History size={17} strokeWidth={2} />
              {t('court.transcript.history.title')}
            </button>
          </div>
          {session.public_summary && <RecapCard summary={session.public_summary} />}
          <CourtroomStage session={session} isRunning={isRunning} />
          {isRunning && (
            <div className="flex justify-center py-1">
              <span className="inline-flex items-center gap-2 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3.5 py-1.5 text-[12px] font-medium text-[var(--fg-3)] shadow-[var(--shadow-1)]">
                <TypingDots />
                {status || t('court.transcript.running')}
              </span>
            </div>
          )}
          <div aria-hidden="true" className="h-1" />
          <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)}>
            {rows}
          </HistoryDrawer>
        </div>
      )}
    </div>
  );
};
