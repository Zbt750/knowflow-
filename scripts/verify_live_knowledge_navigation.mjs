// Actual 5173 Vue + actual 8000 API, strictly GET-only. No model, no DB writes.
import {createRequire} from 'node:module';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const output=resolve('storage/quality-audits/knowledge-navigation-20261019/live-readonly');mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const result={status:'RUNNING',checks:[],errors:[],business_writes:0,model_calls:0};
function paths(nodes,path=[]){return nodes.flatMap(node=>[[...path,node],...paths(node.children,[...path,node])]);}
try{
  for(const width of [1366,390]){
    const context=await browser.newContext({viewport:{width,height:width===390?844:768},reducedMotion:'reduce'});
    await context.route(url=>url.origin==='http://127.0.0.1:5173' && url.pathname.startsWith('/api/'),async route=>{
      if(route.request().method()==='GET')return route.continue();
      result.errors.push('Unexpected non-GET blocked: '+new URL(route.request().url()).pathname);return route.abort();
    });
    const page=await context.newPage();page.on('pageerror',error=>result.errors.push(error.message));
    const response=await context.request.get('http://127.0.0.1:8000/api/knowledge/tree');expect(response.ok()).toBe(true);
    const data=await response.json();
    const candidates=paths(data.nodes).filter(path=>path.length>=3 && path.at(-1).is_assessable && !path.at(-1).children.length && !path.some(n=>n.code.includes('.family.')||n.name.startsWith('专题汇总')));
    expect(candidates.length).toBeGreaterThan(0);const target=candidates[0].at(-1);
    await page.goto('http://127.0.0.1:5173/knowledge');
    await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
    await expect(page.locator('.frog-tree-figure')).toBeAttached();
    await expect(page.locator('.frog-tree-mascot')).toBeAttached();
    const roots=data.nodes;
    expect(roots).toHaveLength(3);
    await expect(page.locator('[role=treeitem][aria-expanded=true]')).toHaveCount(0);
    for(const root of roots){
      await expect(page.getByTestId(`tree-node-${root.code}`)).toBeVisible();
      await expect(page.getByTestId(`tree-node-${root.code}`).locator('xpath=../..')).toHaveAttribute('aria-expanded','false');
      for(const child of root.children)await expect(page.getByTestId(`tree-node-${child.code}`)).toHaveCount(0);
    }
    if(width===390)for(const root of roots)await expect(page.getByTestId(`tree-node-${root.code}`)).toBeInViewport({ratio:.8});
    await expect(page.locator('.canvas-branches path.frog-limb')).toHaveCount(roots.length);
    await expect(page.locator('.canvas-branches path.frog-toe')).toHaveCount(0);
    const firstRootRow=page.getByTestId(`tree-node-${roots[0].code}`).locator('xpath=../..');
    await firstRootRow.locator('.canvas-toggle').click();
    await expect(page.getByTestId(`tree-node-${roots[0].children[0].code}`)).toBeVisible();
    // SVG connector paths can have a zero-height bounding box, so Playwright's
    // visibility heuristic reports them hidden even while the branch is drawn.
    expect(await page.locator('.canvas-branches path.frog-toe').count()).toBeGreaterThan(0);
    await firstRootRow.locator('.canvas-toggle').click();
    await expect(page.locator('.canvas-branches path.frog-toe')).toHaveCount(0);
    await page.screenshot({path:resolve(output,`actual-canvas-collapsed-${width}.png`),fullPage:true});
    await page.getByTestId('knowledge-search').fill(target.code);
    const title=page.getByTestId(`tree-node-${target.code}`);await expect(title).toBeVisible();await title.click();
    await expect(page.getByTestId('detail-title')).toHaveText(target.name);
    await expect(page.getByTestId('knowledge-assistant-link')).toHaveAttribute('href',new RegExp(`knowledge_node_id=${target.id}`));
    await expect(page.getByTestId(`tree-joint-${target.id}`)).toBeVisible();
    await page.getByRole('button',{name:'清除搜索',exact:true}).click();
    await expect(page.locator('[role=treeitem][aria-expanded=true]')).toHaveCount(0);
    await expect(page.getByTestId(`tree-node-${target.code}`)).toHaveCount(0);
    await page.goto(`http://127.0.0.1:5173/knowledge?node=${encodeURIComponent(target.code)}`);
    await expect(title).toBeVisible();await expect(page.getByTestId('detail-title')).toHaveText(target.name);
    if(width===390)await expect(page.getByTestId('detail-title')).toBeInViewport({ratio:.8});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await page.screenshot({path:resolve(output,`actual-canvas-selected-${width}.png`),fullPage:true});
    await page.screenshot({path:resolve(output,`actual-viewport-${width}.png`)});
    await page.reload();await expect(page.getByTestId('detail-title')).toHaveText(target.name);
    result.checks.push({viewport:width,target_code:target.code,target_id:target.id,ninja_frog_attached:true,toe_branch_paths:true,top_level_roots_visible:roots.length,all_children_folded:true,search:true,deep_link:true,refresh:true,no_horizontal_overflow:true});
    await context.close();
  }
  expect(result.errors).toEqual([]);result.status='PASS_ACTUAL_APP_READONLY';
}catch(error){result.status='FAILED';result.errors.push(String(error));process.exitCode=1;}
finally{writeFileSync(resolve(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();}
