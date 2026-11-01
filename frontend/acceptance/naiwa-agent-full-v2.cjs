/* Real system Chrome driver. Every chat is typed and sent through Vue controls.
 * This file never sends a chat by API and never substitutes a model response.
 */
const {chromium} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const ROOT = path.resolve(__dirname, '../..');
const OUT = path.join(ROOT, 'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021');
const RUN = path.join(ROOT, 'storage/manual-experience/naiwa-real-20261020/agent-full-v2-20261021');
const URL = 'http://127.0.0.1:63046';
const read = p => JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
const save = (p, v) => fs.writeFileSync(p, JSON.stringify(v, null, 2), 'utf8');
const emit = v => process.stdout.write(JSON.stringify(v) + '\n');
const append = (name, v) => fs.appendFileSync(path.join(OUT, name), JSON.stringify(v) + '\n', 'utf8');
let scene = null, step = 0;

(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:false,
    args:['--disable-background-networking']});
  const context = await browser.newContext({viewport:{width:1366,height:900}});
  await context.route('**/*', route => {
    const url = new globalThis.URL(route.request().url());
    if (['http:','https:'].includes(url.protocol) &&
        !(url.hostname === '127.0.0.1' && ['63045','63046'].includes(url.port))) return route.abort('blockedbyclient');
    return route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', error => append('browser-errors.jsonl', {time:Date.now(), type:'pageerror', message:String(error)}));
  page.on('console', message => {
    if (message.type() === 'error') append('browser-errors.jsonl', {time:Date.now(),type:'console',message:message.text()});
  });
  page.on('requestfailed', request => append('browser-network.jsonl', {
    time:Date.now(),method:request.method(),url:request.url(),failure:request.failure()}));
  page.on('response', response => {
    if (response.url().includes('/api/')) append('browser-network.jsonl', {
      time:Date.now(),method:response.request().method(),url:response.url(),status:response.status()});
  });
  async function snapshot(label) {
    const safe = String(label).replace(/[^A-Za-z0-9_-]/g,'_');
    const prefix = path.join(OUT, safe);
    const text = await page.locator('body').innerText();
    await page.screenshot({path:prefix+'.png',fullPage:true});
    const controls = await page.locator('textarea,input,button,summary,a').evaluateAll(nodes => nodes.filter(e => {
      const r=e.getBoundingClientRect(); return r.width > 0 && r.height > 0;
    }).map(e => ({tag:e.tagName,id:e.id,testid:e.getAttribute('data-testid'),
      aria:e.getAttribute('aria-label'),text:(e.innerText||'').slice(0,100),
      placeholder:e.getAttribute('placeholder'),disabled:!!e.disabled})).slice(-95));
    const state = {time:Date.now(),url:page.url(),scene,text,controls,
      katex:await page.locator('.katex').count(),katexErrors:await page.locator('.katex-error').count(),
      horizontalOverflow:await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+1)};
    save(prefix+'.json',state); return {screenshot:prefix+'.png',...state};
  }
  emit({ready:true,browser:'visible-system-chrome',version:browser.version(),pid:process.pid,modelRequestsTriggered:0});
  const input = readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  for await (const line of input) {
    if (!line.trim()) continue;
    let action;
    try {
      action=JSON.parse(line); step++;
      const label=action.label || `ui-${String(step).padStart(3,'0')}`;
      if (action.op==='scene') {
        scene=action.scene;
        await context.setExtraHTTPHeaders({'x-naiwa-v2-scene':scene,
          'x-naiwa-v2-nonce':fs.readFileSync(path.join(RUN,'browser-nonce.txt'),'utf8').trim()});
        emit({ok:true,scene,ledger:read(path.join(OUT,'provider-ledger.json')).summary});
      } else if (action.op==='goto') {
        await page.goto(URL+action.path,{waitUntil:'domcontentloaded',timeout:30000});
        await page.waitForTimeout(1000);
        const state=await snapshot(label);emit({...state,text:state.text.slice(-7000)});
      } else if (action.op==='inspect') {
        const state=await snapshot(label);emit({...state,text:state.text.slice(-9000)});
      } else if (action.op==='click') {
        await page.locator(action.selector).click({timeout:10000});
        await page.waitForTimeout(400);
        const state=await snapshot(label);emit({...state,text:state.text.slice(-8000)});
      } else if (action.op==='clickRole') {
        await page.getByRole(action.role||'button',{name:action.name,exact:action.exact!==false}).click({timeout:10000});
        await page.waitForTimeout(500);
        const state=await snapshot(label);emit({...state,text:state.text.slice(-8000)});
      } else if (action.op==='refresh') {
        await page.reload({waitUntil:'domcontentloaded'});await page.waitForTimeout(900);
        const state=await snapshot(label);emit({...state,text:state.text.slice(-9000)});
      } else if (action.op==='viewport') {
        await page.setViewportSize({width:action.width,height:action.height});
        const state=await snapshot(label);emit({...state,text:state.text.slice(-5000)});
      } else if (action.op==='send') {
        const control=read(path.join(OUT,'control.json'));
        const before=read(path.join(OUT,'provider-ledger.json'));
        if (!scene || !control.paid_enabled || control.active_scene!==scene || before.stop_reason ||
            before.requests.some(r=>!r.finished) || before.requests.length>=40 ||
            before.requests.filter(r=>r.case_id===scene).length>=before.scene_limits[scene]) throw Error('UI send blocked: controlled scene not ready');
        const textarea=page.locator(action.selector);
        await textarea.fill(action.text);
        const typed=await textarea.inputValue();
        if (typed!==action.text) throw Error('typed UI text mismatch');
        await page.screenshot({path:path.join(OUT,label+'-typed.png'),fullPage:true});
        const pending=page.waitForResponse(r=>r.request().method()==='POST' &&
          /\/api\/chat\/sessions\/[^/]+\/(assistant:stream|answers:stream)$/.test(new globalThis.URL(r.url()).pathname),{timeout:180000});
        if (action.button) await page.locator(action.button).click();
        else await textarea.press('Enter');
        const response=await pending;
        const sse=await Promise.race([response.text(),new Promise((_,reject)=>setTimeout(()=>reject(Error('SSE outcome unknown:180s')),180000))]);
        fs.writeFileSync(path.join(OUT,label+'.sse'),sse,'utf8');
        await page.waitForTimeout(600);
        const state=await snapshot(label);
        const after=read(path.join(OUT,'provider-ledger.json'));
        const result={label,time:Date.now(),scene,userText:action.text,typedText:typed,url:page.url(),
          sseUrl:response.url(),httpStatus:response.status(),
          reservationsBefore:before.requests.length,reservationsAfter:after.requests.length,
          newRequestIds:after.requests.slice(before.requests.length).map(r=>r.request_id),
          screenshot:state.screenshot,text:state.text,katex:state.katex,katexErrors:state.katexErrors,
          horizontalOverflow:state.horizontalOverflow,stopReason:after.stop_reason,paidEnabled:read(path.join(OUT,'control.json')).paid_enabled};
        save(path.join(OUT,label+'-journey.json'),result); append('ui-journeys.jsonl',result);
        emit({...result,text:result.text.slice(-13000)});
      } else if (action.op==='close') {
        await browser.close();emit({closed:true});break;
      } else throw Error('unknown UI operation');
    } catch(error) {
      const report={action,error:String(error),stack:error.stack,time:Date.now()};
      append('browser-driver-failures.jsonl',report);emit(report);
    }
  }
})().catch(error=>{emit({fatal:String(error),stack:error.stack});process.exitCode=1;});
