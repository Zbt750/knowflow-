import {defineConfig} from '@playwright/test';
import base from './playwright.query-followup.config';
export default defineConfig({...base,testMatch:'scope-math.spec.ts',expect:{timeout:30000},use:{...base.use,headless:false}});
