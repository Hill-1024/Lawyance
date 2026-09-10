/*
 * 模块描述：附件提示词协议回归测试，锁定「图片已可见 / 文档需读取」的表达与往返解析。
 *
 * 运行：pnpm run test:attachment-prompt
 */

import assert from 'node:assert/strict';

import {
  DOCUMENT_ATTACHMENT_HEADER,
  IMAGE_ATTACHMENT_HEADER,
  buildAttachmentPrompt,
  parseDocumentAttachments,
  restoreAttachmentsFromMessage,
  stripAttachmentPrompt,
  stripWorkspacePaths,
} from '../src/lib/attachment-prompt';

/* ── 空输入 ── */
assert.equal(buildAttachmentPrompt([]), '', '没有附件时不应产生任何文本');

/* ── 只有图片：必须说明「已可见」，且不得出现「读取」的误导 ── */
const imageOnly = buildAttachmentPrompt([
  { name: '借条.jpg', path: 'TEMP/u/c/借条.jpg', kind: 'image' },
]);
assert.ok(imageOnly.includes(IMAGE_ATTACHMENT_HEADER), '缺少图片块标题');
assert.ok(imageOnly.includes('借条.jpg'), '缺少图片文件名');
assert.ok(!imageOnly.includes(DOCUMENT_ATTACHMENT_HEADER), '只有图片时不应出现文档块');
// 图片与文档同形：必须带工作区路径，模型据此调用 image_reader
assert.ok(imageOnly.includes('路径: TEMP/u/c/借条.jpg'), '图片块必须带工作区路径');


/* ── 只有文档：保留原有的「请读取」语义与路径 ── */
const docOnly = buildAttachmentPrompt([
  { name: '合同.pdf', path: 'TEMP/u/c/合同.pdf', kind: 'document' },
]);
assert.ok(docOnly.includes(DOCUMENT_ATTACHMENT_HEADER), '缺少文档块');
assert.ok(docOnly.includes('路径: TEMP/u/c/合同.pdf'), '文档需要保留路径供工具读取');
assert.ok(!docOnly.includes(IMAGE_ATTACHMENT_HEADER), '只有文档时不应出现图片块');

/* ── 混合：两块都要有，且文档块在最后（渲染以它为锚点） ── */
const mixed = buildAttachmentPrompt([
  { name: '现场.png', path: 'TEMP/u/c/现场.png', kind: 'image' },
  { name: '合同.pdf', path: 'TEMP/u/c/合同.pdf', kind: 'document' },
  { name: '照片.webp', path: 'TEMP/u/c/照片.webp', kind: 'image' },
]);
assert.ok(mixed.includes(IMAGE_ATTACHMENT_HEADER) && mixed.includes(DOCUMENT_ATTACHMENT_HEADER));
assert.ok(
  mixed.indexOf(DOCUMENT_ATTACHMENT_HEADER) > mixed.indexOf(IMAGE_ATTACHMENT_HEADER),
  '文档块必须排在图片块之后',
);
assert.ok(mixed.includes('现场.png') && mixed.includes('照片.webp'), '图片清单不完整');

/* ── 剥离：正文保留，附件说明不显示在气泡里 ── */
const full = `请看看这个合同\n\n${mixed}`;
const stripped = stripAttachmentPrompt(full);
assert.equal(stripped, '请看看这个合同', '剥离后应只剩用户正文');
assert.ok(!stripped.includes(IMAGE_ATTACHMENT_HEADER), '图片块未被剥离');
assert.ok(!stripped.includes(DOCUMENT_ATTACHMENT_HEADER), '文档块未被剥离');

assert.equal(stripAttachmentPrompt(imageOnly), '', '只有图片块时应剥离为空');
assert.equal(stripAttachmentPrompt('纯文本问题'), '纯文本问题', '无附件说明时应原样返回');
assert.equal(stripAttachmentPrompt(''), '');

/* ── 文档清单解析与剥离保持一致 ── */
const docs = ['合同.pdf', '补充协议.docx'];
const docPrompt = buildAttachmentPrompt(docs.map(name => ({
  name, path: `TEMP/u/c/${name}`, kind: 'document' as const,
})));
assert.deepEqual(parseDocumentAttachments(docPrompt), docs, '文档清单解析结果不一致');
assert.deepEqual(parseDocumentAttachments('没有附件'), []);

