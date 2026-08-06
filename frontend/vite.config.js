import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': {
                // FastAPI binds to IPv4 in local development. Using the
                // explicit loopback address avoids localhost resolving to
                // ::1 when the API is not listening on IPv6.
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
                // Timeout settings for large file uploads (10 minutes)
                timeout: 600000,
                proxyTimeout: 600000,
                // Handle large request bodies
                configure: (proxy, options) => {
                    proxy.on('proxyReq', (proxyReq, req, res) => {
                        // Remove content-length limit issues
                        if (req.headers['content-length']) {
                            proxyReq.setHeader('content-length', req.headers['content-length'])
                        }
                    })
                    proxy.on('error', (err, req, res) => {
                        console.error('Proxy error:', err)
                    })
                }
            },
            '/health': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
        },
    },
})
