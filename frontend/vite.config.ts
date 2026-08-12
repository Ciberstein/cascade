/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The SPA and the API are same-origin in production (the compose stack puts
    // both behind one host), so the app calls the backend's routes as plain
    // relative paths. In dev, Vite serves the SPA on its own port - this proxy
    // forwards those same paths to the backend so no build-time base URL is
    // needed. Mirrors the router prefixes registered in backend/app/main.py;
    // ws:true covers the /ws progress socket's upgrade handshake.
    proxy: Object.fromEntries(
      ['/account', '/packages', '/settings', '/crawl-jobs', '/health', '/ws'].map((path) => [
        path,
        { target: 'http://localhost:8000', changeOrigin: true, ws: true },
      ]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
})
