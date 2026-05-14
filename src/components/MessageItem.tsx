/*
 * 模块描述：单条消息渲染组件，处理 Markdown、思考过程、工具过程、OCP 状态和操作按钮。
 */

import React from 'react';
import { ChevronDown, Info, Paperclip, Undo2, Pencil, RefreshCw } from 'lucide-react';
import { motion } from 'motion/react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import { Message, ThoughtBlock } from '../types';
import { Mermaid } from './Mermaid';
import { BrandMark } from './Brand';

interface MessageItemProps {
  msg: Message;
  isThinking: boolean;
  isLast: boolean;
  onRegenerate?: (id: string) => void;
  onEdit?: (id: string) => void;
  onUndo?: (id: string) => void;
}

const markdownSanitizeSchema: any = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames || []),
    'sup',
    'sub'
  ],
  attributes: {
    ...defaultSchema.attributes,
    a: [
      ...(defaultSchema.attributes?.a || []),
      'href',
      'title'
    ],
    code: [
      ...(defaultSchema.attributes?.code || []),
      ['className', /^language-[\w-]+$/]
    ],
    sup: [],
    sub: []
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto']
  }
};

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

const extractFinalAnswerContent = (text: string) => {
  const extractByTags = (openPattern: RegExp, closePattern: RegExp) => {
    const closeMatches = [...text.matchAll(closePattern)];
    const openMatches = [...text.matchAll(openPattern)];
    if (openMatches.length === 0) return null;

    const closeMatch = closeMatches[closeMatches.length - 1];
    const closeIndex = closeMatch?.index ?? -1;
    const prefix = closeIndex >= 0 ? text.slice(0, closeIndex) : text;
    const prefixOpenMatches = [...prefix.matchAll(openPattern)];
    const openMatch = prefixOpenMatches[prefixOpenMatches.length - 1] || openMatches[openMatches.length - 1];
    const openIndex = openMatch.index ?? -1;
    if (openIndex < 0) return null;

    const candidate = text.slice(openIndex + openMatch[0].length, closeIndex >= 0 ? closeIndex : undefined).trim();
    return candidate || null;
  };

  return (
    extractByTags(/<\s*final_answer\s*>/gi, /<\s*\/\s*final_answer\s*>/gi) ||
    extractByTags(/&lt;\s*final_answer\s*&gt;/gi, /&lt;\s*\/\s*final_answer\s*&gt;/gi) ||
    text
  );
};

const stripBodyWrapperLines = (value: string) => {
  const wrapperPatterns = [
    /^文本内容.{0,120}(无需修复|原样输出).*$/i,
    /^\[?OCP\]?.{0,80}(正在|审查|检查|修复|完成|超时|异常).*$/i,
    /^OCP\s*.{0,80}$/i,
    /^\*\*\[拟定初稿\]\*\*$/i,
    /^\[拟定初稿\]$/i,
    /^正在拟定回答初稿$/i
  ];
  const lines = value.trim().split('\n');
  while (lines.length > 0 && wrapperPatterns.some(pattern => pattern.test(lines[0].trim()))) {
    lines.shift();
    while (lines.length > 0 && !lines[0].trim()) {
      lines.shift();
    }
  }
  return lines.join('\n').trim();
};

const normalizeBodyContent = (text: string) => {
  const taggedFinalAnswer = extractFinalAnswerContent(text);

  return repairMarkdownTables(
    stripBodyWrapperLines(
      taggedFinalAnswer
        .replace(/<\/?\s*(?:response|final_answer)\s*>/gi, '')
        .replace(/&lt;\/?\s*(?:response|final_answer)\s*&gt;/gi, '')
        .trim()
    )
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
    if (
      block.content.includes('审查完成') ||
      block.content.includes('保留当前最佳版本') ||
      block.content.includes('最大检查轮次') ||
      block.content.includes('停止自循环')
    ) return '已完成输出审查';
    if (block.content.includes('超时')) return 'OCP 超时，已使用兜底修复';
    if (block.content.includes('异常')) return 'OCP 异常，已使用兜底修复';
    if (block.content.includes('整理修正版正文')) return '正在整理修正版正文';
    if (block.content.includes('检查正文结构')) return '正在检查正文结构与引用格式';
    return '正在审查输出格式与信源';
  }
  if (block.type === 'memory') {
    if (block.content.includes('完成')) return '记忆整理完成';
    if (block.content.includes('失败') || block.content.includes('异常')) return '记忆整理未完成';
    return '正在整理记忆';
  }
  return '正在分析问题';
};

