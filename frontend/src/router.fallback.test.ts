import {expect,it,vi} from 'vitest';
vi.mock('vue-router',async original=>{const real=await original<typeof import('vue-router')>();return {...real,createWebHistory:()=>real.createMemoryHistory()};});
import {router} from './router';
it.each(['/study','/chat','/knowledge','/materials','/settings'])('keeps valid route %s',path=>{
 expect(router.resolve(path).name).not.toBe('not-found');expect(router.resolve(path).matched.at(-1)?.path).toBe(path);
});
it('unknown routes have their own page and retain the original address',async()=>{
 await router.push('/this-route-does-not-exist-xyz');expect(router.currentRoute.value.name).toBe('not-found');
 expect(router.currentRoute.value.path).toBe('/this-route-does-not-exist-xyz');
});