/* ── 正文里不能残留内部工作区路径 ── */
assert.equal(stripWorkspacePaths('见 TEMP/u/c/a.pdf 谢谢'), '见  谢谢');
assert.equal(stripWorkspacePaths('干净正文'), '干净正文');

/* ── 关键回归：图片块绝不能诱导模型调用读取工具 ── */
const forbidden = ['请读取图片', '读取以下图片', '请根据需要进行读取和处理]\n- 借条.jpg'];
for (const phrase of forbidden) {
  assert.ok(!imageOnly.includes(phrase), `图片块出现误导表述: ${phrase}`);
}
// 行为约束属于系统提示词（core/35-multimodal-input.md），不得写进用户消息


/* ── 往返：发送 → 撤回 必须稳定，数量不得翻倍 ── */
type CycleFile = { name: string; path: string; kind?: 'image' | 'document'; mime?: string };

// 与 handleSend 一致的组装
const sendCycle = (input: string, pending: CycleFile[]) => {
  let content = input.trim();
  if (pending.length > 0) {
    const prompt = buildAttachmentPrompt(pending);
    content += content ? `\n\n${prompt}` : prompt;
  }
  const attachments = pending.map(f => ({ name: f.name, path: f.path, kind: f.kind, mime: f.mime }));
  return { content, attachments };
};

const assertStable = (label: string, original: CycleFile[]) => {
  let { content, attachments } = sendCycle('看下这些材料', original);
  for (let round = 1; round <= 3; round += 1) {
    const { text, files } = restoreAttachmentsFromMessage(content, attachments);
    assert.equal(files.length, original.length, `${label} 第${round}轮撤回数量从 ${original.length} 变成 ${files.length}`);
    const keys = files.map(f => `${f.kind}::${f.name}`);
    assert.equal(new Set(keys).size, keys.length, `${label} 第${round}轮出现重复条目: ${keys.join(', ')}`);
    assert.deepEqual(
      keys.slice().sort(),
      original.map(f => `${f.kind}::${f.name}`).sort(),
      `${label} 第${round}轮附件集合发生变化`,
    );
    assert.equal(text, '看下这些材料', `${label} 第${round}轮正文被污染: "${text}"`);
    ({ content, attachments } = sendCycle(text, files));
  }
};

assertStable('纯图片', [{ name: '借条.png', path: 'TEMP/u/c/借条.png', kind: 'image' }]);
assertStable('纯文档', [{ name: '合同.pdf', path: 'TEMP/u/c/合同.pdf', kind: 'document' }]);
assertStable('两张图片', [
  { name: 'a.png', path: 'TEMP/u/c/a.png', kind: 'image' },
  { name: 'b.png', path: 'TEMP/u/c/b.png', kind: 'image' },
]);
assertStable('图片+文档混合', [
  { name: '现场.png', path: 'TEMP/u/c/现场.png', kind: 'image' },
  { name: '合同.pdf', path: 'TEMP/u/c/合同.pdf', kind: 'document' },
  { name: '补充.docx', path: 'TEMP/u/c/补充.docx', kind: 'document' },
]);

/* ── 双通道取到同一份附件时也必须只出现一次 ── */
const bothChannels = `正文\n\n${buildAttachmentPrompt([
  { name: 'dup.png', path: 'TEMP/u/c/dup.png', kind: 'image' },
  { name: 'dup.pdf', path: 'TEMP/u/c/dup.pdf', kind: 'document' },
])}`;
const restored = restoreAttachmentsFromMessage(bothChannels, [
  { name: 'dup.png', path: 'TEMP/u/c/dup.png', kind: 'image' },
  { name: 'dup.pdf', path: 'TEMP/u/c/dup.pdf', kind: 'document' },
]);
assert.deepEqual(
  restored.files.map(f => `${f.kind}::${f.name}`),
  ['image::dup.png', 'document::dup.pdf'],
  '图片与文档应各出现一次',
);
assert.equal(restored.text, '正文');

