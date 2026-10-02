// Replays recorded synthetic live outputs through the real Vue UI. No external API calls.
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
const [reportPath, samples, output, base='http://127.0.0.1:5175'] = process.argv.slice(2);
if (!reportPath || !samples || !output) throw Error('Usage: report samples new-output-directory [base]');
await fs.mkdir(output); // Fail rather than replace previous evidence.
const report=JSON.parse(await fs.readFile(reportPath,'utf8'));
const dataset=JSON.parse(await fs.readFile('eval/photo-handwriting-v1.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const records=[];
try {
  for(const recorded of report.cases){
    const specification=dataset.cases.find(c=>c.id===recorded.id);
    const context=await browser.newContext({viewport:{width:recorded.id==='blur'?390:1366,height:900}});
    const page=await context.newPage();
    let recognitionCalls=0,reviewCalls=0,unexpectedWrites=0;
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    const id=randomUUID(), kp=randomUUID();
    const item={id,ordinal:1,kp_id:kp,kp_name:'合成验收',question_id:randomUUID(),question_type:specification.type,
      stem:specification.stem,completed:false,estimated_minutes:10,skill_tags:[],is_variant:false,is_review:false,is_external_reference:false};
    const plan={status:'active',plan_id:randomUUID(),study_date:'2026-10-02',completed_count:0,total_count:1,
      items:[item],focus_item_id:id,summary_kps:[],type_summary:{[specification.type]:1},estimated_minutes:10,remaining_minutes:10};
    await page.route('**/api/**',async route=>{
      const request=route.request(), pathname=new URL(request.url()).pathname;
      // Vite modules such as /src/api/study.ts are not API requests.
      if(!pathname.startsWith('/api/')) return route.continue();
      if(pathname==='/api/plans/today') return route.fulfill({json:plan});
      if(pathname==='/api/health') return route.fulfill({json:{status:'ok',database:'connected',environment:'test',retrieval:'ready',worker:'running',llm_configured:true,llm_model:'recorded-replay'}});
      if(pathname.endsWith('/process-reviews/latest')) return route.fulfill({json:null});
      if(pathname.endsWith('/recognize-work')){
        recognitionCalls++;
        expect(request.postDataBuffer().includes(Buffer.from('name="file"'))).toBeTruthy();
        return route.fulfill({status:recorded.status,json:recorded.response});
      }
      if(request.method()==='POST' && pathname.endsWith('/process-reviews')){
        reviewCalls++;
        expect(request.postDataJSON().work_text).toBe(recorded.response.text);
        if(!recorded.review) throw Error('Unexpected review of unreviewed sample');
        return route.fulfill({status:recorded.review.status,json:recorded.review.response});
      }
      if(!['GET','HEAD'].includes(request.method())) unexpectedWrites++;
      return route.fulfill({json:pathname.endsWith('/sessions')?{items:[],total:0}:{nodes:[]}});
    });
    try {
      await page.goto(base+'/study');
      await page.getByTestId('full-paper').click();
      const row=page.locator('li.paper-item').filter({has:page.getByText(specification.stem,{exact:true})});
      await row.getByText('检查我的过程',{exact:true}).click();
      await row.getByText('从照片录入过程',{exact:true}).click();
      const original=row.getByLabel('解题过程或伪代码');
      await original.fill('原稿内容需要保留，不能被自动覆盖。');
      await row.getByLabel('拍照或选择解题过程图片').setInputFiles(path.join(samples,recorded.id+'.png'));
      await expect(row.getByRole('button',{name:'识别图片',exact:true})).toBeDisabled();
      expect(recognitionCalls).toBe(0);
      await row.getByLabel(/同意将这张图片/).check();
      await row.getByRole('button',{name:'识别图片',exact:true}).click();
      await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(recorded.response.text);
      await row.getByText('预览文字与公式',{exact:true}).click();
      const preview=row.locator('.transcription-preview');
      if(recorded.id==='code' && !/\$|\\\(|\\\[/.test(recorded.response.text)) {
        await expect(preview.getByLabel('按代码预览，保留缩进')).toBeChecked();
        await expect(preview.locator('pre')).toHaveText(recorded.response.text);
      }
      if (/\$|\\\(|\\\[/.test(recorded.response.text)) await expect(preview.locator('.katex').first()).toBeVisible();
      else await expect(preview).toContainText(recorded.response.text.split('\n')[0]);
      expect(await preview.locator('.katex-error').count()).toBe(0);
      await page.evaluate(()=>document.fonts.ready);
      await row.screenshot({path:path.join(output,recorded.id+'-recognition.png')});
      await expect(original).toHaveValue('原稿内容需要保留，不能被自动覆盖。');
      expect(reviewCalls).toBe(0);
      await row.getByLabel('用已核对的识别结果替换下方现有过程').check();
      await row.getByRole('button',{name:'确认并填入过程'}).click();
      await expect(original).toHaveValue(recorded.response.text);
      if(recorded.review){
        if(specification.subjective_kind==='algorithm') await row.getByLabel('内容类型').selectOption('algorithm');
        await row.getByRole('button',{name:'获取辅助建议'}).click();
        await expect(row.getByText(/未提供参考解析/)).toBeVisible();
        expect(reviewCalls).toBe(1);
      }
      expect(recognitionCalls).toBe(1); expect(unexpectedWrites).toBe(0); expect(errors).toEqual([]);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      expect(overflow).toBe(false);
      await row.screenshot({path:path.join(output,recorded.id+'.png')});
      records.push({id:recorded.id,passed:true,recognitionCalls,reviewCalls,unexpectedWrites,overflow,pageErrors:errors});
    }catch(error){
      records.push({id:recorded.id,passed:false,error:String(error),pageErrors:errors});
      await page.screenshot({path:path.join(output,recorded.id+'-failed.png'),fullPage:true});
    }finally{
      await context.close();
      await fs.writeFile(path.join(output,'report.json'),JSON.stringify({mode:'RECORDED_SYNTHETIC_REPLAY_NOT_LIVE',records},null,2));
    }
  }
}finally{await browser.close();}
console.log(JSON.stringify(records));
if(records.some(r=>!r.passed))process.exitCode=1;
