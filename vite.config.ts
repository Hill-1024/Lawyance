/*
 * 模块描述：Vite 构建与开发服务器配置，接入 React、Tailwind、路径别名、API 代理和区域路径前缀。
 */

import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { readFileSync } from 'fs'

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
const appConfig = packageJson.appConfig || {}
const appDomain = appConfig.domain || 'cn.lawver.dev'
const appOrigin = `https://${appDomain}`
const nativeApiBase = appConfig.nativeApiBase || appOrigin
const appRegions: string[] = Array.isArray(appConfig.regions)
  ? appConfig.regions.map((region: unknown) => String(region)).filter(Boolean)
  : []
const devServerPort = Number(process.env.LAWVER_VITE_PORT || appConfig.devPort || 5173)
const devServerHost = process.env.LAWVER_VITE_HOST || '127.0.0.1'
const apiProxyTarget = process.env.LAWVER_API_PROXY_TARGET || `http://localhost:${appConfig.port || 8080}`
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

/**
 * 区域路径前缀由网关按 /cn、/asean 等前缀分流，浏览器地址栏保留前缀，而应用自身只认识
 * /、/settings 等路由。资源引用与运行时前缀都依赖 <base>，而 <base> 必须由网关注入到
 * HTML 里（运行时用脚本插入会晚于浏览器预加载扫描器，导致资源被重复请求到默认区域）。
 */
const regionBasePathWarning = () => `(function(){var r=${JSON.stringify(appRegions)};var s=location.pathname.split('/')[1]||'';if(r.indexOf(s)===-1)return;if(document.querySelector('base'))return;console.warn('[Lawver] 检测到区域前缀 /'+s+' 但网关未注入 <base>：静态资源会请求到默认区域，请在 Worker 中注入 <base href="/'+s+'/">。');})();`

const regionBasePathPlugin = (): Plugin => ({
  name: 'lawver-region-base-path',
  transformIndexHtml: {
    order: 'pre',
    handler: () => [
      {
        tag: 'script',
        children: regionBasePathWarning(),
        injectTo: 'body',
      },
    ],
  },
})

// https://vitejs.dev/config/
export default defineConfig({
  // 相对资源路径：实际基准由网关注入的 <base> 决定，根路径与前缀部署共用同一份产物。
  base: './',
  plugins: [react(), tailwindcss(), regionBasePathPlugin()],
  define: {
    __LAWVER_BUILD_INFO__: JSON.stringify(buildInfo),
    __LAWVER_APP_CONFIG__: JSON.stringify({ domain: appDomain, origin: appOrigin, nativeApiBase }),
    __LAWVER_REGIONS__: JSON.stringify(appRegions),
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
