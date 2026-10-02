import { test, expect, apiFetch } from "./fixtures";

async function prepareNumericQuestion() {
  const tree = await (await apiFetch("/api/knowledge/tree")).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(node => [node, ...walk(node.children ?? [])]);
  const node = walk(tree.nodes).find(node => node.code === "math.calculus.limit.lhopital");
  const detail = await (await apiFetch(`/api/knowledge/${node.id}`)).json();
  const question = detail.questions.find((q: any) => q.stem === "求极限 lim(x->0) (e^x - 1) / x 的值。");
  const generated = await apiFetch("/api/plans/today/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected_kp_ids: [node.id] }) });
  expect(generated.ok).toBeTruthy();
  let plan = await generated.json();
  if (!plan.items.some((item: any) => item.question_id === question.id)) {
    plan = await (await apiFetch(`/api/plans/${plan.plan_id}/questions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_ids: [question.id] }),
    })).json();
  }
  return plan.items.find((item: any) => item.question_id === question.id).id as string;
}

for (const view of ["paper", "focus"] as const) {
  test(`${view}：数值分数排版输入可提交，不增加公式编辑器`, async ({ page }) => {
    const itemId = await prepareNumericQuestion();
    if (view === "focus") {
      const plan = await (await apiFetch("/api/plans/today")).json();
      // 隔离 fixture 把其他题记录为空答，让当前专注题确定为目标数值题。
      for (const item of plan.items.filter((item: any) => item.id !== itemId)) {
        const response = await apiFetch(`/api/practice-items/${item.id}/answer-submissions`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idempotency_key: `p4-focus-setup-${item.id}`, raw_answer: "" }),
        });
        expect(response.ok).toBeTruthy();
      }
    }
    await page.goto("/study");
    if (view === "paper") {
      await page.getByTestId("full-paper").click();
      const input = page.getByTestId(`paper-raw-answer-${itemId}`);
      await expect(input).toHaveAttribute("placeholder", /\\frac/);
      await input.fill("\\frac{2}{2}");
      await page.getByTestId(`paper-submit-answer-${itemId}`).click();
      await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
    } else {
      await expect(page.getByTestId("raw-answer")).toHaveAttribute("placeholder", /\\frac/);
      await page.getByTestId("raw-answer").fill("\\frac{2}{2}");
      await page.getByTestId("submit-answer").click();
      await expect(page.getByTestId("answer-submission-notice")).toHaveText("✓");
    }
    const saved = await (await apiFetch("/api/plans/today")).json();
    expect(saved.items.find((item: any) => item.id === itemId).answer_submission.raw_answer).toBe("\\frac{2}{2}");
  });
}

test("全卷数值提交与刷新持久化，累计客观确认", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("2/2");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  await page.reload();
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId(`paper-raw-answer-${itemId}`)).toHaveValue("2/2");
  await expect(page.getByTestId(`paper-raw-answer-${itemId}`)).toBeDisabled();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveAttribute("aria-label", "答案正确");
  const plan = await (await apiFetch("/api/plans/today")).json();
  expect(plan.items.find((item: any) => item.id === itemId).answer_submission.effective_confirmation_count).toBe(1);
});

test("提交前展开解析记录辅助，收起后仍保留", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  const row = page.locator("li.paper-item").filter({ has: page.getByTestId(`paper-raw-answer-${itemId}`) });
  await row.getByRole("button", { name: "查看答案详解" }).click();
  await row.getByRole("button", { name: "收起答案详解" }).click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  const plan = await (await apiFetch("/api/plans/today")).json();
  expect(plan.items.find((item: any) => item.id === itemId).answer_submission.assisted).toBe(true);
});

test("最后一题提交后保留题面和解析，主动完成回看", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  const plan = await (await apiFetch("/api/plans/today")).json();
  for (const item of plan.items) {
    if (item.id === itemId) continue;
    const response = await apiFetch(`/api/practice-items/${item.id}/answer-submissions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `focus-setup-${item.id}`, raw_answer: "" }),
    });
    expect(response.ok).toBeTruthy();
  }
  await page.goto("/study");
  await page.getByTestId("raw-answer").fill("1.0");
  await page.getByTestId("submit-answer").click();
  await expect(page.getByTestId("answer-submission-notice")).toHaveText("✓");
  await expect(page.getByTestId("focus-question")).toBeVisible();
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toBeVisible();
  await page.getByTestId("continue-question").click();
  await expect(page.getByTestId("focus-empty")).toBeVisible();
});

