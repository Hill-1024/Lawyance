import React from 'react';
import { Sparkles, ChevronDown, Loader2, Info, Paperclip, Undo2, Pencil, RefreshCw } from 'lucide-react';
import { motion } from 'motion/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Message } from '../types';
import { Mermaid } from './Mermaid';

interface MessageItemProps {
  msg: Message;
  isThinking: boolean;
  isLast: boolean;
  onRegenerate?: (id: string) => void;
  onEdit?: (id: string) => void;
  onUndo?: (id: string) => void;
}

export const MessageItem: React.FC<MessageItemProps> = ({
  msg,
  isThinking,
  isLast,
  onRegenerate,
  onEdit,
  onUndo
}) => {
  const markdownComponents: any = {
    a(props: any) {
      const { node, ...rest } = props;
      return <a target="_blank" rel="noopener noreferrer" {...rest} />;
    },
    pre(props: any) {
      const { children, ...rest } = props;
      const childrenArray = React.Children.toArray(children);
      const child = childrenArray[0] as any;

      if (child && child.type === 'code' && typeof child.props?.className === 'string' && child.props.className.includes('language-mermaid')) {
        return <>{children}</>;
      }
      return <pre {...rest}>{children}</pre>;
    },
    code(props: any) {
      const {children, className, node, ...rest} = props;
      const match = /language-(\w+)/.exec(className || '');
      if (match && match[1] === 'mermaid') {
        return <Mermaid chart={String(children).replace(/\n$/, '')} />;
      }
      return <code {...rest} className={className}>{children}</code>;
    }
  };

  let blocks: { type: 'think' | 'tool' | 'content', text: string }[] = [];

  const toolMarkers = [
    "️ **正在调用工具处理中...**",
    "️ 执行: ",
    " **工具执行完毕，正在生成最终回复...**"
  ];

  if (msg.role === 'assistant' || (msg.role as string) === 'agent') {
    let thinkDepth = 0;
    let currentBuffer = "";
    let i = 0;
    const content = msg.content || "";

    const processText = (text: string, type: 'think' | 'content') => {
      const lines = text.split('\n');
      let currentText = "";
      for (const line of lines) {
        const isTool = toolMarkers.some(m => line.includes(m));
        if (isTool) {
          if (currentText.trim()) {
            blocks.push({ type, text: currentText.trim() });
            currentText = "";
          }
          blocks.push({ type: 'tool', text: line.trim() });
        } else {
          currentText += line + (line ? "\n" : "");
        }
      }
      if (currentText.trim()) {
        blocks.push({ type, text: currentText.trim() });
      }
    };

    while (i < content.length) {
      if (content.startsWith("<think>", i)) {
        if (currentBuffer.trim()) {
          processText(currentBuffer, 'content');
        }
        currentBuffer = "";
        thinkDepth++;
        i += 7;
      } else if (content.startsWith("</think>", i)) {
        if (thinkDepth > 0) {
          processText(currentBuffer, 'think');
          currentBuffer = "";
          thinkDepth--;
        }
        i += 8;
      } else if (content.startsWith("<final_answer>", i)) {
        if (currentBuffer.trim()) {
          processText(currentBuffer, 'content');
        }
        currentBuffer = "";
        i += 14;
      } else if (content.startsWith("</final_answer>", i)) {
        processText(currentBuffer, 'content');
        currentBuffer = "";
        i += 15;
      } else {
        currentBuffer += content[i];
        i++;
      }
    }

    if (currentBuffer.trim()) {
      if (thinkDepth > 0) {
        processText(currentBuffer, 'think');
      } else {
        processText(currentBuffer, 'content');
      }
    }
  }

  // Heuristic: In agentic messages, content blocks appearing before the last tool/think block
  // are likely part of the thought process.
  const lastThoughtIndex = [...blocks].reverse().findIndex(b => b.type === 'think' || b.type === 'tool');
  if (lastThoughtIndex !== -1) {
    const actualLastIndex = blocks.length - 1 - lastThoughtIndex;
    blocks = blocks.map((b, idx) => {
      if (idx < actualLastIndex && b.type === 'content') {
        return { ...b, type: 'think' };
      }
      return b;
    });
  }

  const groupedBlocks: any[] = [];
  let currentThoughtGroup: any = null;

  for (const block of blocks) {
    if (block.type === 'think' || block.type === 'tool') {
      if (!currentThoughtGroup) {
        currentThoughtGroup = { type: 'thought_process', items: [] };
        groupedBlocks.push(currentThoughtGroup);
      }
      currentThoughtGroup.items.push(block);
    } else {
      if (!block.text.trim()) {
        // Skip whitespace-only content to avoid breaking thought groups
        continue;
      }

      // Merge consecutive content blocks into one
      const lastGroup = groupedBlocks[groupedBlocks.length - 1];
      if (lastGroup && lastGroup.type === 'content') {
        lastGroup.text += "\n\n" + block.text;
      } else {
        groupedBlocks.push({ type: 'content', text: block.text });
      }
      currentThoughtGroup = null;
    }
  }

  const isThinkingBlock = blocks.length > 0 && (blocks[blocks.length - 1].type === 'think' || blocks[blocks.length - 1].type === 'tool');

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 sm:gap-4 max-w-[92%] sm:max-w-[85%] md:max-w-[75%] ${msg.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}
    >
      {/* Avatar */}
      <div className={`shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full flex items-center justify-center mt-1 shadow-sm ${msg.role === 'user' ? 'bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400' : 'bg-white dark:bg-gray-800 text-blue-600 dark:text-blue-400 border border-gray-200 dark:border-gray-700'}`}>
        {msg.role === 'user' ? <div className="font-medium text-sm sm:text-base">U</div> : <Sparkles size={18} className="sm:size-5" />}
      </div>

      {/* Message Content */}
      <div className={`flex flex-col gap-3 min-w-0 w-full ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
        {msg.role === 'user' ? (
          <div className="px-4 py-3 sm:px-6 sm:py-4 text-[15px] sm:text-[16px] leading-relaxed shadow-sm w-fit bg-blue-600 dark:bg-blue-500 text-white rounded-[20px] sm:rounded-[28px] rounded-tr-sm sm:rounded-tr-lg">
            <div className="flex flex-col gap-2">
              {(() => {
                const fileInfoRegex = new RegExp("\\[用户已上传以下文件，请根据需要进行读取和处理\\]\\n([\\s\\S]*)$");
                const match = msg.content.match(fileInfoRegex);
                if (match) {
                  const textContent = msg.content.replace(match[0], '').trim();
                  const files = match[1].split('\n').filter((line: string) => line.startsWith('- ')).map((line: string) => {
                    const nameMatch = line.match(/^- (.*?) \(路径:/);
                    return nameMatch ? nameMatch[1] : line;
                  });
                  return (
                    <>
                      {textContent && <p className="whitespace-pre-wrap">{textContent}</p>}
                      {files.length > 0 && (
                        <div className="flex flex-wrap gap-2 mt-1">
                          {files.map((file: string, i: number) => (
                            <div key={i} className="flex items-center gap-1.5 bg-blue-700/50 dark:bg-blue-600/50 rounded-full px-3 py-1 text-sm">
                              <Paperclip size={14} />
                              <span className="truncate max-w-50">{file}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  );
                }
                return <p className="whitespace-pre-wrap">{msg.content.replace(new RegExp("TEMP/[^\\\\s\"'`)\\]<>*。，！？,?]+", "g"), '').trim()}</p>;
              })()}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5 w-full max-w-full">
            {/* Thought Section (Column) */}
            {groupedBlocks.some(b => b.type === 'thought_process') && (
              <div className="flex flex-col gap-3 w-full max-w-3xl">
                {groupedBlocks.filter(b => b.type === 'thought_process').map((group, index) => {
                  const isLastGroup = index === groupedBlocks.filter(b => b.type === 'thought_process').length - 1;
                  const showThinking = isThinking && isLastGroup && isThinkingBlock;

                  return (
                    <details key={index} className="group w-full" open={showThinking}>
                      <summary className="flex items-center gap-2 cursor-pointer text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors list-none [&::-webkit-details-marker]:hidden select-none w-fit bg-gray-100 dark:bg-gray-800/50 px-4 py-2 rounded-full border border-gray-200 dark:border-gray-700">
                        <ChevronDown size={16} className="transform group-open:-rotate-180 transition-transform duration-200" />
                        {showThinking ? (
                          <span className="flex items-center gap-2">
                            Thinking
                            <span className="flex gap-1">
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.2 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                              <motion.span animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.4 }} className="w-1 h-1 bg-gray-600 dark:bg-gray-400 rounded-full" />
                            </span>
                          </span>
                        ) : "Thought Process"}
                      </summary>
                      <div className="mt-3 mb-2 px-5 py-4 text-[15px] text-gray-600 dark:text-gray-300 border-l-4 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900/30 rounded-r-2xl flex flex-col gap-4 w-full">
                        {group.items.map((item: any, i: number) => {
                          if (item.type === 'think') {
                            return (
                              <div key={i} className="prose prose-sm dark:prose-invert max-w-none w-full prose-p:leading-relaxed prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-200 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none">
                                <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{item.text.trim()}</Markdown>
                              </div>
                            );
                          } else if (item.type === 'tool') {
                            const isLastTool = showThinking && i === group.items.length - 1;
                            return (
                              <div key={i} className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 text-sm text-gray-700 dark:text-gray-300 w-full sm:w-fit shadow-sm flex-shrink-0">
                                <div className="flex-shrink-0">
                                  <Loader2 size={16} className={isLastTool ? "animate-spin text-blue-500" : "text-gray-400"} />
                                </div>
                                <div className="flex-1 min-w-0">
                                  <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{item.text.trim()}</Markdown>
                                </div>
                              </div>
                            );
                          }
                          return null;
                        })}
                      </div>
                    </details>
                  );
                })}
              </div>
            )}

            {/* Main Content Section (Body) */}
            <div className="flex flex-col gap-4 w-full">
              {groupedBlocks.filter(b => b.type === 'content').map((group, index) => {
                let mainContent = group.text;
                mainContent = mainContent.replace(new RegExp("<\\\\/?response>", "g"), '').replace(new RegExp("<\\\\/?final_answer>", "g"), '').trim();

                let sourceContent = "";
                const sourceRegex = new RegExp("(?:---\\s*\\n)?\\s*\\*\\*参考信源[：:]\\*\\*\\s*\\n([\\s\\S]*)$");
                const sourceMatch = mainContent.match(sourceRegex);
                if (sourceMatch) {
                  sourceContent = sourceMatch[1];
                  mainContent = mainContent.replace(sourceMatch[0], "").trim();
                }

                if (!mainContent.trim() && !sourceContent) return null;

                return (
                  <div key={index} className="px-4 py-3 sm:px-6 sm:py-4 text-[15px] sm:text-[16px] leading-relaxed shadow-sm w-full bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[20px] sm:rounded-[28px] rounded-tl-sm sm:rounded-tl-lg border border-gray-200 dark:border-gray-800">
                    <div className="flex flex-col gap-4 w-full">
                      {mainContent.trim() && (
                        <div className="prose prose-base dark:prose-invert max-w-none w-full prose-p:leading-relaxed prose-headings:text-gray-900 dark:prose-headings:text-gray-100 prose-headings:font-medium prose-strong:text-gray-900 dark:prose-strong:text-gray-100 prose-strong:font-medium prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-100 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-100 dark:prose-pre:bg-gray-900 prose-pre:text-gray-900 dark:prose-pre:text-gray-100 prose-pre:border prose-pre:border-gray-200 dark:prose-pre:border-gray-700 prose-pre:rounded-2xl">
                          <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{mainContent}</Markdown>
                        </div>
                      )}
                      {sourceContent && (
                        <div className="source-list-container text-[14px] text-gray-600 dark:text-gray-400 w-full">
                          <div className="font-medium mb-2 text-gray-900 dark:text-gray-100 flex items-center gap-2 uppercase tracking-wider text-[13px]">
                            <Info size={16} />
                            Sources
                          </div>
                          <div className="prose prose-sm dark:prose-invert max-w-none w-full prose-p:my-1 prose-li:my-1 prose-ol:pl-4 prose-ul:pl-4">
                            <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{sourceContent}</Markdown>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {msg.role === 'user' && !isThinking && onUndo && onEdit && onRegenerate && (
          <div className="flex gap-2 self-end mt-1">
            <button
              onClick={() => onUndo(msg.id)}
              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-full transition-colors"
              title="Undo"
            >
              <Undo2 size={14} />
            </button>
            <button
              onClick={() => onEdit(msg.id)}
              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-full transition-colors"
              title="Edit"
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={() => onRegenerate(msg.id)}
              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-full transition-colors"
              title="Regenerate"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
};
