import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '..')
const HOST = '127.0.0.1'
const PORT = 5180

/**
 * El Estudio corre SOLO en 127.0.0.1. El token del backend (STUDIO_TOKEN) se lee
 * del .env de la raíz del repo y lo inyecta el proxy: nunca llega al JS del navegador
 * (no usa el prefijo VITE_, así que Vite no lo expone).
 */
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, REPO_ROOT, '')
  const target = env.STUDIO_API_URL || `http://127.0.0.1:${env.STUDIO_PORT || 8001}`
  const token = env.STUDIO_TOKEN || ''

  if (!token && command === 'serve') {
    console.warn(
      '\n[estudio] STUDIO_TOKEN no está en el .env de la raíz: la API responderá 401.\n' +
        '          Genera uno (ylk studio lo crea al instalar) y reinicia `npm run dev`.\n',
    )
  }

  const allowedOrigins = new Set([`http://${HOST}:${PORT}`, `http://localhost:${PORT}`])

  // El proxy agrega credenciales, así que solo atiende peticiones de la propia página:
  // bloquea otras pestañas/sitios (incluidos otros servidores locales en otro puerto).
  const sameOriginOnly = (req, res) => {
    const site = req.headers['sec-fetch-site']
    const origin = req.headers.origin
    const crossSite = (site && site !== 'same-origin' && site !== 'none') ||
      (origin && !allowedOrigins.has(origin))
    if (!crossSite) return undefined
    if (!res) return false // WebSocket: Vite responde 404 y corta el socket
    res.writeHead(403, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ detail: 'Origen no permitido: el estudio solo acepta peticiones de su propia página.' }))
    return req.url
  }

  // Si la API no está corriendo, respondemos 503 con un detalle claro (Vite usaría 502,
  // que en el contrato significa "falla externa" y confundiría a la UI).
  const offlineAsJson = (proxy) => {
    proxy.on('error', (_err, _req, res) => {
      if (!res || !('req' in res) || res.headersSent || res.writableEnded) return
      res.writeHead(503, { 'Content-Type': 'application/json', 'X-Studio-Proxy': 'offline' })
      res.end(JSON.stringify({ detail: `La API del estudio no responde en ${target}.` }))
    })
  }

  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const proxy = {
    '/api': { target, changeOrigin: true, headers, bypass: sameOriginOnly, configure: offlineAsJson },
    '/ws': { target, changeOrigin: true, ws: true, headers, bypass: sameOriginOnly, configure: offlineAsJson },
  }

  return {
    plugins: [react(), tailwindcss()],
    server: { host: HOST, port: PORT, strictPort: true, proxy },
    preview: { host: HOST, port: PORT, strictPort: true, proxy },
  }
})
