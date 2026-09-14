/*
 * 模块描述：附件提示词协议，集中定义随消息文本下发的附件说明、其剥离逻辑，
 * 以及「一条消息上有哪些附件」的唯一判定入口。
 *
 * 这里同时被 useChat（生成、撤回还原）与 MessageItem（渲染）使用。历史上这段文本
 * 在两处各写一遍字面量，且把图片描述成"请读取的文件"，导致模型误判自己看不到图片，
 * 因此改为单一来源并显式区分「已可见的图片」与「需工具读取的文档」。
 *
 * 附件清单同样只能有一个来源：气泡渲染与撤回还原都走 resolveMessageAttachments，
 * 否则同一份附件会被元数据与文本协议各渲染一次（气泡上下各一份），
 * 图片也会因为缺少元数据而被当成文档、丢掉缩略图。
 */

/** 图片与文档同等对待：都给出工作区路径，由模型调用对应工具按需读取。 */
export const IMAGE_ATTACHMENT_HEADER = '[用户已上传以下图片，可采用 image_reader 查看]';

/**
 * 历史版本的图片块标题。历史消息仍存着旧标题，渲染时必须一并识别，
 * 否则整段附件说明会作为正文暴露在气泡里。
 */
export const LEGACY_IMAGE_ATTACHMENT_HEADERS = [
  '[本轮消息已直接附带以下图片，你可以直接看到图片内容]',
  '[本轮附带图片]',
];

const ALL_IMAGE_HEADERS = [IMAGE_ATTACHMENT_HEADER, ...LEGACY_IMAGE_ATTACHMENT_HEADERS];

export const DOCUMENT_ATTACHMENT_HEADER =
  '[用户已上传以下文件，请根据需要进行读取和处理]';

export type AttachmentPromptInput = {
  name: string;
  path: string;
  kind?: 'image' | 'document';
};

/** 气泡与待发区展示用的附件条目：kind 恒定有值，不再依赖消息元数据是否完整。 */
export type ResolvedAttachment = {
  name: string;
  path: string;
  kind: 'image' | 'document';
  mime?: string;
};

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'];

/**
 * 图片判定：mime 是 image/*，或文件名是已知图片扩展名。
 *
 * 上传（useWorkspace）与渲染/撤回还原共用这一条规则。旧版本消息没有逐条 kind 元数据，
 * 只靠扩展名区分，若两处规则不一致，同一张图会出现「上传时算图片、撤回后算文档」的
 * 漂移：待发区没有缩略图、重发后图片被写进文档块，气泡里就变成一张文件卡片。
 */
export const isImageAttachment = (name: string, mime?: string): boolean => {
  if (String(mime || '').toLowerCase().startsWith('image/')) return true;
  const lower = String(name || '').toLowerCase();
  return IMAGE_EXTENSIONS.some(ext => lower.endsWith(ext));
};

/**
 * 生成附件说明文本块。
 *
 * 图片块必须是**纯事实陈述**：只列出文件名，不写任何祈使句。
 * 早期版本在这里写"请直接依据画面作答，不要声称无法查看图片"，
 * 结果被模型判为提示词注入并触发 L0-1 安全拒绝模板，把正确回答替换掉了。
 * 「图片已可见、不得否认」这类行为约束属于系统提示词（core/35-multimodal-input.md）。
 *
 * 文档块保持在最后，因为历史渲染逻辑以它作为文件清单的起始锚点。
 */
export const buildAttachmentPrompt = (pendingUploads: AttachmentPromptInput[]): string => {
  if (pendingUploads.length === 0) return '';

  const images = pendingUploads.filter(item => item.kind === 'image');
  const documents = pendingUploads.filter(item => item.kind !== 'image');
  const blocks: string[] = [];

  if (images.length > 0) {
    // 与文档块同形：带路径，模型据此调用 image_reader。
    const lines = images.map(item => `- ${item.name} (路径: ${item.path})`).join('\n');
    blocks.push(`${IMAGE_ATTACHMENT_HEADER}\n${lines}`);
  }

  if (documents.length > 0) {
    const lines = documents.map(item => `- ${item.name} (路径: ${item.path})`).join('\n');
    blocks.push(`${DOCUMENT_ATTACHMENT_HEADER}\n${lines}`);
  }

  return blocks.join('\n\n');
};

/**
 * 渲染历史消息时剥离附件说明：内容已由缩略图/文件卡片表达，不必再显示成正文。
 * 图片块与文档块都会移除（文档块恒定在末尾）。
 */
