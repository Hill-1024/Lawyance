/*
 * 模块描述：Vite 构建与开发服务器配置，接入 React、Tailwind、路径别名和 API 代理。
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { readFileSync } from 'fs'

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
const devServerPort = Number(process.env.LAWVER_VITE_PORT || 5173)
const devServerHost = process.env.LAWVER_VITE_HOST || '127.0.0.1'
const apiProxyTarget = process.env.LAWVER_API_PROXY_TARGET || 'http://localhost:8080'
const buildEnvironment = process.env.LAWVER_BUILD_ENV
  || packageJson.appConfig?.environment
  || (process.env.NODE_ENV === 'production' ? 'Web/Vite' : 'Development')
const buildInfo = {
  appName: packageJson.metadata?.name || packageJson.name || 'Lawver',
  version: packageJson.version || '0.0.0',
  description: packageJson.description || '工大法智团队的中文法律 AI 助手原型',
  environment: buildEnvironment,
  buildTime: new Date().toLocaleString('zh-CN', { hour12: false }),
  projectUrl: packageJson.appConfig?.projectUrl || 'https://github.com/Hill-1024/Lawyance',
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __LAWVER_BUILD_INFO__: JSON.stringify(buildInfo),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: devServerPort,
    strictPort: true,
    host: devServerHost,
    watch: {
      ignored: ['**/sessions.json', '**/titles.json'],
    },
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  }
})
