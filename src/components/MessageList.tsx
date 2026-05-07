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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, bottomInset]);

  return (
    <div
      className="custom-scrollbar flex flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-6 sm:py-8"
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