export const stripAttachmentPrompt = (content: string): string => {
  if (!content) return '';
  let text = content;

  // 文档块始终排在最后，从它的标题起直接截断
  const documentIndex = text.indexOf(DOCUMENT_ATTACHMENT_HEADER);
  if (documentIndex >= 0) {
    text = text.slice(0, documentIndex);
  }

  // 图片块：从标题到其后第一个空行（含历史标题）
  let imageIndex = -1;
  for (const header of ALL_IMAGE_HEADERS) {
    const at = text.indexOf(header);
    if (at >= 0) {
      imageIndex = imageIndex < 0 ? at : Math.min(imageIndex, at);
    }
  }
  if (imageIndex >= 0) {
    const rest = text.slice(imageIndex);
    const blockEnd = rest.search(/\n\s*\n/);
    text = text.slice(0, imageIndex) + (blockEnd >= 0 ? rest.slice(blockEnd) : '');
  }

  return text.replace(/\n{3,}/g, '\n\n').trim();
};

/** 文本协议里的附件条目：name/path 来自行内容，block 记录它写在哪个块里。 */
export type ParsedAttachmentEntry = {
  name: string;
  path: string;
  block: 'image' | 'document';
};

const ATTACHMENT_BLOCKS: { header: string; block: 'image' | 'document' }[] = [
  ...ALL_IMAGE_HEADERS.map(header => ({ header, block: 'image' as const })),
  { header: DOCUMENT_ATTACHMENT_HEADER, block: 'document' as const },
];

/**
 * 解析消息文本里的附件块（图片块与文档块，含历史标题）。
 *
 * 逐行扫描而不是按标题切切片：文档块恒定在末尾且可能没有结尾空行，
 * 而图片块总是夹在正文与文档块之间——按块内空行收尾对两种排布都成立。
 * 路径必须一并取出：撤回重发时若丢掉路径，模型就再也读不到这个文件了。
 */
export const parseAttachmentEntries = (content: string): ParsedAttachmentEntry[] => {
  if (!content) return [];
  const entries: ParsedAttachmentEntry[] = [];
  let block: 'image' | 'document' | null = null;

  for (const rawLine of content.split('\n')) {
    const line = rawLine.trim();
    const matchedBlock = ATTACHMENT_BLOCKS.find(item => line === item.header);
    if (matchedBlock) {
      block = matchedBlock.block;
      continue;
    }
    if (!block) continue;
    if (!line) {
      block = null;
      continue;
    }
    if (!line.startsWith('- ')) continue;

    const withPath = line.match(/^- (.*?) \(路径: ?(.*?)\)$/);
    const name = (withPath ? withPath[1] : line.slice(2)).trim();
    if (name) entries.push({ name, path: (withPath?.[2] ?? '').trim(), block });
  }

  return entries;
};

/** 去掉消息里残留的工作区路径，避免把内部路径显示给用户。 */
export const stripWorkspacePaths = (content: string): string =>
  content.replace(/TEMP\/[^\s"'`)\]<>*。，！？,?]+/g, '').trim();

/**
 * 汇总一条消息上的附件，供气泡渲染与撤回还原共用。
 *
 * 这是「附件只出现一次」的唯一出口：气泡上下的图片缩略图与文档卡片、以及撤回后
 * 待发区的条目，全部由它派生。此前气泡分别从消息元数据与文本协议各取一次，
 * 一份附件于是上下各显示一遍。
 *
 * kind 一律按 mime/扩展名重新判定，而不是照抄元数据——被旧逻辑写坏的记录
 * （图片存成 document）也能在这里自愈。
 */
export const resolveMessageAttachments = (
  content: string,
  attachments?: MessageAttachmentLike[],
): ResolvedAttachment[] => {
  const records = attachments || [];
  const parsed = parseAttachmentEntries(content || '');
  const seen = new Set<string>();
  const resolved: ResolvedAttachment[] = [];

  const collect = (name: string, path: string, mime?: string) => {
    if (!name) return;
    const kind = isImageAttachment(name, mime) ? 'image' : 'document';
    const key = `${kind}::${name}`;
    if (seen.has(key)) return;
    seen.add(key);
    resolved.push({ name, path, kind, mime });
  };

  // 元数据在前：它带着上传时的 mime 与工作区路径，比文本协议更可靠。
  records.forEach(record => collect(record.name, record.path, record.mime));

  // 文本协议兜底：历史消息没有元数据，路径与顺序只能从这里取。
  parsed.forEach(entry => {
    const record = records.find(item => item.name === entry.name);
    collect(entry.name, entry.path || record?.path || '', record?.mime);
  });

  return resolved;
};

/**
 * 从历史消息还原「待发送附件」与「用户正文」。
 *
 * 返回值必须与气泡渲染完全一致（都走 resolveMessageAttachments），否则撤回一次
 * 待发区就会多出一份、或者把文档复制成图片。
 */
export const restoreAttachmentsFromMessage = (
  content: string,
  attachments?: MessageAttachmentLike[],
): { text: string; files: ResolvedAttachment[] } => {
  const source = content || '';
  return {
    text: stripWorkspacePaths(stripAttachmentPrompt(source)),
    files: resolveMessageAttachments(source, attachments),
  };
};

export type MessageAttachmentLike = {
  name: string;
  path: string;
  kind?: 'image' | 'document';
  mime?: string;
};
