import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: 'frontend',
  publicDir: resolve(__dirname, 'public'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/recommend': 'http://127.0.0.1:8000',
      '/generate': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/summary': 'http://127.0.0.1:8000',
      '/analytics': 'http://127.0.0.1:8000',
      '/benchmark': 'http://127.0.0.1:8000',
      '/feedback': 'http://127.0.0.1:8000',
      '/history': 'http://127.0.0.1:8000',
      '/replay': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/config': 'http://127.0.0.1:8000',
      '/prompt': 'http://127.0.0.1:8000',
      '/docs': 'http://127.0.0.1:8000',
      '/openapi.json': 'http://127.0.0.1:8000',
    },
  },
});
