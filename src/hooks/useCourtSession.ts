/*
 * 模块描述：模拟法庭状态 Hook，管理 court_sessions、庭审回合流、插嘴队列、错误回滚与庭审工作区心跳。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import type { ContextUsage, ConversationMemory, CourtAgentState, CourtAgentStates, CourtCaseType, CourtPublicEvent, CourtSession, CourtSpeaker, CourtState } from '../types';
import { fileDB } from '../lib/db';
import { isNative } from '../lib/platform';
import { clearCourtMemory, courtTurn, deleteWorkspace, sendHeartbeat } from '../services/api';

const generateUUID = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
};

const nowIso = () => new Date().toISOString();

const idleAgent = (): CourtAgentState => ({
  status: 'idle',
  memory_snapshot: null,
  last_context_usage: null
});

const createAgentStates = (): CourtAgentStates => ({
  judge: idleAgent(),
  opponent: idleAgent(),
  reviewer: idleAgent(),
  user: idleAgent()
});

/** 兼容旧 session（缺 user agent state）的访问保护。 */
const ensureAgentStates = (existing: Partial<CourtAgentStates> | undefined | null): CourtAgentStates => ({
  judge: existing?.judge ?? idleAgent(),
  opponent: existing?.opponent ?? idleAgent(),
  reviewer: existing?.reviewer ?? idleAgent(),
  user: existing?.user ?? idleAgent()
});

const createCourtState = (caseType: CourtCaseType, userSide: string): CourtState => ({
  case_type: caseType,
  user_side: userSide,
  phase: 'opening',
  phase_turn_counts: {},
  total_turns: 0,
  pending_interjection: false,
  awaiting_user: false,
  forced_advance_requested: false,
  speaker_last_positions: {},
  trial_over: false,
  user_agent_enabled: false
});

const createPublicEvent = (
  speaker: CourtSpeaker,
  phase: string,
  content: string,
  type: CourtPublicEvent['type'] = speaker === 'system' ? 'system' : 'speech',
  byUserAgent = false
): CourtPublicEvent => {
  const now = nowIso();
  const base: CourtPublicEvent = {
    id: generateUUID(),
    type,
    speaker,
    phase,
    content,
    created_at: now,
    updated_at: now
  };
  if (byUserAgent) {
    base.by_user_agent = true;
  }
  return base;
};

const caseTypeLabel: Record<CourtCaseType, string> = {
  civil: '民事',
  administrative: '行政',
  criminal: '刑事'
};

const isCourtSpeaker = (value: unknown): value is keyof CourtAgentStates => (
  value === 'judge' || value === 'opponent' || value === 'reviewer' || value === 'user'
);

const speakerLabel = (s: CourtSpeaker | string | undefined) => {
  switch (s) {
    case 'judge': return '法官';
    case 'opponent': return '对方律师';
    case 'reviewer': return '复盘员';
    case 'user': return '用户方';
    default: return '庭审代理';
  }
};

// 工具名 → 中文动作标签。让用户清楚看到 AI 在调用什么。
const TOOL_ACTION_LABELS: Record<string, string> = {
  get_article: '查阅法条',
  search_article: '语义检索法条',
  get_linked_content: '核验法源 URL',
  match_legal_case: '检索类似判例',
  web_search: '联网检索',
  web_fetch: '抓取公开网页',
  pdf_text_reader: '阅读 PDF 卷宗',
  word_reader: '阅读 Word 卷宗',
  list_workspace_files: '清点案卷文件',
  retrieve_conversation_memory: '回溯本角色记忆',
  inspect_conversation_memory: '梳理已有记忆',
  update_conversation_memory: '记录关键事实',
  get_company_profile: '查询企业资料',
  get_company_registration_info: '查询企业登记信息',
  get_contact_info: '查询企业联系方式',
  get_external_investments: '查询对外投资',
  get_key_personnel: '查询主要人员',
  get_listing_info: '查询上市信息',
  get_shareholder_info: '查询股东信息'
};

const formatThoughtToolStatus = (speaker: CourtSpeaker | string, content: string): string | null => {
  const match = content.match(/执行:\s*`([\w_]+)`/);
  if (match) {
    const tool = match[1];
    const label = TOOL_ACTION_LABELS[tool] || `调用工具 ${tool}`;
    return `${speakerLabel(speaker)}正在${label}…`;
  }
  if (content.includes('工具执行完毕') || content.includes('工具调用')) {
    return `${speakerLabel(speaker)}已收集材料，正在组织发言…`;
  }
  return null;
};

