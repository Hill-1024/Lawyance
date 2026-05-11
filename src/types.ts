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

export type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
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

export type ConversationMemoryEvent = {
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

export type ConversationMemoryFact = {
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

export type ConversationMemoryFocus = {
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
  created_at?: string;
  updated_at?: string;
};