// 元数据与文本协议都列出同一份文档时，不能变成两份
const doubledDoc = `正文\n\n${DOCUMENT_ATTACHMENT_HEADER}\n- same.pdf (路径: TEMP/u/c/same.pdf)`;
const doubled = restoreAttachmentsFromMessage(doubledDoc, [
  { name: 'same.pdf', path: 'TEMP/u/c/same.pdf', kind: 'document' },
]);
assert.equal(doubled.files.length, 1, `同文档被重复还原: ${doubled.files.length} 份`);

/* ── 旧消息（有文本协议但无元数据）仍能还原文档 ── */
const legacy = `旧消息正文\n\n[用户已上传以下文件，请根据需要进行读取和处理]\n- legacy.pdf (路径: TEMP/u/c/legacy.pdf)`;
const legacyRestored = restoreAttachmentsFromMessage(legacy);
assert.deepEqual(legacyRestored.files, [{ name: 'legacy.pdf', path: '', kind: 'document' }], '旧消息文档还原失败');
assert.equal(legacyRestored.text, '旧消息正文');

/* ── 历史消息兼容：旧标题的图片块也必须被剥离 ── */
{
  const legacySamples = [
    '[本轮消息已直接附带以下图片，你可以直接看到图片内容]\n请直接依据画面作答，不要声称无法查看图片，也不要尝试用工具读取图片。\n- logo.png',
    '[本轮附带图片]\n- logo.png',
  ];
  for (const legacy of legacySamples) {
    const content = `这个图标是什么\n\n${legacy}`;
    assert.equal(
      stripAttachmentPrompt(content),
      '这个图标是什么',
      `历史图片块未被剥离: ${legacy.slice(0, 24)}`,
    );
  }
  // 历史块 + 文档块混合
  const mixedLegacy = `问题\n\n[本轮消息已直接附带以下图片，你可以直接看到图片内容]\n提示\n- a.png\n\n${DOCUMENT_ATTACHMENT_HEADER}\n- b.pdf (路径: TEMP/u/c/b.pdf)`;
  assert.equal(stripAttachmentPrompt(mixedLegacy), '问题', '历史图片块与文档块混合时剥离失败');
}

console.log('✅ 附件提示词协议全部通过（含往返与去重）');

/* ── 工作区路径归一：绝对/相对必须被视为同一文件 ── */
{
  const { toWorkspaceRelativePath, normalizeWorkspacePath } = await import('../src/lib/workspace-path');

  const CU = '/Users/x/proj/TEMP/u/conv/a.png';
  assert.equal(toWorkspaceRelativePath(CU), 'TEMP/u/conv/a.png');
  assert.equal(toWorkspaceRelativePath('/Users/x/proj/Result/u/conv/out.pdf'), 'Result/u/conv/out.pdf');
  assert.equal(toWorkspaceRelativePath('TEMP/u/conv/a.png'), 'TEMP/u/conv/a.png');
  assert.equal(toWorkspaceRelativePath('Result/u/conv/out.pdf'), 'Result/u/conv/out.pdf');
  assert.equal(toWorkspaceRelativePath('C:\\proj\\TEMP\\u\\a.png'), 'TEMP/u/a.png', 'Windows 反斜杠也要归一');
  assert.equal(toWorkspaceRelativePath(''), null);
  assert.equal(toWorkspaceRelativePath(null), null);
  assert.equal(toWorkspaceRelativePath('/etc/passwd'), null, '非工作区路径必须拒绝');
  assert.equal(toWorkspaceRelativePath('relative/without/root.txt'), null);

  // 关键：同一个文件无论以哪种形态传入，归一结果必须一致，
  // 否则本地文件库会以不同主键存下两条记录，界面上就显示为两份。
  assert.equal(toWorkspaceRelativePath(CU), toWorkspaceRelativePath('TEMP/u/conv/a.png'));
  assert.equal(normalizeWorkspacePath(CU), 'TEMP/u/conv/a.png');
  assert.equal(normalizeWorkspacePath(''), '', '归一失败时保留原值');

  // 形似但不是工作区内的路径不得被误当作工作区文件
  assert.equal(toWorkspaceRelativePath('/tmp/TEMPX/a.png'), null);
  assert.equal(toWorkspaceRelativePath('/tmp/ResultX/a.png'), null);
}

console.log('✅ 工作区路径归一全部通过');