const AUTO_ERROR_THRESHOLD = 2;

const isAbortError = (error: unknown) => (
  typeof error === 'object' &&
  error !== null &&
  'name' in error &&
  (error as { name?: string }).name === 'AbortError'
);

/**
 * 给定一个事件 id，把公开记录截取到该事件（含），并基于截取后的事件重算结构化庭审状态。
 * 撤回与分支共用此函数：撤回是原地替换，分支是用截取数据生成新 session。
 */
const deriveStateAtCutoff = (
  session: CourtSession,
  cutoffEventId: string
): { truncatedEvents: CourtPublicEvent[]; recomputedState: CourtState } | null => {
  const idx = session.public_events.findIndex(event => event.id === cutoffEventId);
  if (idx < 0) return null;
  const truncatedEvents = session.public_events.slice(0, idx + 1);

  const counts: Record<string, number> = {};
  const positions: Record<string, number> = {};
  let total = 0;
  for (const event of truncatedEvents) {
    if (event.speaker === 'system') continue;
    if (event.type !== 'speech') continue;
    counts[event.phase] = (counts[event.phase] || 0) + 1;
    total += 1;
    positions[event.speaker] = total;
  }

  // 末位若是用户 interjection，意味着插话尚未被法官处理。
  let pendingInterjection = false;
  for (let i = truncatedEvents.length - 1; i >= 0; i -= 1) {
    const event = truncatedEvents[i];
    if (event.speaker === 'system') continue;
    if (event.speaker === 'user' && event.type === 'interjection') {
      pendingInterjection = true;
    }
    break;
  }

  let lastSpeechPhase: string | null = null;
  for (let i = truncatedEvents.length - 1; i >= 0; i -= 1) {
    if (truncatedEvents[i].speaker !== 'system') {
      lastSpeechPhase = truncatedEvents[i].phase;
      break;
    }
  }
  const fallbackPhase = truncatedEvents[truncatedEvents.length - 1]?.phase || session.court_state.phase;

  return {
    truncatedEvents,
    recomputedState: {
      ...session.court_state,
      phase: lastSpeechPhase || fallbackPhase,
      phase_turn_counts: counts,
      total_turns: total,
      speaker_last_positions: positions,
      pending_interjection: pendingInterjection,
      awaiting_user: false,
      forced_advance_requested: false,
      trial_over: false
    }
  };
};

