import React, { useEffect, useRef } from 'react';
import { Message } from '../types';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  onRegenerate: (id: string) => void;
  onEdit: (id: string) => void;
  onUndo: (id: string) => void;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading,
  onRegenerate,
  onEdit,
  onUndo
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4 sm:py-6 flex flex-col gap-6 sm:gap-8 custom-scrollbar">
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
      <div ref={messagesEndRef} className="h-4" />
    </div>
  );
};
