import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // The backend needs no CORS change: the dev server is the origin.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // SSE has to stream through unbuffered.
        ws: false,
      },
    },
  },
});
