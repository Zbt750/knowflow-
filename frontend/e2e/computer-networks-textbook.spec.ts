import { expect, test } from '@playwright/test';
import { readdirSync, readFileSync } from 'node:fs';

const lessonDir = new URL('../../seed/lessons/', import.meta.url);
const lessons = readdirSync(lessonDir).filter(name => name.endsWith('.md')).map(name => ({
  code: name.slice(0, -3), markdown: readFileSync(new URL(name, lessonDir), 'utf8'),
})).filter(lesson =>
  (lesson.code === 'cs408.cn' || lesson.code.startsWith('cs408.cn.topic.'))
  && lesson.markdown.includes('knowledge-lesson-quality:subject-textbook-draft-v3'),
);

test('计算机网络40份节点讲解可阅读，公式无渲染错误', async ({ page }) => {
  test.setTimeout(300000);
  expect(lessons).toHaveLength(40);
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
      return route.fulfill({ json: { id: code, code, name, subject: '408', is_assessable: true,
        markdown: lesson.markdown, breadcrumbs: [{ code, name }], question_count: 0, exam_reference_count: 0 } });
    }
    return route.fulfill({ json: { status: 'ok', database: 'connected', sessions: [], recommendations: [] } });
  });
  for (const lesson of lessons) {
    await page.goto(`/knowledge/${lesson.code}/lesson`);
    const article = page.getByTestId('lesson-article');
    await expect(article).toContainText(lesson.markdown.match(/^# (.+)$/m)![1]);
    if (lesson.code !== 'cs408.cn') await expect(article).toContainText('例题');
    if (lesson.markdown.includes('$')) await expect(article.locator('.katex').first()).toBeVisible();
    await expect(article.locator('.katex-error')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(pageConsole).toEqual([]);
});
