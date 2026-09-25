# 考研知识库（掌握度自适应学习）

本地单用户的考研学习知识库：知识树 + 今日学习卷 + 资料摄取与可信检索 + 可信问答与题库追练。

- 不实现：登录、多用户、JWT、Redis、Celery、微服务、OCR、联网搜题、LLM 自动生成正式题、记忆卡 SRS、笔记模块、统计页面。
- 部署目标是 **Docker Compose 本地部署**，不做公网云部署。

## 当前进度

见 `docs/reference-build-status.md` 第 1 节。**参考版本的阶段 A–G 已完成验收，Docker Compose 已实际部署验证，并打过 `reference-project-verified-v1` 标签。** 当前工作区有标签之后的前端迭代；标签的验证结果不自动覆盖这些未冻结改动，需以本轮回归结果为准。

本轮（2026-09-24）针对前端问题的回归：`npm run typecheck`、`npm run build` 通过；隔离测试库按 `scripts/run-e2e.ps1` 准备后，**77 条 E2E 全通过、0 跳过**；新增资料正文接口的 2 条直接测试通过。本轮未重新执行全量后端 pytest 或 Docker 验收，不能把旧冻结标签当成当前工作区的新冻结结论。

已完成的能力：

- 知识树：父节点只汇总、叶子可考核；只有 `is_assessable` 叶子能绑定题目与自评
- 今日学习：准备页推荐 → 用户确认 → 生成练习卷 → 专注/全卷模式 → 四种自评 → 追加练习题
- 毕业规则：每个可考核叶子拥有独立 `MasteryPolicy`，按真实题量、题型配额、考法标签、变式题数量和跨天跨度共同判断；节点整体自评只贡献透明的基础确认，不能代替真实做题
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

当前 **Web 设置页只读**：模型密钥、接口地址和模型名仍由服务端 `.env` 配置。项目没有登录与访问控制，因此不提供可通过网页写入密钥的接口；页面内模型配置留待有本机访问边界的桌面版设计。桌面安装包本身也不属于已完成的 A–G 参考版本。

> 检索默认**不启用重排**（`RERANKER_MODEL` 为空），这是正常配置而不是降级；
> 配置了模型但加载失败时会自动退回融合顺序并如实报告 `degraded_reasons`。

> **注意推理模型的输出预算。** 如果 `LLM_MODEL` 用的是推理模型
> （如 `deepseek-flash`，会先输出 `reasoning_content` 思考再输出正文），
> **思考与正文共享 `LLM_MAX_OUTPUT_TOKENS`**。实测该项目在 `800` 时
> 出现过「正文只剩 9 字」甚至正文为空（表现为「回答生成失败」），
> 因为长 prompt 的思考就能吃掉上千 token。
> 因此默认取 `4000`，并额外配置 `LLM_RETRY_MAX_OUTPUT_TOKENS=8000`：
> 首轮失败时**以更大预算**重试一次（原样重试等于再赌一次同样的额度）。
> 排查时看日志里的 `max_tokens_used` 与 `detail`，就能分辨是不是额度不够。

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

## 安全约定

- `.env`、`.env.example` 之外的任何文件都不得出现真实密码、数据库 URL、API Key 或本机绝对路径。
- 上传资料、日志与前端响应不得泄露本机绝对路径或原始异常文本。
- 错误响应统一为 `{"error": {"code": ..., "message": ...}}`，前端按 `code` 分支。
