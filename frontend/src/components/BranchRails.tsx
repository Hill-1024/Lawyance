/*
 * 模块描述：分支侧栏的连接线绘制组件。按 flattenBranchTree 输出的祖先 trail 与
 * isLastSibling 标记，画出 vertical / T / L 形指引线，直观呈现父子层级。
 */

import React from 'react';

interface BranchRailsProps {
  ancestorTrails: boolean[];
  isLastSibling: boolean;
}

const RAIL_BG = 'bg-[var(--border-default)]';
const RAIL_WIDTH = 'w-3';

/**
 * 一个 depth=N 节点画 N 列轨道：
 *   - 前 N-1 列：祖先 axis；按 ancestorTrails[i] 决定是否画一条贯穿的纵线
 *   - 最后一列：当前节点的 connector
 *       · 上半纵线（始终有，连到父分支轨道）
 *       · 横线（拐进节点内容）
 *       · 下半纵线（仅当还有后续兄弟需要被连接时）
 */
export const BranchRails: React.FC<BranchRailsProps> = ({ ancestorTrails, isLastSibling }) => {
  const depth = ancestorTrails.length;
  if (depth === 0) return null;

  return (
    <div aria-hidden="true" className="flex shrink-0 items-stretch self-stretch">
      {Array.from({ length: depth - 1 }, (_, index) => (
        <div key={`anc-${index}`} className={`relative ${RAIL_WIDTH} shrink-0`}>
          {ancestorTrails[index] && (
            <span className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 ${RAIL_BG}`} />
          )}
        </div>
      ))}
      <div className={`relative ${RAIL_WIDTH} shrink-0`}>
        {/* 上半纵线：从父行的轨道连下来 */}
        <span className={`absolute left-1/2 top-0 h-1/2 w-px -translate-x-1/2 ${RAIL_BG}`} />
        {/* 横线：拐进节点 */}
        <span className={`absolute left-1/2 top-1/2 h-px w-1/2 -translate-y-1/2 ${RAIL_BG}`} />
        {/* 下半纵线：还有后续兄弟时延续 */}
        {!isLastSibling && (
          <span className={`absolute left-1/2 top-1/2 h-1/2 w-px -translate-x-1/2 ${RAIL_BG}`} />
        )}
      </div>
    </div>
  );
};
