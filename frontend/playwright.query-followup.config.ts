import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testDir: './acceptance',
  testMatch: 'query-followup.spec.ts',
  use: { ...base.use, headless: true },
  webServer: {
    command: `npm run dev -- --port ${new URL(process.env.E2E_WEB_BASE!).port} --strictPort`,
    url: process.env.E2E_WEB_BASE!,
    env: { ...process.env, VITE_API_PROXY_TARGET: process.env.E2E_API_BASE! },
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
