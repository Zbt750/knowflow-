import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// This journey needs its own fixed-provider backend and owned PostgreSQL.
// Keep it separate from the ordinary suite rather than skipping it there.
export default defineConfig({
  ...base,
  testDir: './acceptance',
  testMatch: ['generation-conversation-persistence.spec.ts','generation-quantity.spec.ts','zero-paid-learning-loop.spec.ts'],
  webServer: {
    command:`npm run dev -- --port ${new URL(process.env.E2E_WEB_BASE ?? 'http://127.0.0.1:5174').port} --strictPort`,
    url:process.env.E2E_WEB_BASE ?? 'http://127.0.0.1:5174',
    env:{...process.env,VITE_API_PROXY_TARGET:process.env.E2E_API_BASE ?? 'http://127.0.0.1:8001'},
    reuseExistingServer:false,
    timeout:120_000,
  },
});
