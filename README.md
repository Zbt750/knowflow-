# 考研知识库（掌握度自适应学习）

本地单用户的考研学习知识库：知识树 + 今日学习卷 + 资料摄取与可信检索 + 可信问答与题库追练。

- 不实现：登录、多用户、JWT、Redis、Celery、微服务、独立通用 OCR 服务、联网搜题、LLM 自动生成正式题、记忆卡 SRS、笔记模块、统计页面。
- 部署目标是 **Docker Compose 本地部署**，不做公网云部署。

## 当前进度

2026-10-02 增加“照片录入过程”：在今日学习的折叠式过程审阅中选择图片，明确同意发送至模型，识别后编辑确认，再由用户主动发起原有文字/伪代码辅助审阅。支持独立视觉配置或复用支持图片的问答模型；不自动判分、不更新掌握度、不保存图片到项目存储。真实手写准确率尚未验证，详情见 [照片录入说明](docs/photo-transcription-2026-10-02.md)。

随后完成6张合成手写照片、2次过程审阅的受限真实验收，关键内容和遮挡处理本轮符合预期，但不能推为真实学生手写准确率。发现并修复共享Markdown反斜杠公式渲染问题，新增折叠公式预览；伪代码转写Prompt另补纯文本约束，该Prompt更新尚待真实复测。详见 [合成照片真实验收](docs/photo-handwriting-live-review-2026-10-02.md)。

下一轮已定点复测v2伪代码/遮挡两例：本次伪代码保持纯文本和缩进、遮挡未猜写；代码样例耗时反而增加，未宣称效率提升。新增可切换代码预览，展示切换不改原稿。详见 [v2定点收口](docs/photo-transcription-v2-closeout-2026-10-02.md)。

2026-10-01 的 P3 增加知识节点“学习证据”视图：概念与条件、最终结果计算、变式与应用、证明与讨论（408 另含算法与程序）。依据当前有效作答和待复测只读展示，不给掌握百分比、不改变毕业规则；Agent 读取同一计算结果的精简摘要。过程能力不由最终答案或 AI 辅助审阅确认，原卷引用不冒充在线题。实现边界与本轮测试见 [P3 能力证据说明](docs/capability-evidence-p3-2026-10-01.md)。

P4 按黄金候选的实际需求补有限自然对数最终答案比较器与数值分数输入格式，保留未核验/不支持时的 unknown，不做通用符号判等或过程判题。专注和整卷仅调整输入提示，候选未晋级或导入。范围、证据门禁和测试见 [P4 判题说明](docs/bounded-final-grading-p4-2026-10-01.md)。

2026-10-01 的 P2 增加同题“再试一次”和默认折叠的作答记录，保留每次答案与证据。立即自行改正、看解析后完成和新安排的独立复测分开记录；即时改正不新增独立确认、不自动清除错题复测。前端响应丢失重试幂等、跨窗口过期提交受保护，旧自述不回填为机器判题。范围、限制与本轮测试见 [P2 同题作答与证据](docs/attempt-sequence-evidence-p2-2026-10-01.md)。P1 黄金候选仍待人工内容核验；照片录入进展见上方本轮说明。

2026-09-30 增加文字/伪代码过程辅助审阅、反馈恢复与本卷作答小结，保持折叠入口和简约布局；审阅不判分、不修改掌握度，后续答案记录为辅助作答。另提供实际证据事实清单、知识资产只读审计。范围与限制见 [本轮说明](docs/process-review-and-quality-audits-2026-09-30.md)。图片审阅与安装包属于后续独立工作，不计为当前功能完成。

今日学习也可从小结中的折叠“回看错题”直接回到本卷已判错题目，阅读解析；回看不重复产生作答记录或清除待复测。见 [错题回看说明](docs/study-wrong-answer-revisit-2026-09-30.md)。

见 `docs/reference-build-status.md` 第 1 节。**参考版本的阶段 A–G 已完成验收，Docker Compose 已实际部署验证，并打过 `reference-project-verified-v1` 标签。** 当前工作区有标签之后的前端迭代；标签的验证结果不自动覆盖这些未冻结改动，需以本轮回归结果为准。

本轮（2026-09-24）针对前端问题的回归：`npm run typecheck`、`npm run build` 通过；隔离测试库按 `scripts/run-e2e.ps1` 准备后，**77 条 E2E 全通过、0 跳过**；新增资料正文接口的 2 条直接测试通过。本轮未重新执行全量后端 pytest 或 Docker 验收，不能把旧冻结标签当成当前工作区的新冻结结论。

