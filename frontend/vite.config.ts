/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The FastAPI backend (uvicorn artlab.api:app --port 8000)
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // Vitest (`npm test`) reads this block. jsdom is a fake browser DOM in Node, so React components
  // can render and be clicked in tests without a real browser.
  test: {
    environment: 'jsdom',
  },
})
