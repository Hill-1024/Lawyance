/*
 * 模块描述：消息列表组件，负责渲染消息流并在用户停留底部时自动跟随。
 */

import React, { useLayoutEffect, useRef } from 'react';
import { Message } from '../types';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  conversationId?: string;
  messages: Message[];
  isLoading: boolean;
  activeAssistantMessageId?: string | null;
  bottomInset?: number;
  onRegenerate: (id: string) => void;
  onAnswerChoice?: (id: string, value: string) => void;
  onEdit: (id: string) => void;
  onUndo: (id: string) => void;
  onBranch?: (id: string) => void;
}

export const MessageList: React.FC<MessageListProps> = ({
  conversationId,
  messages,
  isLoading,
  activeAssistantMessageId,
  bottomInset = 0,
  onRegenerate,
  onAnswerChoice,
  onEdit,
  onUndo,
  onBranch
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const previousListStateRef = useRef({
    conversationId: '',
    count: 0,
    lastId: '',
    lastRenderKey: '',
    bottomInset: 0
  });

  const isNearBottom = (element: HTMLDivElement) => {
    return element.scrollHeight - element.scrollTop - element.clientHeight < 96;
  };

  const getMessageRenderKey = (message?: Message) => {
    if (!message) return '';

    const thoughtKey = message.thought_blocks
      ?.map(block => `${block.id}:${block.content.length}`)
      .join('|') || '';
    return [
      message.id,
      message.content.length,
      thoughtKey,
      message.pending_choice
        ? `${message.pending_choice.id}:${message.pending_choice.answered ? 'answered' : 'pending'}:${message.pending_choice.selected_value || ''}`
        : '',
      message.download_path || ''
    ].join('::');
  };

  const scrollToBottom = (behavior: ScrollBehavior = 'auto') => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  useLayoutEffect(() => {
    const container = scrollContainerRef.current;
    const lastMessage = messages[messages.length - 1];
    const lastRenderKey = getMessageRenderKey(lastMessage);
    const previous = previousListStateRef.current;
    const listKey = conversationId || '';
    const hasConversationChanged = listKey !== previous.conversationId;
    const hasNewMessage = messages.length !== previous.count || lastMessage?.id !== previous.lastId;
    const hasLastMessageChanged = lastRenderKey !== previous.lastRenderKey;
    const normalizedBottomInset = Math.round(bottomInset);
    const hasBottomInsetChanged = normalizedBottomInset !== previous.bottomInset;
    const shouldFollow =
      hasConversationChanged ||
      shouldStickToBottomRef.current ||
      previous.count === 0 ||
      (hasNewMessage && lastMessage?.role === 'user');

    previousListStateRef.current = {
      conversationId: listKey,
      count: messages.length,
      lastId: lastMessage?.id || '',
      lastRenderKey,
      bottomInset: normalizedBottomInset
    };

    if (!container || (!hasConversationChanged && !hasNewMessage && !hasLastMessageChanged && !hasBottomInsetChanged)) return;
    if (!shouldFollow) return;

    scrollToBottom(hasConversationChanged || isLoading ? 'auto' : 'smooth');
    shouldStickToBottomRef.current = true;
  }, [conversationId, messages, isLoading, bottomInset]);

  const scrollStyle = {
    overflowAnchor: 'none',
    ...(bottomInset > 0 ? { scrollPaddingBottom: `calc(${bottomInset}px + 1rem)` } : {})
  } as React.CSSProperties;

  return (
    <div
      ref={scrollContainerRef}
      onScroll={(event) => {
        shouldStickToBottomRef.current = isNearBottom(event.currentTarget);
      }}
      data-testid="message-list-scroll"
      className="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto px-4 py-6 sm:px-6 sm:py-8"
      style={scrollStyle}
    >
      <div className="mx-auto flex min-w-0 w-full max-w-3xl flex-col gap-6 sm:gap-8">
        {messages.map((msg, index) => {
          const isLast = index === messages.length - 1;
          const isThinking = isLoading && msg.role === 'assistant' && (
            activeAssistantMessageId ? msg.id === activeAssistantMessageId : isLast
          );

          return (
            <MessageItem
              key={msg.id}
              msg={msg}
              isThinking={isThinking}
              isLast={isLast}
              onRegenerate={onRegenerate}
              onAnswerChoice={onAnswerChoice}
              onEdit={onEdit}
              onUndo={onUndo}
              onBranch={onBranch}
            />
          );
        })}
        <div
          ref={messagesEndRef}
          aria-hidden="true"
          style={{ height: bottomInset > 0 ? bottomInset + 16 : 16 }}
        />
      </div>
    </div>
  );
};