已完成的能力：

- 知识树：父节点只汇总、可考核叶子绑定练习题；历年题号通过独立来源索引关联，不进入掌握度与今日练习
- 今日学习：准备页推荐 → 用户确认 → 生成练习卷 → 专注/全卷模式 → 提交最终答案或折叠式自行对照 → 追加练习题
- 毕业规则：每个可考核叶子拥有独立 `MasteryPolicy`，可靠独立正确结果按题量、题型配额、考法标签、变式题数量和跨天跨度共同判断；新节点及练习自述均不增加确认，旧历史保留但不改写为客观证据
- 查看答案始终可用，且是纯读取，不影响掌握度与毕业
- 资料库：上传 Markdown / TXT / DOCX / 文本层 PDF → 后台任务解析、按标题树分块 → 建立向量与关键词索引 → 状态变为「可检索」后可被引用
- 混合检索：正文向量 + 正文 BM25 + 标题树 BM25（资料名/章节名命中后扩展子树），RRF 融合；历史基准 Hit@6 = 1.000、MRR@6 = 0.962 来自新增标题路前的 14 条中文用例，扩展后需重新评测
- 引用可回跳：每个块都满足 `content == normalized_text[start:end]`，正文权威始终在 PostgreSQL

- 可信问答：两种模式严格隔离（内置资料 / 我的资料），先检索后回答，引用只来自本次命中的 chunk，支持 POST SSE 流式与停止；追问只记弱信号，追练候选只从已有题库取

- **归因依据可见**：回答下方显示「归因到哪个叶子知识点、依据是正文里的哪一个来源编号（如 [C1]）、检索命中第几位、语义相关度多少」。
  归因决定推荐哪些追练题，所以它不能只给结论 —— 用户据此能自己判断这次归因是否符合预期。
  依据随消息落库（`chat_messages.matched_kp_basis`），刷新后仍在；「我的资料」模式按契约不做归因与追练。
- **归因阈值建在语义相关度上**（原始向量余弦，`KP_MIN_COSINE`），**不是** RRF 融合分：
  融合分只看名次，任何第一名都必然拿到约 0.03，越界问题（知识库里根本没有）也不例外；
  实测正常命中余弦 0.57–0.83、越界最高 0.34。因此问「这个软件怎么安装」这类问题时
  不再被硬凑一个知识点，也就不会给出无关的追练题。
- **追练推荐与困惑标记只认「当前这条回答」的归因**：不会回溯历史里旧回答的知识点，
  当前回答没归因时按钮不可点、候选为空。

参考版本的阶段 E、F、G 验收记录分别见 `docs/reference-build-status.md` 第 22、26、27 节；包括 OpenAPI 契约、十态状态矩阵、前进/后退、窄窗口、容器内功能与数据持久化验证。

**设置页现支持本机模型配置**（`SettingsPage.vue`）：在 `APP_ENV=dev`、本机 loopback 访问时，可保存接口地址、模型 ID、密钥、输出上限和超时，下一次问答立即生效，无需重启；正在生成的回答继续使用原配置。密钥留空保留原值，主动勾选移除才清除，保存后输入框清空，接口不会回显密钥。

配置保存在被 Git 忽略的 `storage/config/model-settings.bin`，不修改原 `.env`。本机保存值在 dev 重启后优先于 `.env`；Windows 使用当前用户的 DPAPI 加密，其他系统使用权限为 0600 的本地文件（不是加密存储）。Windows 配置不能直接迁移到另一台电脑或另一个用户，需要重新填密钥。损坏的本机配置会停用旧密钥并在设置页提示重新保存，不会偷偷回退使用另一套密钥。

**生产 Web 配置接口仍禁用**：项目尚无登录与访问控制，`APP_ENV=prod/test`、远程客户端、非本机 Host、转发头和跨站来源均不能读取或写入模型配置。保存要求本机读取取得的 `X-Settings-Token`，响应禁止缓存。公网或反向代理部署必须显式设置 `APP_ENV=prod`，配置仍由管理员通过环境变量管理。`key_configured` 只代表已填密钥，不是上游连通性或余额验证。桌面安装包本身仍未完成。

### Markdown 与前端验证

