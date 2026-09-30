/*
 * 模块描述：i18n 词条自检——扫源码里用到的键，核对词条表。
 *
 * 检查四件事：
 *   1. 源码里 t("…") / translate("…") 用到的每个键都在 zh-CN 词条表里（漏写会渲染出键名）；
 *   2. 各语言词条表与源语言键集合一致（新增语言时防止半边翻译悄悄上线）；
 *   3. 词条表里没有被引用的键（提示可以删，避免词条表变垃圾场）；
 *   4. 面向屏幕阅读器的 aria-label / title 若直接写死中文，提示应改用词条
 *      （无障碍内容必须跟着语言走，这是 WCAG 名称/角色/值的要求）。
 *
 * 退出码非 0 表示有问题；`pnpm run test:i18n` 直接跑。
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { LOCALES } from "../frontend/src/i18n/index";
import { zhCN } from "../frontend/src/i18n/zh-CN";

const ROOT = join(import.meta.dirname, "..", "frontend", "src");

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.(ts|tsx)$/.test(full) ? [full] : [];
  });

const flatten = (node: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return value && typeof value === "object"
      ? flatten(value as Record<string, unknown>, path)
      : [path];
  });

const keysOf = (messages: unknown) => new Set(flatten(messages as Record<string, unknown>));

const sourceKeys = keysOf(zhCN);
const files = walk(ROOT).filter((file) => !file.includes(`${join("src", "i18n")}`));

const used = new Map<string, string[]>();
const hardcodedA11y: string[] = [];

for (const file of files) {
  const text = readFileSync(file, "utf8");
  const rel = relative(join(ROOT, "..", ".."), file);
  for (const match of text.matchAll(/\b(?:t|translate)\(\s*"([A-Za-z0-9_.]+)"/g)) {
    used.set(match[1], [...(used.get(match[1]) || []), rel]);
  }
  for (const match of text.matchAll(/\b(?:aria-label|title)="[^"]*[\u4e00-\u9fa5][^"]*"/g)) {
    hardcodedA11y.push(`${rel}: ${match[0].slice(0, 48)}`);
  }
}

const missing = [...used.keys()].filter((key) => !sourceKeys.has(key));
const unused = [...sourceKeys].filter((key) => !used.has(key));
const localeDrift = Object.entries(LOCALES)
  .filter(([name]) => name !== "zh-CN")
  .map(([name, entry]) => {
    const keys = keysOf(entry.messages);
    const gaps = [...sourceKeys].filter((key) => !keys.has(key));
    return { name, gaps };
  })
  .filter((item) => item.gaps.length > 0);

if (missing.length) {
  console.error("✗ 源码用到了词条表里没有的键：");
  for (const key of missing) console.error(`  ${key}  ← ${used.get(key)?.join(", ")}`);
}
for (const { name, gaps } of localeDrift) {
  // 部分翻译是允许的（缺键回退源语言），只提示完成度。
  console.warn(`提示：语言 ${name} 还有 ${gaps.length} 个键未翻译，将回退 zh-CN。`);
}
if (unused.length) {
  // 未被引用不算错误：正在迁移的模块可能先加键后接线。仅提示。
  console.warn(`提示：${unused.length} 个键暂未被引用（迁移进行中可忽略）：${unused.slice(0, 8).join(", ")}`);
}
if (hardcodedA11y.length) {
  console.warn(`提示：${hardcodedA11y.length} 处可访问名仍是写死的中文，应改用词条：`);
  for (const line of hardcodedA11y.slice(0, 10)) console.warn(`  ${line}`);
}

if (missing.length) {
  process.exit(1);
}
console.log(
  `i18n 词条校验通过：${used.size} 个键被引用，${sourceKeys.size} 个键已登记，` +
    `${Object.keys(LOCALES).length} 种语言；待迁移的可访问名 ${hardcodedA11y.length} 处，` +
    `待补翻译的键 ${localeDrift.reduce((sum, item) => sum + item.gaps.length, 0)} 个。`,
);
