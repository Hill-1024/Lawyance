/*
 * 模块描述：credits 耗尽提示的门控组件。判定全部收在这里，Workbench 只管渲染——
 * max/business、运维豁免、余额未归零、勾过「不再提醒」、14 天冷却期内，都不弹；
 * 条件首次同时满足时回调 onOpen()，之后由父级 state 控制显隐。
 *
 * 冷却记录存 localStorage（lawver.upgradeNudge）：forever=true 永久关闭；
 * lastSeen 为上次展示/点击时刻，14 天内不再弹。
 */

import { useEffect, useRef } from "react";
import { UpgradeNudge } from "./UpgradeNudge";

const STORAGE_KEY = "lawver.upgradeNudge";
const COOLDOWN_MS = 14 * 24 * 3600 * 1000;

type Gate = { forever?: boolean; lastSeen?: number };

const readGate = (): Gate => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") as Gate;
  } catch {
    return {};
  }
};

const writeGate = (gate: Gate) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(gate));
  } catch {
    // 写不进（隐私模式等）只影响记忆，不影响本次展示。
  }
};

export function UpgradeNudgeGate({
  plan,
  balance,
  exempt,
  open,
  onOpen,
  onClose,
}: {
  plan?: string;
  balance: number | null;
  exempt: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: (options: { forever: boolean }) => void;
}) {
  // onOpen/onClose 存 ref：判定 effect 只依赖数据条件，不因回调身份反复执行。
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const eligible =
    balance != null && !exempt && plan !== "max" && plan !== "business" && balance <= 0;

  useEffect(() => {
    if (!eligible || open) return;
    const gate = readGate();
    if (gate.forever) return;
    if (gate.lastSeen && Date.now() - gate.lastSeen < COOLDOWN_MS) return;
    onOpenRef.current();
  }, [eligible, open]);

  const handleClose = (options: { forever: boolean }) => {
    const gate = readGate();
    writeGate({ forever: options.forever || Boolean(gate.forever), lastSeen: Date.now() });
    onCloseRef.current(options);
  };

  if (!open) return null;
  return <UpgradeNudge onClose={handleClose} />;
}
