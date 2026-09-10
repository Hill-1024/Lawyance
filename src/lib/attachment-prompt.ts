/*
 * 模块描述：附件提示词协议，集中定义随消息文本下发的附件说明与其剥离逻辑。
 *
 * 这里同时被 useChat（生成）与 MessageItem（渲染前剥离）使用。历史上这段文本
 * 在两处各写一遍字面量，且把图片描述成"请读取的文件"，导致模型误判自己看不到图片，
 * 因此改为单一来源并显式区分「已可见的图片」与「需工具读取的文档」。
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

/** 取出消息中的文档附件名列表（沿用既有渲染约定）。 */
export const parseDocumentAttachments = (content: string): string[] => {
  const marker = `${DOCUMENT_ATTACHMENT_HEADER}\n`;
  const index = content.indexOf(marker);
  if (index < 0) return [];
  return content
    .slice(index + marker.length)
    .split('\n')
    .filter(line => line.startsWith('- '))
    .map(line => line.match(/^- (.*?) \(路径:/)?.[1] ?? line.slice(2))
    .filter(Boolean);
};

/** 去掉消息里残留的工作区路径，避免把内部路径显示给用户。 */
export const stripWorkspacePaths = (content: string): string =>
  content.replace(/TEMP\/[^\s"'`)\]<>*。，！？,?]+/g, '').trim();

/**
 * 从历史消息还原「待发送附件」与「用户正文」。
 *
 * 图片从消息元数据（attachments）还原，文档从文本协议还原——这是两条独立通道。
 * 同一份附件理论上只应被其中一条取到，但为避免任何情况下重复出现（撤回后待发区
 * 每个文件变成两份），这里按「kind + 文件名」去重，并保留首次出现的顺序。
 */
export const restoreAttachmentsFromMessage = (
  content: string,
  attachments?: MessageAttachmentLike[],
): { text: string; files: AttachmentPromptInput[] } => {
  const source = content || '';
  const records = attachments || [];

  const documentMarker = `${DOCUMENT_ATTACHMENT_HEADER}\n`;
  const documentIndex = source.indexOf(documentMarker);
  const documentNames = documentIndex >= 0 ? parseDocumentAttachments(source) : [];

  // 只保留元数据里真实存在的文档；没有元数据的旧消息才回退到纯文本协议。
  const documents = documentNames.map(name => {
    const record = records.find(item => item.name === name);
    return {
      name,
      path: record?.path ?? '',
      kind: 'document' as const,
    };
  });

  const images = records
    .filter(item => item.kind === 'image')
    .map(item => ({
      name: item.name,
      path: item.path,
      kind: 'image' as const,
      mime: item.mime,
    }));

  // 图片优先展示在待发区最前，随后是文档。
  const seen = new Set<string>();
  const files: AttachmentPromptInput[] = [];
  for (const file of [...images, ...documents]) {
    const key = `${file.kind}::${file.name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    files.push(file);
  }

  const body = documentIndex >= 0 ? source.slice(0, documentIndex) : source;

  return { text: stripWorkspacePaths(stripAttachmentPrompt(body)), files };
};

export type MessageAttachmentLike = {
  name: string;
  path: string;
  kind?: 'image' | 'document';
  mime?: string;
};
