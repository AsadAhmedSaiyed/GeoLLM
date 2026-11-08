import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// FastAPI (web_app.py) runs on this address. All backend routes are proxied
// during development so the new UI talks to the exact same, unchanged backend.
const BACKEND = 'http://127.0.0.1:8000';

export default defineConfig(({ command }) => ({
  plugins: [react()],

  // Production assets are served by FastAPI's existing `/static` mount,
  // so the built app lives at /static/dist/ (no backend change needed).
  base: command === 'build' ? '/static/dist/' : '/',

  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
    },
  },

  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // REST + SSE (/api/tasks/{id}/stream). SSE streams pass through unbuffered.
      '/api': { target: BACKEND, changeOrigin: true },
      // Generated run artifacts and input datasets (static mounts in web_app.py).
      '/runs': { target: BACKEND, changeOrigin: true },
      '/data': { target: BACKEND, changeOrigin: true },
    },
  },

  build: {
    // Output OUTSIDE frontend/ into static/dist. Old UI files in static/js and
    // static/css are never touched; only this dist folder is rebuilt.
    outDir: path.resolve(import.meta.dirname, '../static/dist'),
    emptyOutDir: true,
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('maplibre-gl')) return 'vendor-maplibre';
            if (id.includes('three')) return 'vendor-three';
            if (id.includes('react/') || id.includes('react-dom/')) return 'vendor-react';
            if (
              id.includes('lucide-react') ||
              id.includes('react-resizable-panels') ||
              id.includes('sonner') ||
              id.includes('marked')
            ) {
              return 'vendor-ui';
            }
          }
        },
      },
    },
  },
}));
