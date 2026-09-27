import assert from 'node:assert/strict';

import { collectLiveConvIds, selectCleanupTargets } from '../src/lib/storage-cleanup';

const liveIds = collectLiveConvIds(
  [{ id: 'conv-a' }, { id: 'conv-b' }],
  [{ id: 'court-1' }],
);
assert.deepEqual([...liveIds].sort(), ['conv-a', 'conv-b', 'court-1']);
// 数字 id 一律按字符串比较，与 IndexedDB 读回的行为一致
assert.ok(collectLiveConvIds([{ id: 123 as unknown as string }], []).has('123'));

const file = (id: string, convId: string, size: number | null) => ({
  id,
  convId,
  blob: size === null ? null : { size },
});

// 现有对话的真实附件保留；空占位与孤儿（含空孤儿）删除；字节数只累计被删记录
const plan = selectCleanupTargets(
  [
    file('f1', 'conv-a', 1_500_000),   // 活会话真实附件 → 保留
    file('f2', 'conv-a', 0),           // 活会话空占位 → 删
    file('f3', 'conv-x', 2_500_000),   // 孤儿真实附件 → 删
    file('f4', 'conv-x', 0),           // 孤儿空占位 → 删
    file('f5', 'court-1', 100),        // 庭审记录附件算存活 → 保留
    file('f6', 'conv-y', null),        // blob 缺失 → 删
  ],
  liveIds,
);
assert.deepEqual(plan.fileIds.sort(), ['f2', 'f3', 'f4', 'f6']);
assert.deepEqual(plan.orphanConvIds.sort(), ['conv-x', 'conv-y']);
assert.equal(plan.spaceSaved, 2_500_000);

// 同一会话多条孤儿记录只报告一次 convId（镜像还原按会话整批删除）
const dedup = selectCleanupTargets(
  [file('g1', 'conv-z', 10), file('g2', 'conv-z', 20)],
  liveIds,
);
assert.deepEqual(dedup.orphanConvIds, ['conv-z']);
assert.equal(dedup.fileIds.length, 2);
assert.equal(dedup.spaceSaved, 30);

// 存活集合为空（还原到空备份）时全部记录都是孤儿
const allOrphan = selectCleanupTargets(
  [file('h1', 'conv-a', 500), file('h2', 'conv-b', 0)],
  new Set(),
);
assert.deepEqual(allOrphan.fileIds.sort(), ['h1', 'h2']);
assert.equal(allOrphan.spaceSaved, 500);

// 空列表不动、字节数为 0
const empty = selectCleanupTargets([], liveIds);
assert.deepEqual(empty, { fileIds: [], orphanConvIds: [], spaceSaved: 0 });

console.log('storage cleanup: orphan/placeholder selection and live-id collection checks passed');