export function useCourtSession(enabled = true) {
  const [courtSessions, setCourtSessions] = useState<CourtSession[]>([]);
  const [currentCourtId, setCurrentCourtId] = useState('');
  const [isInitialized, setIsInitialized] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [composerText, setComposerText] = useState('');
  const sessionsRef = useRef<CourtSession[]>([]);
  const currentCourtIdRef = useRef('');
  const isRunningRef = useRef(false);
  const consecutiveErrorsRef = useRef(0);
  const activeAbortRef = useRef<AbortController | null>(null);

  const abortActiveTurn = useCallback(() => {
    activeAbortRef.current?.abort();
    activeAbortRef.current = null;
  }, []);

  useEffect(() => () => abortActiveTurn(), [abortActiveTurn]);

  useEffect(() => {
    if (!isNative()) return;

    let listener: { remove: () => Promise<void> } | undefined;
    CapacitorApp.addListener('appStateChange', ({ isActive }) => {
      if (!isActive) abortActiveTurn();
    }).then(handle => {
      listener = handle;
    });

    return () => {
      listener?.remove();
    };
  }, [abortActiveTurn]);

  const commitSessions = useCallback((updater: (prev: CourtSession[]) => CourtSession[]) => {
    const next = updater(sessionsRef.current);
    sessionsRef.current = next;
    setCourtSessions(next);
  }, []);

  const patchSession = useCallback((sessionId: string, updater: (session: CourtSession) => CourtSession) => {
    commitSessions(prev => prev.map(session => (
      session.id === sessionId
        ? { ...updater(session), updated_at: nowIso() }
        : session
    )));
  }, [commitSessions]);

  const currentCourtSession = useMemo(
    () => courtSessions.find(session => session.id === currentCourtId) || null,
    [courtSessions, currentCourtId]
  );

  const getCurrentSession = useCallback(() => (
    sessionsRef.current.find(session => session.id === currentCourtIdRef.current) || null
  ), []);

  // 初始加载。
  useEffect(() => {
    const initData = async () => {
      const savedCourtSessions = await fileDB.getCourtSessions();
      // 兼容旧数据：旧 session 的 agent_states 没有 user 字段，statefully 兜底。
      const normalized = savedCourtSessions.map(session => ({
        ...session,
        agent_states: ensureAgentStates(session.agent_states)
      }));
      sessionsRef.current = normalized;
      setCourtSessions(normalized);
      if (normalized.length > 0) {
        setCurrentCourtId(normalized[0].id);
        currentCourtIdRef.current = normalized[0].id;
      }
      setIsInitialized(true);
    };
    initData();
  }, []);

  // 同步 ref。
  useEffect(() => {
    currentCourtIdRef.current = currentCourtId;
  }, [currentCourtId]);

  // 切换 session 时，清掉残留的草稿，避免串台。
  useEffect(() => {
    setComposerText('');
  }, [currentCourtId]);

  // 持久化到 IndexedDB。
  useEffect(() => {
    if (!isInitialized) return;
    fileDB.saveCourtSessions(courtSessions).catch(error => {
      console.error('Failed to save court sessions to IndexedDB:', error);
    });
  }, [courtSessions, isInitialized]);

  // 心跳保活，防止庭审 workspace 文件被清理。
  useEffect(() => {
    if (!enabled || !isInitialized || !currentCourtId) return;

    sendHeartbeat(currentCourtId).catch(console.error);
    const interval = setInterval(() => {
      sendHeartbeat(currentCourtId).catch(console.error);
    }, 5 * 60 * 1000);

    const handleReconnect = () => {
      sendHeartbeat(currentCourtId).catch(console.error);
    };
    window.addEventListener('focus', handleReconnect);
    window.addEventListener('online', handleReconnect);

    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', handleReconnect);
      window.removeEventListener('online', handleReconnect);
    };
  }, [currentCourtId, enabled, isInitialized]);

  const createCourtSession = useCallback((input: {
    case_type: CourtCaseType;
    user_side: string;
    shared_dossier: CourtSession['shared_dossier'];
    private_brief: CourtSession['private_brief'];
  }) => {
    const id = generateUUID();
    const now = nowIso();
    const summary = input.shared_dossier.summary.trim();
    const titleSource = summary || `${caseTypeLabel[input.case_type]}模拟法庭`;
    const session: CourtSession = {
      id,
      title: titleSource.length > 22 ? `${titleSource.slice(0, 22)}...` : titleSource,
      case_type: input.case_type,
      user_side: input.user_side,
      shared_dossier: input.shared_dossier,
      private_brief: input.private_brief,
      public_events: [
        createPublicEvent('system', 'opening', `庭审已创建。案由：${caseTypeLabel[input.case_type]}；用户方立场：${input.user_side}。`, 'system')
      ],
      public_summary: '',
      court_state: createCourtState(input.case_type, input.user_side),
      agent_states: createAgentStates(),
      pending_interjections: [],
      auto_mode: false,
      created_at: now,
      updated_at: now
    };

    commitSessions(prev => [session, ...prev]);
    setCurrentCourtId(id);
    currentCourtIdRef.current = id;
    consecutiveErrorsRef.current = 0;
    setStatus('庭审已创建，可手动推进第一轮。');
    return id;
  }, [commitSessions]);

  const deleteCourtSession = useCallback(async (sessionId: string) => {
    commitSessions(prev => {
      const next = prev.filter(session => session.id !== sessionId);
      if (currentCourtIdRef.current === sessionId) {
        const nextId = next[0]?.id || '';
        setCurrentCourtId(nextId);
        currentCourtIdRef.current = nextId;
      }
      return next;
    });
    await fileDB.deleteFilesByConvId(sessionId);
    await fileDB.deleteCourtSession(sessionId);
    try {
      await deleteWorkspace(sessionId);
    } catch (error) {
      console.error('Failed to delete court workspace on server:', error);
    }
  }, [commitSessions]);

  const updateCourtSession = useCallback((sessionId: string, patch: Partial<CourtSession>) => {
    patchSession(sessionId, session => ({ ...session, ...patch }));
  }, [patchSession]);

  // 用户发言落入公开记录。speech 类型同步把 phase 计数/total/speaker_last_positions 加上，
  // 让后端 FSM 能在 alternating 阶段正确推进。
  const appendUserEvent = useCallback((sessionId: string, content: string, type: CourtPublicEvent['type']) => {
    patchSession(sessionId, session => {
      const phase = session.court_state.phase;
      const event = createPublicEvent('user', phase, content, type);
      const isInterjection = type === 'interjection';
      const counts = { ...session.court_state.phase_turn_counts };
      const positions = { ...session.court_state.speaker_last_positions };
      let total = session.court_state.total_turns;
      if (!isInterjection) {
        counts[phase] = (counts[phase] || 0) + 1;
        total = total + 1;
        positions.user = total;
      }
      return {
        ...session,
        public_events: [...session.public_events, event],
        court_state: {
          ...session.court_state,
          awaiting_user: false,
          pending_interjection: isInterjection ? true : session.court_state.pending_interjection,
          forced_advance_requested: false,
          phase_turn_counts: counts,
          speaker_last_positions: positions,
          total_turns: total
        }
      };
    });
  }, [patchSession]);

  const sendUserSpeech = useCallback((rawContent?: string) => {
    const session = getCurrentSession();
    const content = (rawContent ?? composerText).trim();
    if (!session || !content) return;

    if (isRunningRef.current) {
      const event = createPublicEvent('user', session.court_state.phase, content, 'interjection');
      patchSession(session.id, prev => ({
        ...prev,
        pending_interjections: [...prev.pending_interjections, event]
      }));
      setStatus('插话已排队，当前发言结束后进入公开记录。');
    } else {
      const eventType = session.court_state.awaiting_user ? 'speech' : 'interjection';
      appendUserEvent(session.id, content, eventType);
      setStatus(eventType === 'speech' ? '你的发言已记录。' : '插话已记录，下一轮由法庭处理。');
    }

    setComposerText('');
  }, [appendUserEvent, composerText, getCurrentSession, patchSession]);

  const setAutoMode = useCallback((enabledAuto: boolean) => {
    const session = getCurrentSession();
    if (!session) return;
    patchSession(session.id, prev => ({
      ...prev,
      auto_mode: enabledAuto
    }));
    if (enabledAuto) {
      consecutiveErrorsRef.current = 0;
    }
    setStatus(enabledAuto ? '自动推进已开启。' : '已切换为手动推进。');
  }, [getCurrentSession, patchSession]);

  /** 切换"我方 AI 代理"模式。开启后轮到用户发言时由 user_agent 接管。 */
  const setUserAgentMode = useCallback((enabled: boolean) => {
    const session = getCurrentSession();
    if (!session) return;
    patchSession(session.id, prev => ({
      ...prev,
      court_state: {
        ...prev.court_state,
        user_agent_enabled: enabled
      }
    }));
    setStatus(enabled ? '我方代理已开启，轮到你发言时由 AI 代理出庭。' : '我方代理已关闭，由你接管发言。');
  }, [getCurrentSession, patchSession]);

  const forceAdvance = useCallback(() => {
    const session = getCurrentSession();
    if (!session || session.court_state.trial_over) return;
    patchSession(session.id, prev => ({
      ...prev,
      court_state: {
        ...prev.court_state,
        awaiting_user: false,
        forced_advance_requested: true
      }
    }));
    setStatus('已请求法庭推进到下一阶段。');
  }, [getCurrentSession, patchSession]);

  /** 撤回本场庭审到指定事件之后的状态被全部清除。同步清三角色后端 memory，避免 AI 幻觉记得被撤回的内容。 */
  const rewindToEvent = useCallback(async (sessionId: string, eventId: string) => {
    const session = sessionsRef.current.find(item => item.id === sessionId);
    if (!session) return;
    const derived = deriveStateAtCutoff(session, eventId);
    if (!derived) return;
    const removedCount = session.public_events.length - derived.truncatedEvents.length;

    patchSession(sessionId, prev => ({
      ...prev,
      public_events: derived.truncatedEvents,
      pending_interjections: [],
      public_summary: '',
      court_state: derived.recomputedState,
      agent_states: createAgentStates()
    }));
    consecutiveErrorsRef.current = 0;
    setStatus(removedCount > 0 ? `已撤回到选中点，删除 ${removedCount} 条后续记录。` : '已撤回到选中点。');

    try {
      await clearCourtMemory(sessionId);
    } catch (error) {
      console.error('Failed to clear court memory after rewind:', error);
    }
  }, [patchSession]);

  /** 从指定事件创建分支为新庭审。后端 memory scope 派生自 (user, court_session_id)，新 UUID 自然得到干净的 AI 状态。 */
  const branchFromEvent = useCallback((sessionId: string, eventId: string): string | null => {
    const session = sessionsRef.current.find(item => item.id === sessionId);
    if (!session) return null;
    const derived = deriveStateAtCutoff(session, eventId);
    if (!derived) return null;

    const newId = generateUUID();
    const now = nowIso();
    const baseTitle = session.title.endsWith('（分支）') ? session.title : `${session.title}（分支）`;
    const newSession: CourtSession = {
      ...session,
      id: newId,
      title: baseTitle,
      shared_dossier: { ...session.shared_dossier },
      private_brief: { ...session.private_brief },
      public_events: derived.truncatedEvents.map(event => ({ ...event })),
      pending_interjections: [],
      public_summary: '',
      court_state: derived.recomputedState,
      agent_states: createAgentStates(),
      auto_mode: false,
      parent_id: sessionId,
      branch_point_event_id: eventId,
      created_at: now,
      updated_at: now
    };

    commitSessions(prev => [newSession, ...prev]);
    setCurrentCourtId(newId);
    currentCourtIdRef.current = newId;
    consecutiveErrorsRef.current = 0;
    setStatus(`已从选中点创建分支「${baseTitle}」。`);
    return newId;
  }, [commitSessions]);

  const drainInterjections = useCallback((sessionId: string) => {
    let drained = false;
    patchSession(sessionId, session => {
      if (session.pending_interjections.length === 0) return session;
      drained = true;
      return {
        ...session,
        public_events: [...session.public_events, ...session.pending_interjections],
        pending_interjections: [],
        court_state: {
          ...session.court_state,
          pending_interjection: true,
          awaiting_user: false
        }
      };
    });
    if (drained) setStatus('插话已进入公开记录，下一轮优先处理。');
    return drained;
  }, [patchSession]);

  // 处理 SSE 流。返回是否发生 error。
  const processCourtStream = useCallback(async (response: Response, sessionId: string): Promise<{ hadError: boolean; errorMessage?: string; failedSpeaker?: keyof CourtAgentStates }> => {
    const reader = response.body?.getReader();
    if (!reader) return { hadError: false };

    const decoder = new TextDecoder();
    let streamBuffer = '';
    let activeEventId = '';
    let hadError = false;
    let errorMessage = '';
    let failedSpeaker: keyof CourtAgentStates | undefined;

    const updateAgentStatus = (speaker: unknown, statusValue: CourtAgentStates[keyof CourtAgentStates]['status']) => {
      if (!isCourtSpeaker(speaker)) return;
      patchSession(sessionId, session => ({
        ...session,
        agent_states: {
          ...session.agent_states,
          [speaker]: {
            ...session.agent_states[speaker],
            status: statusValue
          }
        }
      }));
    };

    const ensureActiveEvent = (
      speaker: CourtSpeaker,
      phase: string,
      initialContent = '',
      byUserAgent = false
    ) => {
      if (activeEventId) return activeEventId;
      const event = createPublicEvent(speaker, phase, initialContent, 'speech', byUserAgent);
      activeEventId = event.id;
      patchSession(sessionId, session => ({
        ...session,
        public_events: [...session.public_events, event]
      }));
      return event.id;
    };

    const updateActiveEvent = (updater: (event: CourtPublicEvent) => CourtPublicEvent) => {
      if (!activeEventId) return;
      patchSession(sessionId, session => ({
        ...session,
        public_events: session.public_events.map(event => (
          event.id === activeEventId ? updater(event) : event
        ))
      }));
    };

    const handleStreamData = (data: any) => {
      const speaker = (data.speaker || 'system') as CourtSpeaker;
      const phase = data.phase || getCurrentSession()?.court_state.phase || 'opening';

      // 只在显式 court_state 事件里更新结构化状态，避免每个 content chunk 都重写一次。
      if (data.type === 'court_state') {
        if (data.court_state) {
          patchSession(sessionId, session => ({
            ...session,
            court_state: data.court_state,
            public_summary: typeof data.transcript_summary === 'string' ? data.transcript_summary : session.public_summary
          }));
        }
        return;
      }

      if (data.type === 'content') {
        updateAgentStatus(speaker, 'running');
        ensureActiveEvent(speaker, phase, '', Boolean(data.by_user_agent));
        updateActiveEvent(event => ({
          ...event,
          content: `${event.content}${data.content || ''}`,
          updated_at: nowIso()
        }));
      } else if (data.type === 'content_replace') {
        updateAgentStatus(speaker, 'done');
        ensureActiveEvent(speaker, phase, '', Boolean(data.by_user_agent));
        updateActiveEvent(event => ({
          ...event,
          content: data.content || '',
          updated_at: nowIso()
        }));
      } else if (data.type === 'memory_sync' && isCourtSpeaker(speaker)) {
        patchSession(sessionId, session => ({
          ...session,
          agent_states: {
            ...session.agent_states,
            [speaker]: {
              ...session.agent_states[speaker],
              memory_snapshot: data.content as ConversationMemory,
              status: 'done',
              last_turn_id: data.turn_id || session.agent_states[speaker].last_turn_id
            }
          }
        }));
      } else if (data.type === 'context_usage' && isCourtSpeaker(speaker)) {
        patchSession(sessionId, session => ({
          ...session,
          agent_states: {
            ...session.agent_states,
            [speaker]: {
              ...session.agent_states[speaker],
              last_context_usage: data.content as ContextUsage
            }
          }
        }));
      } else if (data.type === 'thought') {
        if (data.thought_type === 'tool') {
          const label = formatThoughtToolStatus(speaker, String(data.content || ''));
          if (label) setStatus(label);
        }
      } else if (data.type === 'error') {
        hadError = true;
        errorMessage = data.content || '庭审回合出错。';
        if (isCourtSpeaker(speaker)) {
          failedSpeaker = speaker;
        }
        updateAgentStatus(speaker, 'error');
        setStatus(errorMessage);
      }
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        streamBuffer += decoder.decode(value, { stream: true });
        const lines = streamBuffer.split('\n');
        streamBuffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const dataStr = line.slice(6);
          if (dataStr === '[DONE]') continue;
          try {
            handleStreamData(JSON.parse(dataStr));
          } catch {
            console.warn('Failed to parse court stream data:', dataStr);
          }
        }
      }

      if (streamBuffer.trim().startsWith('data: ')) {
        const dataStr = streamBuffer.trim().slice(6);
        if (dataStr && dataStr !== '[DONE]') {
          try {
            handleStreamData(JSON.parse(dataStr));
          } catch {
            console.warn('Failed to parse trailing court stream data:', streamBuffer);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    return { hadError, errorMessage, failedSpeaker };
  }, [getCurrentSession, patchSession]);

  const runNextTurn = useCallback(async () => {
    const session = getCurrentSession();
    if (!session || isRunningRef.current || session.court_state.trial_over) return;
    // 等用户发言时，除非用户已开启 "我方代理"（user_agent 接管），否则不进入下一轮。
    if (
      session.court_state.awaiting_user
      && !session.court_state.forced_advance_requested
      && !session.court_state.user_agent_enabled
    ) {
      setStatus('当前等待用户方发言。');
      return;
    }

    // 拍一份 stream 前的快照，AI 失败时回滚结构化状态和半截发言，避免污染后续 FSM。
    const turnSnapshot = {
      court_state: session.court_state,
      public_events: session.public_events,
      public_summary: session.public_summary,
      agent_states: session.agent_states
    };

    isRunningRef.current = true;
    setIsRunning(true);
    setStatus('正在推进下一轮庭审。');
    const abortController = new AbortController();
    activeAbortRef.current?.abort();
    activeAbortRef.current = abortController;

    const handleAutoFallback = () => {
      if (consecutiveErrorsRef.current < AUTO_ERROR_THRESHOLD) return;
      const failedSession = getCurrentSession();
      if (failedSession?.auto_mode) {
        patchSession(failedSession.id, prev => ({ ...prev, auto_mode: false }));
        setStatus(`已连续 ${AUTO_ERROR_THRESHOLD} 次失败，自动推进已切换为手动。`);
      }
    };

    const rollbackFailedTurn = (message: string, failedSpeaker?: keyof CourtAgentStates) => {
      patchSession(session.id, prev => {
        const restoredAgentStates = { ...turnSnapshot.agent_states };
        if (failedSpeaker) {
          restoredAgentStates[failedSpeaker] = {
            ...restoredAgentStates[failedSpeaker],
            status: 'error'
          };
        } else {
          (['judge', 'opponent', 'reviewer', 'user'] as Array<keyof CourtAgentStates>).forEach(role => {
            if (prev.agent_states[role]?.status === 'running') {
              restoredAgentStates[role] = {
                ...restoredAgentStates[role],
                status: 'error'
              };
            }
          });
        }

        const errorEvent = createPublicEvent(
          'system',
          turnSnapshot.court_state.phase,
          `庭审回合出错：${message || '未知错误'}`,
          'system'
        );
        return {
          ...prev,
          court_state: turnSnapshot.court_state,
          public_events: [...turnSnapshot.public_events, errorEvent],
          public_summary: turnSnapshot.public_summary,
          agent_states: restoredAgentStates
        };
      });
    };

    try {
      const response = await courtTurn(session, abortController.signal);
      const { hadError, errorMessage, failedSpeaker } = await processCourtStream(response, session.id);

      if (hadError) {
        rollbackFailedTurn(errorMessage || '庭审回合出错。', failedSpeaker);
        consecutiveErrorsRef.current += 1;
        handleAutoFallback();
      } else {
        consecutiveErrorsRef.current = 0;
      }

      const hadInterjections = drainInterjections(session.id);
      const latest = sessionsRef.current.find(item => item.id === session.id);

      if (hadError) {
        // status 已在 stream 里设置
      } else if (latest?.court_state.trial_over) {
        setStatus('庭审已结束，复盘意见已写入记录。');
      } else if (latest?.court_state.awaiting_user) {
        setStatus('等待用户方发言。');
      } else if (hadInterjections) {
        setStatus('插话已进入公开记录，下一轮优先处理。');
      } else if (!latest?.pending_interjections.length) {
        setStatus('本轮已完成。');
      }
    } catch (error: any) {
      if (isAbortError(error)) {
        patchSession(session.id, prev => ({
          ...prev,
          court_state: turnSnapshot.court_state,
          public_events: turnSnapshot.public_events,
          public_summary: turnSnapshot.public_summary,
          agent_states: turnSnapshot.agent_states
        }));
        setStatus('已停止当前庭审回合。');
        return;
      }

      console.error('Court turn failed:', error);
      // 网络/认证类异常也回滚本回合产生的状态和半截发言。
      consecutiveErrorsRef.current += 1;
      const message = error?.message || '庭审回合失败';
      rollbackFailedTurn(message);
      setStatus(message);
      handleAutoFallback();
    } finally {
      if (activeAbortRef.current === abortController) {
        activeAbortRef.current = null;
      }
      isRunningRef.current = false;
      setIsRunning(false);
    }
  }, [drainInterjections, getCurrentSession, patchSession, processCourtStream]);

  // 自动模式：监听结构变化触发下一轮。
  useEffect(() => {
    if (!currentCourtSession || !currentCourtSession.auto_mode || isRunning || currentCourtSession.court_state.trial_over) {
      return;
    }
    if (
      currentCourtSession.court_state.awaiting_user
      && !currentCourtSession.court_state.forced_advance_requested
      && !currentCourtSession.court_state.user_agent_enabled
    ) {
      return;
    }

    const timer = setTimeout(() => {
      runNextTurn();
    }, 450);
    return () => clearTimeout(timer);
  }, [
    currentCourtSession?.auto_mode,
    currentCourtSession?.court_state.awaiting_user,
    currentCourtSession?.court_state.forced_advance_requested,
    currentCourtSession?.court_state.total_turns,
    currentCourtSession?.court_state.trial_over,
    currentCourtSession?.court_state.user_agent_enabled,
    currentCourtSession?.pending_interjections.length,
    isRunning,
    runNextTurn
  ]);

  return {
    courtSessions,
    currentCourtId,
    setCurrentCourtId,
    currentCourtSession,
    isInitialized,
    isRunning,
    status,
    composerText,
    setComposerText,
    createCourtSession,
    deleteCourtSession,
    updateCourtSession,
    sendUserSpeech,
    runNextTurn,
    setAutoMode,
    setUserAgentMode,
    forceAdvance,
    rewindToEvent,
    branchFromEvent
  };
}
