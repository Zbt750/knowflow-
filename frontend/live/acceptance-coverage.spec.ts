import { expect, test, type Page } from "@playwright/test";

// User explicitly requested real acceptance-file checks. No reset, no other materials,
// no evaluator endpoint: only ordinary chat calls to the currently configured model.
const owned = new Set<string>();
const results: Array<Record<string, unknown>> = [];
const expected = ["A", "B", "C", "D", "E", "F", "G"];
const concepts = [/前端|后端|连通|连接|工程底座/, /学习|练习|知识树/, /上传|解析|索引|摄取/, /问答|引用|追练/, /前端|页面|窄屏|布局|四页/, /Docker|容器|部署/i, /人工|冻结|最终|全流程|普通用户|完整.{0,12}(流程|走|路径)|从头到尾/];
const questions = [
  "帮我看我的验收文件的大概讲述内容",
  "验收.md 主要讲了什么？请简要概括。",
  "《验收》有哪些阶段？各自验收什么？",
  "把验收这份文件从头到尾的主要内容总结一下。",
  "你好，我想知道我有一个叫做验收的文件里面大概说了什么内容。",
  "请完整列出验收文件中的每一个阶段，不要只说阶段 A。",
  "帮我看看验收文件都写了些什么",
  "这份验收资料都讲些啥？",
  "验收主要涉及哪些内容？各部分分别干什么？",
];

test.beforeAll(async ({ request }) => {
  const list = await (await request.get("/api/materials?limit=100")).json();
  const target = list.items.find((m: { title: string; source_type: string }) => m.title === "验收" && m.source_type === "user");
  expect(target?.status).toBe("ready");
  const source = await request.get(`/api/materials/${target.id ?? target.material_id}/content`);
  expect(source.status()).toBe(200);
  const reference = await source.json();
  for (const stage of expected) expect(reference.text).toMatch(new RegExp(`阶段\\s*${stage}`));
});

test.afterAll(async ({ request }, info) => {
  await info.attach("acceptance-results.json", { contentType: "application/json", body: Buffer.from(JSON.stringify(results, null, 2)) });
  // Delete only the temporary sessions created by this run; never the original session.
  for (const id of owned) await request.delete(`/api/chat/sessions/${id}`);
});

test.beforeEach(async ({ page }) => {
  // Keep every created test session identifiable without mocking its response.
  await page.route("**/api/chat/sessions", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    return route.continue({ postData: JSON.stringify({ ...body, title: `诊断-验收覆盖-${Date.now()}` }) });
  });
});

async function draft(page: Page) {
  await page.goto("/chat");
  const switcher = page.getByTestId("scope-switch");
  await expect(switcher).toBeEnabled();
  if ((await switcher.getAttribute("aria-label"))?.startsWith("当前内置资料")) await switcher.click();
  await expect(switcher).toHaveAttribute("aria-label", "当前我的资料，切换到内置资料");
  await page.locator('button[title="新建对话"]').click();
}

