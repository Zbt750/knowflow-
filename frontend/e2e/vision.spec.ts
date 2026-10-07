import { test, expect, apiFetch } from "./fixtures";

async function prepareProcess(page: any) {
  const tree = await (await apiFetch('/api/knowledge/tree')).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(n => [n, ...walk(n.children ?? [])]);
  const node = walk(tree.nodes).find(n => n.code === 'math.calculus.limit.lhopital');
  const generated = await apiFetch('/api/plans/today/generate', { method: 'POST', headers: { 'Content-Type':'application/json' },
    body: JSON.stringify({ selected_kp_ids:[node.id] }) });
  expect(generated.ok).toBeTruthy();
  const plan = await generated.json();
  const item = plan.items.find((row: any) => row.question_type === 'calculation');
  await page.goto('/study'); await page.getByTestId('full-paper').click();
  const row = page.locator('li.paper-item').filter({ has: page.getByTestId(`paper-raw-answer-${item.id}`) });
  await row.getByText('检查我的过程', { exact:true }).click();
  await row.getByText('从照片录入过程', { exact:true }).click();
  return row;
}

const syntheticImage = { name:'synthetic.png', mimeType:'image/png',
  buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9xkAAAAASUVORK5CYII=', 'base64') };
const recognition = { text:'识别的原稿：[无法辨认]，再对分子分母求导。', model:'synthetic-vision', duration_ms:1,
  requires_confirmation:true, changes_mastery:false, image_stored:false };

test('切换整卷专注保留未确认识别文字，不保留图片或自动发送', async ({ page }) => {
  let calls = 0, reviews = 0;
  await page.route('**/recognize-work', async route => {
    calls++; await route.fulfill({json:recognition});
  });
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/process-reviews')) reviews++;
  });
  const row = await prepareProcess(page);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  const draft = row.getByLabel('识别结果，确认前可修改');
  await expect(draft).toHaveValue(recognition.text);
  const edited = '已逐字核对的过程，尚未确认填入。';
  await draft.fill(edited);
  for (let i = 0; i < 2; i++) {
    await page.getByTestId('mode-focus').click();
    await page.getByTestId('full-paper').click();
    await row.getByText('检查我的过程',{exact:true}).click();
    await row.getByText('从照片录入过程',{exact:true}).click();
    await expect(draft).toHaveValue(edited);
    await expect(row.getByAltText('待识别的过程图片预览')).toHaveCount(0);
    await expect(row.getByLabel('拍照或选择解题过程图片')).toHaveValue('');
    await expect(row.getByLabel('解题过程或伪代码')).toHaveValue('');
  }
  await row.getByRole('button',{name:'确认并填入过程'}).click();
  await expect(row.getByLabel('解题过程或伪代码')).toHaveValue(edited);
  await expect(draft).toHaveCount(0);
  expect(calls).toBe(1); expect(reviews).toBe(0);
});

test('保留的识别草稿可清除，离开今日学习不持久保存', async ({ page }) => {
  await page.route('**/recognize-work', route => route.fulfill({json:recognition}));
  const row = await prepareProcess(page);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(recognition.text);
  await page.getByTestId('mode-focus').click();
  await page.getByTestId('full-paper').click();
  await row.getByText('检查我的过程',{exact:true}).click();
  await row.getByText('从照片录入过程',{exact:true}).click();
  await row.getByRole('button',{name:'清除识别草稿'}).click();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveCount(0);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(recognition.text);
  await page.getByRole('link',{name:'知识树',exact:true}).click();
  await page.getByRole('link',{name:'今日学习',exact:true}).click();
  await page.getByTestId('full-paper').click();
  await row.getByText('检查我的过程',{exact:true}).click();
  await row.getByText('从照片录入过程',{exact:true}).click();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveCount(0);
});