`MarkdownContent.vue` 统一渲染 AI 回答、资料正文和知识讲解：先用 marked 解析，再经 DOMPurify 净化，禁止 img/iframe/style；公式按需加载 KaTeX 与样式，`trust=false`，代码块不参与公式解析。异步加载期间会核对最新文本与组件生命周期，避免旧回答渲染到新内容。加载失败保留原文并提示刷新。

页面路由按需加载，首次进入不再下载全部页面及公式库。前端可执行 `npm run test:unit`（Vitest，纯逻辑回归）、`npm run typecheck`、`npm run build`；完整浏览器回归仍按项目 E2E 隔离库流程执行。

后端业务错误、校验错误、未匹配路由、方法错误和未捕获异常共用 `{error:{code,message,details?}}`。422 的 details 只含安全字段名、规则代码和中文提示，不含原始 input/body、异常文本或敏感上下文。OpenAPI 快照和前端类型同步生成。

> 检索默认**不启用重排**（`RERANKER_MODEL` 为空），这是正常配置而不是降级；
> 配置了模型但加载失败时会自动退回融合顺序并如实报告 `degraded_reasons`。

> **注意推理模型的输出预算。** 如果 `LLM_MODEL` 用的是推理模型
> （如 `deepseek-flash`，会先输出 `reasoning_content` 思考再输出正文），
> **思考与正文共享 `LLM_MAX_OUTPUT_TOKENS`**。实测该项目在 `800` 时
> 出现过「正文只剩 9 字」甚至正文为空（表现为「回答生成失败」），
> 因为长 prompt 的思考就能吃掉上千 token。
> 因此默认取 `4000`，并额外配置 `LLM_RETRY_MAX_OUTPUT_TOKENS=8000`：
> 首轮达到输出上限时，即使已有半截正文，也会**以更大预算**完整重生成一次；
> 前端替换旧正文，不拼接两个回答。恢复预算至少为基础预算两倍（自动翻倍最多 32768），
> 同时尊重更大的显式重试配置。一般网络错误在已有正文时不会自动重放。
> 网络静默仍受请求超时控制；详细回答及恢复轮次的总生成时限为请求超时两倍、最多 180 秒。
> 两轮仍失败时保留未完成正文和失败标记，不宣称完成、不提供可用引用。
> 排查时查看日志 `detail` 的 budget、content_chars、reasoning_chars；不记录思考原文或密钥。
> 真实前端测试方法与边界见 [问答浏览器测试](docs/live-front-chat-check.md)。

## 环境要求

| 组件 | 本机已验证版本 |
|---|---|
| Python | 3.12.10 |
| Node / npm | 24.18.0 / 11.16.0 |
| PostgreSQL | 18.4 |
| 浏览器（Playwright 用） | 系统 Google Chrome |

## 首次准备

### 1. 数据库

本机系统 PostgreSQL 服务无法启动时，使用项目内独立集群（端口 5433）：

```powershell
# 初始化（只在第一次执行）
& 'C:\Program Files\PostgreSQL\18\bin\initdb.exe' -D 'D:\考研跑通项目\.pgdata' -U postgres -E UTF8 --locale=C -A trust

# 启动
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\考研跑通项目\.pgdata' -l 'D:\考研跑通项目\.pgdata\server.log' -o "-p 5433 -c listen_addresses=127.0.0.1" start

# 建角色与库
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -p 5433 -U postgres -d postgres -c "CREATE ROLE kaoyan LOGIN PASSWORD 'kaoyan_dev_pw';"
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -p 5433 -U postgres -d postgres -c "CREATE DATABASE kaoyan OWNER kaoyan ENCODING 'UTF8';"
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -p 5433 -U postgres -d postgres -c "CREATE DATABASE kaoyan_test OWNER kaoyan ENCODING 'UTF8';"

# 停止
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\考研跑通项目\.pgdata' stop
```

### 2. 配置

```powershell
Copy-Item .env.example .env
# 按本机情况修改 .env；.env 已被 .gitignore 排除，绝不提交
```

### 3. 迁移

```powershell
python -m alembic upgrade head
python -m alembic current      # 期望显示最新 revision + (head)
python -m alembic check        # 期望 No new upgrade operations detected.
```

## 常用命令（CMD，项目根目录执行）

