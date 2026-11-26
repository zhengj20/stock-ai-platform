import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import http from 'http'

// 复用连接，减少 ECONNRESET
const keepAliveAgent = new http.Agent({ keepAlive: true, maxSockets: 20 })

export default defineConfig({
  plugins: [vue()],
  build: { sourcemap: true },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    // 允许花生壳等外网穿透域名访问（域名可能更换，如 *.vicp.fun/*.vica.pw/*.h3xs.com，直接放开）
    allowedHosts: true,
    proxy: {
      '/sim-trading': {
        target: 'http://localhost:5174',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sim-trading/, '/api/v1/sim-trading'),
        timeout: 300000,
        agent: keepAliveAgent,
      },
      '/api': {
        target: 'http://localhost:5174',
        changeOrigin: true,
        timeout: 300000,
        agent: keepAliveAgent,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              delete proxyRes.headers['content-length']
            }
          })

          proxy.on('error', (err, req, res) => {
            console.error(`[vite] proxy error: ${req.url} - ${err.code}`)
            
            // ECONNRESET 自动重试（uvicorn --reload 重启时常见）
            if (!res.headersSent && err.code === 'ECONNRESET') {
              const retryCount = parseInt(req.headers['x-retry-count'] || '0')
              if (retryCount < 3) {
                req.headers['x-retry-count'] = String(retryCount + 1)
                console.log(`[vite] ECONNRESET retry ${retryCount + 1}/3: ${req.url}`)
                setTimeout(() => {
                  if (res.headersSent) return
                  
                  const retryReq = http.request({
                    hostname: 'localhost',
                    port: 8000,
                    path: req.url,
                    method: req.method,
                    headers: req.headers,
                  }, (retryRes) => {
                    if (!res.headersSent) {
                      res.writeHead(retryRes.statusCode, retryRes.headers)
                      retryRes.pipe(res)
                    }
                  }).on('error', () => {
                    if (!res.headersSent) {
                      res.writeHead(502)
                      res.end(JSON.stringify({ error: '后端连接重置，请刷新重试' }))
                    }
                  })
                  
                  req.pipe(retryReq)
                }, 1000 * (retryCount + 1))
                return
              }
            }
            
            if (!res.headersSent) {
              res.writeHead(502)
              res.end(JSON.stringify({
                error: '后端连接重置，请刷新重试',
                detail: '后端可能正在处理大量数据请求'
              }))
            }
          })
        },
      },
    },
  },
})
