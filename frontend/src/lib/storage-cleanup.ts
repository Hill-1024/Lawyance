/*
 * 模块描述：本地存储清理的纯判定逻辑，供垃圾回收与镜像还原共用，可独立测试。
 */

export interface CleanupCandidateFile {
  id: string;
  convId: string;
  blob?: { size: number } | null;
}

export interface CleanupPlan {
  /** 待删除的文件记录主键 */
  fileIds: string[];
  /** 记录全部失效的会话 id（其文件记录已包含在 fileIds 中） */
  orphanConvIds: string[];
  /** 删除释放的字节数（按 blob.size 估算） */
  spaceSaved: number;
}

/**
 * 选出应删除的文件记录：空占位（blob 缺失或 0 字节，来自生成文件下载失败的
 * 占位写入）与孤儿（convId 已不属于任何现存会话/庭审记录）。liveConvIds 内的
 * 真实附件一律保留。
 */
export const selectCleanupTargets = (
  files: CleanupCandidateFile[],
  liveConvIds: ReadonlySet<string>,
): CleanupPlan => {
  const fileIds: string[] = [];
  const orphanConvIds = new Set<string>();
  let spaceSaved = 0;

  for (const file of files) {
    const isEmpty = !file.blob || file.blob.size === 0;
    const isOrphan = !liveConvIds.has(file.convId);
    if (!isEmpty && !isOrphan) continue;
    fileIds.push(file.id);
    spaceSaved += file.blob?.size || 0;
    if (isOrphan) orphanConvIds.add(file.convId);
  }

  return { fileIds, orphanConvIds: [...orphanConvIds], spaceSaved };
};

/** 现存会话与庭审记录的 id 集合，即文件记录允许归属的范围。 */
export const collectLiveConvIds = (
  conversations: ReadonlyArray<{ id: string }>,
  courtSessions: ReadonlyArray<{ id: string }>,
): Set<string> => {
  const ids = new Set<string>();
  for (const conv of conversations) ids.add(String(conv.id));
  for (const session of courtSessions) ids.add(String(session.id));
  return ids;
};
