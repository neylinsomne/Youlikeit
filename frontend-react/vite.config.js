import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api/clips': 'http://localhost:3100',
      '/api/categories': 'http://localhost:3100',
      '/api/series': 'http://localhost:3100',
      '/api/quotes': 'http://localhost:3100',
      '/api/render': 'http://localhost:3100',
      '/api/pipeline': 'http://localhost:8001',
      '/api/movies': 'http://localhost:8001',
      '/api/shorts': 'http://localhost:8001',
      '/api/analytics': 'http://localhost:8001',
      '/api/manga': 'http://localhost:8001',
      '/api/knowledge': 'http://localhost:8001',
      '/api/curriculum': 'http://localhost:8001',
      '/api/status': 'http://localhost:8001',
      '/files': 'http://localhost:3100',
      '/panels': 'http://localhost:3100',
    },
  },
})
