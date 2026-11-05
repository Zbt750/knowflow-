// Real Vue interactions with completely intercepted protocol fixtures. No
// database, model call, generated qualification or user learning data is used.
import { expect, test, type Page } from '@playwright/test';

const sid = '11111111-1111-4111-8111-111111111111';
const node = '22222222-2222-4222-8222-222222222222';
const confirmationId = '33333333-3333-4333-8333-333333333333';
const failedId = '44444444-4444-4444-8444-444444444444';
const secondNode = '55555555-5555-4555-8555-555555555555';
const statement = '帮我生成一道类似的题';
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

async function fixture(page: Page, options: { nodes?: Array<{ kp_id: string; name: string; code: string; question_types: string[] }>; selectedKpId?: string | null; replyText?: string } = {}) {
  const history: any[] = [];
  const requests: any[] = [];
  let fail = true;
  let cancelled = false;
  let loseTerminal = false;
  let retryable = true;
  let httpFailure = false;
  let appends = 0;
  let stale = false;
  let currentCardId = confirmationId;
  const nodes = options.nodes ?? [{ kp_id: node, name: '定积分的计算', code: 'test.integral', question_types: ['calculation'] }];
  const confirmation = { question: statement, message: '先确认具体知识点，确认后才会生成。', selected_kp_id: options.selectedKpId === undefined ? node : options.selectedKpId, question_count: 1, difficulty: 'medium', nodes };
  const message = (message_id: string, role: string, content: string, extra = {}) => ({ message_id, role, content, status: 'completed', citations: [], matched_kp_id: null, ...extra });
  // Only intercept backend endpoints rooted at /api. A broad **/api/** glob
  // also matches Vite source modules such as /src/api/health.ts and leaves the
  // app blank instead of exercising the study/chat UI.
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', database: 'connected', environment: 'test', llm_configured: true } });
    if (path === '/api/materials') return route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } });
    if (path === '/api/practice-requests') return route.fulfill({ json: [] });
    if (path === '/api/knowledge/tree') return route.fulfill({ json: { nodes: [] } });
    // The study chat dock belongs to an already-created daily paper. Setup
    // now uses HomeLearningWorkbench, not the post-generation chat launcher.
    if (path === '/api/plans/today') return route.fulfill({ json: {
      status: 'active', study_date: '2026-10-18', plan_id: '99999999-9999-4999-8999-999999999999',
      completed_count: 0, total_count: 0, items: [], retry_wrong_items: [], focus_item_id: null,
      summary_kps: [], type_summary: {}, estimated_minutes: 0, remaining_minutes: 0,
    } });
    if (path === '/api/chat/sessions') {
      const purpose = new URL(route.request().url()).searchParams.get('purpose') ?? 'qa';
      const studyDate = await page.evaluate(()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));
      return route.fulfill({ json: route.request().method() === 'POST' ? { session_id: sid, title: '协议测试', mode: 'builtin', purpose:route.request().postDataJSON().purpose } : [{ session_id: sid, title: '协议测试', mode: 'builtin',purpose,study_date:purpose==='study'?studyDate:null }] });
    }
    if (path.endsWith('/messages')) return route.fulfill({ json: history.map(item => item.message_id === confirmationId && cancelled ? { ...item, personal_generation_confirmation: null } : item) });
    if (path.endsWith(`/generation-confirmations/${confirmationId}/cancel`)) { cancelled = true; return route.fulfill({ json: { message_id: confirmationId, status: 'cancelled' } }); }
    if (path === '/api/personal-questions/append' || path === '/api/plans/today/generate') { appends++; return route.fulfill({ status: 500, json: { error: { code: 'unexpected_write', message: '不应自动追加或生成今日卷' } } }); }
    if (path.endsWith('/assistant:stream')) {
      const body = route.request().postDataJSON(); requests.push(body);
      if (options.replyText) {
        const replyId = '88888888-8888-4888-8888-888888888888';
        history.push(message('qa-user', 'user', body.question), message(replyId, 'assistant', options.replyText));
        return route.fulfill({ contentType: 'text/event-stream', body: frame('meta', {message_id:replyId}) +
          frame('delta', {text:options.replyText}) + frame('done', {answer:options.replyText, status:'completed'}) });
      }
      if (!body.personal_generation_confirmed_kp_id) {
        for (const old of history) old.personal_generation_confirmation = null;
        currentCardId = requests.length === 1 ? confirmationId : '77777777-7777-4777-8777-777777777777';
        const card = {...confirmation, question:body.question};
        history.push(message(`source-user-${requests.length}`, 'user', body.question), message(currentCardId, 'assistant', card.message, { personal_generation_confirmation: card }));
        return route.fulfill({ contentType: 'text/event-stream', body: frame('meta', { message_id: currentCardId }) + frame('personal_generation_confirmation', card) + frame('delta', { text: card.message }) + frame('done', { status: 'completed' }) });
      }
      expect(body.personal_generation_confirmation_message_id).toBe(currentCardId);
      if (stale) return route.fulfill({ status:409, json:{error:{code:'personal_generation_confirmation_invalid', message:'出题位置已变化，请重新提出要求。'}} });
      if (httpFailure) return route.fulfill({ status: 500, json: { error: { code: 'internal_error', message: 'internal error' } } });
      const text = fail ? '' : '生成服务已恢复；尚未加入今日学习。';
      const reply = message(failedId, 'assistant', text, { request_key: body.request_key, status: fail ? 'failed' : 'completed', retryable, study_context: body.study_context, personal_generation_mode: body.personal_generation_mode, personal_generation_confirmed_kp_id: body.personal_generation_confirmed_kp_id, personal_generation_confirmation_message_id: body.personal_generation_confirmation_message_id, assistant_error_code: fail ? retryable ? 'personal_generation_storage_forbidden' : 'personal_generation_failed' : null });
      const existing = history.findIndex(item => item.message_id === failedId);
      if (existing >= 0) history[existing] = reply; else history.push(reply);
      return route.fulfill({ contentType: 'text/event-stream', body: frame('meta', { message_id: failedId }) + (loseTerminal ? '' : fail ? frame('error', { message_id: failedId, retryable, code: retryable ? 'personal_generation_storage_forbidden' : 'personal_generation_failed', message: retryable ? '保存权限不足' : '生成未通过检查，本批次已结束。' }) : frame('delta', { text }) + frame('done', { status: 'completed', answer: text })) });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'fixture_not_found', message: `未定义协议夹具 ${path}` } } });
  });
  return { history, requests, get appends() { return appends; }, get cancelled() { return cancelled; }, set stale(value:boolean) { stale=value; }, set fail(value: boolean) { fail = value; }, set retryable(value: boolean) { retryable = value; }, set loseTerminal(value: boolean) { loseTerminal = value; }, set httpFailure(value: boolean) { httpFailure = value; } };
}

