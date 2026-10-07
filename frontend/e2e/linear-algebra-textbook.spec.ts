import { expect, test } from '@playwright/test';
import { readdirSync, readFileSync } from 'node:fs';

const lessonDir = new URL('../../seed/lessons/', import.meta.url);
const linearExamCodes = new Set([
  'math.exam.f4e5ed0360ea', 'math.exam.44eab8b0d00b', 'math.exam.08a5efb8a98d',
  'math.exam.985c26775327', 'math.exam.c106a40cda48', 'math.exam.9bda63607d7e',
  'math.exam.6df0d75f1b07', 'math.exam.f29397bf3b27', 'math.exam.7d6f5725a5ab',
  'math.exam.0aad93648d60', 'math.exam.f99711e0ea65', 'math.exam.8b6ba0b9a789',
  'math.exam.36050d277510', 'math.exam.9a1731a929ab', 'math.exam.712e07e16572',
  'math.exam.90bbbeb58b4a', 'math.exam.7af99f485eff', 'math.exam.8d8ad14b2a44',
  'math.exam.0949f5ff08f9',
]);
const lessons = readdirSync(lessonDir).filter(name => name.endsWith('.md')).map(name => ({
  code: name.slice(0, -3), markdown: readFileSync(new URL(name, lessonDir), 'utf8'),
})).filter(lesson =>
  (lesson.code === 'math.linear-algebra' || lesson.code.startsWith('math.linear-algebra.') || linearExamCodes.has(lesson.code))
  && !lesson.code.includes('.family.')
  && lesson.markdown.includes('knowledge-lesson-quality:subject-textbook-draft-v3'),
);

test('线性代数27份讲解可独立阅读，公式无渲染错误', async ({ page }) => {
  test.setTimeout(300000);
  expect(lessons).toHaveLength(27);
  const errors: string[] = [];
  const pageConsole: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') pageConsole.push(message.text()); });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const code = decodeURIComponent(url.pathname.split('/').pop() ?? '');
    const lesson = lessons.find(row => row.code === code);
    if (url.pathname.startsWith('/api/knowledge/lessons/') && lesson) {
      const name = lesson.markdown.match(/^# (.+)$/m)?.[1];
      return route.fulfill({ json: { id: code, code, name, subject: '数学二', is_assessable: true,
        markdown: lesson.markdown, breadcrumbs: [{ code, name }], question_count: 0, exam_reference_count: 0 } });
    }
    return route.fulfill({ json: { status: 'ok', database: 'connected', sessions: [], recommendations: [] } });
  });
  for (const lesson of lessons) {
    await page.goto(`/knowledge/${lesson.code}/lesson`);
    const article = page.getByTestId('lesson-article');
    await expect(article).toContainText('例题');
    await expect(article).toContainText(lesson.markdown.match(/^# (.+)$/m)![1]);
    await expect(article.locator('.katex').first()).toBeVisible();
    await expect(article.locator('.katex-error')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(pageConsole).toEqual([]);
});
