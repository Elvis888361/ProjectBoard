/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,

    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // Keep the browser's Host (localhost:5173) so the backend sees the request as
        // same-origin. changeOrigin:true would rewrite it to the target and trip the
        // CSRF origin check.
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.ts',
  },
})