const thoughtTypeLabel: Record<ThoughtBlock['type'], string> = {
  reasoning: 'Reasoning',
  draft: 'Draft',
  tool: 'Tool',
  ocp: 'OCP',
  memory: 'Memory'
};

const sanitizeThoughtContent = (content: string, type: ThoughtBlock['type']) => {
  if (type === 'draft') {
    const draft = stripBodyWrapperLines(
      extractFinalAnswerContent(content)
        .replace(/<\/?\s*(?:response|final_answer)\s*>/gi, '')
        .replace(/&lt;\/?\s*(?:response|final_answer)\s*&gt;/gi, '')
        .trim()
    );
    return draft || '正在拟定回答初稿';
  }

  const leakedInstructionPatterns = [
    /<\/?\s*final_answer\s*>/i,
    /final_answer/i,
    /禁止\s*emoji/i,
    /纯文本\s*和\s*Markdown/i,
    /必须使用纯文本/i,
    /最终回复必须/i,
    /引用格式要规范/i,
    /底部信源必须/i,
    /底部列出参考信源/i,
    /检查约束/i,
    /^限制[:：]/i,
    /系统指令/i,
    /禁止凭记忆/i,
    /工具未返回内容/i,
    /严禁泄露/i,
    /严禁闲聊/i,
    /不要输出文件路径/i,
    /确保没有\s*emoji/i,
    /retrieve_conversation_memory/i,
    /我应该只输出/i,
    /不要有任何解释/i,
    /包含了标签/i,
    /错误地给了分析/i
  ];

  const cleaned = content
    .split('\n')
    .filter(line => !leakedInstructionPatterns.some(pattern => pattern.test(line)))
    .join('\n')
    .replace(/<\/?\s*(?:response|final_answer)\s*>/gi, '')
    .replace(/&lt;\/?\s*(?:response|final_answer)\s*&gt;/gi, '')
    .trim();

  return cleaned || getStatusLabel({ id: 'sanitized', type, content }) || '正在分析问题';
};

