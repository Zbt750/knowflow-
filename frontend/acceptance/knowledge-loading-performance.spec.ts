import {test,expect} from '@playwright/test';

test('measure real isolated knowledge navigation without model or business writes',async({page},info)=>{
  expect(process.env.APP_ENV).toBe('test');
  const health=await (await page.request.get(process.env.E2E_API_BASE!+'/api/health')).json();
  expect(health.environment).toBe('test');
  const backend=await (await page.request.get(process.env.E2E_API_BASE!+'/api/test/knowledge-benchmark')).json();
  await info.attach('backend-performance',{body:JSON.stringify(backend,null,2),contentType:'application/json'});
  const measurements:any[]=[];const requests:string[]=[];const errors:string[]=[];
  // Keep the same network guard as the baseline. Playwright routing disables
  // browser HTTP caching, so before/after UI timings compare the same setting.
  await page.route('**/api/**',route=>{
    const request=route.request();if(request.method()!=='GET'){errors.push('unexpected write '+request.url());return route.abort();}
    requests.push(new URL(request.url()).pathname);return route.continue();
  });
  page.on('pageerror',error=>errors.push(error.message));
  for(const kind of ['first','refresh','return']){
    const before=requests.length;let start=0;
    if(kind==='first'){start=Date.now();await page.goto('/knowledge');}
    else if(kind==='refresh'){start=Date.now();await page.reload();}
    else{await page.getByRole('link',{name:'设置',exact:true}).click();await expect(page).toHaveURL(/settings/);start=Date.now();await page.getByRole('link',{name:'知识树',exact:true}).click();}
    await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
    await expect(page.locator('.canvas-node-name')).toHaveCount(3);
    const visible=Date.now()-start;
    await page.locator('.canvas-toggle').first().click();
    await expect(page.locator('.canvas-node-name')).not.toHaveCount(3);
    const interactive=Date.now()-start;
    await page.getByRole('button',{name:'收起分支',exact:true}).click();
    await expect(page.locator('.canvas-node-name')).toHaveCount(3);
    // Allow background revalidation to settle before accounting for requests.
    await page.waitForLoadState('networkidle');
    measurements.push({kind,visible_ms:visible,interactive_ms:interactive,
      tree_requests:requests.slice(before).filter(p=>p==='/api/knowledge/tree').length,
      detail_requests:requests.slice(before).filter(p=>/^\/api\/knowledge\/[0-9a-f-]+$/.test(p)).length});
  }
  await info.attach('navigation-performance',{body:JSON.stringify(measurements,null,2),contentType:'application/json'});
  const initial=await page.request.get(process.env.E2E_API_BASE!+'/api/knowledge/tree');
  const conditional=await page.request.get(process.env.E2E_API_BASE!+'/api/knowledge/tree',{headers:{'If-None-Match':initial.headers()['etag']}});
  expect(conditional.status()).toBe(304);expect((await conditional.body()).length).toBe(0);
  await page.getByTestId('knowledge-search').fill('TEST_PERF.topic.000');
  await expect(page.getByTestId('tree-node-TEST_PERF.topic.000')).toBeVisible();
  await page.getByTestId('tree-node-TEST_PERF.topic.000').click();
  await expect(page.getByTestId('detail-title')).toHaveText('隔离性能知识点000');
  await expect(page.getByTestId('knowledge-assistant-link')).toHaveAttribute('href',/knowledge_node_id=/);
  await page.screenshot({path:info.outputPath('desktop-knowledge.png')});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'收起分支',exact:true}).click();
  await page.getByRole('button',{name:'清除搜索',exact:true}).click();
  await expect(page.locator('.canvas-node-name')).toHaveCount(3);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await expect(page.locator('.frog-tree-figure')).toBeAttached();
  await page.screenshot({path:info.outputPath('mobile-knowledge.png'),fullPage:true});
  expect(errors).toEqual([]);
  await info.attach('performance',{body:JSON.stringify({backend,measurements,errors},null,2),contentType:'application/json'});
  console.log('KNOWLEDGE_PERFORMANCE '+JSON.stringify({backend,measurements}));
});
