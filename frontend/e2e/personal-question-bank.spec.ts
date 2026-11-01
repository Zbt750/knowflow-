// Product contract: generated questions are saved first, then explicitly added
// to a day's paper. All network responses below are isolated UI fixtures.
import { test, expect, type Page } from '@playwright/test';

test.setTimeout(30000);
const sid = '11111111-1111-4111-8111-111111111111';
const kp = '22222222-2222-4222-8222-222222222222';
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function item(id: string, questionId: string, type: string, ordinal: number) {
  return { id, question_id: questionId, kp_id: kp, kp_name: '定积分的计算', question_type: type,
    ordinal, stem: `${id} 合成题目`, options: type === 'single_choice' ? { A: '1', B: '2', C: '3', D: '4' } : null,
    completed: false, completed_at: null, is_variant: false, skill_tags: [], estimated_minutes: 5,
    is_review: false, is_external_reference: false, answer_submission: null,
    answer_grading_method: type === 'single_choice' ? 'ai_generated_single_choice' : 'ai_generated_numeric_final' };
}

function nodeQuestions(generated: boolean, hidden: boolean) {
  const questions: any[] = [{ id: 'q-public', kp_id: kp, bank_scope: 'public', question_type: 'fill_blank',
    difficulty: 'intermediate', stem: '公共正式题：计算定积分的值。', is_variant: false,
    question_source: { source_type: 'exam', content_status: 'unknown', year: 2024, question_number: 2,
      subject: '数学二', paper_title: '2024 数学二' },
    trust: { question_provenance: 'real_exam', source_attestation_current: true,
      source_status: 'traceable', presentation_label: '历年真题整理版', practice_eligible: true } }];
  if (generated && !hidden) questions.push({ id: 'q-new-choice', kp_id: kp, bank_scope: 'personal',
    question_type: 'single_choice', difficulty: 'basic', stem: 'AI生成练习：求定积分。',
    options: { A: '1', B: '2', C: '3', D: '4' }, is_variant: false, question_source: null,
    trust: { question_provenance: 'ai_generated_practice', bank_scope: 'personal',
      practice_eligible: true, evidence_capability: 'personal_practice_only' } });
  return questions;
}

