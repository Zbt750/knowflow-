// Replay actual isolated REST captures. The generator in this run is explicitly
// simulated; these cases never represent paid-model quality measurements.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";
import { questionSourceLabel } from "../src/lib/questionSource";

const file=process.env.QUESTION_GENERATION_PILOT_REPORT;
test.skip(!file,"Requires ignored C1 simulation report; no exam/answers embedded in source.");
const report=file?JSON.parse(readFileSync(resolve(file),"utf8")):null;

for(const kind of ["original","adapted","completion"]){
  test(`模拟生成真实业务捕获：${kind}来源与专注全卷`,async({page})=>{
    const c=report.candidates.find((row:any)=>row.mode===kind && row.status==="AUTO_PASS");
    // Completion candidates enrich the existing source question in place; the
    // browser capture therefore points at its parent question ID, unlike the
    // original/adapted candidates which are newly stored under candidate ID.
    const entry={id:kind==="completion" ? c.record.parent_question_id : c.candidate_id};
    const capture=report.business.ui_capture;
    const item=structuredClone(capture.plan.items.find((i:any)=>i.question_id===entry.id));
    const plan={...structuredClone(capture.plan),items:[item],total_count:1,focus_item_id:item.id};
    const answer=capture.answers[item.id],receipt=capture.first_submissions[item.id];
    const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
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
    await expect(page.getByTestId("question-source")).toHaveText(
      questionSourceLabel(item.question_source,false,item.question_trust,item.is_variant));
    if(item.options){const wrong=Object.keys(item.options).find(k=>k!==answer.correct_answer.trim())!;await page.getByTestId(`option-${wrong}`).check();}
    else await page.getByTestId("raw-answer").fill("0");
    await page.getByTestId("submit-answer").click();
    await expect(page.getByTestId("answer-submission-notice")).toHaveText("×");
    await page.getByTestId("answer-explanation").click();
    await expect(page.getByTestId("focus-answer")).toContainText("参考解析：");
    await page.getByTestId("full-paper").click();
    await expect(page.getByTestId(`paper-submission-${item.id}`)).toHaveText("×");
    expect(errors).toEqual([]);
  });
}
