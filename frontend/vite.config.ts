import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

// Single source of the version shown in the UI: the VERSION file at the project root.
const appVersion = readFileSync(new URL('../VERSION', import.meta.url), 'utf-8').trim();

const frontendPort = Number(process.env.FRONTEND_PORT ?? '5173');
const frontendHost = process.env.FRONTEND_HOST ?? '127.0.0.1';
const backendUrl = process.env.BACKEND_URL ?? `http://${process.env.SERVER_HOST ?? '127.0.0.1'}:${process.env.SERVER_PORT ?? '8081'}`;

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    host: frontendHost,
    port: frontendPort,
    strictPort: true,
    proxy: { '/api': { target: backendUrl, changeOrigin: true } },
  },
  // ./start.sh (normal use) serves the built interface with «vite preview»: same address and the same /api proxy.
  preview: {
    host: frontendHost,
    port: frontendPort,
    strictPort: true,
    proxy: { '/api': { target: backendUrl, changeOrigin: true } },
  },
});
