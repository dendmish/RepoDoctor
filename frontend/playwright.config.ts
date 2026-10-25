import { defineConfig, devices } from '@playwright/test';

// D1 browser smoke uses explicit MSW. Real-backend E2E belongs to D4.
export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  use: { baseURL: 'http://127.0.0.1:5179', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chromium' } }],
});
