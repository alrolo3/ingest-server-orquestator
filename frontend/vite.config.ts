import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const INGEST_API_TARGET =
  process.env.VITE_INGEST_API_URL ||
  process.env.VITE_API_URL ||
  'http://localhost:8000';

const apiProxy = {
  '/api': {
    target: INGEST_API_TARGET,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    host: true, // Allow external connections
    proxy: apiProxy,
  },
  preview: {
    port: 3000,
    host: true, // Allow external connections for preview mode too
    proxy: apiProxy,
  },
});
