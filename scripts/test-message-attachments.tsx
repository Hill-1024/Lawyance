/*
 * 模块描述：消息气泡附件渲染回归测试。
 *
 * 对真实的 MessageItem 做一次服务端渲染，数一数每条附件在气泡里渲染了几份。
 * 之所以要组件级验证：附件曾同时从「消息元数据」与「文本协议」两条路渲染，
 * 表现是同一份附件在气泡上下各出现一份——这种缺陷只有看渲染结果才锁得住。
 *
 * 运行：pnpm run test:message-attachments
 */

import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { MessageItem } from '../frontend/src/components/MessageItem';
import { DialogProvider } from '../frontend/src/contexts/DialogContext';
import { DOCUMENT_ATTACHMENT_HEADER, IMAGE_ATTACHMENT_HEADER } from '../frontend/src/lib/attachment-prompt';

type RenderCase = {
  label: string;
  content: string;
  attachments?: { name: string; path: string; kind: 'image' | 'document'; mime?: string }[];
  /** 期望渲染出的附件槽位，格式 `kind:name`；每个只允许出现一次。 */
  expected: string[];
};

const IMAGE_BLOCK = (name: string) => `${IMAGE_ATTACHMENT_HEADER}\n- ${name} (路径: TEMP/u/c/${name})`;
const DOC_BLOCK = (name: string) => `${DOCUMENT_ATTACHMENT_HEADER}\n- ${name} (路径: TEMP/u/c/${name})`;

const cases: RenderCase[] = [
  {
    label: '新消息：图片块 + 文档块 + 元数据',
    content: `看下这些材料\n\n${IMAGE_BLOCK('借条.png')}\n\n${DOC_BLOCK('合同.pdf')}`,
    attachments: [
      { name: '借条.png', path: 'TEMP/u/c/借条.png', kind: 'image', mime: 'image/png' },
      { name: '合同.pdf', path: 'TEMP/u/c/合同.pdf', kind: 'document' },
    ],
    expected: ['image:借条.png', 'document:合同.pdf'],
  },
  {
    label: '旧消息：图片被旧版本写进文档块，且没有元数据',
    content: `看下这些材料\n\n${DOC_BLOCK('借条.png')}\n- 合同.pdf (路径: TEMP/u/c/合同.pdf)`,
    expected: ['image:借条.png', 'document:合同.pdf'],
  },
  {
    label: '被旧撤回流程写坏的消息：元数据把图片记成文档、路径为空',
    content: `看下这些材料\n\n${IMAGE_BLOCK('借条.png')}\n\n${DOC_BLOCK('合同.pdf')}`,
    attachments: [
      { name: '借条.png', path: '', kind: 'document' },
      { name: '合同.pdf', path: '', kind: 'document' },
    ],
    expected: ['image:借条.png', 'document:合同.pdf'],
  },
  {
    label: '只有图片',
    content: `这张图什么意思\n\n${IMAGE_BLOCK('现场.png')}`,
    attachments: [{ name: '现场.png', path: 'TEMP/u/c/现场.png', kind: 'image', mime: 'image/png' }],
    expected: ['image:现场.png'],
  },
  {
    label: '纯文本消息',
    content: '帮我看看这个借条怎么写',
    expected: [],
  },
];

const renderBubble = (item: RenderCase) => renderToStaticMarkup(
  <DialogProvider>
    <MessageItem
      msg={{
        id: 'test-message',
        role: 'user',
        content: item.content,
        attachments: item.attachments,
        created_at: '2026-01-01T00:00:00.000Z',
        updated_at: '2026-01-01T00:00:00.000Z',
      } as any}
      isThinking={false}
      isLast
    />
  </DialogProvider>,
);

for (const item of cases) {
  const html = renderBubble(item);
  const slots = (html.match(/data-attachment="[^"]+"/g) || [])
    .map(match => match.slice('data-attachment="'.length, -1));

  assert.equal(
    new Set(slots).size,
    slots.length,
    `${item.label}：同一附件被渲染了多份 → ${slots.join(', ')}`,
  );
  assert.deepEqual(
    slots.slice().sort(),
    item.expected.slice().sort(),
    `${item.label}：附件渲染结果不符`,
  );

  // 气泡正文里不得漏出附件清单原文或工作区路径。
  for (const marker of [IMAGE_ATTACHMENT_HEADER, DOCUMENT_ATTACHMENT_HEADER, 'TEMP/']) {
    assert.ok(!html.includes(marker), `${item.label}：气泡里漏出 ${marker}`);
  }

  console.log(`✅ ${item.label} → ${slots.join(', ') || '无附件'}`);
}

console.log('✅ 消息气泡附件渲染全部通过（每条附件只渲染一份）');
