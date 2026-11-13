import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const frontendPort = Number(process.env.FRONTEND_PORT ?? '5173');
const frontendHost = process.env.FRONTEND_HOST ?? '127.0.0.1';
const backendUrl = process.env.BACKEND_URL ?? `http://${process.env.SERVER_HOST ?? '127.0.0.1'}:${process.env.SERVER_PORT ?? '8081'}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: frontendHost,
    port: frontendPort,
    strictPort: true,
    proxy: { '/api': { target: backendUrl, changeOrigin: true } },
  },
});
