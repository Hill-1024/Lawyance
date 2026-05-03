import React from 'react';
import { Sparkles, ChevronDown, Loader2, Info, Paperclip, Undo2, Pencil, RefreshCw } from 'lucide-react';
import { motion } from 'motion/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Message, ThoughtBlock } from '../types';
import { Mermaid } from './Mermaid';

interface MessageItemProps {
  msg: Message;
  isThinking: boolean;
  isLast: boolean;
  onRegenerate?: (id: string) => void;
  onEdit?: (id: string) => void;
  onUndo?: (id: string) => void;
}

const splitQuotePrefix = (line: string) => {
  const match = line.match(/^(\s*(?:>\s*)*)(.*)$/);
  return {
    prefix: match ? match[1] : "",
    body: match ? match[2] : line
  };
};

const repairMarkdownTables = (text: string) => {
  if (!text.includes('|')) return text;

  const countPipes = (value: string) => (value.match(/\|/g) || []).length;

  const expandCollapsedTableLines = (rawText: string) => {
    const expanded: string[] = [];

    rawText.split('\n').forEach(originalLine => {
      const { prefix, body } = splitQuotePrefix(originalLine);
      if (countPipes(body) < 6) {
        expanded.push(originalLine);
        return;
      }

      const firstPipeIndex = body.indexOf('|');
      const beforeTable = firstPipeIndex > 0 ? body.slice(0, firstPipeIndex).trimEnd() : "";
      const tableTail = firstPipeIndex >= 0 ? body.slice(firstPipeIndex).trim() : body.trim();
      const hasCollapsedBoundary = /\|\s+\|\s*:?-{3,}/.test(tableTail) || (tableTail.match(/\|\s+\|/g) || []).length >= 2;

      if (!hasCollapsedBoundary) {
        expanded.push(originalLine);
        return;
      }

      if (beforeTable) {
        expanded.push(`${prefix}${beforeTable}`.trimEnd());
      }
      tableTail.replace(/\|\s+(?=\|)/g, '|\n').split('\n').forEach(row => {
        if (row.trim()) {
          expanded.push(`${prefix}${row.trim()}`.trimEnd());
        }
      });
    });

    return expanded;
  };

  const parseCells = (line: string) => {
    const { prefix, body } = splitQuotePrefix(line);
    let row = body.trim();
    if (!row.startsWith('|')) row = `| ${row}`;
    if (!row.endsWith('|')) row = `${row} |`;
    return {
      prefix,
      cells: row.slice(1, -1).split('|').map(cell => cell.trim())
    };
  };

  const isSeparatorCells = (cells: string[]) => {
    return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell.replace(/\s/g, '')));
  };

  const isTableLikeLine = (line: string) => {
    const { body } = splitQuotePrefix(line);
    const stripped = body.trim();
    return stripped.includes('|') && countPipes(stripped) >= 2;
  };

  const normalizeRow = (prefix: string, cells: string[], width: number, separator = false) => {
    const normalizedCells = separator ? Array(width).fill('---') : [...cells, ...Array(width).fill('')].slice(0, width);
    return `${prefix}| ${normalizedCells.join(' | ')} |`;
  };

  const appendBlankBeforeTable = (target: string[], prefix: string) => {
    if (!target.length || !target[target.length - 1].trim()) return;
    target.push(prefix.includes('>') ? prefix.trimEnd() : '');
  };

  const flushTable = (buffer: string[], target: string[]) => {
    if (!buffer.length) return;

    const parsedRows = buffer.map(parseCells);
    const dataRows = parsedRows.filter(row => !isSeparatorCells(row.cells));
    if (dataRows.length < 2) {
      target.push(...buffer);
      buffer.length = 0;
      return;
    }

    const tablePrefix = parsedRows[0].prefix;
    const separatorRows = parsedRows.filter(row => isSeparatorCells(row.cells));
    const width = Math.max(2, separatorRows.length ? separatorRows[0].cells.length : Math.max(...dataRows.map(row => row.cells.length)));
    appendBlankBeforeTable(target, tablePrefix);
    target.push(normalizeRow(parsedRows[0].prefix, parsedRows[0].cells, width));

    const secondIsSeparator = parsedRows.length > 1 && isSeparatorCells(parsedRows[1].cells);
    if (secondIsSeparator) {
      target.push(normalizeRow(parsedRows[1].prefix, parsedRows[1].cells, width, true));
    } else {
      target.push(normalizeRow(tablePrefix, [], width, true));
    }

    const trailingTexts: Array<{ prefix: string; text: string }> = [];
    parsedRows.slice(secondIsSeparator ? 2 : 1).forEach(row => {
      if (!isSeparatorCells(row.cells)) {
        if (row.cells.length > width) {
          const trailingText = row.cells.slice(width).join(' | ').trim();
          if (trailingText) {
            trailingTexts.push({ prefix: row.prefix, text: trailingText });
          }
        }
        target.push(normalizeRow(row.prefix, row.cells, width));
      }
    });
    trailingTexts.forEach(({ prefix, text }) => {
      target.push(`${prefix}${text}`.trimEnd());
    });
    if (target.length && target[target.length - 1].trim()) {
      target.push(tablePrefix.includes('>') ? tablePrefix.trimEnd() : '');
    }
    buffer.length = 0;
  };

  const lines = expandCollapsedTableLines(text);
  const repaired: string[] = [];
  const tableBuffer: string[] = [];
  let inFence = false;

  lines.forEach(line => {
    if (line.trim().startsWith('```')) {
      flushTable(tableBuffer, repaired);
      inFence = !inFence;
      repaired.push(line);
      return;
    }

    if (!inFence && isTableLikeLine(line)) {
      tableBuffer.push(line);
    } else {
      flushTable(tableBuffer, repaired);
      repaired.push(line);
    }
  });

  flushTable(tableBuffer, repaired);
  return repaired.join('\n');
};