| 命令 | 作用 |
|---|---|
| `scripts\start-dev.cmd` | 启动 PostgreSQL + 后端 + 前端，确认就绪后返回 |
| `scripts\stop-dev.cmd` | 停止全部服务 |
| `scripts\status.cmd` | 查看服务状态、今日学习、每个叶子的毕业条件缺口 |
| `scripts\reset-today.cmd` | 重置今日学习，让「生成今日练习卷」可重新走一遍 |
| `scripts\shift-days.cmd` | 只看当前毕业条件 |
| `scripts\shift-days.cmd 2` | 跨天毕业测试：把学习历史整体挪到 2 天前 |
| `scripts\shift-days.cmd -2` | 移回真实时间 |
| **`scripts\graduate-demo.cmd first`** | **一键准备第一天：做完题并把时间移到两天前** |
| **`scripts\graduate-demo.cmd retest`** | **一键准备复测日：把一道复测题放到今天的卷里** |
| `scripts\graduate-demo.cmd show` | 只看当前毕业缺口 |
| `scripts\seed.cmd` | 灌入 / 刷新种子知识点与题库（幂等） |
| `scripts\test.cmd` | 跑全部测试：pytest + alembic check + 前端构建 + 端到端 |

> `start-dev.cmd` 内部调用同名 `.ps1`（用 `powershell -ExecutionPolicy Bypass -File`），
> 因此不需要修改任何执行策略设置；后端与前端各开一个独立窗口，日志直接可见。

## 一键启动（PowerShell 等价写法）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
```

脚本会依次确认 PostgreSQL 可接受连接、后端 `/api/health` 返回 200、前端端口就绪，
然后打印地址并立刻退出（约 8 秒）。后端与前端各开一个独立窗口，日志直接可见。

- 停止全部服务：`powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1`
- 重新演示「今日学习」主流程：`powershell -ExecutionPolicy Bypass -File scripts\reset-today.ps1`

### 为什么要用 reset-today

产品规则规定**同一天不能重新生成整卷**，所以点过一次「生成今日练习卷」后，
再进 `/study` 会直接进入答题态。想重新走一遍完整流程，先执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\reset-today.ps1
```

它会清空 `daily_plans`、`practice_items`、`question_attempts`、`learning_events`，
并把所有叶子状态复位为 `unseen`；**知识点与题库保留**。之后刷新 `http://127.0.0.1:5173/study`
就会重新出现准备页与推荐列表，「生成今日练习卷」按钮可以再次点击。

> 后端不暴露任何重置接口，这个动作只能由本机脚本显式执行。

### 不等两天，完整验证一次「跨天毕业」

**2026-09-30 更新：以下为旧自评演示的历史说明，不再适用于当前规则。** `graduate-demo.cmd first/retest` 已在连接数据库前拒绝执行；`show` 保留只读查询。请用 `python -m pytest tests/unit/mastery/test_objective_evidence.py -q` 核验客观确认规则，用 `python -m pytest tests/integration/test_learning_loop.py::test_self_reports_across_three_days_do_not_graduate -q` 核验跨天自述不会毕业。不要按旧指引清空真实学习数据。

<details>
<summary>旧自评演示记录（已停用）</summary>

这里要区分两个时间概念：

- **毕业前的跨天确认**：由该知识点的 `MasteryPolicy.min_day_span` 决定。当前种子策略通常要求首尾有效确认至少跨 2 个上海自然日。
- **毕业后的复测日期**：知识点毕业后才会生成 `next_review_at`，默认第一轮为 7 天后。它不是“等待两天才能毕业”的同一个条件。

当天一次性做完全部题时，跨天跨度仍然是 0，因此系统不应立即让知识点毕业。开发验收时不需要真的等待，也不要修改 Windows 系统时间；使用演示脚本平移**演示数据库中的学习时间**即可。

如果只想快速验证后端规则、API 和数据库落库，可以先运行这一条集成测试：

```cmd
python -m pytest tests/integration/test_learning_loop.py::test_graduation_succeeds_after_cross_day_confirmation -q
```

测试通过表示：同一天完成全部其他门槛时仍不能毕业，时间推进到第三个上海自然日并再次确认后可以毕业，同时会写入 `mastered_at` 和默认 7 天后的 `next_review_at`。测试通过注入时钟模拟日期，只操作 `kaoyan_test` 测试库，不修改开发库，也不需要等待。

下面的页面演示用于继续验证前端交互、真实 API 和开发库能够一起完成毕业链路。

> **数据提醒：** `graduate-demo.cmd first` 会清空当前计划、作答、学习事件和所有叶子的掌握状态，但保留知识树、题库和毕业策略。只应在 `D:\考研跑通项目` 的本地演示库中使用；有需要保留的真实练习记录时不要执行。

#### 第一步：启动并确认服务正常