async function setup(page: Page, { activeToday = true, generatedInitially = false, generalGeneration = false, longHistory = false } = {}) {
  page.on('pageerror', (error) => console.log('PAGE_ERROR', error.message));
  const items = [item('old-blank', 'q-old-blank', 'fill_blank', 1), item('old-big', 'q-old-big', 'calculation', 2)];
  const history: any[] = [];
  if (longHistory) {
    for (let index = 0; index < 18; index++) history.push({
      message_id: `older-${index}`, role: index % 2 ? 'assistant' : 'user',
      content: '此前的学习交流。'.repeat(18), status: 'completed', citations: [],
    });
  }
  let generated = generatedInitially;
  let hidden = false;
  let planExists = activeToday;
  let appends = 0;
  let appended = false;
  const kpNode = { id: kp, code: generalGeneration ? 'test.geometric_series' : 'test.integral',
    name: generalGeneration ? '等比级数的敛散性与求和' : '定积分的计算', subject: '考研数学', ordinal: 0,
    is_assessable: true, is_reference_only: false, state: 'unseen', children: [], online_question_count: generated ? 2 : 1,
    practice_eligible_question_count: generated ? 2 : 1, gap_items: [], required_question_types: {},
    excluded_question_types: [], required_skill_tags: [] };
  const today = () => planExists
    ? { status: 'active', plan_id: 'plan', study_date: '2026-10-09', total_count: items.length,
      completed_count: 0, items, summary_kps: [], type_summary: {}, estimated_minutes: 10, remaining_minutes: 10 }
    : { status: 'setup', study_date: '2026-10-09', recommendations: [], selected_kp_ids: [] };

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', database: 'connected' } });
    if (path === '/api/plans/today') return route.fulfill({ json: today() });
    if (path === '/api/plans/today/recommendations') return route.fulfill({ json: {
      status:'setup', study_date:'2026-10-09', recommendations:[{kp_id:kp,name:kpNode.name,next_step:'复习并继续练习'}],
    } });
    if (path === '/api/plans/today/generate') {
      if (route.request().postDataJSON().extend_existing && !items.some(entry => entry.question_id === 'q-extended')) {
        items.push(item('extended','q-extended','calculation',items.length+1));
      }
      planExists = true;
      return route.fulfill({ json: today() });
    }
    if (path === '/api/practice-requests') return route.fulfill({ json: [] });
    if (path === '/api/knowledge/tree') return route.fulfill({ json: { nodes: [kpNode] } });
    if (path === `/api/knowledge/${kp}`) return route.fulfill({ json: { node: kpNode,
      questions: nodeQuestions(generated, hidden), attempts: [], exam_references: [], capability_profile: null,
      lesson_available: false, materials_ready: false } });
    if (path === '/api/chat/sessions') return route.fulfill({ json: { session_id: sid, title: '合成会话', mode: 'builtin', purpose: 'study' } });
    if (path.endsWith('/messages')) return route.fulfill({ json: history });
    if (path === '/api/question-bank') {
      const params = url.searchParams;
      const search = params.get('search') ?? '';
      const includeHidden = params.get('include_hidden') === 'true';
      if (params.get('scope') === 'public') {
        const publicQuestion = nodeQuestions(false, false)[0];
        const rows = publicQuestion.stem.includes(search) ? [publicQuestion] : [];
        return route.fulfill({ json: { total: rows.length, items: rows } });
      }
      if (!generated) return route.fulfill({ json: { total: 0, items: [] } });
      const question = { id: 'q-new-choice', kp_id: kp, bank_scope: 'personal', hidden,
        question_type: generalGeneration ? 'proof' : 'single_choice', difficulty: 'basic',
        stem: generalGeneration ? '证明等比级数在公比绝对值小于1时收敛，并推导求和公式。' : 'AI生成练习：求定积分。',
        options: generalGeneration ? null : { A: '1', B: '2', C: '3', D: '4' }, practice_eligible: true };
      const rows = (includeHidden || !hidden) && question.stem.includes(search) ? [question] : [];
      return route.fulfill({ json: { total: rows.length, items: rows } });
    }
    if (path.endsWith('/visibility')) {
      hidden = Boolean(route.request().postDataJSON().hidden);
      return route.fulfill({ json: { id: 'q-new-choice', hidden } });
    }
    if (path === '/api/personal-questions/append') {
      appends += 1;
      if (!planExists) planExists = true; // Existing append API creates the day only after UI confirmation.
      const added = appended ? 0 : 1;
      appended = true;
      if (!items.some((entry) => entry.question_id === 'q-new-choice')) {
        items.push(item('new-choice', 'q-new-choice', 'single_choice', items.length + 1));
      }
      return route.fulfill({ json: { plan_id: 'plan', numbers: [], added } });
    }
    if (path === '/api/plans/plan/questions') {
      appends += 1;
      if (!items.some((entry) => entry.question_id === 'q-new-choice')) {
        items.push(item('new-choice', 'q-new-choice', 'single_choice', items.length + 1));
      }
      return route.fulfill({ json: today() });
    }
    if (path.endsWith('/assistant:stream')) {
      const body = route.request().postDataJSON();
      if (!body.personal_generation_confirmed_kp_id) {
        const confirmation = { question: body.question, message: '先确认具体知识点，再生成新题。',
          nodes: [{ kp_id: kp, name: kpNode.name, code: kpNode.code,
            question_types: generalGeneration ? ['single_choice', 'fill_blank', 'proof', 'calculation', 'subjective'] : ['single_choice', 'fill_blank'] }],
          selected_kp_id: kp, question_count: 1, difficulty: 'basic' };
        history.push({ role: 'user', content: body.question, message_id: 'confirm-user', status: 'completed', citations: [] },
          { role: 'assistant', content: confirmation.message, message_id: 'confirm-reply', status: 'completed', citations: [], personal_generation_confirmation: confirmation });
        return route.fulfill({ contentType: 'text/event-stream', body:
          frame('meta', { message_id: 'confirm-reply' }) + frame('personal_generation_confirmation', confirmation) +
          frame('delta', { text: confirmation.message }) + frame('done', { answer: confirmation.message, status: 'completed' }) });
      }
      expect(body.personal_generation_confirmed_kp_id).toBe(kp);
      expect(body.personal_generation_confirmation_message_id).toBe('confirm-reply');
      generated = true;
      const result = { batch_id: 'batch', status: 'completed', question_ids: ['q-new-choice'],
        reference_only_question_ids: generalGeneration ? ['q-new-choice'] : [],
        message: '题目已保存到对应知识节点的题目列表中，尚未加入今日学习。', numbers: [], appended_question_ids: [] };
      history.push({ role: 'assistant', content: result.message, message_id: 'reply', status: 'completed', citations: [], personal_generation: result });
      return route.fulfill({ contentType: 'text/event-stream', body:
        frame('meta', { message_id: 'reply', capability: 'generation' }) + frame('personal_generation', result) +
        frame('delta', { text: result.message }) + frame('done', { answer: result.message, status: 'completed' }) });
    }
    return route.fulfill({ json: [] });
  });
  return { get generated() { return generated; }, get appends() { return appends; }, get items() { return items; } };
}

