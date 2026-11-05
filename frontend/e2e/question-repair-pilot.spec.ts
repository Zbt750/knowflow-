// Browser rendering of actual REST captures from the isolated B3 real-question
// replay. No new database/model calls, no synthetic question replacement.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";
import { questionSourceLabel } from "../src/lib/questionSource";

const file = process.env.QUESTION_REPAIR_PILOT_REPORT;
test.skip(!file, "Requires ignored private B3 report; never commit exam content into a UI fixture.");
const report = file ? JSON.parse(readFileSync(resolve(file), "utf8")) : null;

for (const reference of [false, true]) {
  test(`隔离真实题API回放：${reference ? "参考用途未判定" : "有界客观反馈"}与专注全卷`, async ({ page }) => {
    const capture = report.business.ui_capture;
    const entry = report.business.cases.find((r: any) => (r.result === "unknown") === reference);
    const item = structuredClone(capture.plan.items.find((i: any) => i.question_id === entry.question_id));
    const plan = { ...structuredClone(capture.plan), items: [item], total_count: 1, focus_item_id: item.id };
    const response = capture.first_submissions[item.id];
    const answer = capture.answers[item.id];
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/plans/today") return route.fulfill({ json: plan });
      if (path === "/api/knowledge/tree") return route.fulfill({ json: { nodes: [] } });
      if (path === "/api/practice-requests") return route.fulfill({ json: [] });
      if (path.endsWith("/answer-submissions")) {
        item.completed = true; item.answer_submission = response;
        return route.fulfill({ json: response });
      }
      if (path.endsWith("/answer-reveal") || path.endsWith("/answer")) return route.fulfill({ json: answer });
      return route.fulfill({ json: { status: "ok", database: "connected", items: [] } });
    });
    await page.goto("/study");
    const focus = page.getByTestId("focus-question");
    await expect(focus.getByTestId("question-source")).toHaveText(
      questionSourceLabel(item.question_source,false,item.question_trust,item.is_variant));
    if (item.options) {
      const wrong = Object.keys(item.options).find(k => k !== answer.correct_answer.trim())!;
      await page.getByTestId(`option-${wrong}`).check();
    } else await page.getByTestId("raw-answer").fill("0");
    await page.getByTestId("submit-answer").click();
    await expect(page.getByTestId("answer-submission-notice")).toHaveText(reference ? "未判定" : "×");
    await page.getByTestId("answer-explanation").click();
    await expect(page.getByTestId("focus-answer")).toContainText("参考解析：");
    await expect(page.getByTestId("focus-answer")).toContainText(answer.explanation.slice(0, 8).replace(/\$/g, ""));
    await page.getByTestId("full-paper").click();
    await expect(page.getByTestId(`paper-submission-${item.id}`)).toHaveText(reference ? "未判定" : "×");
    await expect(page.getByTestId("paper-list").getByTestId("question-source")).toHaveText(
      questionSourceLabel(item.question_source,false,item.question_trust,item.is_variant));
    expect(errors).toEqual([]);
  });
}
