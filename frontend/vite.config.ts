import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

export default defineConfig({
  plugins: [react(), {
    name: 'dev-only-msw-worker',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/mockServiceWorker.js', (_request, response) => {
        response.setHeader('Content-Type', 'application/javascript');
        response.end(readFileSync(new URL('./node_modules/msw/lib/mockServiceWorker.js', import.meta.url)));
      });
    },
  }],
  publicDir: false,
  server: { host: '127.0.0.1', proxy: { '/api': 'http://localhost:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.{ts,tsx}'] },
});