test("服务器已保存但响应丢失，前端重试复用提交键", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  const keys: string[] = [];
  await page.route(`**/api/practice-items/${itemId}/answer-submissions`, async route => {
    keys.push(route.request().postDataJSON().idempotency_key);
    if (keys.length === 1) {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      await route.abort();
    } else await route.continue();
  });
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByText("提交未确认，请重试；同一答案不会重复记入。")).toBeVisible();
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
});

test("猜对只记录辅助信号，刷新后保留信心", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  await page.getByTestId(`paper-confidence-${itemId}`).selectOption("guess");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  const plan = await (await apiFetch("/api/plans/today")).json();
  expect(plan.items.find((item: any) => item.id === itemId).answer_submission.effective_confirmation_count).toBe(0);
  await page.reload();
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId(`paper-confidence-${itemId}`)).toHaveValue("guess");
});

test("错题刷新后可直接回看解析，不重复作答或清除复测", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("3");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("×");
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveAttribute("aria-label", "答案错误");
  const plan = await (await apiFetch("/api/plans/today")).json();
  const kpId = plan.items.find((item: any) => item.id === itemId).kp_id;
  const detail = await (await apiFetch(`/api/knowledge/${kpId}`)).json();
  expect(detail.node.pending_review_count).toBe(1);
  expect(detail.node.assessment_basis).toBe("objective_v1");
  const saved = plan.items.find((item: any) => item.id === itemId).answer_submission;
  await page.reload();
  const review = page.getByTestId("wrong-answer-review");
  await expect(review).not.toHaveAttribute("open", "");
  await review.getByText("回看错题", { exact: false }).click();
  await page.getByTestId(`revisit-wrong-${itemId}`).click();
  await expect(page.getByTestId("focus-stem")).toHaveText("求极限 lim(x->0) (e^x - 1) / x 的值。");
  await expect(page.getByTestId("answer-submission-notice")).toHaveText("×");
  await expect(page.getByTestId("raw-answer")).toHaveValue("3");
  await expect(page.getByTestId("raw-answer")).toBeDisabled();
  await expect(page.getByTestId("submit-answer")).toHaveCount(0);
  await expect(page.getByTestId("focus-question")).toBeFocused();
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toBeVisible();
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toHaveCount(0);
  const after = await (await apiFetch("/api/plans/today")).json();
  expect(after.items.find((item: any) => item.id === itemId).answer_submission).toEqual(saved);
  const afterDetail = await (await apiFetch(`/api/knowledge/${kpId}`)).json();
  expect(afterDetail.node.pending_review_count).toBe(1);
});

test("专注模式答错不自动跳题，可看解析再继续", async ({ page }) => {
  await prepareNumericQuestion();
  await page.goto("/study");
  const stem = await page.getByTestId("focus-stem").innerText();
  // 当前卷按题型排序，专注题可能是选择题，也可能是填空题。
  const option = page.getByTestId("option-A");
  if (await option.count()) await option.check();
  else await page.getByTestId("raw-answer").fill("999");
  await page.getByTestId("submit-answer").click();
  await expect(page.getByTestId("focus-stem")).toHaveText(stem);
  await expect(page.getByTestId("continue-question")).toHaveText("下一题");
  await expect(page.getByTestId("submit-answer")).toHaveCount(0);
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toBeVisible();
  await page.getByTestId("continue-question").click();
  await expect(page.getByTestId("focus-stem")).not.toHaveText(stem);
});

test("同题自行改正保留两次记录，刷新不消除错题复测", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  const input = page.getByTestId(`paper-raw-answer-${itemId}`);
  await input.fill("3");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("×");
  const before = await (await apiFetch("/api/plans/today")).json();
  const previous = before.items.find((item: any) => item.id === itemId).answer_submission;
  const history = page.getByTestId(`attempt-history-${itemId}`);
  await expect(history).not.toHaveAttribute("open", "");
  await history.locator("summary").click();
  await expect(history.locator("li")).toHaveCount(1);
  await page.getByTestId(`paper-retry-answer-${itemId}`).click();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue("");
  await input.fill("1");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  await expect(history.locator("li")).toHaveCount(2);
  await expect(history).toContainText("自行改正");
  const after = await (await apiFetch("/api/plans/today")).json();
  const target = after.items.find((item: any) => item.id === itemId);
  expect(after.completed_count).toBe(before.completed_count);
  expect(target.answer_submission.previous_attempt_id).toBe(previous.attempt_id);
  expect(target.answer_submission.sequence_category).toBe("self_corrected");
  expect(target.answer_submission.effective_confirmation_count).toBe(0);
  const node = await (await apiFetch(`/api/knowledge/${target.kp_id}`)).json();
  expect(node.node.pending_review_count).toBe(1);
  await page.reload();
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId(`paper-raw-answer-${itemId}`)).toHaveValue("1");
  await expect(page.getByTestId(`paper-retry-answer-${itemId}`)).toHaveCount(0);
  const savedHistory = page.getByTestId(`attempt-history-${itemId}`);
  await savedHistory.locator("summary").click();
  await expect(savedHistory.locator("li")).toHaveCount(2);
  await expect(savedHistory.locator("li").first().locator('[aria-label="答案错误"]')).toHaveText("×");
});

