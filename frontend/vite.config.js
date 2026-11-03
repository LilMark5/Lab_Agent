import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置文件：开发时提供 @ 别名和 /api、/uploads 代理。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    // 默认端口为什么不是 5173：
    // Radmin VPN 的 RvControlSvc 会以 Bound 状态预占 5173/5174 等一批端口，
    // 此时 Vite 绑定端口会直接抛 EACCES（而不是 EADDRINUSE），
    // Vite 的「端口被占就自动 +1」对 EACCES 不生效，于是启动直接失败。
    // 5175 目前不在 Radmin 的占用列表里；若将来又被占，改这个数字即可。
    port: 5175,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            // 关闭 SSE 代理缓冲，让过程事件实时到浏览器。
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        }
      },
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