```cmd
scripts\start-dev.cmd
scripts\status.cmd
```

如果尚未灌入种子数据，先运行：

```cmd
scripts\seed.cmd
```

#### 第二步：准备“两天前”的第一轮学习记录

```cmd
scripts\graduate-demo.cmd first
```

该命令会：

1. 清理旧的演示学习记录；
2. 选择默认的“洛必达法则”知识点；
3. 通过真实的组卷与自评 Service 完成第一轮题目；
4. 把这轮作答、学习事件和状态时间整体前移 2 天；
5. 输出当前每条毕业条件的完成情况。

此时知识点通常只缺一次今天的确认，状态不应被脚本直接改成 `mastered`。

也可以指定其他知识点名称关键词：

```cmd
scripts\graduate-demo.cmd first --kp 等价无穷小
```

#### 第三步：把复测题放进今天的练习卷

```cmd
scripts\graduate-demo.cmd retest
```

脚本会优先按当前毕业缺口选择题目；没有新题可选时，会取一道人已做过、最适合复测的题恢复为待做。它只准备题目，不会替用户完成最后一次确认。

#### 第四步：在前端亲手完成最后一次确认

打开 `http://127.0.0.1:5173/study`，完成专注模式中出现的复测题并选择“已掌握”。然后运行：

```cmd
scripts\graduate-demo.cmd show
scripts\status.cmd
```

通过标准：

- 页面显示该知识点为“已毕业”；
- `graduate-demo.cmd show` 显示所有毕业条件均满足；
- 确认日期首尾相差至少该策略要求的天数；
- 数据库中的知识点状态为 `mastered`；
- `mastered_at` 有值；
- `next_review_at` 已生成，默认是毕业后的第 7 天；
- 练习记录中保留第一轮和本次复测的真实 `QuestionAttempt`。

如果最后仍未毕业，先看 `graduate-demo.cmd show` 输出的具体缺口。不同知识点的门槛不同，可能缺少指定题型、考法标签、变式题或真实题目数量，不能再用“固定做满三题”判断。

#### 第五步：重新演示

再次执行 `scripts\graduate-demo.cmd first` 会重新准备整套演示数据。只想重新生成今天的卷，可使用：

```cmd
scripts\reset-today.cmd
```

`shift-days.cmd` 是更底层的诊断工具，会整体修改已有学习时间。普通毕业演示优先使用 `graduate-demo.cmd`，避免方向传错或重复平移。

</details>

## 手动运行

### 后端

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- OpenAPI：<http://127.0.0.1:8000/docs>

### 前端

```powershell
cd frontend
npm install
npm run dev
```

- 页面：<http://127.0.0.1:5173>（默认跳转 `/study`）
- 开发期 Vite 把相对 `/api` 代理到 `http://127.0.0.1:8000`

## 种子数据

```powershell
python scripts/seed.py        # 按 code 幂等 upsert；可重复执行
```

- `seed/syllabus.json`：11 个知识点，其中 5 个可考核叶子
- `seed/questions.json`：当前共 22 道题，各叶子为 4–5 道；题量和题型按各自毕业策略配置，不再固定为每个叶子 3 道题
- 每个叶子的题库必须覆盖其 `MasteryPolicy` 要求的真实题量、题型配额、考法标签和变式题；覆盖不足时生成练习卷会返回 `question_pool_incomplete`
- `seed/lessons/<知识点 code>.md`：系统讲解文件。知识树节点可打开独立阅读页；历年题号关联规则与来源边界见 [`docs/exam-question-reference-index.md`](docs/exam-question-reference-index.md)。
- `seed.py` 会按文件名和内容哈希幂等导入叶子讲解，以及 `seed/materials/builtin/*.md` 下的项目自编参考资料为 `builtin` 资料，再由后台任务建立问答索引；文件正文仍是阅读页的唯一来源。修改讲解后重跑 `seed.py` 即可更新索引，已上传的个人资料不会因此被覆盖。
- 数学（二）和 408 原创核心讲义、历年试卷来源索引见 `seed/materials/builtin/` 与 `resources/考研统考资料_数学二_408_2000至2026/`。公开仓库只收录原创讲解与来源链接，不镜像整套无明确再发布许可的真题/商业解析；现有来源目录不是逐题考点映射的完成声明。

需要重新演示今日主流程时（同一天不允许重新生成整卷）：