test("专注模式取消重试恢复旧答案，看解析后完成仍是辅助证据", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  const submitted = await apiFetch(`/api/practice-items/${itemId}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `focus-retry-first-${itemId}`, raw_answer: "3" }),
  });
  expect(submitted.ok).toBeTruthy();
  await page.goto("/study");
  await page.getByTestId("wrong-answer-review").locator("summary").click();
  await page.getByTestId(`revisit-wrong-${itemId}`).click();
  await page.getByTestId("retry-answer").click();
  await page.getByTestId("raw-answer").fill("999");
  await page.getByTestId("cancel-answer-retry").click();
  await expect(page.getByTestId("raw-answer")).toHaveValue("3");
  await expect(page.getByTestId("raw-answer")).toBeDisabled();
  let history = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`)).json();
  expect(history.items).toHaveLength(1);
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toBeVisible();
  await page.getByTestId("retry-answer").click();
  await expect(page.getByTestId("focus-answer")).toHaveCount(0);
  await page.getByTestId("raw-answer").fill("1");
  await page.getByTestId("submit-answer").click();
  await expect(page.getByTestId("answer-submission-notice")).toHaveText("✓");
  await expect(page.getByTestId("focus-stem")).toHaveText("求极限 lim(x->0) (e^x - 1) / x 的值。");
  history = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`)).json();
  expect(history.items).toHaveLength(2);
  expect(history.items[1].sequence_category).toBe("solution_assisted_correct");
  expect(history.items[1].effective_confirmation_count).toBe(0);
});

test("重试响应丢失不重复保存，保留前驱作答与提交键", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  const first = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `retry-loss-first-${itemId}`, raw_answer: "3" }),
  })).json();
  const bodies: any[] = [];
  await page.route(`**/api/practice-items/${itemId}/answer-submissions`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    bodies.push(route.request().postDataJSON());
    if (bodies.length === 1) {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      await route.abort();
    } else await route.continue();
  });
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-retry-answer-${itemId}`).click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByText("提交未确认，请重试；同一答案不会重复记入。")).toBeVisible();
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toEqual(bodies[1]);
  expect(bodies[0].expected_previous_attempt_id).toBe(first.attempt_id);
  const history = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`)).json();
  expect(history.items).toHaveLength(2);
});

test("另一窗口先提交后，过期重试不会覆盖最新记录", async ({ page }) => {
  const itemId = await prepareNumericQuestion();
  const first = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `stale-first-${itemId}`, raw_answer: "3" }),
  })).json();
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  await page.getByTestId(`paper-retry-answer-${itemId}`).click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  const other = await apiFetch(`/api/practice-items/${itemId}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `stale-other-${itemId}`, raw_answer: "4", expected_previous_attempt_id: first.attempt_id }),
  });
  expect(other.ok).toBeTruthy();
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-raw-answer-${itemId}`)).toBeDisabled();
  await expect(page.getByTestId(`paper-raw-answer-${itemId}`)).toHaveValue("4");
  const history = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`)).json();
  expect(history.items).toHaveLength(2);
  expect(history.items[1].raw_answer).toBe("4");
  await page.getByTestId(`paper-retry-answer-${itemId}`).click();
  await page.getByTestId(`paper-raw-answer-${itemId}`).fill("1");
  await page.getByTestId(`paper-submit-answer-${itemId}`).click();
  await expect(page.getByTestId(`paper-submission-${itemId}`)).toHaveText("✓");
  const finalHistory = await (await apiFetch(`/api/practice-items/${itemId}/answer-submissions`)).json();
  expect(finalHistory.items).toHaveLength(3);
  expect(finalHistory.items[2].previous_attempt_id).toBe(history.items[1].attempt_id);
});