async function generateFromStudy(page: Page) {
  await page.getByTestId('study-frog-launcher').click();
  await page.getByTestId('task-goal').fill('生成1道定积分选择题');
  await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await expect(page.getByTestId('personal-generation-result')).toHaveCount(0);
  await expect(page.getByTestId('task-goal')).toHaveValue('');
  await page.getByTestId('confirm-generation-node').click();
  await expect(page.getByTestId('personal-generation-result')).toBeVisible();
}

test('unregistered topic can confirm a proof question and keeps reference-only save-before-add boundary', async ({ page }) => {
  const state = await setup(page, { generalGeneration: true });
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  await page.getByTestId('task-goal').fill('给我出一道等比级数的证明题');
  await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('generation-node-select')).toContainText('等比级数的敛散性与求和');
  expect(state.generated).toBe(false);
  await page.getByTestId('confirm-generation-node').click();
  await expect(page.getByTestId('personal-generation-result')).toContainText('证明等比级数');
  await expect(page.getByTestId('personal-generation-result')).toContainText('所属知识点：等比级数');
  await expect(page.getByTestId('general-generation-reference-notice')).toContainText('尚未完整独立验证');
  expect(state.appends).toBe(0);
  await page.getByTestId('personal-generation-result').getByRole('button', { name: '暂不加入' }).click();
  expect(state.generated).toBe(true);
  expect(state.appends).toBe(0);
});

test('study generation saves and previews but does not append until explicit confirmation', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/study');
  await expect(page.getByTestId('focus-stem')).toContainText('old-blank');
  await page.getByTestId('raw-answer').fill('未提交的草稿');
  await generateFromStudy(page);
  await expect(page.getByTestId('personal-generation-result')).toContainText('题目已保存');
  await expect(page.getByTestId('personal-generation-result')).toContainText('AI生成练习');
  await expect(page.getByTestId('focus-stem')).toContainText('old-blank');
  await expect(page.getByTestId('raw-answer')).toHaveValue('未提交的草稿');
  expect(state.generated).toBe(true);
  expect(state.appends).toBe(0);
  expect(state.items.some((entry) => entry.question_id === 'q-new-choice')).toBe(false);
  await expect(page.getByRole('button', { name: '查看题库' })).toHaveCount(0);

  await page.getByTestId('personal-generation-result').getByRole('button', { name: '加入今日学习' }).click();
  await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
  expect(state.appends).toBe(1);
  expect(state.items.some((entry) => entry.question_id === 'q-new-choice')).toBe(true);
  await page.getByRole('button', { name: '收起奶蛙对话' }).click();
  await page.getByTestId('full-paper').click();
  const paper = await page.locator('.paper-item').allTextContents();
  expect(paper.join(' ')).toContain('new-choice');
  expect(paper.join(' ')).toContain('old-blank');
});