```powershell
python scripts/reset_today.py
```

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 探活；数据库不可用返回 503，并报告 `retrieval` / `worker` 状态 |
| GET | `/api/knowledge/tree` | 知识树；父节点 `state` 为 null |
| GET | `/api/knowledge/{kp_id}` | 叶子详情：状态、题库、练习记录 |
| GET | `/api/knowledge/lessons/{code}` | 系统讲解 Markdown、章节路径与关联题数 |
| POST | `/api/knowledge/{kp_id}/self-assessment` | 叶子整体自评（父节点返回 409） |
| GET | `/api/plans/today` | 无卷时返回 `setup` + 推荐，有卷时返回活动计划 |
| POST | `/api/plans/today/generate` | 生成今日练习卷；同一天只能成功一次 |
| GET | `/api/plans/{plan_id}/items` | 读取练习卷 |
| POST | `/api/plans/{plan_id}/questions` | 从已有题库追加到卷尾 |
| GET | `/api/practice-items/{item_id}/answer` | 答案与解析（纯读取） |
| POST | `/api/practice-items/{item_id}/self-assessments` | 一道题的自评（含 skip） |
| POST | `/api/materials` | 上传资料（multipart；标题与来源用 query 参数）并加入处理队列 |
| GET | `/api/materials` | 资料列表 + 分状态统计 |
| GET | `/api/materials/{id}` | 资料详情：块数、索引版本、最近任务 |
| GET | `/api/materials/{id}/chunks` | 块预览（标题路径、字数、知识点编号） |
| DELETE | `/api/materials/{id}` | 删除资料（同时清理向量与关键词索引） |
| POST | `/api/materials/{id}/reindex` | 重建索引（新建一条任务） |
| POST | `/api/materials/{id}/retry` | 重试失败资料 |
| POST | `/api/materials/search` | 调试用混合检索（与问答同一链路） |

错误响应统一为 `{"error": {"code": ..., "message": ...}}`。

## 测试与评估

> **pytest 与 e2e 的前置条件正好相反**，这一点必须知道，否则会白跑或误判：
>
> - `python -m pytest` 用独立的 `kaoyan_test` 库，**不需要后端**，
>   而且**要求后端没在运行**：后端会占用嵌入模型与 Chroma 的内存，
>   本机内存有限时曾把 PostgreSQL 挤到被系统杀掉（需要崩溃恢复）。
> - `npm run test:e2e` 用真实浏览器打 `/api/*`，**必须有后端在运行**。
>
> `scripts\test.cmd` 会分别检查这两种前提：后端在跑时**跳过 pytest**、
> 后端没跑时**跳过 e2e**，并以非零码结束、打印 `PARTIAL`，
> 绝不会把「跳过」算成「通过」。

```powershell
# 后端（pytest.ini 已固定 APP_ENV=test 与 kaoyan_test）
# 前置：先停掉后端（scripts\stop-dev.cmd）
python -m pytest

# 前置环境检查（--strict 要求后端未运行；--need-backend 要求后端已运行）
python scripts\check_test_env.py

# 前端类型检查与构建
cd frontend
npm run build

# 前端浏览器测试（使用系统 Chrome）
# 前置：后端必须已经在运行（脚本会给出提示，不会静默失败）
#   scripts\start-dev.cmd
npm run test:e2e
```

> **端到端测试不会碰你自己的资料。** 它只创建、也只清理带 `E2E-` 前缀的测试资料，
> 并且按「用例开始时的资料 id 基线」做差集，用例失败时同样会清理。
> 代码里**没有**「清空资料库」这种能力 —— 验收命令绝不该是破坏性的操作。
>
> 会话历史则**没有**同等的隔离：聊天用例新建会话会留下「新对话」条目。
> 这是已知问题，处理方式见 `docs/reference-build-changes.md` 的 D-19。

```powershell
# 资料端到端验收（真实模型 + 真实向量库 + 真实 HTTP，需后端已启动）
# 会记录起始资料，结束后只删自己创建的那一条，并逐条核对你的资料未被动过
python scripts\e2e_materials_check.py

# 检索质量评估（真实模型，在临时库中进行，不污染开发索引）
python scripts\run_retrieval_eval.py

# 向量库状态自查
python scripts\check_retrieval.py

# 重建全部资料的向量索引
# 向量库是可重建的派生索引：正文与分块都在 PostgreSQL 里，
# 索引损坏或被删掉时执行这个即可恢复，不需要重新上传资料
python scripts\rebuild_all_indexes.py

# 部署配置静态校验（本机无 Docker 时能做的最强检查）
python scripts\check_deploy_config.py
```

