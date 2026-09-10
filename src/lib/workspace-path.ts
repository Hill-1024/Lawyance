/*
 * 模块描述：工作区路径形态归一，供本地文件库与工作区同步共用。
 *
 * 历史版本的上传接口返回绝对路径，而列表接口返回工作区相对路径。
 * 同一个文件因此会被当成两个不同文件（两条本地记录、或被误判为生成文件回灌），
 * 表现为"每个文件变成两份"。归一化必须收敛到唯一实现并被存储层复用。
 */

export const WORKSPACE_ROOTS = ['TEMP', 'Result'] as const;

/**
 * 把路径折算成 `TEMP/…` 或 `Result/…` 相对形式；无法识别为工作区路径时返回 null。
 */
export const toWorkspaceRelativePath = (path: unknown): string | null => {
  const candidate = String(path ?? '').replace(/\\/g, '/').trim();
  if (!candidate) return null;
  for (const root of WORKSPACE_ROOTS) {
    if (candidate.startsWith(`${root}/`)) return candidate;
  }
  for (const root of WORKSPACE_ROOTS) {
    const index = candidate.indexOf(`/${root}/`);
    if (index >= 0) return candidate.slice(index + 1);
  }
  return null;
};

/** 归一化失败时保留原值，适合"能归一就归一"的场景。 */
export const normalizeWorkspacePath = (path: unknown): string => {
  const raw = String(path ?? '');
  return toWorkspaceRelativePath(raw) ?? raw;
};
