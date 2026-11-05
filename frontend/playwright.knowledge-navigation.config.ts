import {defineConfig} from '@playwright/test';
import base from './playwright.config';
// 所有 API 都由用例拦截。未预期 API 直接失败，绝不代理真实库或模型。
export default defineConfig({...base,testDir:'./acceptance',testMatch:'knowledge-navigation.spec.ts',
  outputDir:'../storage/quality-audits/knowledge-navigation-20261019/browser-artifacts',
  use:{...base.use,baseURL:'http://127.0.0.1:5193'},timeout:30_000,
  webServer:{command:'npm run dev -- --port 5193 --strictPort',url:'http://127.0.0.1:5193',
    env:{...process.env,VITE_API_PROXY_TARGET:'http://127.0.0.1:9'},reuseExistingServer:false}});
