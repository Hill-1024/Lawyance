/*
 * 模块描述：消息列表组件，负责渲染消息流并在用户停留底部时自动跟随。
 */

import React, { useEffect, useRef } from 'react';
import { Message } from '../types';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  bottomInset?: number;
  onRegenerate: (id: string) => void;
  onEdit: (id: string) => void;
  onUndo: (id: string) => void;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading,
  bottomInset = 0,
  onRegenerate,
  onEdit,
  onUndo
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const previousListStateRef = useRef({
    count: 0,
    lastId: '',
    lastRenderKey: ''
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
      message.download_path || ''
    ].join('::');
  };

  const scrollToBottom = (behavior: ScrollBehavior = 'auto') => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  useEffect(() => {
    const container = scrollContainerRef.current;
    const lastMessage = messages[messages.length - 1];
    const lastRenderKey = getMessageRenderKey(lastMessage);
    const previous = previousListStateRef.current;
    const hasNewMessage = messages.length !== previous.count || lastMessage?.id !== previous.lastId;
    const hasLastMessageChanged = lastRenderKey !== previous.lastRenderKey;
    const shouldFollow =
      shouldStickToBottomRef.current ||
      previous.count === 0 ||
      (hasNewMessage && lastMessage?.role === 'user');

    previousListStateRef.current = {
      count: messages.length,
      lastId: lastMessage?.id || '',
      lastRenderKey
    };

    if (!container || (!hasNewMessage && !hasLastMessageChanged && bottomInset <= 0)) return;
    if (!shouldFollow) return;

    scrollToBottom(hasNewMessage && !isLoading ? 'smooth' : 'auto');
    shouldStickToBottomRef.current = true;
  }, [messages, isLoading, bottomInset]);

  return (
    <div
      ref={scrollContainerRef}
      onScroll={(event) => {
        shouldStickToBottomRef.current = isNearBottom(event.currentTarget);
      }}
      data-testid="message-list-scroll"
      className="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-6 sm:py-8"
      style={bottomInset > 0 ? { scrollPaddingBottom: `calc(${bottomInset}px + 1rem)` } : undefined}
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 sm:gap-8">
        {messages.map((msg, index) => {
          const isLast = index === messages.length - 1;
          const isThinking = isLoading && isLast && msg.role === 'assistant';

          return (
            <MessageItem
              key={msg.id}
              msg={msg}
              isThinking={isThinking}
              isLast={isLast}
              onRegenerate={onRegenerate}
              onEdit={onEdit}
              onUndo={onUndo}
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
