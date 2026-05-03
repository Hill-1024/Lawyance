export type ThoughtBlock = {
  id: string;
  type: 'reasoning' | 'draft' | 'tool' | 'ocp';
  content: string;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thought_blocks?: ThoughtBlock[];
  reasoning_content?: string;
  thought_signature?: string;
  download_path?: string;
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
  created_at: string;
  updated_at: string;
  keywords: string[];
  entities?: string[];
  semantic_tags?: string[];
  superseded_by?: string;
};

export type ConversationMemoryFocus = {
  id: string;
  text: string;
  status: 'active';
  priority: number;
  created_at: string;
  updated_at: string;
  keywords: string[];
  entities?: string[];
  semantic_tags?: string[];
};

export type ConversationMemory = {
  version: number;
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
};
