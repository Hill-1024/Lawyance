/*
 * 模块描述：构建时应用信息入口，由 Vite define 注入版本、环境和构建时间。
 */

export interface LawverBuildInfo {
  appName: string;
  version: string;
  description: string;
  environment: string;
  buildTime: string;
  projectUrl: string;
}

declare const __LAWVER_BUILD_INFO__: LawverBuildInfo | undefined;

const FALLBACK_BUILD_INFO: LawverBuildInfo = {
  appName: 'Lawver',
  version: '0.0.0',
  // 仅作为构建元数据（构建脚本会覆盖）；界面上显示的是 settings.about.description 词条。
  description: 'Lawver',
  environment: 'Development',
  buildTime: 'unknown',
  projectUrl: 'https://github.com/Hill-1024/Lawyance',
};

export const BUILD_INFO: LawverBuildInfo = typeof __LAWVER_BUILD_INFO__ !== 'undefined'
  ? __LAWVER_BUILD_INFO__
  : FALLBACK_BUILD_INFO;
