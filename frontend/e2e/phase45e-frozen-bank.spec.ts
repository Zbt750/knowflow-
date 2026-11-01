// Rendering replay of frozen real REST captures; not a new backend or model call.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";

const reportPath=process.env.PHASE45E_CAPTURE_REPORT ?? "../storage/quality-audits/phase45d-20261009/foundation-pilot-v5/report.json";
const report=JSON.parse(readFileSync(resolve(reportPath),"utf8"));
const capture=report.ordinary_practice?.ui_capture ?? report.practice_retest_and_progress_closure.ui_capture;

for(const kind of ["single_choice","fill_blank"]){
  for(const width of [1366,390]){
    test(`冻结业务题面 ${kind} ${width}：提交后留题、解析、全卷`,async({page})=>{
      const item=structuredClone(capture.plan.items.find((row:any)=>row.question_type===kind && capture.first_submissions[row.id]));
      expect(item).toBeTruthy();
      const plan={...structuredClone(capture.plan),items:[item],total_count:1,focus_item_id:item.id};
      const answer=capture.answers[item.id],receipt=capture.first_submissions[item.id];
      const failures:string[]=[];page.on("pageerror",e=>failures.push(e.message));
      await page.setViewportSize({width,height:768});
      await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{
        const path=new URL(route.request().url()).pathname;
        if(path==="/api/plans/today")return route.fulfill({json:plan});
        if(path==="/api/knowledge/tree")return route.fulfill({json:{nodes:[]}});
        if(path==="/api/practice-requests")return route.fulfill({json:[]});
        if(path.endsWith("/answer-submissions")){item.completed=true;item.answer_submission=receipt;return route.fulfill({json:receipt});}
        if(path.endsWith("/answer")||path.endsWith("/answer-reveal"))return route.fulfill({json:answer});
        return route.fulfill({json:{status:"ok",database:"connected",items:[]}});
      });
      await page.goto("/study");
      if(kind==="single_choice"){
        const wrong=Object.keys(item.options).find(k=>k!==answer.correct_answer.trim())!;
        await page.getByTestId(`option-${wrong}`).check();
      }else await page.getByTestId("raw-answer").fill("0");
      await page.getByTestId("submit-answer").click();
      await expect(page.getByTestId("answer-submission-notice")).toHaveText("×");
      await page.getByTestId("answer-explanation").click();
      await expect(page.getByTestId("focus-answer")).toContainText("参考解析：");
      await page.getByTestId("full-paper").click();
      await expect(page.getByTestId(`paper-submission-${item.id}`)).toHaveText("×");
      expect(failures).toEqual([]);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    });
  }
}