test('frog chat expands and restores without losing the draft or creating a plan', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/study');
  const launcher = page.getByTestId('study-frog-launcher');
  await launcher.click();
  const chat = page.getByRole('region', { name: '奶蛙学习助手对话' });
  const compact = await chat.boundingBox();
  expect(compact).not.toBeNull();
  const input = page.getByTestId('task-goal');
  await input.fill('这是一条尚未发送的草稿');
  await page.getByRole('button', { name: '放大奶蛙对话' }).click();
  await expect(page.getByRole('button', { name: '还原奶蛙对话' })).toHaveAttribute('aria-pressed', 'true');
  const large = await chat.boundingBox();
  expect(large!.width).toBeGreaterThan(compact!.width);
  expect(large!.height).toBeGreaterThan(compact!.height);
  expect(large!.x).toBeLessThanOrEqual(12);
  expect(large!.y).toBeLessThanOrEqual(12);
  await expect(input).toHaveValue('这是一条尚未发送的草稿');
  await page.getByRole('button', { name: '还原奶蛙对话' }).click();
  expect((await chat.boundingBox())!.width).toBe(compact!.width);
  await page.getByRole('button', { name: '放大奶蛙对话' }).click();
  await input.press('Escape');
  await expect(chat).toBeVisible();
  await expect(page.getByRole('button', { name: '放大奶蛙对话' })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: '放大奶蛙对话' }).click();
  await page.getByRole('button', { name: '收起奶蛙对话' }).click();
  await launcher.click();
  expect((await chat.boundingBox())!.width).toBe(compact!.width);
  await expect(input).toHaveValue('这是一条尚未发送的草稿');
  expect(state.appends).toBe(0);
  expect(state.generated).toBe(false);
});

test('postponing keeps the saved question but makes no append request', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/study');
  await generateFromStudy(page);
  const result = page.getByTestId('personal-generation-result');
  await result.getByRole('button', { name: '暂不加入' }).click();
  await expect(result).toContainText('已暂不加入');
  expect(state.generated).toBe(true);
  expect(state.appends).toBe(0);
  expect(state.items.some((entry) => entry.question_id === 'q-new-choice')).toBe(false);
});

test('an existing paper keeps recommendation selection and extends without replacing prior questions', async ({ page }) => {
  const state = await setup(page, {generatedInitially:true});
  await page.clock.setFixedTime(new Date('2026-10-09T00:00:02+08:00'));
  await page.goto('/study');
  const originalIds = state.items.map(item => item.id);
  await expect(page.getByTestId('extend-plan')).toBeVisible();
  await page.getByTestId('extend-plan').click();
  await expect(page.getByTestId('recommended-kp')).toContainText('定积分');
  expect(state.items.map(item => item.id)).toEqual(originalIds);
  const request = page.waitForRequest(request => request.url().endsWith('/api/plans/today/generate'));
  await page.getByTestId('generate-plan').click();
  expect((await request).postDataJSON().extend_existing).toBe(true);
  await expect(page.getByTestId('study-setup')).toHaveCount(0);
  expect(originalIds.every(id => state.items.some(item => item.id === id))).toBe(true);
  expect(state.items.some(item => item.question_id === 'q-extended')).toBe(true);
  await page.reload();
  await expect(page.getByTestId('extend-plan')).toBeVisible();
  await expect(page.getByTestId('append-questions')).toBeVisible();
});

test('long conversation reveals the generated question node and actions without scrolling back through history', async ({ page }, testInfo) => {
  const state = await setup(page, { longHistory: true });
  await page.goto('/study');
  await generateFromStudy(page);
  const result = page.getByTestId('personal-generation-result');
  await expect(result).toContainText('所属知识点：定积分的计算');
  await expect(result).toContainText('AI生成练习：求定积分。');
  const add = result.getByRole('button', { name: '加入今日学习', exact: true });
  const postpone = result.getByRole('button', { name: '暂不加入', exact: true });
  await expect(add).toBeEnabled();
  await expect(postpone).toBeEnabled();
  const controlsAreInView = async () => {
    const container = await page.getByTestId('frog-conversation').boundingBox();
    const controls = await add.boundingBox();
    return Boolean(container && controls && controls.y >= container.y &&
      controls.y + controls.height <= container.y + container.height);
  };
  await expect.poll(controlsAreInView).toBe(true);
  expect(state.appends).toBe(0);
  // The preview belongs after its own reply, not before all conversation text.
  await expect(result.locator('xpath=preceding-sibling::*[1]')).toContainText('尚未加入今日学习');
  await page.reload();
  await page.getByTestId('study-frog-launcher').click();
  await expect(result).toContainText('所属知识点：定积分的计算');
  await expect.poll(controlsAreInView).toBe(true);
  expect(state.appends).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('saved-question-preview.png') });
});

