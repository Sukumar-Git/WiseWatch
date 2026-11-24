import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'serve-onnx',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/yolov8n.onnx') {
            const file = path.resolve('yolov8n.onnx')
            if (fs.existsSync(file)) {
              res.setHeader('Content-Type', 'application/octet-stream')
              return fs.createReadStream(file).pipe(res)
            }
          }
          next()
        })
      }
    }
  ],
  server: { proxy: { '/api': 'http://localhost:8000', '/thumbs': 'http://localhost:8000' } }
})
