import { test, expect, type Page } from '@playwright/test';

const a = '11111111-1111-4111-8111-111111111111';
const b = '22222222-2222-4222-8222-222222222222';
function message(id: string, content: string) {
  return [{message_id: id, role: 'assistant', content, status:'completed', matched_kp_id:null, citations:[]}];
}
async function setup(page: Page) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/health') return route.fulfill({json:{status:'ok',database:'connected',environment:'test',retrieval:'ready',worker:'running',llm_configured:true}});
    if (path === '/api/materials') return route.fulfill({json:{items:[],total:1,stats:{total:1,ready:1}}});
    if (path === '/api/plans/today') return route.fulfill({json:{status:'setup',study_date:'2026-09-27',recommendations:[]}});
    if (path === '/api/chat/sessions') return route.fulfill({json:[{session_id:a,title:'会话A',mode:'user'},{session_id:b,title:'会话B',mode:'user'}]});
    if (path.endsWith('/messages')) return route.fulfill({json:message(path.includes(a)?a:b,path.includes(a)?'A 会话正文':'B 会话正文')});
    return route.fulfill({json:{error:{code:'not_found',message:'审计虚拟接口不存在'}},status:404});
  });
}

test('快速切换会话时，旧请求不能覆盖当前会话正文', async ({page}) => {
  await setup(page);
  await page.goto('/chat');
  await page.waitForTimeout(1000);
  await expect(page.locator('.message-row--assistant')).toContainText('A 会话正文');
  let release!: () => void;
  let requested = false;
  const gate = new Promise<void>(resolve => {release=resolve;});
  await page.route(`**/api/chat/sessions/${a}/messages`, async route => {
    requested = true;
    await gate;
    await route.fulfill({json:message(a,'A 会话正文')});
  });
  await page.getByRole('button',{name:'会话A',exact:false}).click();
  await expect.poll(()=>requested).toBe(true);
  await page.getByRole('button',{name:'会话B',exact:false}).click();
  await expect(page.locator('.message-row--assistant')).toContainText('B 会话正文');
  release();
  await expect(page.locator('.conversation-row.selected')).toContainText('会话B');
  await page.waitForTimeout(300);
  await expect(page.locator('.message-row--assistant')).toContainText('B 会话正文');
});

test('打开已失效的会话应局部报错，而不是让整块问答页消失',async ({page}) => {
  await setup(page);
  await page.goto('/chat');
  await expect(page.locator('.message-row--assistant')).toContainText('A 会话正文');
  await page.route(`**/api/chat/sessions/${b}/messages`,route=>route.fulfill({status:404,json:{error:{code:'chat_session_not_found',message:'会话不存在'}}}));
  await page.getByRole('button',{name:'会话B',exact:false}).click();
  await page.waitForTimeout(300);
  await expect(page.locator('.chat-workspace')).toBeVisible();
});

test('引用加输入超过后端上限时，应保留问题和引用供用户缩短', async ({page}) => {
  await setup(page);
  let length = 0;
  await page.route('**/api/chat/sessions/*/answers:stream',route=>{
    length = route.request().postDataJSON().question.length;
    return route.fulfill({status:422,json:{error:{code:'validation_failed',message:'请求参数不符合要求',details:[{field:'body.question',code:'string_too_long',message:'最多4000字符'}]}}});
  });
  await page.goto('/chat');
  const answer = page.locator('.message-row--assistant .message-bubble').last();
  await expect(answer).toContainText('A 会话正文');
  await answer.evaluate(element=>{
    const range=document.createRange();range.selectNodeContents(element.querySelector('p')??element);
    const selection=window.getSelection();selection?.removeAllRanges();selection?.addRange(range);
    element.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  });
  await page.getByTestId('quote-selected-answer').click();
  const question='问'.repeat(4000);
  await page.locator('#chat-question').fill(question);
  await page.locator('.send-button').click();
  expect(length).toBe(0);
  await expect(page.locator('.chat-notice--error')).toBeVisible();
  expect.soft((await page.locator('#chat-question').inputValue()).length).toBe(question.length);
  await expect.soft(page.getByTestId('composer-quotes')).toBeVisible();
});

test('服务端在接收提问前失败，应恢复草稿与引用', async ({page}) => {
  await setup(page);
  await page.route('**/api/chat/sessions/*/answers:stream', route => route.fulfill({
    status: 503, json: {error: {code: 'retrieval_unavailable', message: '检索暂不可用'}},
  }));
  await page.goto('/chat');
  const answer = page.locator('.message-row--assistant .message-bubble').last();
  await expect(answer).toContainText('A 会话正文');
  await answer.evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element.querySelector('p') ?? element);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    element.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
  });
  await page.getByTestId('quote-selected-answer').click();
  await page.locator('#chat-question').fill('请解释这段');
  await page.locator('.send-button').click();
  await expect(page.locator('.chat-notice--error')).toContainText('检索暂不可用');
  await expect(page.locator('.messages')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('#chat-question')).toHaveValue('请解释这段');
  await expect(page.getByTestId('composer-quotes')).toContainText('A 会话正文');
});

