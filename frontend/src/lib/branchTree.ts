/*
 * 模块描述：通用分支树构建器。把含 parent_id 的扁平列表展开成 DFS 顺序的带深度记录，
 * 供主聊天与模拟法庭的侧栏共同渲染父子缩进关系。
 */

export type BranchTreeRow<T> = {
  item: T;
  depth: number;
  isLastSibling: boolean;
  hasChildren: boolean;
  /** 各祖先层在该行位置是否还有后续兄弟节点；用于绘制持续的纵向连接线。 */
  ancestorTrails: boolean[];
};

type WithBranch = { id: string; parent_id?: string };

/**
 * 输入保持调用方原始顺序（一般是按时间倒序）。同一父下的孩子按它们在输入中的顺序排列；
 * 没有 parent_id 或 parent 已被删除的项作为根节点（孤儿提升）。
 */
export function flattenBranchTree<T extends WithBranch>(items: T[]): BranchTreeRow<T>[] {
  const byId = new Map<string, T>();
  for (const item of items) byId.set(item.id, item);

  const childrenOf = new Map<string, T[]>();
  const roots: T[] = [];
  for (const item of items) {
    const parentId = item.parent_id;
    if (parentId && byId.has(parentId)) {
      const bucket = childrenOf.get(parentId);
      if (bucket) bucket.push(item);
      else childrenOf.set(parentId, [item]);
    } else {
      roots.push(item);
    }
  }

  const out: BranchTreeRow<T>[] = [];
  const walk = (nodes: T[], depth: number, trails: boolean[]) => {
    nodes.forEach((node, index) => {
      const isLast = index === nodes.length - 1;
      const kids = childrenOf.get(node.id);
      out.push({
        item: node,
        depth,
        isLastSibling: isLast,
        hasChildren: Boolean(kids && kids.length > 0),
        ancestorTrails: [...trails]
      });
      if (kids && kids.length > 0) {
        walk(kids, depth + 1, [...trails, !isLast]);
      }
    });
  };
  walk(roots, 0, []);
  return out;
}
