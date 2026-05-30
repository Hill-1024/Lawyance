/*
 * 模块描述：前端共享类型定义，描述消息、对话、工具调用和对话记忆结构。
 */

export type ThoughtBlock = {
  id: string;
  type: 'reasoning' | 'draft' | 'tool' | 'ocp' | 'memory';
  content: string;
};

export type BackendHistoryMessage = {
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  tool_calls?: unknown[];
  tool_call_id?: string;
  name?: string;
};

export type ContextUsage = {
  prompt_tokens: number;
  cached_tokens?: number;
  cache_miss_tokens?: number;
  threshold_tokens: number;
  max_context_tokens: number;
  over_threshold: boolean;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  stream_id?: string;
  stream_buffered?: boolean;
  stream_status?: 'streaming' | 'done' | 'error';
  last_committed_seq?: number;
  /** Android 原生前台服务的流 id；WebView 重建后据此重新接上仍在进行的原生流。 */
  native_stream_id?: string;
  thought_blocks?: ThoughtBlock[];
  reasoning_content?: string;
  thought_signature?: string;
  download_path?: string;
  tool_calls?: unknown[];
  tool_call_id?: string;
  name?: string;
  context_messages?: BackendHistoryMessage[];
  created_at?: string;
  updated_at?: string;
};

type ConversationMemoryEvent = {
  id: string;
  type: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  summary: string;
  keywords: string[];
  entities?: string[];
  semantic_tags?: string[];
  created_at: string;
  updated_at: string;
  turn_id?: string;
};

type ConversationMemoryFact = {
  id: string;
  kind: string;
  text: string;
  status: 'active' | 'deprecated';
  priority: number;
  confidence: number;
  source_event_ids: string[];
  source_turn_id?: string;
  created_at: string;
  updated_at: string;
  keywords: string[];
  entities?: string[];
  semantic_tags?: string[];
  fact_key?: string;
  source_text?: string;
  memory_reason?: string;
  superseded_by?: string;
  supersedes?: string;
};

type ConversationMemoryFocus = {
  id: string;
  text: string;
  status: 'active' | 'deprecated';
  priority: number;
  created_at: string;
  updated_at: string;
  keywords: string[];
  entities?: string[];
  semantic_tags?: string[];
  focus_type?: 'case' | 'dialog';
  source_text?: string;
  memory_reason?: string;
};

export type ConversationMemory = {
  version: number;
  revision?: number;
  scope: {
    type: 'conversation';
    future_user_scope?: string | null;
  };
  conversation_id?: string;
  events: ConversationMemoryEvent[];
  facts: ConversationMemoryFact[];
  focus: ConversationMemoryFocus[];
  updated_at: string;
  last_synced_at: string;
};

export type Conversation = {
  id: string;
  title: string;
  messages: Message[];
  memory?: ConversationMemory;
  context_usage?: ContextUsage;
  /** 分支自哪个会话。删除原会话后会孤儿化，arrival 时按根节点显示。 */
  parent_id?: string;
  /** 分叉点指向的 message.id，用于追溯分支来源。 */
  branch_point_message_id?: string;
  created_at?: string;
  updated_at?: string;
};

export type CourtCaseType = 'civil' | 'administrative' | 'criminal';
export type CourtSpeaker = 'user' | 'judge' | 'opponent' | 'reviewer' | 'system';

export type CourtPublicEvent = {
  id: string;
  type: 'speech' | 'interjection' | 'system';
  speaker: CourtSpeaker;
  phase: string;
  content: string;
  /** 由用户方 AI 代理（user_agent）产生的发言；UI 上会标记。 */
  by_user_agent?: boolean;
  created_at: string;
  updated_at?: string;
};

export type CourtState = {
  case_type: CourtCaseType;
  user_side: string;
  phase: string;
  phase_turn_counts: Record<string, number>;
  total_turns: number;
  pending_interjection: boolean;
  awaiting_user: boolean;
  forced_advance_requested: boolean;
  speaker_last_positions: Record<string, number>;
  trial_over: boolean;
  /** 开启后，FSM 决定的 awaiting_user 由用户方 AI 代理接管发言。 */
  user_agent_enabled?: boolean;
};

export type CourtAgentState = {
  memory_snapshot?: ConversationMemory | null;
  status: 'idle' | 'running' | 'done' | 'error';
  last_context_usage?: ContextUsage | null;
  last_turn_id?: string;
};

export type CourtAgentStates = {
  judge: CourtAgentState;
  opponent: CourtAgentState;
  reviewer: CourtAgentState;
  /** 用户方 AI 代理的私有记忆与状态。即使没开启代理模式，字段也存在，便于一致访问。 */
  user: CourtAgentState;
};

export type CourtSession = {
  id: string;
  title: string;
  case_type: CourtCaseType;
  user_side: string;
  shared_dossier: {
    summary: string;
    claims: string;
    evidence: string;
  };
  private_brief: {
    strategy: string;
    logic_chain: string;
    risk_notes: string;
  };
  public_events: CourtPublicEvent[];
  public_summary: string;
  court_state: CourtState;
  agent_states: CourtAgentStates;
  pending_interjections: CourtPublicEvent[];
  auto_mode: boolean;
  /** 分支自哪个庭审。删除原庭审后会孤儿化，按根节点显示。 */
  parent_id?: string;
  /** 分叉点指向的 public_event.id。 */
  branch_point_event_id?: string;
  created_at: string;
  updated_at: string;
};