## 目录结构

```text
backend/            FastAPI 应用（app.py 工厂 + lifespan、config、db、errors）
  api/routes/       health / study / materials 路由；deps.py 提供依赖
  models/           SQLAlchemy ORM（learning.py 学习闭环、rag.py 资料与分块、jobs.py 任务）
  ingestion/        解析、文本规范化、标题树、分块、落盘
  retrieval/        向量库、关键词索引、RRF 融合、重排、检索栈组装
  services/         业务服务（学习闭环、资料摄取、检索、混合搜索）
  jobs/             后台任务：租约、重试、崩溃恢复、运行线程
  eval/             检索评估数据集加载与指标（纯函数）
migrations/         Alembic（env.py 从 get_settings() 取 URL；alembic.ini 必须纯 ASCII）
tests/              pytest（unit/ 纯函数、api/ 路由、integration/ 数据库、retrieval/ 检索、materials/ 摄取）
frontend/           Vue3 + Vite
  src/api/          统一 API 客户端（相对 /api）
  src/pages/        四个页面（study / knowledge / materials / chat）
  src/components/   系统状态等
  nginx/            前端容器的 Nginx 配置（构建时 COPY）
  e2e/              Playwright 端到端测试
eval/dataset/       检索评估用例（JSONL）
seed/materials/     随仓库提供的内置讲义
scripts/            种子、演示、验收与评估脚本（含 .cmd 一键入口）
docs/               构建记录（status / checklist / changes）与部署说明
docker-compose.yml  本地部署编排（详见 docs/deploy-docker.md）
```

## 最终答案提交（2026-09-29）

今日学习支持纸笔作答后提交最终答案。已核验的单选/单一数值题可以自动核对；证明、讨论、程序及未核验题只保存作答，不猜测评分。客观掌握度升级后，可靠独立正确结果按不同题累计确认，仍须满足既有考核及跨天条件；看过解析或明确猜测的正确结果不累计。答错仅撤销该题确认，安排复测，不清空其他题成果。

查看解析会记录辅助作答标记，提交结果和证据刷新后保留。升级前必须备份数据库；本机备份与迁移入口为 `python scripts/upgrade_answer_evidence.py --apply`，核验配置定向同步为 `python scripts/sync_verified_grading.py --apply`，不得用重灌数据库替代迁移。

实现边界、接口和验证记录见 [答题证据改造说明](docs/answer-submission-upgrade-2026-09-29.md)。

掌握依据保留历史：旧自评历史不批量换算成客观正确率。自 2026-09-30 起，所有新节点及练习自述都是辅助信号，无论节点的历史依据为何，都不增加毕业确认或重置既有客观成果。旧事件回放保留原规则；新规则见 [自述边界与真实模型验收](docs/self-report-policy-and-live-evaluation-2026-09-30.md)。

第二批核验已支持14道演示题（8单选、6单一数值），不是整个真题库自动评分。运行 `python scripts/audit_grading_coverage.py` 可只读检查实际题库覆盖，原卷引用与可作答题分别统计。核验及内容勘误见 [第二批核验记录](docs/grading-review-batch2-2026-09-29.md)。

## 学习任务草案（2026-09-29）

Agent 另有隔离场景评测入口，默认不调用模型；真实调用需明确授权。记录真实工具、约束、耗时、重试和可观测用量，不发送私人资料。实际坏例、范围约束和复测限制见 [学习 Agent 场景评测](docs/learning-agent-evaluation-2026-09-29.md)。

连续修改、题量不足与排除范围的收口，以及协议 Agent 与现有规则选题器的离线对照，见 [任务收口与规则对照](docs/learning-agent-finalization-and-comparison-2026-09-29.md)。对照脚本 `python scripts/compare_learning_planners.py` 默认不调用真实模型，不代表已证明 Agent 优于规则。

问答评测读取本轮模型实际收到的逐片段证据，而非重新检索，见 [实际证据评测](docs/actual-evidence-evaluation-2026-09-29.md)。同步/流式答案生成已增加请求级用量、结束原因和重试记录，见 [生成调用记录](docs/chat-generation-observability-2026-09-29.md)。上游未返回的用量标为未知；当前统计不包含意图分类等辅助调用，不能作为总费用。

