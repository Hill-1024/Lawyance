/*
 * 模块描述：Vite 构建与开发服务器配置，接入 React、Tailwind、路径别名和 API 代理。
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { readFileSync, writeFileSync } from 'fs'

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
const devServerPort = Number(process.env.LAWVER_VITE_PORT || 5173)
const devServerHost = process.env.LAWVER_VITE_HOST || '127.0.0.1'
const apiProxyTarget = process.env.LAWVER_API_PROXY_TARGET || 'http://localhost:8080'

/** 生产子路径。本地开发保持 /；挂到 global.lawver.dev/asean/ 时设为 /asean/。 */
const publicBase = (() => {
  const raw = (process.env.VITE_PUBLIC_BASE || '/').trim() || '/'
  if (raw === '/') return '/'
  const withLead = raw.startsWith('/') ? raw : `/${raw}`
  return withLead.endsWith('/') ? withLead : `${withLead}/`
})()
const buildEnvironment = process.env.LAWVER_BUILD_ENV
  || packageJson.appConfig?.environment
  || (process.env.NODE_ENV === 'production' ? 'Web/Vite' : 'Development')
const buildInfo = {
  appName: packageJson.metadata?.name || packageJson.name || 'Lawver',
  version: packageJson.version || '0.0.0',
  description: packageJson.description || '工大法智团队的中文法律 AI 助手原型',
  environment: buildEnvironment,
  buildTime: new Date().toLocaleString('zh-CN', { hour12: false }),
  projectUrl: packageJson.appConfig?.projectUrl || 'https://github.com/Meteor109/Lawyance',
}

// https://vitejs.dev/config/
export default defineConfig({
  base: publicBase,
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'lawver-public-base-manifest',
      apply: 'build',
      closeBundle() {
        const manifestPath = path.resolve(__dirname, 'dist/manifest.webmanifest')
        try {
          const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
          const prefix = (value: string) => {
            if (!value.startsWith('/') || publicBase === '/') return value
            return `${publicBase}${value.replace(/^\//, '')}`
          }
          manifest.id = publicBase
          manifest.start_url = publicBase
          manifest.scope = publicBase
          if (Array.isArray(manifest.icons)) {
            manifest.icons = manifest.icons.map((icon: { src?: string }) => ({
              ...icon,
              src: icon.src ? prefix(icon.src) : icon.src,
            }))
          }
          if (Array.isArray(manifest.shortcuts)) {
            manifest.shortcuts = manifest.shortcuts.map((item: { url?: string; icons?: { src?: string }[] }) => ({
              ...item,
              url: item.url ? prefix(item.url) : item.url,
              icons: item.icons?.map(icon => ({ ...icon, src: icon.src ? prefix(icon.src) : icon.src })),
            }))
          }
          writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
        } catch {
          /* 没有 manifest 时跳过，不影响构建 */
        }
      },
    },
  ],
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
