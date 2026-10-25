import { defineConfig, devices } from '@playwright/test';

// D1–D3 browser acceptance uses explicit MSW. Real-backend E2E belongs to D4.
export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  use: { baseURL: 'http://127.0.0.1:5179', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'chromium' } }],
});