内置资料问答可展开“安排学习”，输入本次目标及时间，模型通过只读工具读取知识范围、真实作答、题库和内置讲解，生成后端校验的草案。支持修改、取消和刷新恢复；用户显式确认后可加入今日卷，重复确认不会重复添加，不修改掌握度。纯知识复习保留在草案，不创建空卷。模型需支持 function tool calling。范围、恢复方式和验证限制见 [学习任务 Agent 第一阶段](docs/learning-task-agent-readonly-2026-09-29.md)；当前写入边界见 [确认与今日卷联动](docs/learning-task-confirmation-2026-09-29.md)。

## 真题接入与桌面发布基础（2026-10-01）

人工核验题包可通过 `python scripts/import_reviewed_questions.py reviewed-pack.json` 只读预览，显式 `--apply` 才写入。来源、答案及叶子节点必须核验；不会把原卷引用冒充在线题或改写历史掌握度。桌面已有 PDF 的文字层审计、题包导入约束、发布目录/资源清单以及 RAG 受限复测边界见 [发布基础与 RAG 记录](docs/release-foundations-and-rag-2026-10-01.md)。

`python scripts/desktop_preflight.py` 仅生成资源清单；目前不是安装器。程序沙箱只有默认关闭的策略层，尚未接入执行；图片审阅未接入视觉 Provider。

桌面启动原型已支持同一个本地后端提供 API 和构建前端，不依赖 Vite；用户目录与开发 `.env`/密钥隔离。`scripts/run_desktop_backend.py --check` 需要显式资源目录和专用本机数据库配置，只读预检。启动方式、测试发现和安装包剩余门禁见 [桌面启动桥接](docs/desktop-host-bridge-2026-10-01.md)，不是现成安装器。

后续已增加 `--managed-postgres --pg-bin <审核过的PG18-bin绝对路径>`：在独立用户目录创建/复用专用集群，首次迁移及内置内容初始化，退出只停止本次启动的实例；升级前备份失败时阻止迁移。实际运行仍使用源码布局和本机 PG18，不是免环境安装包。目录、凭据、测试与尚未覆盖的强杀恢复/完整备份边界见 [桌面数据库编排](docs/desktop-owned-postgres-2026-10-01.md)。

## 安全约定

P5 新增 [证据驱动的下一次学习安排回归](docs/agent-evidence-loop-p5-2026-10-01.md)：复用现有 Agent，验证作答后再次运行任务实际读取 P2/P3 证据，区分独立正确、即时纠正、辅助、猜测和未知；协议测试不等于真实模型能力，当前真实闭环评测及黄金内容人工审核仍待补证。

P0 后已建立两个小型 [P1 Golden Learning Slice](docs/golden-learning-slice-p1-2026-10-01.md)：定积分计算和二叉树基础各 8 道原创合成候选，复用已有判题、题包及学习任务链路。六项内容审核与讲解哈希分开记录，自动检查不能晋级 VERIFIED；当前尚未人工核验或导入开发库。可阅读 [逐题审核清单](eval/golden/integral_binary_tree_v1.review.md)，离线运行 `python scripts/audit_golden_learning_slice.py`；结构检查成功不代表 `release_ready=true`。

当前RAG证据已进行 [P0基线审计](docs/current-rag-baseline-p0-2026-10-01.md) 与获准后的 [当前实测冻结](docs/current-rag-baseline-measured-2026-10-01.md)：当前v5+比较首轮6000完整16例已测，历史全量与定点分数仍按版本分别保留，不拼分或删除坏例。F .9418 / AR .7371 / P .7381 / R .9762；独立人工审核pending，不宣称全业务质量达标。离线冻结/封装工具不会调用模型或裁判。

常规 `scripts/run-e2e.ps1` 默认启动隔离测试库与离线模型协议替身，不调用外部大模型；只能验证界面和业务链路，不能代表真实回答质量。真实 Agent、过程审阅和 RAGAS 评测须使用各自的隔离脚本，另行确认数据范围与调用上限。

学习任务的错题证据、网络恢复、确认前题目版本检查和知识资产统计见 [本轮闭环改造](docs/learning-task-recovery-and-evidence-2026-09-30.md)。刷新任务只读取保存结果，不重新运行模型或覆盖未保存目标；改题后的旧草案须重新生成。

- `.env`、`.env.example` 之外的任何文件都不得出现真实密码、数据库 URL、API Key 或本机绝对路径。
- 上传资料、日志与前端响应不得泄露本机绝对路径或原始异常文本。
- 错误响应统一为 `{"error": {"code": ..., "message": ...}}`，前端按 `code` 分支。