test('study: 跨午夜旧确认卡不发送到新会话，原要求可重新确认', async ({ page }) => {
  const state = await fixture(page);
  await page.clock.install({time:new Date('2026-10-18T23:59:58+08:00')});
  // Keep 23:59 fixed during page startup; elapsed browser setup must not cross
  // midnight before the test explicitly advances the business clock.
  await page.clock.setFixedTime(new Date('2026-10-18T23:59:58+08:00'));
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  const composer = page.getByTestId('task-goal');
  await composer.fill(statement); await composer.press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));
  await page.getByTestId('confirm-generation-node').click();
  await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
  await expect(composer).toHaveValue(statement);
  expect(state.requests).toHaveLength(1);
  expect(state.appends).toBe(0);
  await composer.press('Enter');
  await expect.poll(() => state.requests.length).toBe(2);
  expect(state.requests[1].personal_generation_confirmation_message_id).toBeNull();
  expect(state.requests[1].personal_generation_confirmed_kp_id).toBeNull();
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
});

for (const surface of ['study', 'chat'] as const) {
  test(`${surface}: 待确认卡不拦截补充原题或新的出题要求`, async ({ page }) => {
    const state = await fixture(page);
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    await expect(page.getByTestId('generation-confirmation')).toBeInViewport();
    const source = String.raw`当 |x|<1 时，求级数 \sum_{n=1}^{\infty}nx^n 的和。`;
    await composer.fill(source); await composer.press('Enter');
    await expect(composer).toHaveValue('');
    await expect.poll(() => state.requests.length).toBe(2);
    expect(state.requests[1].question).toBe(source);
    expect(state.requests[1].personal_generation_confirmation_message_id).toBeNull();
    expect(state.requests[1].request_key).not.toBe(state.requests[0].request_key);
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(2);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 失效确认后可以发送全新要求而不重试旧卡`, async ({ page }) => {
    const state = await fixture(page);
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    state.stale = true;
    await page.getByTestId('confirm-generation-node').click();
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
    state.stale = false;
    await composer.fill('再来一道综合性更强的练习题'); await composer.press('Enter');
    await expect.poll(() => state.requests.length).toBe(3);
    expect(state.requests[2].retry_of_message_id).toBeUndefined();
    expect(state.requests[2].personal_generation_confirmation_message_id).toBeNull();
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 中文与数学公式渲染及刷新恢复一致`, async ({ page }, testInfo) => {
    const reply = String.raw`中文推导，𝛼 与 ∞，先独立思考。
行内公式 \(x_1^2+\alpha\)。
\[\sum\_{n=1}^{\infty}nx^n=\frac{x}{(1-x)^2},\quad |x|<1\]
\[\begin{bmatrix}1&2\\3&4\end{bmatrix}\]
\[\begin{aligned}F(x)&=\int_0^x t^2\,dt\\F'(x)&=x^2\end{aligned}\]`;
    const state = await fixture(page, {replyText:reply});
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill('请解释这个求和公式'); await composer.press('Enter');
    await expect(page.locator('.katex')).toHaveCount(4);
    await expect(page.locator('.katex-error')).toHaveCount(0);
    await expect(page.getByText('中文推导，𝛼 与 ∞，先独立思考。', {exact:false})).toBeVisible();
    expect(state.history.at(-1).content).toBe(reply);
    await page.reload();
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    await expect(page.locator('.katex')).toHaveCount(4);
    await expect(page.locator('.katex-error')).toHaveCount(0);
    await page.screenshot({path:testInfo.outputPath('chinese-math-history.png')});
  });

  test(`${surface}: 无法渲染的公式保留原文并给出明确提示`, async ({ page }) => {
    await fixture(page, {replyText:String.raw`中文说明。\(\unknownMathCommand{x}\) 后续文字仍可阅读。`});
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill('解释这个公式'); await composer.press('Enter');
    await expect(page.getByText('部分公式格式不完整，已保留原文；可以请奶蛙重新排版这部分公式。')).toBeVisible();
    await expect(page.locator('.katex')).toHaveCount(0);
    await expect(page.getByText(String.raw`中文说明。\(\unknownMathCommand{x}\) 后续文字仍可阅读。`, {exact:true})).toBeVisible();
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
  });

  test(`${surface}: 确认生成与重试只保留一条用户提问，已保存失败不回填输入`, async ({ page }) => {
    const state = await fixture(page);
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    await expect(page.getByTestId('generation-confirmation')).toBeInViewport();
    await composer.fill('我还想问的下一条草稿');
    await page.getByTestId('confirm-generation-node').click();
    await expect(page.getByText(/当前应用账号缺少出题保存权限/).first()).toBeVisible();
    await expect(page.getByText(/尚未调用模型/).first()).toBeVisible();
    await expect(page.getByRole('button', { name: '重试这条回复', exact: true })).toBeVisible();
    await expect(composer).toHaveValue('我还想问的下一条草稿');
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.requests).toHaveLength(2);
    const failedRequest = state.requests[1];
    state.fail = false;
    await page.getByRole('button', { name: '重试这条回复', exact: true }).click();
    await expect.poll(() => state.requests.length).toBe(3);
    expect(state.requests[2]).toMatchObject({ question: statement, request_key: failedRequest.request_key, retry_of_message_id: failedId, personal_generation_confirmation_message_id: confirmationId, personal_generation_confirmed_kp_id: node, personal_generation_mode: failedRequest.personal_generation_mode, study_context: failedRequest.study_context });
    await expect(composer).toHaveValue('我还想问的下一条草稿');
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 暂不生成持久取消，刷新不重新出现确认卡`, async ({ page }) => {
    const state = await fixture(page);
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await page.getByRole('button', { name: '暂不生成', exact: true }).click();
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
    expect(state.cancelled).toBe(true);
    await page.reload();
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
    expect(state.requests).toHaveLength(1);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 已结束失败批次不能重复收费重试，只能显式编辑为新提问`, async ({ page }) => {
    const state = await fixture(page); state.retryable = false;
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await page.getByTestId('confirm-generation-node').click();
    await expect(page.getByRole('button', { name: '编辑原提问', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '重试这条回复', exact: true })).toHaveCount(0);
    await expect(composer).toHaveValue('');
    await page.getByRole('button', { name: '编辑原提问', exact: true }).click();
    await expect(composer).toHaveValue(statement);
    expect(state.requests).toHaveLength(2);
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 终止帧丢失先读取已完成历史，禁止自动再次请求`, async ({ page }) => {
    const state = await fixture(page); state.fail = false; state.loseTerminal = true;
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await page.getByTestId('confirm-generation-node').click();
    const conversation = surface === 'study' ? page.getByTestId('frog-conversation') : page.locator('.messages');
    await expect(conversation).toContainText('生成服务已恢复');
    await expect(page.getByRole('button', { name: '重试这条回复', exact: true })).toHaveCount(0);
    await expect(composer).toHaveValue('');
    expect(state.requests).toHaveLength(2);
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.appends).toBe(0);
  });
}

for (const surface of ['study', 'chat'] as const) {
  test(`${surface}: 选择知识点后可直接在聊天输入“确定”继续原始出题请求`, async ({ page }) => {
    const state = await fixture(page, {
      selectedKpId: null,
      nodes: [
        { kp_id: node, name: '定积分的计算', code: 'test.integral', question_types: ['calculation'] },
        { kp_id: secondNode, name: '反常积分', code: 'test.improper-integral', question_types: ['calculation'] },
      ],
    });
    state.fail = false;
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    await page.getByTestId('generation-node-select').selectOption(node);
    await composer.fill('确定'); await composer.press('Enter');
    await expect.poll(() => state.requests.length).toBe(2);
    expect(state.requests[1]).toMatchObject({
      question: statement,
      personal_generation_confirmation_message_id: confirmationId,
      personal_generation_confirmed_kp_id: node,
    });
    await expect(composer).toHaveValue('');
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 多个知识点未选择时“确定”不会猜选或触发生成`, async ({ page }) => {
    const state = await fixture(page, {
      selectedKpId: null,
      nodes: [
        { kp_id: node, name: '定积分的计算', code: 'test.integral', question_types: ['calculation'] },
        { kp_id: secondNode, name: '反常积分', code: 'test.improper-integral', question_types: ['calculation'] },
      ],
    });
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.fill(statement); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible();
    await composer.fill('确定'); await composer.press('Enter');
    await expect(page.getByText(/请先在出题卡中选择知识点/)).toBeVisible();
    await expect(composer).toHaveValue('确定');
    expect(state.requests).toHaveLength(1);
    expect(state.history.filter(item => item.role === 'user')).toHaveLength(1);
    expect(state.appends).toBe(0);
  });

  test(`${surface}: 复合输入框聚焦时只显示外层一个边框`, async ({ page }) => {
    await fixture(page);
    await page.goto(surface === 'study' ? '/study' : `/chat?session_id=${sid}`);
    if (surface === 'study') await page.getByTestId('study-frog-launcher').click();
    const composer = surface === 'study' ? page.getByTestId('task-goal') : page.locator('#chat-question');
    await composer.focus();
    const innerStyle = await composer.evaluate((node) => {
      const style = getComputedStyle(node);
      return { outline: style.outlineStyle, shadow: style.boxShadow, borderWidth: style.borderWidth };
    });
    expect(innerStyle.outline).toBe('none');
    expect(innerStyle.shadow).toBe('none');
    expect(innerStyle.borderWidth).toBe('0px');
    const shell = surface === 'study' ? page.locator('.frog-composer-entry') : page.locator('.chat-main .composer');
    const outerStyle = await shell.evaluate((node) => {
      const style = getComputedStyle(node);
      return { borderWidth: style.borderWidth, shadow: style.boxShadow };
    });
    expect(outerStyle.borderWidth).toBe('1px');
    expect(outerStyle.shadow).toBe('none');
  });
}

test('study: HTTP internal_error 显示可理解的恢复提示，不把服务端原文放进对话', async ({ page }) => {
  const state = await fixture(page);
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  const composer = page.getByTestId('task-goal');
  await composer.fill(statement); await composer.press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  state.httpFailure = true;
  await page.getByTestId('confirm-generation-node').click();
  const alert = page.getByTestId('frog-turn-error');
  await expect(alert).toContainText('本次处理未完成，已保存这条提问');
  await expect(alert).not.toContainText('internal error');
  expect(state.requests).toHaveLength(2);
  expect(state.appends).toBe(0);
});
