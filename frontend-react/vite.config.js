import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://yt-api:8001',
        changeOrigin: true,
      },
    },
  },
})