for (const width of [1280,390]) {
  test(`照片核对窗口缩放、编辑同步、键盘与布局（${width}px）`, async ({ page }) => {
    await page.setViewportSize({width,height:844});
    let calls=0, reviews=0;
    await page.route('**/recognize-work', async route=>{ calls++; await route.fulfill({json:recognition}); });
    page.on('request',request=>{
      if(request.method()==='POST' && request.url().endsWith('/process-reviews')) reviews++;
    });
    const row=await prepareProcess(page);
    const image=await page.evaluate(()=>{
      const canvas=document.createElement('canvas'); canvas.width=1200; canvas.height=1600;
      const context=canvas.getContext('2d')!; context.fillStyle='white'; context.fillRect(0,0,1200,1600);
      context.fillStyle='black'; context.font='40px sans-serif'; context.fillText('x_1 + x_2 = 3',40,80);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await row.getByLabel('拍照或选择解题过程图片').setInputFiles({
      name:'local-layout-fixture.png',mimeType:'image/png',buffer:Buffer.from(image,'base64'),
    });
    const open=row.getByRole('button',{name:'放大核对',exact:true});
    await open.click();
    const modal=page.getByRole('dialog',{name:'照片与识别文字核对'});
    await expect(modal).toBeVisible();
    await expect(modal.getByRole('button',{name:'关闭核对'})).toBeFocused();
    await expect(modal.getByText('识别完成后，可在这里对照原图修改文字。')).toBeVisible();
    expect(calls).toBe(0);
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
    await expect(open).toBeFocused();
    await row.getByLabel(/同意将这张图片/).check();
    await row.getByRole('button',{name:'识别图片',exact:true}).click();
    await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(recognition.text);
    await open.click();
    const enlarge=modal.getByRole('button',{name:'放大照片',exact:true});
    const shrink=modal.getByRole('button',{name:'缩小照片',exact:true});
    await expect(shrink).toBeDisabled();
    for(let i=0;i<8;i++) await enlarge.click();
    await expect(enlarge).toBeDisabled();
    await expect(modal.getByText('300%',{exact:true})).toBeVisible();
    const pane=modal.getByRole('region',{name:'原图，可滚动查看'});
    expect(await pane.evaluate(element=>element.scrollWidth>element.clientWidth)).toBe(true);
    await pane.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(()=>pane.evaluate(element=>element.scrollLeft)).toBeGreaterThan(0);
    await modal.getByRole('button',{name:'适应窗口',exact:true}).click();
    await expect(modal.getByText('100%',{exact:true})).toBeVisible();
    const edit=modal.getByLabel('对照原图修改识别文字');
    await edit.fill('核对后：x_1 + x_2 = 3，尚未提交');
    await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue('核对后：x_1 + x_2 = 3，尚未提交');
    if(width===390) {
      const imageBox=await pane.boundingBox(), textBox=await edit.boundingBox();
      expect(textBox!.y).toBeGreaterThanOrEqual(imageBox!.y+imageBox!.height);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    expect(await modal.evaluate(element=>element.scrollWidth<=element.clientWidth)).toBe(true);
    for(let i=0;i<6;i++) {
      await page.keyboard.press('Tab');
      expect(await modal.evaluate(element=>element.contains(document.activeElement))).toBe(true);
    }
    for(let i=0;i<6;i++) {
      await page.keyboard.press('Shift+Tab');
      expect(await modal.evaluate(element=>element.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(open).toBeFocused();
    await expect(row.getByLabel('解题过程或伪代码')).toHaveValue('');
    expect(calls).toBe(1); expect(reviews).toBe(0);
    await row.getByRole('button',{name:'移除图片',exact:true}).click();
    await expect(modal).toHaveCount(0);
  });
}

test('不合格新图本地拒绝并保留已核对草稿，不额外调用模型', async ({ page }) => {
  let calls=0;
  await page.route('**/recognize-work', async route => {
    calls++; await route.fulfill({json:recognition});
  });
  const row=await prepareProcess(page);
  const picker=row.getByLabel('拍照或选择解题过程图片');
  await picker.setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  const draft=row.getByLabel('识别结果，确认前可修改');
  await expect(draft).toHaveValue(recognition.text);
  await draft.fill('核对后的文字和公式');
  const wide=await page.evaluate(()=>{
    const canvas=document.createElement('canvas'); canvas.width=4097; canvas.height=1;
    return canvas.toDataURL('image/png').split(',')[1];
  });
  const invalidFiles=[
    {name:'unsupported.heic',mimeType:'image/heic',buffer:Buffer.from('not-supported')},
    {name:'empty.png',mimeType:'image/png',buffer:Buffer.alloc(0)},
    {name:'too-large.png',mimeType:'image/png',buffer:Buffer.alloc(5*1024*1024+1)},
    {name:'corrupt.png',mimeType:'image/png',buffer:Buffer.from('not-an-image')},
    {name:'wide.png',mimeType:'image/png',buffer:Buffer.from(wide,'base64')},
  ];
  for (const candidate of invalidFiles) {
    await picker.setInputFiles(candidate);
    await expect(row.getByRole('alert')).toBeVisible();
    await expect(row.getByRole('button',{name:'识别图片',exact:true})).toBeEnabled();
    await expect(draft).toHaveValue('核对后的文字和公式');
    await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
    await expect(row.getByLabel(/同意将这张图片/)).toBeChecked();
    expect(calls).toBe(1);
  }
  await row.getByRole('button',{name:'移除图片',exact:true}).click();
  await picker.setInputFiles(syntheticImage);
  await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
  await expect(row.getByRole('alert')).toHaveCount(0);
  await expect(row.getByLabel(/同意将这张图片/)).not.toBeChecked();
});

test('本地检查期间移除图片，迟到检查不能恢复图片或发送请求', async ({ page }) => {
  let calls=0;
  await page.route('**/recognize-work', async route => { calls++; await route.fulfill({json:recognition}); });
  const row=await prepareProcess(page);
  const picker=row.getByLabel('拍照或选择解题过程图片');
  await picker.setInputFiles(syntheticImage);
  await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
  await page.evaluate(()=>{
    const original=Image.prototype.decode;
    Image.prototype.decode=async function () {
      await original.call(this);
      await new Promise<void>(resolve=>{ (window as any).finishImageCheck=resolve; });
    };
  });
  await picker.setInputFiles({...syntheticImage,name:'another.png'});
  await expect(row.getByRole('status')).toHaveText('正在检查图片…');
  await expect(row.getByRole('button',{name:'识别图片',exact:true})).toBeDisabled();
  await page.waitForFunction(()=>typeof (window as any).finishImageCheck==='function');
  await row.getByRole('button',{name:'移除图片',exact:true}).click();
  await page.evaluate(()=>{ (window as any).finishImageCheck(); });
  await expect(row.getByRole('status')).toHaveCount(0);
  await expect(row.getByAltText('待识别的过程图片预览')).toHaveCount(0);
  await expect(picker).toBeEnabled();
  expect(calls).toBe(0);
});

test('取消重新识别保留图片和已核对草稿，迟到结果不能覆盖', async ({ page }) => {
  let calls=0;
  let pending: any;
  await page.route('**/recognize-work', async route => {
    calls++;
    if (calls===1) await route.fulfill({json:recognition});
    else pending=route;
  });
  const row=await prepareProcess(page);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  const draft=row.getByLabel('识别结果，确认前可修改');
  await expect(draft).toHaveValue(recognition.text);
  await draft.fill('已核对的原稿');
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles([]);
  await expect(draft).toHaveValue('已核对的原稿');
  await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await expect.poll(()=>calls).toBe(2);
  await row.getByRole('button',{name:'取消等待',exact:true}).click();
  await expect(draft).toHaveValue('已核对的原稿');
  await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
  await expect(row.getByLabel(/同意将这张图片/)).toBeChecked();
  await pending.fulfill({json:{...recognition,text:'迟到结果'}}).catch(()=>{});
  await expect(draft).toHaveValue('已核对的原稿');
  await expect(row.getByLabel('解题过程或伪代码')).toHaveValue('');
  await row.getByRole('button',{name:'移除图片',exact:true}).click();
  await expect(draft).toHaveCount(0);
});

test('伪代码预览保留缩进，切换预览格式不改原稿或自动审阅', async ({ page }) => {
  const text='二分查找：\nwhile l <= r:\n    if a[mid] < x: l = mid\nreturn -1';
  await page.route('**/recognize-work',route=>route.fulfill({json:{...recognition,text}}));
  const row=await prepareProcess(page);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await row.getByText('预览文字与公式',{exact:true}).click();
  const format=row.getByLabel('按代码预览，保留缩进');
  await expect(format).toBeChecked();
  await expect(row.locator('.code-preview')).toHaveText(text);
  await format.uncheck();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(text);
  await expect(row.getByLabel('解题过程或伪代码')).toHaveValue('');
});

test('识别预览保留反斜杠公式和矩阵，代码不渲染且HTML继续净化', async ({ page }) => {
  const text = String.raw`公式 \(x_1^2\)
\[
A=\begin{bmatrix}1&-2\\0&3\end{bmatrix}
\]

` + '```text\n\\(code_should_stay_raw\\)\n```\n<script>window.photoInjected=true</script><img src=x onerror="window.photoInjected=true">';
  await page.route('**/recognize-work', route => route.fulfill({json:{...recognition,text}}));
  const row = await prepareProcess(page);
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await expect(row.getByLabel('识别结果，确认前可修改')).toHaveValue(text);
  await row.getByText('预览文字与公式',{exact:true}).click();
  const preview=row.locator('.transcription-preview');
  await expect(preview.locator('.katex')).toHaveCount(2);
  await expect(preview.locator('.katex-error')).toHaveCount(0);
  await expect(preview.locator('pre code')).toContainText('\\(code_should_stay_raw\\)');
  await expect(preview.locator('pre .katex, script, img')).toHaveCount(0);
  expect(await page.evaluate(()=> (window as any).photoInjected)).toBeUndefined();
});

test('图片先同意再识别，编辑确认后填入，不自动审阅或覆盖原稿', async ({ page }) => {
  let calls = 0, reviewCalls = 0;
  await page.route('**/recognize-work', async route => {
    calls++; expect(route.request().postData()).toContain('consent');
    await route.fulfill({ json:recognition });
  });
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/process-reviews')) reviewCalls++; });
  const row = await prepareProcess(page);
  const original = row.getByLabel('解题过程或伪代码');
  await original.fill('我原来写的过程需要保留，不能被识别静默覆盖。');
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await expect(row.getByRole('button',{name:'识别图片',exact:true})).toBeDisabled();
  expect(calls).toBe(0);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  const draft = row.getByLabel('识别结果，确认前可修改');
  await expect(draft).toHaveValue(recognition.text);
  await expect(original).toHaveValue('我原来写的过程需要保留，不能被识别静默覆盖。');
  await draft.fill('我已核对文字和公式，这是修改后的过程。');
  await expect(row.getByRole('button',{name:'确认并填入过程'})).toBeDisabled();
  await row.getByLabel('用已核对的识别结果替换下方现有过程').check();
  await row.getByRole('button',{name:'确认并填入过程'}).click();
  await expect(original).toHaveValue('我已核对文字和公式，这是修改后的过程。');
  expect(calls).toBe(1); expect(reviewCalls).toBe(0);
});

test('图片识别失败保留原稿，没有自动重试，移除后可重新选择同一文件', async ({ page }) => {
  let calls = 0;
  await page.route('**/recognize-work', async route => { calls++; await route.fulfill({status:503,
    json:{ error:{ code:'vision_output_incomplete',message:'识别未完整返回，未自动重试' } }}); });
  const row = await prepareProcess(page);
  const original = row.getByLabel('解题过程或伪代码');
  await original.fill('需要保留的文字过程，不因失败而被清空。');
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await row.getByLabel(/同意将这张图片/).check();
  await row.getByRole('button',{name:'识别图片',exact:true}).click();
  await expect(row.getByRole('alert')).toContainText('未自动重试');
  expect(calls).toBe(1);
  await expect(original).toHaveValue('需要保留的文字过程，不因失败而被清空。');
  await row.getByRole('button',{name:'移除图片'}).click();
  await row.getByLabel('拍照或选择解题过程图片').setInputFiles(syntheticImage);
  await expect(row.getByAltText('待识别的过程图片预览')).toBeVisible();
  await expect(row.getByLabel(/同意将这张图片/)).not.toBeChecked();
});

test('独立视觉设置默认折叠，刷新保留未保存密钥，保存不修改问答配置', async ({ page }) => {
  let saved: any = null;
  let chatWrites = 0;
  const view = { base_url:'https://api.deepseek.com',model:'deepseek-flash',reuse_chat_model:true,
    configured:true,key_configured:false,max_output_tokens:4000,timeout_seconds:60,csrf_token:'synthetic-csrf',storage_warning:false };
  await page.route('**/api/settings/vision', async route => {
    if (route.request().method() === 'PUT') {
      saved = route.request().postDataJSON();
      expect(route.request().headers()['x-settings-token']).toBe('synthetic-csrf');
      await route.fulfill({json:{...view,reuse_chat_model:false,key_configured:true}});
    } else await route.fulfill({json:view});
  });
  page.on('request', request => { if(request.method() === 'PUT' && request.url().endsWith('/settings/model')) chatWrites++; });
  await page.goto('/settings');
  await expect(page.getByTestId('vision-reuse')).not.toBeVisible();
  await page.getByText('拍照识别模型',{exact:true}).click();
  await page.getByTestId('vision-reuse').uncheck();
  await page.getByTestId('vision-key').fill('synthetic-private-key');
  await page.getByRole('button',{name:'刷新配置',exact:true}).click();
  await expect(page.getByTestId('vision-key')).toHaveValue('synthetic-private-key');
  await page.getByRole('button',{name:'保存视觉配置',exact:true}).click();
  await expect(page.getByText(/已保存。未发送测试图片/)).toBeVisible();
  expect(saved.api_key).toBe('synthetic-private-key'); expect(saved.reuse_chat_model).toBe(false);
  expect(chatWrites).toBe(0); await expect(page.getByTestId('vision-key')).toHaveValue('');
});
