const {createRequire}=require('node:module'),path=require('node:path'),fs=require('node:fs');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL,results=[];
async function main(){const browser=await chromium.launch({channel:'chrome',headless:true});const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},storageState:path.join(out,'browser-state.json')});const page=await ctx.newPage();
 const write=()=>fs.writeFileSync(path.join(out,'free-ui-results.json'),JSON.stringify(results,null,2));
 try{
  await page.goto('/materials');const answers=page.getByTestId('material-search-assistant');await expect(answers).toHaveCount(4);await expect(answers.last().locator('.katex')).not.toHaveCount(0);await page.evaluate(()=>document.fonts.ready);await answers.last().scrollIntoViewIfNeeded();
  results.push({id:'RAG-math-restored',katex:await answers.last().locator('.katex').count(),errors:await answers.last().locator('.katex-error').count(),mathNotice:await answers.last().locator('.math-load-note').allTextContents(),text:await answers.last().innerText(),html:await answers.last().innerHTML()});write();await page.screenshot({path:path.join(out,'RAG-math-settled.png'),fullPage:true});
  const qa=JSON.parse(fs.readFileSync(path.join(out,'browser-results.json'),'utf8')).find(r=>r.id==='QA1').session_id;
  await page.goto('/chat?session_id='+qa);await expect(page.locator('.message-row--assistant')).toHaveCount(2);const toggles=page.getByRole('button',{name:'展开完整回答',exact:true});while(await toggles.count())await toggles.first().click();
  await expect(page.locator('.message-row--assistant').last().locator('.katex')).not.toHaveCount(0);await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(out,'QA-expanded-settled.png'),fullPage:true});results.push({id:'QA-restored-render',katex:await page.locator('.message-row--assistant .katex').count(),errors:await page.locator('.katex-error').count(),notices:await page.locator('.math-load-note').allTextContents()});write();
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'QA-mobile.png'),fullPage:true});results.push({id:'mobile',overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});write();
 }finally{write();await browser.close();}}
main().catch(e=>{results.push({status:'BLOCKED',error:e.stack});fs.writeFileSync(path.join(out,'free-ui-results.json'),JSON.stringify(results,null,2));process.exitCode=1;});
