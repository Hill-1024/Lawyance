export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning_content?: string;
  thought_signature?: string;
  download_path?: string;
};

export type Conversation = {
  id: string;
  title: string;
  messages: Message[];
};