const WorkflowStatusIcon: React.FC<{ status: 'running' | 'done' }> = ({ status }) => (
  <svg
    className={`lawver-status-glyph ${status === 'running' ? 'is-running' : 'is-done'}`}
    viewBox="0 0 16 16"
    aria-hidden="true"
  >
    {status === 'running' ? (
      <>
        <circle className="status-track" cx="8" cy="8" r="7" />
        <circle className="status-sweep" cx="8" cy="8" r="7" pathLength="50" strokeDashoffset="0" />
      </>
    ) : (
      <>
        <circle className="status-ring" cx="8" cy="8" r="7" pathLength="50" />
        <path className="status-check" d="M5 8.4 L7.2 10.6 L11 6.4" />
      </>
    )}
  </svg>
);

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
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.2, 0, 0, 1] }}
      className={`flex max-w-full gap-3 sm:gap-4 ${msg.role === 'user' ? 'self-end flex-row-reverse md:max-w-[85%]' : 'self-start'}`}
    >
      <div className={`mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full shadow-[var(--shadow-1)] sm:h-10 sm:w-10 ${msg.role === 'user' ? 'bg-[var(--accent-quiet)] text-[var(--brand-primary-700)] dark:text-[var(--accent)]' : 'border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'}`}>
        {msg.role === 'user' ? <div className="text-sm font-medium sm:text-base">U</div> : <BrandMark className="h-5 w-5" />}
      </div>

      <div className={`flex flex-col gap-3 min-w-0 w-full ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
        {msg.role === 'user' ? (
          <div className="message-copy w-fit rounded-[24px_8px_24px_24px] bg-[var(--accent)] px-4 py-3 text-[15px] leading-relaxed text-[var(--accent-on)] shadow-[var(--shadow-1)] sm:px-5 sm:py-3.5 sm:text-[16px]">
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
                            <div key={i} className="flex items-center gap-1.5 rounded-full bg-black/15 px-3 py-1 text-sm">
                              <Paperclip size={14} strokeWidth={2} />
                              <span className="max-w-[200px] truncate">{file}</span>
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
            <div className="flex w-full max-w-full flex-col gap-5">
            {(thoughtBlocks.length > 0 || (isThinking && collapsedStatus)) && (
              <div className="flex w-full max-w-3xl flex-col gap-3">
                {thoughtBlocks.length > 0 ? (
                  <details data-testid="thought-process" className="group w-full" open={showThinking}>
                    <summary className="lawver-pressable flex w-fit cursor-pointer select-none items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-inset)] px-3.5 py-2 text-[13px] font-medium leading-none text-[var(--fg-2)] transition-colors list-none hover:text-[var(--fg-1)] [&::-webkit-details-marker]:hidden">
                      <ChevronDown size={14} strokeWidth={2} className="transform transition-transform duration-200 group-open:-rotate-180" />
                      {showThinking ? (
                        <span className="flex items-center gap-2">
                          Thinking
                          <span className="flex gap-1">
                            <span className="lawver-bloom-dot h-1 w-1 rounded-full bg-[var(--fg-3)]" />
                            <span className="lawver-bloom-dot h-1 w-1 rounded-full bg-[var(--fg-3)]" />
                            <span className="lawver-bloom-dot h-1 w-1 rounded-full bg-[var(--fg-3)]" />
                          </span>
                        </span>
                      ) : "Thought Process"}
                      {collapsedStatus && (
                        <span className="max-w-72 truncate text-xs font-normal text-[var(--fg-3)]">
                          {collapsedStatus}
                        </span>
                      )}
                    </summary>
                    <div data-testid="thought-column" className="mb-2 mt-3 flex w-full flex-col rounded-r-[14px] border-l-[3px] border-[var(--border-default)] bg-[rgba(59,98,184,0.04)] px-[18px] py-3.5 text-[13px] leading-[1.6] text-[var(--fg-2)]">
                      {thoughtBlocks.map((block, index) => {
                        const stepStatus = showThinking && block.id === latestThought?.id ? 'running' : 'done';
                        const blockContent = sanitizeThoughtContent(block.content, block.type);
                        return (
                          <div key={block.id} data-testid="thought-step" data-step-type={block.type} className={`flex w-full flex-col gap-1.5 py-1 ${index > 0 ? 'mt-1.5 border-t border-dashed border-[var(--border-default)] pt-3.5' : ''}`}>
                            <div className={`thought-step-label flex items-center gap-2 text-[10px] font-semibold uppercase leading-none tracking-[0.08em] ${stepStatus === 'running' ? 'is-running' : 'is-done'}`}>
                              <WorkflowStatusIcon key={`${block.id}-${stepStatus}`} status={stepStatus} />
                              <span className="thought-step-label-text">{thoughtTypeLabel[block.type]}</span>
                            </div>
                            <div className="thought-copy prose dark:prose-invert w-full max-w-none">
                              <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSanitizeSchema]]} components={markdownComponents}>{blockContent}</Markdown>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                ) : (
                  <div className="flex w-fit items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-inset)] px-3.5 py-2 text-[13px] font-medium leading-none text-[var(--fg-2)]">
                    <WorkflowStatusIcon status="running" />
                    <span>{collapsedStatus}</span>
                  </div>
                )}
              </div>
            )}

            {mainContent && (
              <div data-testid="assistant-content" className="w-full rounded-[8px_24px_24px_24px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 text-[var(--fg-1)] shadow-[var(--shadow-1)] sm:px-5 sm:py-3.5">
                <div className="message-copy prose dark:prose-invert w-full max-w-none">
                  <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSanitizeSchema]]} components={markdownComponents}>{mainContent}</Markdown>
                </div>
              </div>
            )}

            {msg.download_path && (
              <div className="source-list-container w-full text-[14px] text-[var(--fg-2)]">
                <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
                  <Info size={14} strokeWidth={2} />
                  Generated file
                </div>
              </div>
            )}
          </div>
        )}
        {msg.role === 'user' && !isThinking && onUndo && onEdit && onRegenerate && (
          <div className="mt-1 flex gap-2 self-end">
            <button
              onClick={() => onUndo(msg.id)}
              className="rounded-full p-1.5 text-[var(--fg-4)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              title="Undo"
            >
              <Undo2 size={14} strokeWidth={2} />
            </button>
            <button
              onClick={() => onEdit(msg.id)}
              className="rounded-full p-1.5 text-[var(--fg-4)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              title="Edit"
            >
              <Pencil size={14} strokeWidth={2} />
            </button>
            <button
              onClick={() => onRegenerate(msg.id)}
              className="rounded-full p-1.5 text-[var(--fg-4)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              title="Regenerate"
            >
              <RefreshCw size={14} strokeWidth={2} />
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
};
