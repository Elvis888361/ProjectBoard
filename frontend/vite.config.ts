/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy /api to the backend so the browser sees ONE origin in dev.
    //
    // This isn't a convenience -- it's what makes the auth design work. The session is
    // an httpOnly cookie (forced on us by EventSource, which cannot send an
    // Authorization header). Same-origin means the cookie is sent automatically, there
    // is no CORS preflight, no `allow_credentials`, and SameSite=Lax behaves in dev
    // exactly as it does in prod. Dev and prod differ in as few ways as I could manage.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.ts',
  },
})