test('adding with no today paper requires confirmation before creating or appending', async ({ page }) => {
  const state = await setup(page, { activeToday: false });
  await page.goto('/study');
  await generateFromStudy(page);
  const result = page.getByTestId('personal-generation-result');
  page.once('dialog', (dialog) => dialog.dismiss());
  await result.getByRole('button', { name: '加入今日学习' }).click();
  await expect(result).toContainText('加入今日学习');
  expect(state.appends).toBe(0);
  expect(state.items.some((entry) => entry.question_id === 'q-new-choice')).toBe(false);

  page.once('dialog', (dialog) => dialog.accept());
  await result.getByRole('button', { name: '加入今日学习' }).click();
  await expect(result).toContainText('这批题已加入今日学习');
  expect(state.appends).toBe(1);
  expect(state.items.some((entry) => entry.question_id === 'q-new-choice')).toBe(true);
  // The setup -> active switch remounts this result. Reload must also recover
  // the actual membership, without another append or an enabled duplicate CTA.
  await page.reload();
  await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
  await expect(page.getByTestId('personal-generation-result').getByRole('button', { name: '加入今日学习', exact: true })).toHaveCount(0);
  expect(state.appends).toBe(1);
});

test('knowledge node questions unify public and AI practice with search, hide, restore and explicit add', async ({ page }) => {
  const state = await setup(page, { generatedInitially: true });
  await page.goto('/knowledge?node=test.integral&tab=questions');
  const list = page.getByTestId('question-bank');
  await expect(list).toContainText('公共正式题');
  await expect(list).toContainText('AI生成练习：求定积分');
  await expect(list).toContainText('真题整理');
  await expect(list).toContainText('AI生成练习');
  await expect(page.getByText('个人 AI 题库', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: '题库归属' })).toHaveCount(0);

  await page.getByLabel('搜索本知识点题目').fill('AI生成练习');
  await expect(list).toContainText('AI生成练习：求定积分');
  await expect(list).not.toContainText('公共正式题：计算定积分的值');
  const generatedRow = list.locator('li.pool-item').filter({ hasText: 'AI生成练习：求定积分' });
  await generatedRow.getByRole('button', { name: '隐藏' }).click();
  await expect(list).not.toContainText('AI生成练习：求定积分');

  await page.getByLabel('显示已隐藏的 AI 练习').check();
  const hiddenRow = list.getByTestId('hidden-personal-question');
  await expect(hiddenRow).toContainText('AI生成练习：求定积分');
  await hiddenRow.getByRole('button', { name: '恢复显示' }).click();
  await expect(list).toContainText('AI生成练习：求定积分');
  expect(state.appends).toBe(0);

  page.once('dialog', (dialog) => dialog.accept());
  await list.locator('li.pool-item').filter({ hasText: 'AI生成练习：求定积分' })
    .getByRole('button', { name: '加入今日学习' }).click();
  await expect(page.getByText('已加入今日学习，可在那里作答并查看解析。', { exact: true })).toBeVisible();
  await expect.poll(() => state.appends).toBe(1);
});

test('leaving study aborts the in-flight assistant stream', async ({ page }) => {
  await setup(page);
  await page.addInitScript(() => {
    const target = window as Window & { __phase45iAbortCount?: number };
    target.__phase45iAbortCount = 0;
    const original = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      init?.signal?.addEventListener('abort', () => { target.__phase45iAbortCount = (target.__phase45iAbortCount ?? 0) + 1; }, { once: true });
      return original(input, init);
    }) as typeof window.fetch;
  });
  let started!: () => void;
  const requestStarted = new Promise<void>((resolve) => { started = resolve; });
  let release!: () => void;
  const heldResponse = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/assistant:stream', async (route) => {
    started(); await heldResponse;
    try { await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: done\ndata: {"status":"completed"}\n\n' }); }
    catch { /* Navigation intentionally cancelled this browser request. */ }
  });
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  await page.getByTestId('task-goal').fill('安排今天的复习');
  await page.getByTestId('task-arrange').click();
  await requestStarted;
  await page.locator('a[href="/knowledge"]').first().click();
  await expect(page).toHaveURL(/\/knowledge/);
  await expect.poll(() => page.evaluate(() => ((window as Window & { __phase45iAbortCount?: number }).__phase45iAbortCount ?? 0))).toBe(1);
  release();
});
