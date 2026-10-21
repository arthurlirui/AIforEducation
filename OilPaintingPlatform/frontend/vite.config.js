import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Backend API base URL. In dev, the Vite proxy forwards /api and /files to the
// FastAPI server on port 8000, so the frontend can use relative URLs.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/files': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
