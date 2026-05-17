/*
 * 模块描述：Vite 构建与开发服务器配置，接入 React、Tailwind、路径别名和 API 代理。
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 8080,
    strictPort: true,
    host: '0.0.0.0',
    watch: {
      ignored: ['**/sessions.json', '**/titles.json'],
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  }
})