async function ask(page: Page, question: string, allStages = true) {
  await page.locator("#chat-question").fill(question);
  await expect(page.locator(".send-button")).toBeEnabled();
  const responsePromise = page.waitForResponse(r => r.url().includes("/answers:stream") && r.request().method() === "POST");
  const createdPromise = page.waitForResponse(r => new URL(r.url()).pathname === "/api/chat/sessions" && r.request().method() === "POST", { timeout: 1000 }).catch(() => null);
  const start = Date.now();
  await page.locator(".send-button").click();
  const created = await createdPromise;
  if (created) owned.add((await created.json()).session_id);
  const response = await responsePromise;
  await response.finished();
  const frames = (await response.text()).split("\n\n").filter(Boolean).map(f => ({ event: f.match(/^event: (.+)$/m)?.[1], data: JSON.parse(f.match(/^data: (.+)$/m)?.[1] ?? "{}") }));
  const done = frames.find(f => f.event === "done");
  const answer = String(done?.data.answer ?? "");
  const stages = expected.filter(stage => new RegExp(`阶段\\s*${stage}|(?:^|\\n)\\s*(?:[-*]\\s*)?\\*{0,2}${stage}\\s*[:：、.—–-]`, "m").test(answer));
  results.push({ question, elapsed_ms: Date.now() - start, answer, stages, retrieved: frames.find(f => f.event === "meta")?.data, error: frames.find(f => f.event === "error")?.data });
  console.log(JSON.stringify({ question, characters: answer.length, stages, elapsed_ms: Date.now() - start }));
  expect(frames.find(f => f.event === "error")).toBeUndefined();
  expect(answer.length).toBeGreaterThan(50);
  expect(answer).not.toMatch(/\[citation:\d+\]/);
  if (allStages) {
    expect(stages, "Must cover the actual seven stages, not just produce a completed answer").toEqual(expected);
    const plain = answer.replace(/\*/g, "");
    const mentions = [...plain.matchAll(/阶段\s*([A-G])|(?<![A-Za-z0-9])([A-G])(?=\s*[:：、.．—–(（-]|\s*阶段|\s*\|)/g)];
    for (let i = 0; i < expected.length; i++) {
      const sections = mentions.flatMap((m, index) => (m[1] ?? m[2]) === expected[i]
        ? [plain.slice(m.index!, mentions[index + 1]?.index ?? plain.length)] : []);
      expect(sections.some(section => concepts[i].test(section)), `Stage ${expected[i]} must explain its actual function, regardless of Markdown format`).toBe(true);
    }
    expect(answer).not.toMatch(/只有.{0,10}阶段\s*A|其余阶段.{0,15}(?:没有|无法|缺失)/);
  }
  await expect(page.locator("#chat-question")).toBeEnabled();
  return answer;
}

for (const question of questions) {
  test(`真实验收覆盖：${question}`, async ({ page }) => { await draft(page); await ask(page, question); });
}

test("先细讲阶段A，再重新概述全部阶段", async ({ page }) => {
  await draft(page);
  const a = await ask(page, "只概述验收文件的阶段 A，其余阶段不要讲。", false);
  expect(a).toMatch(/阶段\s*A/);
  expect(a).toMatch(/前端|后端|连通/);
  expect(a).not.toMatch(/(?:^|\n)\s*#{0,4}\s*\*{0,2}阶段\s*[B-G]\s*[:：]/);
  await ask(page, "帮我看我的验收文件的大概讲述内容");
  await ask(page, "每一个阶段都给我细讲一下");
});

test("省略文件名连续追问，不能只沿用上一个阶段", async ({ page }) => {
  await draft(page);
  await ask(page, questions[0]);
  await ask(page, "剩下的阶段呢？请把所有阶段都说全。");
  await ask(page, "这些阶段分别怎么验收，给我完整讲解。");
});

test("原会话旧回答上下文副本，重新概述必须覆盖A到G", async ({ page, request }) => {
  const id = process.env.LIVE_ACCEPTANCE_CLONE_ID;
  test.skip(!id, "Requires a separately created diagnostic copy, never the original session");
  const sessions = await (await request.get("/api/chat/sessions?mode=user")).json();
  expect(sessions.find((s: { session_id: string; title: string }) => s.session_id === id)?.title).toBe("诊断-验收旧会话副本");
  owned.add(id!);
  await page.goto(`/chat?session_id=${id}`);
  await expect(page.getByTestId("scope-switch")).toBeEnabled();
  await ask(page, questions[0]);
  await ask(page, "每一个阶段都给我细讲一下");
});

test("具体规则不能用泛泛的阶段概述代替", async ({ page }) => {
  await draft(page);
  const c = await ask(page, "验收文件里阶段 C 的重建索引和删除资料，分别要检查什么？", false);
  expect(c).toMatch(/旧索引/);
  expect(c).toMatch(/成功.{0,15}(切换|新版本)|切换.{0,15}(成功|新版本)/);
  expect(c).toMatch(/删除/);
  expect(c).toMatch(/不能.{0,15}检索|不再.{0,15}检索|无法.{0,15}检索/);
  const f = await ask(page, "验收文件里阶段 F 要如何验证数据不会丢？停止容器时有哪些禁忌？", false);
  expect(f).toContain("docker compose down");
  expect(f).toContain("-v");
  expect(f).toMatch(/不能|不要|禁止/);
  expect(f).toMatch(/资料/);
  expect(f).toMatch(/练习|记录/);
  expect(f).toMatch(/对话|问答/);
});
