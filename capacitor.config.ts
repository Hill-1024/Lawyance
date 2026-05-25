/*
 * 模块描述：Capacitor 原生客户端配置，固定应用标识、静态产物目录和基础插件选项。
 */

import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'moe.mutsumi.lawver',
  appName: 'Lawver',
  webDir: 'dist',
  server: {
    androidScheme: 'https',
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: false,
    },
  },
};

export default config;
