import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Local dev: frontend on :5174, API on :8001 (`npm run dev` needs no flags).
    port: 5174,
    strictPort: true,
    proxy: {
      // Dev-time proxy so the frontend can call relative /api/... paths with
      // no CORS setup and no baseURL config - the same origin layout as
      // production, where the API serves the built files itself
      // (serve_frontend in api/app.py).
      '/api': {
        // Override with MARKETMYNA_API=http://127.0.0.1:<port> npm run dev.
        target: process.env.MARKETMYNA_API ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
