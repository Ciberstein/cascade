/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The SPA and the API are same-origin in production (the compose stack puts
    // them behind one host), so the app calls relative /api paths. In dev, Vite
    // serves the SPA on its own port - this proxy keeps those same relative
    // paths working, including the WebSocket upgrade for live progress.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
})
