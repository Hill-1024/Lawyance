/*
 * 模块描述：前端 lint 配置。只管 React Hooks 的两条硬规则，类型检查仍由 tsc 负责（pnpm lint 两步都跑）。
 *
 * - rules-of-hooks：hook 必须在组件顶层、每次渲染以相同顺序调用（不能写在早退、条件或循环之后）。
 * - exhaustive-deps：effect / useCallback / useMemo 里读到的响应式值都要进依赖数组。
 *   不想让某个值触发重跑时，用 useEffectEvent 把那段逻辑拿出 effect，而不是从数组里删掉它。
 *
 * 两条都设为 error：这类问题不会在类型检查里暴露，只能靠 lint 在提交前拦住。
 */

import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default [
  { ignores: ['dist/**', 'android/**', 'node_modules/**'] },
  {
    files: ['frontend/src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
    },
  },
];
