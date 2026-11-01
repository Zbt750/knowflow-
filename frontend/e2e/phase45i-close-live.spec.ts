// Real Vue -> real backend -> frozen DeepSeek payload -> real isolated DB.
import {test,expect} from '@playwright/test';
test('explicit five-item request reports actual saves and supports study/history without paid calls',async({page,request})=>{
  test.skip(process.env.PHASE45I_CLOSE_BROWSER !== '1', 'Requires the dedicated isolated Phase 4.5I browser backend and frozen provider.');
  const api=process.env.E2E_API_BASE!;
  const stats=async()=>await (await request.get(api+'/_phase45i/stats')).json();
  await page.goto('/study');await expect(page.getByTestId('focus-stem')).toContainText('TEST_FIXTURE');
  await page.getByTestId('study-frog-launcher').click();
  const send=async(text:string)=>{
    await page.getByTestId('task-goal').fill(text);
    const response=page.waitForResponse(r=>r.url().includes('assistant:stream'));
    await page.getByTestId('task-arrange').click();const r=await response;await r.body();return r;
  };
  await send('请解释导数的含义，不需要新题');expect((await stats()).frozen_provider_calls).toBe(0);
  await send('帮我安排现有题的复习');expect((await stats()).frozen_provider_calls).toBe(0);
  await send('给我生成5道这个知识点的练习题。');
  // The product deliberately requires a user-confirmed assessable node before
  // generation. Exercise that real step instead of treating intent as consent.
  const confirmation=page.getByTestId('generation-confirmation');
  await expect(confirmation).toBeVisible();
  await expect(confirmation.getByTestId('generation-node-select')).toHaveValue(/.+/);
  const generationResponse=page.waitForResponse(r=>r.url().includes('assistant:stream'));
  await confirmation.getByTestId('confirm-generation-node').click();
  const response=await generationResponse;await response.body();
  const original=response.request().postDataJSON();
  await expect(page.getByTestId('frog-conversation')).toContainText('1道通过检查');
  let state=await stats();expect(state.frozen_provider_calls).toBe(5);expect(state.personal_count).toBe(1);expect(state.practice_items).toBe(1);
  const generated=state.personal_questions[0];
  expect(generated.kp_id).toBeTruthy();expect(generated.current_version_id).toBeTruthy();
  expect(generated.version_number).toBe(1);expect(generated.content_hash).toMatch(/^[a-f0-9]{64}$/);
  expect(generated.version_stem).toContain('3x');
  expect(generated.evidence_capability).toBe('personal_practice_only');
  expect(state.personal_practice_bindings).toHaveLength(0);
  expect(state.personal_attempt_bindings).toHaveLength(0);
  const appendResponse=page.waitForResponse(r=>r.url().endsWith('/api/personal-questions/append')&&r.request().method()==='POST');
  await page.getByTestId('personal-generation-result').getByRole('button',{name:'加入今日学习'}).click();
  expect((await (await appendResponse).json()).added).toBe(1);
  state=await stats();expect(state.practice_items).toBe(2);expect(state.personal_practice_bindings).toHaveLength(1);
  expect(state.personal_practice_bindings[0]).toMatchObject({question_id:generated.question_id,
    question_version_id:generated.current_version_id,kp_id:generated.kp_id});
  const duplicateAppend=await request.post(api+'/api/personal-questions/append',{data:{question_ids:[generated.question_id]}});
  expect(duplicateAppend.ok()).toBeTruthy();expect((await duplicateAppend.json()).added).toBe(0);
  state=await stats();expect(state.practice_items).toBe(2);expect(state.personal_practice_bindings).toHaveLength(1);
  const duplicate=await request.post(response.url(),{data:original});await duplicate.body();
  state=await stats();expect(state.frozen_provider_calls).toBe(5);expect(state.personal_count).toBe(1);
  await page.getByRole('button',{name:'收起奶蛙对话'}).click();
  await page.getByTestId('continue-question').click();await expect(page.getByTestId('focus-stem')).toContainText('3x');
  await page.getByTestId('option-A').click();
  const submitted=page.waitForResponse(r=>r.url().endsWith('/answer-submissions')&&r.request().method()==='POST');
  await page.getByTestId('submit-answer').click();const submission=await (await submitted).json();
  expect(submission.result).toBe('right');expect(submission.effective_confirmation_count).toBe(0);
  expect(submission.question_version_id).toBe(generated.current_version_id);
  await expect(page.getByTestId('answer-submission-notice')).toBeVisible();
  await page.getByTestId('answer-explanation').click();await expect(page.getByTestId('focus-answer')).toContainText('逐项求导');
  const history=await (await request.get(api+`/api/practice-items/${submission.practice_item_id}/answer-submissions`)).json();
  expect(history.items.some((r:any)=>r.attempt_id===submission.attempt_id&&r.question_version_id===generated.current_version_id)).toBeTruthy();
  state=await stats();expect(state.personal_attempt_bindings).toEqual([expect.objectContaining({question_id:generated.question_id,
    question_version_id:generated.current_version_id,objective_result:'right'})]);
  expect(state.personal_learning_event_bindings.length).toBeGreaterThan(0);
  expect(state.personal_learning_event_bindings.every((e:any)=>e.question_version_id===generated.current_version_id)).toBeTruthy();
  expect(state.strict_evidence_count).toBe(0);expect(state.mastered_at).toBeNull();expect(state.state).toBe('unseen');
  await page.reload();await page.getByTestId('full-paper').click();
  await expect(page.getByTestId(`paper-submission-${submission.practice_item_id}`)).toHaveAttribute('aria-label','答案正确');
  await page.goto('/knowledge?node=math.exam.de439863790e&tab=questions');
  const bank=page.getByTestId('question-bank');
  await expect(bank).toContainText('AI练习');
  const generatedQuestion=bank.getByTestId('personal-node-question');
  await generatedQuestion.getByRole('button',{name:'隐藏',exact:true}).click();
  await expect(bank.getByTestId('personal-node-question')).toHaveCount(0);
  await expect(page.getByText('个人 AI 题库',{exact:true})).toHaveCount(0);
  state=await stats();expect(state.attempt_count).toBe(1);expect(state.learning_event_count).toBe(1);
  const historicalVersionId=state.personal_practice_bindings[0].question_version_id;
  expect(state.personal_attempt_bindings[0].question_version_id).toBe(historicalVersionId);
  expect(state.personal_learning_event_bindings.length).toBeGreaterThan(0);
  expect(state.personal_learning_event_bindings.every((e:any)=>e.question_version_id===historicalVersionId)).toBeTruthy();
  expect(state.personal_question_versions.some((v:any)=>v.question_version_id===historicalVersionId)).toBeTruthy();
  expect(state.strict_evidence_count).toBe(0);expect(state.mastered_at).toBeNull();expect(state.state).toBe('unseen');expect(state.paid_calls).toBe(0);
});
