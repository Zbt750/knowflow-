import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './acceptance', testMatch: process.env.BUSINESS_SPEC || 'business-turn.spec.ts', workers: 1, retries: 0,
  timeout: 60_000,
  outputDir: `${process.env.BUSINESS_AUDIT_DIR}/browser-artifacts`,
  reporter: [['list'], ['junit', { outputFile: `${process.env.BUSINESS_AUDIT_DIR}/browser-junit.xml` }]],
  use: {baseURL: process.env.E2E_WEB_BASE, channel:'chrome', headless:true,
    viewport:{width:1366,height:768}, screenshot:'only-on-failure', trace:'retain-on-failure'},
});