const normalizeBodyContent = (text: string) => {
  return repairMarkdownTables(
    text
      .replace(/<\/?response>/g, '')
      .replace(/<\/?final_answer>/g, '')
      .trim()
  ).trim();
};

const getStatusLabel = (block?: ThoughtBlock) => {
  if (!block) return null;
  if (block.type === 'draft') return '正在拟定回答初稿';
  if (block.type === 'tool') {
    const toolMatch = block.content.match(/执行:\s*`([^`]+)`/);
    if (toolMatch) return `正在执行 ${toolMatch[1]}`;
    if (block.content.includes('工具执行完毕')) return '正在生成最终回复';
    return '正在调用工具';
  }
  if (block.type === 'ocp') {
    if (block.content.includes('审查完成')) return '已完成输出审查';
    if (block.content.includes('超时')) return 'OCP 超时，已使用兜底修复';
    if (block.content.includes('异常')) return 'OCP 异常，已使用兜底修复';
    if (block.content.includes('整理修正版正文')) return '正在整理修正版正文';
    if (block.content.includes('检查正文结构')) return '正在检查正文结构与引用格式';
    return '正在审查输出格式与信源';
  }
  return '正在分析问题';
};

const thoughtTypeLabel: Record<ThoughtBlock['type'], string> = {
  reasoning: 'Reasoning',
  draft: 'Draft',
  tool: 'Tool',
  ocp: 'OCP'
};

export const MessageItem: React.FC<MessageItemProps> = ({
  msg,
  isThinking,
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

  const thoughtBlocks = msg.role === 'assistant' ? (msg.thought_blocks || []).filter(block => block.content.trim()) : [];
  const mainContent = msg.role === 'assistant' ? normalizeBodyContent(msg.content || '') : '';
  const latestThought = thoughtBlocks[thoughtBlocks.length - 1];
  const collapsedStatus = getStatusLabel(latestThought) || (isThinking ? '正在思考' : null);
  const showThinking = isThinking && thoughtBlocks.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 sm:gap-4 max-w-[92%] sm:max-w-[85%] md:max-w-[75%] ${msg.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}
    >
      <div className={`shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full flex items-center justify-center mt-1 shadow-sm ${msg.role === 'user' ? 'bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400' : 'bg-white dark:bg-gray-800 text-blue-600 dark:text-blue-400 border border-gray-200 dark:border-gray-700'}`}>
        {msg.role === 'user' ? <div className="font-medium text-sm sm:text-base">U</div> : <Sparkles size={18} className="sm:size-5" />}
      </div>

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
                return <p className="whitespace-pre-wrap">{msg.content.replace(/TEMP\/[^\s"'`)\]<>*。，！？,?]+/g, '').trim()}</p>;
              })()}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5 w-full max-w-full">
            {(thoughtBlocks.length > 0 || (isThinking && collapsedStatus)) && (
              <div className="flex flex-col gap-3 w-full max-w-3xl">
                {thoughtBlocks.length > 0 ? (
                  <details data-testid="thought-process" className="group w-full" open={showThinking}>
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
                      {collapsedStatus && (
                        <span className="text-xs font-normal text-gray-500 dark:text-gray-400 max-w-72 truncate">
                          {collapsedStatus}
                        </span>
                      )}
                    </summary>
                    <div data-testid="thought-column" className="mt-3 mb-2 px-5 py-4 text-[15px] text-gray-600 dark:text-gray-300 border-l-4 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900/30 rounded-r-2xl flex flex-col gap-4 w-full">
                      {thoughtBlocks.map((block) => {
                        const isActiveTool = showThinking && block.id === latestThought?.id && (block.type === 'tool' || block.type === 'ocp');
                        return (
                          <div key={block.id} data-testid="thought-step" data-step-type={block.type} className="w-full">
                            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                              {(block.type === 'tool' || block.type === 'ocp') && <Loader2 size={13} className={isActiveTool ? "animate-spin text-blue-500" : "text-gray-400"} />}
                              <span>{thoughtTypeLabel[block.type]}</span>
                            </div>
                            <div className="prose prose-sm dark:prose-invert max-w-none w-full prose-p:leading-relaxed prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-200 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none">
                              <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{block.content.trim()}</Markdown>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                ) : (
                  <div className="flex items-center gap-2 w-fit bg-gray-100 dark:bg-gray-800/50 px-4 py-2 rounded-full border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-600 dark:text-gray-400">
                    <Loader2 size={14} className="animate-spin text-blue-500" />
                    <span>{collapsedStatus}</span>
                  </div>
                )}
              </div>
            )}

            {mainContent && (
              <div data-testid="assistant-content" className="px-4 py-3 sm:px-6 sm:py-4 text-[15px] sm:text-[16px] leading-relaxed shadow-sm w-full bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[20px] sm:rounded-[28px] rounded-tl-sm sm:rounded-tl-lg border border-gray-200 dark:border-gray-800">
                <div className="prose prose-base dark:prose-invert max-w-none w-full prose-p:leading-relaxed prose-headings:text-gray-900 dark:prose-headings:text-gray-100 prose-headings:font-medium prose-strong:text-gray-900 dark:prose-strong:text-gray-100 prose-strong:font-medium prose-a:text-blue-600 dark:prose-a:text-blue-400 prose-code:text-gray-900 dark:prose-code:text-gray-100 prose-code:bg-gray-100 dark:prose-code:bg-gray-700 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-100 dark:prose-pre:bg-gray-900 prose-pre:text-gray-900 dark:prose-pre:border prose-pre:border-gray-200 dark:prose-pre:border-gray-700 prose-pre:rounded-2xl">
                  <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={markdownComponents}>{mainContent}</Markdown>
                </div>
              </div>
            )}

            {msg.download_path && (
              <div className="source-list-container text-[14px] text-gray-600 dark:text-gray-400 w-full">
                <div className="font-medium mb-2 text-gray-900 dark:text-gray-100 flex items-center gap-2 uppercase tracking-wider text-[13px]">
                  <Info size={16} />
                  Generated file
                </div>
              </div>
            )}
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
