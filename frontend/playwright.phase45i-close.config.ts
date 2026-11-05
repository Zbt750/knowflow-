import {defineConfig} from '@playwright/test';
if(process.env.PHASE45I_CLOSE_OFFLINE!=='1')throw new Error('Owned offline environment required');
export default defineConfig({
  testDir:'./e2e',testMatch:['phase45i-close-live.spec.ts','personal-question-bank.spec.ts'],
  workers:1,timeout:60000,retries:0,
  use:{baseURL:process.env.E2E_WEB_BASE,channel:'chrome',viewport:{width:1366,height:768},screenshot:'only-on-failure',trace:'retain-on-failure'},
  webServer:{command:`npm run dev -- --port ${process.env.PHASE45I_CLOSE_WEB_PORT}`,url:process.env.E2E_WEB_BASE!,
    env:{...process.env,VITE_API_PROXY_TARGET:process.env.E2E_API_BASE!},reuseExistingServer:false,timeout:60000},
});
