/*
 * 模块描述：会话标题展示规则——还没有任何用户消息的会话属于「未命名」，
 * 其存储标题只是占位符，由调用方按当前语言渲染，避免把写死的默认标题当成真实数据展示。
 */

import type { Conversation } from '../types';

export const isUntitledConversation = (conversation: Pick<Conversation, 'id' | 'messages'>): boolean =>
  Boolean(conversation.id) && !conversation.messages?.some(message => message.role === 'user');