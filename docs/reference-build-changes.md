# 参考项目设计变更记录

> 本文件记录**每一次设计变更的原因**，以及**文档与真实代码的冲突及最终选择**。
> 规则：不允许长期保留“文档写 A、真实代码是 B”却不记录的情况。
> 最后更新：阶段 A 完成。

## 0. 编号约定（并发写作防撞号）

这份文档会被**多轮、可能并发的**写作追加内容。2026-09-20 一天之内就撞了两次号：
先是 D-25 / D-26 被两批内容各用了一次，随后 `## 19.` 与 `## 20.` 也在两份文档里
各出现两次 —— 撞号的后果不是「难看」，而是**互相引用会同时指向两个不同的东西**
（例如「详见 changes D-25」变得无法确定指的是哪一条）。

因此定下规则，追加内容时照做：

1. **章节**用 `## N. 标题`（两位数无关，递增即可），**变更条目**用 `### D-NN 标题`；
   两者不要混用层级（曾把一条变更写成 `## D-32`，破坏了体系）。
2. 追加**变更条目**时，先搜一遍现有最大编号再取下一个：
   `Select-String -Path docs\reference-build-changes.md -Pattern '^### D-\d+'`
3. 追加**章节**时同理先看已用到几：
   `Select-String -Path docs\reference-build-*.md -Pattern '^## '`
4. 发现撞号时，**给后写的一方改号，并在这里留一行说明**（照 D-31 那条的做法），
   不要悄悄改掉先写的 —— 别处可能已经引用了旧编号。
5. `status` / `checklist` 里的编号要与 `changes` 的 `D-NN` 对得上；
   改号后必须回头检查引用。

## 1. 冲突处理原则（本项目的执行顺序）

当教学文档之间、文档与真实运行结果之间存在冲突时：

1. 先保证核心产品规则不被破坏；
2. 选择更安全、更简单、更可运行、更可测试的设计；
3. 修正实际代码；
4. 记录冲突、最终选择和原因（本文件）；
5. 同步受影响的教学文档；
6. 不允许长期保留“文档写 A、真实代码是 B”。

## 2. 阶段 A 的变更

### C-01 数据库端口：5432 → 5433

- **文档写法**：`DATABASE_URL=postgresql+psycopg://kaoyan:...@127.0.0.1:5432/kaoyan`，库名 `kaoyan` / `kaoyan_test`。
- **真实情况**：系统已装 PostgreSQL 18.4，但服务 `postgresql-x64-18` 处于 Stopped，`Start-Service` 被系统拒绝（提权后仍失败），5432 上没有任何监听。
- **最终选择**：在项目内用 `initdb` 建立独立集群，`.pgdata` 置于项目根（已 gitignore），端口 **5433**，监听 `127.0.0.1`，认证 `trust`。**库名严格保持文档的 `kaoyan` / `kaoyan_test`**。
- **原因**：不依赖管理员权限、可复现、可随时重建、不污染系统安装；库名保持一致才能让文档的迁移与测试命令原样可用。端口只在 `.env` / `.env.example` 一处体现差异，Docker 部署内部仍用标准 5432。
- **影响**：`.env`、`.env.example`；`tests/conftest.py` 的默认测试 URL。

### C-02 `alembic.ini` 必须是纯 ASCII

- **真实故障**：`python -m alembic revision --autogenerate` 直接崩溃：
  `UnicodeDecodeError: 'gbk' codec can't decode byte 0xaa in position 36: illegal multibyte sequence`。
- **原因**：Alembic 通过 `configparser.read(..., encoding="locale")` 读取 `alembic.ini`；本机 locale 是 GBK，而该文件最初含中文注释。
- **最终选择**：`alembic.ini` 全文件纯 ASCII（实测非 ASCII 字节数 = 0），文件头用英文注明“必须保持 ASCII”；所有中文说明放在 `migrations/env.py`。
- **原因**：这是 Alembic + Windows GBK locale 的硬约束，不是风格问题。保持 ASCII 可以让任何 locale 下都能运行。

### C-03 Playwright 浏览器：自带 chromium → 系统 Chrome

- **文档写法**：`playwright install chromium`，`PLAYWRIGHT_BROWSERS_PATH=0`。
- **真实情况**：`cdn.playwright.dev` 不可达（`基础连接已经关闭: 接收时发生错误`），`npx playwright install chromium` 长时间下载 0 字节；但系统已装 Google Chrome 与 Edge。
- **最终选择**：`playwright.config.ts` 使用 `channel: "chrome"`；`package.json` 的 `test:e2e` 去掉 `PLAYWRIGHT_BROWSERS_PATH`，`test:e2e:install` 保留供日后 CDN 可用时使用。
- **原因**：在这个环境里下载自带浏览器是**不可完成**的路径；使用系统 Chrome 能得到等价且真实的浏览器验证，不必把冒烟测试降级为跳过。

### C-04 Vite 必须忽略 Playwright 的临时目录（真实崩溃修复）

- **真实故障**：前端开发服务器两次以 `EBUSY` 崩溃（exit code 1）：
  `Error: EBUSY: resource busy or locked, watch '...\frontend\.playwright.config.ts.4172.*.tmpdir\playwright.config.ts.tmp'`
  以及 `...\frontend\e2e\.navigation.spec.ts.4172.*.tmpdir\navigation.spec.ts.tmp'`。
- **原因**：Playwright 加载 ESM 配置与测试文件时会**在文件所在目录**创建 `<文件名>.tmpdir/<文件名>.tmp`。Windows 上该临时文件在被占用状态下被 Vite 的 `FSWatcher` 命中，Node 抛出未捕获的 `error` 事件直接结束进程。
- **最终选择**：`vite.config.ts` 的 `server.watch.ignored` 排除 `**/*.tmpdir/**`、`**/*tmpdir*/**`、`**/.playwright*/**`、`**/test-results/**`、`**/playwright-report/**`、`**/blob-report/**`。
- **原因**：这是本机真实观测到的稳定性缺陷（不是猜测）。只忽略根目录一层的 `.playwright*` 不够——Playwright 的临时目录出现在**每个**测试文件旁边，因此必须用递归通配。
- **验证**：修复后重跑 `npm run test:e2e`（2 passed），开发服务器保持存活。

### C-05 健康检查的依赖注入点：`backend/db.get_db` → `backend/api/deps.get_db`

- **文档写法**：`health.py` 直接 `from backend.db import get_db`，测试用 `app.dependency_overrides[get_db]`。
- **最终选择**：新增 `backend/api/deps.py` 暴露 `get_db` 与 `get_session_factory`，路由只 import 本模块；`deps.get_db` 内部转发到 `backend.db.get_db`。
- **原因**：让“路由使用的依赖对象”唯一且稳定。测试覆盖 `backend.api.deps.get_db` 即可，不必依赖 `backend.db` 模块对象是否被重新绑定，降低脆弱性；同时为后续需要独立会话的 SSE 与后台任务提供 `get_session_factory` 出口（文档也要求 SSE 不能用请求级 Session）。

### C-06 阶段 A 只建 Batch A 的 7 张表（有意为之，非遗漏）

- **文档写法**：Batch A 建 `knowledge_points`、`kp_states`、`learning_events`、`questions`、`daily_plans`、`practice_items`、`question_attempts`；Batch B（资料与索引）在摄取篇建，Batch C（问答）在问答篇建。
- **最终选择**：**严格只建 Batch A 的 7 张表**，一条初始迁移 `e265f44be662_create_learning_core_tables.py`。
- **原因**：`materials`、`document_chunks`、`chunk_knowledge_points`、`document_jobs`、`chat_sessions`、`chat_messages`、`message_citations` 在本轮已读取的文档片段中**没有完整的列定义**（例如 `document_chunks` 与 `message_citations` 的完整字段表未出现）。凭猜测建表会违反“不把错误设计继续实现下去”，也会让后续阶段的 `alembic check` 产生无意义的差异。因此按文档的批次顺序在对应阶段建表。
- **影响**：`/materials` 与 `/chat` 在阶段 A/C 之前仍是占位页——这是阶段安排，不是 bug。

### C-07 `next-step` 属性是否真的传到 `nextStep` prop（实测而非猜测）

- **疑问**：页面用 `next-step="..."`，组件 `PhasePlaceholder` 声明的 prop 是 `nextStep`。
- **处理**：不靠推测，直接在 Playwright 中断言四个占位页的文案真实渲染（`实现知识点推荐、用户选点和当日练习卷。` 等）。
- **结果**：断言全部通过 → Vue 3 会把 `next-step` 规范化成 `nextStep`，属性传递正常，**无需修改**。
- **原因**：把“看起来可能有问题”的怀疑变成可执行断言，避免无谓改动和无根据结论。

### C-08 `kp_states.kp_id` 同时为主键与外键

- **文档写法**：`kp_states` 的 `kp_id` 是 `Uuid` FK → `knowledge_points.id`，`ondelete="CASCADE"`，并且**同时是主键**。
- **最终选择**：`kp_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True)`。
- **验证**：迁移生成 `PrimaryKeyConstraint('kp_id', name='pk_kp_states')` 与 `ForeignKeyConstraint(..., ondelete='CASCADE')`；`test_migrations.py` 断言 `pk_kp_states` 存在。
- **原因**：一个叶子至多一行状态投影，用 PK 表达比额外加唯一约束更简单可靠，也符合文档。

### C-09 枚举的表达方式：跟随文档用 `String(n)`，不建 Postgres ENUM

- **文档写法**：所有枚举类字段都是 `sa.String(n)` + Python 侧 `default=`；**没有** `CREATE TYPE ... AS ENUM`，Batch A **没有** CHECK 约束（`DocumentJob` 有 CHECK，但那是 Batch B）。
- **最终选择**：Batch A 严格跟随——`state`、`status`、`self_grade`、`objective_result`、`question_type`、`grading_mode`、`difficulty` 全部 `String(n)`；取值域由 `backend/models/enums.py` 的 `StrEnum` 与应用层校验保证。
- **原因**：Postgres ENUM 的增删值需要额外迁移，对单人本地项目是可避免的复杂度；`String + 应用层枚举` 更好改、更好测，且与文档一致。

### C-10 `questions.explanation` 为 NOT NULL

- **文档写法**：`explanation: Mapped[str] = mapped_column(Text, nullable=False)`。
- **最终选择**：保留 `nullable=False`。
- **原因**：产品规则要求“答案详解始终可以查看”，解析缺失会让页面出现空答案区。强制非空可让种子数据阶段就暴露缺失，而不是上线后才发现。**对种子数据的要求：每道题都必须有非空解析。**

### C-11 `daily_plans.status` 默认 `draft` 但产品状态只有三种

- **文档写法**：ORM `default="draft"`；产品规则的状态是 `setup / active / completed`（其中 `setup` 是**前端没有活动计划时的展示态**，不是数据库行）。
- **最终选择**：数据库保留 `draft` 默认值，但**创建计划时直接写 `active`**（文档的 `create_initial_plan` 也显式写 `status="active"`）。
- **原因**：`setup` 不该在数据库里存在（它就是“没有计划行”）；`draft` 作为默认值不会出现在真实流程中。这样数据库状态只有 `active` / `completed`，而前端三态由“有无计划行 + 计划状态”推导，语义不重不漏。

### C-12 `create_db_engine` 显式设置建连超时与连接池等待上限（真实缺陷修复）

- **文档写法**：`create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)`，**没有** `connect_args` 与 `pool_timeout`。
- **真实故障**：停止 PostgreSQL 后，`GET /api/health` 既不是 200 也不是 503，而是 **90 秒无任何响应**；uvicorn 日志中完全没有该请求的记录，说明事件循环已被占住。
- **根因**：psycopg 在没有 `connect_timeout` 时建连会长时间挂起。文档的设计假设“数据库不可用时驱动会很快报错并走到 503 分支”，但实测在本机 Windows 上并不成立；而单进程 uvicorn 一旦被同步驱动阻塞，连返回 503 都做不到——**契约在真实故障下失效**。
- **最终选择**：新增常量 `DB_CONNECT_TIMEOUT_SECONDS = 5`、`DB_POOL_TIMEOUT_SECONDS = 10`，并在 `create_db_engine()` 中传入 `connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS}` 与 `pool_timeout=DB_POOL_TIMEOUT_SECONDS`。
- **验证**：数据库确实停止时，直连与经 Vite 代理都返回 503 与同一错误体，耗时 5.21s / 5.03s；恢复后 0.13s 返回 200。
- **回归保护**：`tests/unit/test_db_engine_timeouts.py` 三个用例（含“连到必然拒绝的端口必须快速失败”的行为断言）。
- **原因**：产品的健康检查契约（文档第 03 条：数据库故障必须返回 503 且不泄露细节）是**必须成立**的业务规则。当实现方式让该规则在真实故障下失效时，必须改实现而不是改契约。

### C-13 健康检查 503 的分支也需要“真实故障”验证

- **做法**：阶段 A 不只依赖 `FakeSession` 单测与 Playwright 路由拦截，还**真的停掉了 PostgreSQL 集群**，用 `curl -i` 观察真实响应。
- **结果**：正是这一步暴露了 C-12 的缺陷——两套既有测试都是绿的，但真实数据库中断时契约不成立。
- **原因**：`FakeSession` 覆盖的是“SQL 抛错”这一层，而真实故障发生在更早的“建立连接”阶段，两者路径不同。后续阶段（资料摄取失败重试、索引重建、SSE 失败与取消）都必须沿用“真的制造故障并观测”的验证方式。
## 3. 阶段 B 的变更

### C-14 `daily_plans.status` 必须能真的变成 `completed`（真实缺陷修复）

- **文档写法**：`item.completed_at = now` 之后直接 `select(...).where(completed_at IS NULL)`，为空则写 `plan.status = "completed"`。
- **真实故障**：会话配置是 `autoflush=False`（文档自己的 `create_session_factory` 也是），所以那次查询读的是**数据库里的旧值**，会把刚做完的这道题自己查回来，`remaining` 永远不为 `None`。
- **后果**：`daily_plans.status` 永远停在 `active`；总结页状态不可达；而且因为计划不是 `active`……实际更糟——`append_questions_to_plan` 只检查 `plan.status != "active"` 就拒绝，所以「已完成的卷不能追加」这条规则也失效，**已完成的卷仍可继续加题**。
- **最终选择**：在赋值 `completed_at` / `latest_self_grade` 之后、查询剩余题之前插入 `session.flush()`。
- **原因**：这是「不改契约、只修实现」的典型。`autoflush=False` 是**有意选择**（避免一次查询意外写入半成品），不能为了这个 bug 把它打开；正确的做法是在读之前显式 flush。
- **回归保护**：`test_plan_row_status_becomes_completed_in_database`（直接查库断言 `completed`）+ `test_append_to_completed_plan_is_rejected`。

### C-15 跨天口径必须只有一份实现（`confirmation_dates`）

- **冲突**：状态机把 `manual_confirmed_at` 计入跨天判定，而知识节点的展示字段 `first_confirmed_on` / `last_confirmed_on` / `day_span` 只统计 `evidence_window`。
- **后果**：用户点过「我已掌握」之后再做题，页面显示的跨度会小于状态机实际使用的跨度，同一份数据出现两个答案。
- **最终选择**：在 `backend/mastery/rules.py` 新增 `confirmation_dates()`，`graduation_check` 与 `study._node_view` 共用它。
- **原因**：凡是「同一个业务数字出现在两处」，就必须只有一个实现。页面上的跨度是用户判断「还差什么」的依据，不能和判定口径不一致。
- **回归保护**：`test_node_route_day_span_uses_same_calendar_as_state_machine`。

### C-16 `objective_result` 固定写 `unknown`（有意保留）

- **文档冲突**：一处硬编码 `objective_result="unknown"`，另一处说「选择题可同时存 right/wrong」，还有前端要显示「自动判题参考」。
- **最终选择**：阶段 B 保持 `unknown`，**不实现**自动判分；`reference-build-checklist.md` 对应项保持未勾选。
- **原因**：产品规则明确「最终掌握度和毕业完全以 `self_grade` 为主」，且「`objective_result` 只是复盘参考」。要真正写入 `right/wrong`，必须先把用户的选项与 `correct_answer` 比较，而请求体里没有「用户选了哪个选项」这个字段——需要新增契约。在没有明确需求前不引入一个恒为 `unknown` 的假字段，也不为了填满一个 UI 格子去猜语义。

### C-17 追加接口的路径与 404 语义（跟随文档）

- **文档给的确切路径是** `POST /api/plans/{plan_id}/questions`（不存在 `/api/plans/today/append`），节点整体自评是 `POST /api/knowledge/{kp_id}/self-assessment`。
- **冲突**：契约表声明追加可能返回 404，但错误码映射表里没有 `question_not_found`，实现会把「题目不存在」返回成 422。
- **最终选择**：按契约表补齐 `question_not_found → 404`，并在 `errors.SAFE_MESSAGES` 中登记该码。
- **原因**：404 与 422 对前端是不同的分支（前者是「资源没了」，后者是「请求不合法」），必须按契约给对。

### C-18 暂不实现「重置某知识点状态」的接口

- **文档情况**：状态机实现了 `STATE_RESET` 事件分支，但 9 个端点里没有任何入口，错误码表里也没有对应码。
- **最终选择**：保留 `transition()` 对 `STATE_RESET` 的处理（纯函数层完整），但**不新增路由**；开发期需要复位时用 `scripts/reset_today.py`。
- **原因**：给用户一个「一键清空这个知识点的掌握度」的按钮是有破坏性的产品决策，文档没有定义入口、权限与确认流程，不应擅自加。需要时应先补产品规则。

### C-19 前端不计算任何业务状态

- **做法**：掌握度、有效确认数、是否毕业、`reason_code`、基础确认数全部来自后端响应；前端只做「机器码 → 中文」映射。
- **唯一例外**：知识树父节点的「已毕业 N/M」由前端数子节点得到。
- **原因**：规则明确「父节点只汇总」，且叶子状态本身来自后端；前端只是把已知状态聚合计数，不推导掌握度。这样即使后端改了毕业规则，页面也不会给出不同结论。
### C-20 选择题的 `objective_result` 已真实实现（修订 C-16）

- **背景**：C-16 曾判定「不实现自动判分」，理由是请求体里没有「用户选了哪个选项」。阶段 B 收尾时补齐了这条缺失的契约，因此该项由「不实现」改为「已实现」。
- **最终选择**：
  - `SubmitSelfAssessmentRequest` 新增可选字段 `selected_option`（`max_length=8`）。
  - 新增纯函数 `objective_result_for(*, selected_option, correct_answer) -> str`：**只有**用户明确选了选项**且**题目有标准答案时才判定 `right`/`wrong`；选项比较前统一 `strip().upper()`；其余一切情况（填空、纸笔、主观题、未作答、空串）保持 `unknown`。
  - 前端在专注模式与全卷模式都提供可点选的选项。
- **原因**：
  1. 产品规则要求「选择题可以保存 `objective_result=right/wrong`」，这是可以真实做到的，之前只是因为缺输入字段才搁置。
  2. 但规则同时写明「`objective_result` 只是复盘参考，绝不能覆盖或代替 `self_grade`」，所以**填空/主观题绝不做字符串包含之类的猜测判分**——那会把「不确定」伪装成「确定」。
- **验证**：`tests/unit/test_objective_result.py`（9 个参数化用例）+ `tests/integration/test_learning_loop.py` 两条端到端断言：选错选项却自评「已掌握」时，`objective_result="wrong"` 但有效确认数照常 +1；把标准答案原样填进 `raw_answer` 的填空题仍然记录 `unknown`。

### C-21 准备页「从知识树补充」只列可考核叶子

- **产品规则**：「用户可以从知识树补充今天想学的叶子节点」。
- **最终选择**：准备页新增「从知识树补充」入口，弹出**扁平化的可考核叶子列表**（父节点不出现），勾选即加入今天的选点；父子层级仍在 `/knowledge` 页完整展示。
- **原因**：
  1. 「今天学什么」的选择只需要叶子——父节点不能答题、不能毕业，让它出现在选点里只会误导。
  2. 扁平列表复用同一份 `GET /api/knowledge/tree` 数据，不新增接口，也不需要在前端重复实现一套树。
- **验证**：E2E 断言选择器内恰有 5 个可考核叶子、父节点名不出现、取消/重新勾选会真实改变「已选 N 个知识点」。
### C-22 已完成的卷必须允许继续追加题目（真实缺陷修复）

- **现象**：用户把今日 3 道题全部做完后点「追加练习题」，后端返回 `409 plan_not_active`，无法继续练习。已用真实环境复现：
  `追加前 status=completed 题数=3 已完成=3` → `追加结果 HTTP 409 {'error': {'code': 'plan_not_active'}}`。
- **根因**：`plan.status` 被当成**持久状态**使用，被塞进了两个互相冲突的语义：
  1. 「今天是否还在进行」——取决于题目完成情况；
  2. 「这张卷是否还能追加」——应该只取决于「它是否还是今天那张卷」。
  全部做完 → `completed` → 连追加也被挡住，而产品规则只说「追加到 `max(ordinal)+1` 的卷尾」，
  从未说过「做完就不许再练」。
- **附带缺陷**：`_build_today_active()` 当时又**重新推导** status（按完成情况算），
  于是可能出现「数据库写着 completed、接口却说 active」的两套结论，追加接口与页面据此得出不同判断。
- **最终选择**：
  1. `append_questions_to_plan()` 接受 `{"active", "completed"}`；真正禁止追加的只有 `draft`（还没生成好的卷）。
  2. 追加成功且卷原本是 `completed` 时，把卷改回 `active`——卷里又有了未完成的题，这是事实。
  3. `_build_today_active()` 直接返回 `plan.status`，接口与数据库永远一致；
     状态只在真正变化的两处事务里维护（全部做完时改 `completed`、追加新题时改回 `active`）。
- **原因**：这是「用户能否继续学习」的功能性问题，产品规则的精神是**用户决定今天学多少**。
  把「今天暂时做完」误当成「今天不许再练」，等于让系统替用户关掉学习入口。
- **验证**：
  - `tests/integration/test_learning_loop.py::test_append_to_completed_plan_reactivates_it`：完成后追加返回 200、
    卷变回 `active`、新题在卷尾 `ordinal=4`、`focus_item_id` 指向新题、数据库与接口状态一致。
  - E2E `做完全部题后仍可追加练习，计划回到进行中`：真实做完 3 题 → 出现空态 → 追加 → 状态回到「进行中（3 / 4）」。
- **同步修正的界面文案**：专注模式空态现在明确告诉用户「想继续练就点下面的『追加练习题』：
  选中的题会加到卷尾，今天的计划会重新变成进行中」，而不是只让他等到明天。
## 4. 重大设计升级：每知识点独立毕业策略（2026-09 起）

### 4.1 为什么改

原设计「每个知识点固定 3 道题 + 1 道变式 + 跨 2 天」适合快速做出闭环，但存在真实问题：

- 不同知识点难度与考法不同，统一门槛不合理；
- 只考选择题的知识点被迫练大题，只考大题的知识点被迫做选择题；
- 做够 3 道题不代表覆盖了主要考法；
- 推荐器不知道用户真正缺哪类题，只能重复推荐。

### 4.2 新的毕业判定

```python
can_graduate = (
    effective_confirmations >= policy.min_confirmations
    and distinct_real_questions >= policy.min_real_questions
    and required_question_types_satisfied   # 必考题型配额
    and required_skill_tags_satisfied       # 必考考法覆盖
    and variant_count >= policy.required_variant_count
    and day_span >= policy.min_day_span
)
```

判定顺序与原因码：

| 顺序 | 条件 | 未满足时的原因码 |
|---:|---|---|
| 1 | 有效确认数（含基础确认） | `insufficient_confirmed_evidence` |
| 2 | 不同真实题目数 | `insufficient_real_questions` |
| 3 | 每种必考题型的配额 | `missing_question_type:<type>` |
| 4 | 真实变式题数量 | `missing_real_variant` |
| 5 | 必考考法覆盖 | `missing_skill_tag:<tag>` |
| 6 | 首尾确认跨天 | `insufficient_day_span` |

### 4.3 策略存储

每个可考核叶子一行 `kp_mastery_policies`：

| 字段 | 含义 |
|---|---|
| `min_confirmations` | 有效确认数下限 |
| `min_real_questions` | 不同真实题数下限（基础确认不能替代） |
| `required_question_types` | 题型配额，如 `{"single_choice":1,"calculation":2}` |
| `excluded_question_types` | 该知识点不使用的题型，推荐与组卷都会排除 |
| `required_skill_tags` | 必考考法标签 |
| `required_variant_count` | 真实变式题数量 |
| `min_day_span` | 跨天要求 |
| `manual_mastered_credit` | 节点整体自评贡献的基础确认数（默认 2） |

**没有配置的叶子使用默认策略**（3 确认 / 3 真实题 / 1 变式 / 跨 2 天）。

### 4.4 题目分类

`questions` 新增三个字段：

| 字段 | 含义 | 取值 |
|---|---|---|
| `question_role` | 学习作用 | `basic` / `typical` / `variant` / `comprehensive` |
| `skill_tags` | 考法标签 | 如 `["适用条件","0/0 型"]` |
| `estimated_minutes` | 预计完成时间 | 选择 3 / 填空 5 / 计算 12 / 证明 20（默认值，可覆盖） |

**题型（怎么答）与角色（起什么作用）互不替代**：策略只约束题型与考法，不约束角色。

### 4.5 推荐与组卷

**知识点层优先级**：未掌握 → 到期复测 → 部分掌握 → 毕业证据不足 → 从未学习 → 巩固中。

**知识点内选题（`backend/mastery/selection.py`）**：按「缺口逐步补齐」的贪心算法，
每一轮选能补齐最多缺口项的题，加入模拟窗口后重算缺口，直到缺口补齐、达到上限或预算用尽。

这样选题数恰好够补缺口，不会出现「策略要求 2 道计算题却选了 3 道」。

**时间预算**：轻量 45 / 标准 90 / 深度 120 分钟，按 `estimated_minutes` 汇总裁剪。

### 4.6 前端需要展示的缺口明细

接口 `GET /api/knowledge/tree` 与 `/api/knowledge/{kp_id}` 现在返回：

```json
{
  "gap_items": [
    {"key": "effective_confirmations", "label": "有效确认", "current": 4, "required": 5, "satisfied": false},
    {"key": "type:fill_blank", "label": "填空题", "current": 0, "required": 1, "satisfied": false},
    {"key": "day_span", "label": "跨天确认", "current": 0, "required": 2, "satisfied": false}
  ],
  "next_step": "完成 1 道填空题",
  "required_question_types": {"single_choice": 1, "fill_blank": 1, "calculation": 2},
  "excluded_question_types": ["proof", "subjective"],
  "required_skill_tags": ["适用条件", "0/0 型"]
}
```

`gap_items` 与 `next_step` 由 `analyze_gaps()` 生成，**与状态机使用同一份计算**，
因此页面显示的进度一定等于毕业判定使用的进度。

### 4.7 题库容量校验

组卷时按该知识点自己的策略检查题库是否够用：

- 只检查 `required_question_types` 里的题型；
- `excluded` 的题型不参与检查——明确不考大题的叶子没有大题是正常的；
- 不足时返回 `question_pool_incomplete`，并且不留下半张卷。
### 4.8 每日推荐的知识点层优先级（已实现）

| 层 | 分数区间 | 判据 | 理由码 |
|---|---|---|---|
| 1 | 100–101 | 最近一次自评是 `not_mastered` | `not_mastered` |
| 2 | 99–100 | `next_review_at <= now` | `overdue_review` |
| 3 | 98–99 | 最近一次自评是 `partial` | `partial_mastery` |
| 4 | 97–98 | 有证据但尚未毕业 | `insufficient_evidence` |
| 5 | 96–97 | `unseen` 且无任何证据 | `preview` |
| 6 | 95–96 | 已毕业且未到复测日 | `consolidating` |

- **冲突规则**（已确认）：上次未掌握 + 正好到复测日 → 按**第 1 层**处理，
  因为「做错了」比「到点了」更紧急。
- **同层内排序**：按「距上次练习的天数」降序，久未练习的靠前；
  分数小数部分归一化到 `[0,1)`，保证层级之间绝不重叠。
- **推荐条数**：最多 6 个（已确认保持）。
- **稳定排序**：同分再按 `kp_id`，避免刷新时顺序乱跳。

### 4.9 题库耗尽时的复测选题（真实缺陷修复）

**问题**：某知识点的题全部练过、只剩跨天门未满足时，选题返回**空**，
页面只能靠兜底随便给一道；而真正该复测的（最久没确认的）反而排不到。

**根因**：
1. `_missing_gap_keys()` 刻意排除了 `day_span`，导致跨天门永远不驱动选题；
2. 收益模型只在新题时计入 `real_questions`，重做旧题被当成零收益。

**修复**：收益模型区分两类题：

| 题目类型 | 能推进的条件项 |
|---|---|
| 没做过的题 | 不同真实题数、必考题型、必考考法、变式题 |
| 已确认过的题（重做） | **只有**跨天跨度（符合「重做只刷新确认时间」的规则） |

并新增 `reference_time` 参数：判断「重做能否把首尾确认日期拉开」必须知道今天是哪天，
否则复测日无法判断收益，就会既推荐不出题、也可能在同一天反复推荐同一道题。

选题结果新增 `is_review` 字段，页面据此区分「新题」与「复测」。
`reason` 文案区分：`复测：再做一次确认以推进跨天毕业` / `复测：巩固已掌握的内容`。

### 4.10 前端需要展示的三件事

1. **推荐卡**：层级标签 + `next_step`（如「完成 1 道填空题」）+ `missing_types`（预计加入什么题）；
2. **知识节点概览**：`gap_items` 逐条进度（有效确认 4/5、填空题 0/1…）；
3. **练习卷**：`type_summary`（选择题 2 道、填空 2 道…）与 `estimated_minutes`（预计 45 分钟）。
### 4.11 前端展示（本轮完成）

| 位置 | 展示内容 | 数据来源 |
|---|---|---|
| `/study` 准备页推荐卡 | 层级标签、**下一步**（如「完成 1 道填空题」）、**预计加入**（缺失题型） | `RecommendationItem.reason` / `next_step` / `missing_types` |
| `/study` 准备页 | **时间预算**选择：轻量 45 / 标准 90 / 深度 120 分钟 | `GeneratePlanRequest.budget` |
| `/study` 答题页 | 卷子构成（选择题 2 道、填空 2 道…）与**预计总时长 / 待做时长** | `TodayActive.type_summary` / `estimated_minutes` / `remaining_minutes` |
| `/study` 全卷与专注模式 | 每题的题型、学习角色、变式标记、**复测标记**、预计时长、考法标签 | `PlanItemView` 新字段 |
| `/knowledge` 概览 | **毕业进度逐项列表**（✓/○ + 当前/要求）与**下一步** | `KnowledgeNodeView.gap_items` / `next_step` |
| `/knowledge` 概览 | 该知识点的**考核要求**：必考题型、不考题型、必考考法 | `required_question_types` / `excluded_question_types` / `required_skill_tags` |

页面**不自己计算毕业条件**：`gap_items` 与 `next_step` 都由后端 `analyze_gaps()` 给出，
与状态机使用的是同一份计算。

### 4.12 顺带修复的真实可用性缺陷

**全卷模式的选择题选项此前只是静态文本，无法点选**——用户在「阅览全卷」里遇到选择题
只能看选项、不能作答，客观结果也就永远写不进去。现已改为可点选的单选按钮。

### 4.13 `shift-days` 脚本的问题

`scripts/shift_learning_days.py` 在字段改名后**已经坏了**（仍在读旧的
`policy.required_confirmed_questions`）。已重写为直接复用 `analyze_gaps()`，
并改进了输出：

- 明确打印「『现在』被当作哪天（真实日期是哪天）」；
- 用 `[OK]/[缺]` 逐项列出每个叶子的毕业缺口，并给出下一步；
- 打印每个叶子的确认日期区间与跨度；
- 末尾给出「接下来按什么顺序操作」的三步指引。

关于语义（使用者曾困惑的一点）：脚本把历史时间**前移** N 天，
效果等价于「让现在看起来是 N 天之后」——因为毕业看的是
「首尾确认日期相差多少天」，把历史推远与把今天拉近是同一件事。

## 5. 阶段 C 的变更

### C-23 资料只做「可重建的派生索引」，正文权威始终在 PostgreSQL

教学文档里 Chroma 与 PostgreSQL 的关系没有写死。本项目明确选择：
**`document_chunks` 是正文与 offset 的唯一权威副本，Chroma 只是派生索引**。

理由：引用必须能回跳原文，而回跳依赖 `normalized_text` 的 offset 坐标系。
如果检索结果直接采用向量库里存的 `document`，那么索引一旦陈旧，引用就会指向
一段与正文不一致的文字。因此检索结果一律用 chunk_id 回数据库取正文，
向量库里的 `document` 只用于一致性核对。

**一致性表现**：删掉整个 `storage/chroma` 只会让检索为空，资料页点「重建索引」即可恢复，
不需要重新上传文件。这条性质有测试覆盖（`test_content_comes_from_database_not_vector_store`）。

### C-24 索引版本号格式定为 `v1-<16 位十六进制>`（补齐文档缺失的格式契约）

教学文档只说 `index_version` 是字符串，没有格式约定，也没有说明何时变化。
本项目把格式固定为 `v1-` 加 16 位小写十六进制，输入是
`content_hash | embedding_model | chunk 算法版本 | max_chars` 的 SHA-256 前缀。

这么定带来两个可验证的性质：
1. **确定性**：相同正文 + 相同模型 + 相同分块算法 → 永远同一个版本号，
   于是能不能跳过重建是可判断的，而不是靠猜；
2. **可校验**：`is_valid_index_version()` 能拦住任何手写或迁移过程中产生的脏值，
   也有单元测试覆盖非法格式。

### C-25 上传 20 MB 与解析 5 MB 的上限不一致：保留两档但明确语义

教学文档里上传上限写 20 MB，解析阶段又提到 5 MB，两者冲突。
本项目的处理是**同时保留但赋予不同语义**，而不是二选一：

- `MAX_UPLOAD_BYTES = 20 MB`：单次 HTTP 上传的字节上限，超了返回 `file_too_large`（413）；
- `MAX_SOURCE_BYTES = 5 MB`：解析阶段读入内存的上限，超了返回同类错误。

理由：上传宽松一点让用户能传大文件并先把文件安全落盘（落盘是流式的，不吃内存）；
解析阶段要真正把整篇读进内存做正则与分块，必须收紧以免一个超大文件把内存打满。
两档语义不同，因此不是矛盾而是分工。**这是有意的设计选择，已在此记录。**

### C-26 `SearchFilters` 的四字段契约全部真实生效

教学文档的接口契约写了 4 个过滤字段，而示例实现里只用了 2 个。
本项目四个字段都落地并逐条测试：

| 字段 | 语义 | 测试 |
|---|---|---|
| `material_ids` | 只在指定资料内检索 | `test_filters_restrict_materials_and_source_types` |
| `source_types` | builtin / user 过滤 | 同上 |
| `index_versions` | 只检索指定版本 | `test_wrong_index_version_is_not_retrievable` |
| `excluded_material_ids` | 显式排除 | `test_filters_restrict_materials_and_source_types` |

另外补了一条文档没写但必须正确的语义：**空元组表示「检索不到任何东西」，不是「不过滤」**。
`build_index_filter()` 在没有任何 ready 资料时返回空元组而不是 `None`；
`None` 的含义是「不过滤」，用它会让不该检索的资料被召回。

### C-27 关键词索引重建时机：必须在版本激活之后（真实缺陷修复）

`build_index()` 完成时资料状态还是 `indexing`，而关键词索引只收录
`ready` 且「当前激活版本」的块。因此在 `build_index` 内部重建关键词索引会
**得到一个空索引**，症状是「关键词候选恒为 0」——
检索接口仍然返回结果（向量路在工作），所以这个缺陷在肉眼检查时几乎不可见。

修法：`build_index` 不再碰关键词索引，改由 `run_job` 在 `activate_version()`
之后调用 `rebuild_keyword_index()`。回归测试：
`test_keyword_index_is_populated_after_ingest`。

### C-28 索引版本必须先算再写库（真实缺陷修复）

版本号依赖 `content_hash`，而 `content_hash` 只有解析之后才知道。
最初的写法是「先用占位版本写一遍 chunks，解析后再用真实版本写一遍」，
结果是库里留下**两倍块数**（15 → 30），而且旧版本永远不会被清理。

修法：把解析拆成两步 —— `plan_material()`（纯内存：读文件、规范化、分块）
与 `parse_material()`（按给定版本写库）。`run_job` 的顺序变为
「plan → 算版本 → 写库」，只写一次。

### C-29 `<!-- kp:code -->` 的归属规则写死为「紧邻其下方标题」（真实缺陷修复）

教学文档说这个注释用于建立 chunk 与知识点的显式关联，但没说归给哪个标题。
原实现用「父节点正文起点 → 第一个子节点起点」当范围，而父节点正文起点在
父标题行**之后**，于是注释落到父节点之外，**整份文档的注释全部错位一格**：
5 个注释里只有最后 1 个归属正确。

新规则：注释归属于**紧邻其下方**的那个标题（中间只允许空行）；
该标题的子标题继承同一 code（这样整章共用一个标记也成立）。
实现改为二分查找，顺带把原先的 O(节点数 × 行数) 扫描降到 O(节点数 × log 行数)。
有 11 条测试覆盖，包括「注释与标题之间隔着正文时不算紧邻」。

### C-30 越界用例的口径：检索层返回最像的块是预期行为

评估数据集里有「知识库里根本没有答案」的用例（如「这个软件怎么安装」）。
最初把「返回了结果」记为误报，指标直接是 1.000 —— 这个口径是错的：
**按相似度排序的检索层没有能力也没有义务判断「该不该回答」**，
那是问答层（阶段 D）的职责。

改为记录「最高相似度分数」与「强信号率（≥ 0.7 的比例）」。实测
越界用例最高相似度只有 **0.031**，强信号率 **0.000**，
说明阶段 D 用一个中等阈值即可可靠拒答，不必依赖模型自觉。

### C-31 前端资料页不展示 `stored_path`

`stored_path` 是相对资料根目录的内部路径，接口一律不返回。
理由：它是服务器文件系统结构的线索，对用户毫无价值，泄露只会带来风险。
详情接口只给标题、原始文件名、大小、状态、索引版本、块数与任务信息。

### C-32 nginx 模板里不混用 envsubst 变量与 nginx 变量

nginx 官方镜像会对 `/etc/nginx/templates/*.template` 做 envsubst，
而 envsubst 不认识 `$host`、`$scheme` 这些 nginx 自身变量。
若同一份配置里既有 `${BACKEND}` 又有 `$host`，就必须正确配置环境变量白名单；
白名单一旦写错，`$host` 会被替换成空，表现为「代理能通但 Host 头为空」，
排查成本很高。

本项目选择：**上游地址用固定 `upstream` 块写死，模板里不出现任何 `${...}` 占位变量**。
Compose 网络里后端服务名固定为 `backend`，因此这不损失灵活性。
`scripts/check_deploy_config.py` 会校验有效配置行里不含 `${`。

### C-33 `.gitattributes` 固定行尾：容器脚本必须 LF，Windows 脚本必须 CRLF

`clone`/`checkout` 时 autocrlf 会把 `.sh` 改写成 CRLF，容器里会报
`exec backend/docker-entrypoint.sh: no such file or directory` ——
这个报错完全看不出是行尾问题。因此用 `.gitattributes` 显式声明：

- 默认 `eol=lf`（含 `.sh`、`Dockerfile`、nginx 配置）；
- `*.cmd` / `*.bat` / `*.ps1` 用 `eol=crlf`（Windows 脚本）；
- 二进制文件不做转换。

### C-34 应用启动不因检索不可用而失败

embedding 模型或向量库不可用时，**后端仍然正常启动**：
只有检索接口返回 `503 retrieval_unavailable`，学习闭环、知识树、
资料上传解析全部不受影响。`/api/health` 新增 `retrieval` 与 `worker`
两个字段，让「后端活着但检索不可用」这种情况可被一眼识别。

理由：检索是增强能力而不是系统地基。让一个模型下载失败导致整个应用起不来，
是把一个局部问题放大成全站故障。

### C-35 向量检索依赖单列 `requirements-embed.txt`

`torch` + `sentence-transformers` 体积数百 MB。放进基础依赖会让
Docker 构建时间和镜像体积都失控。因此拆成独立文件，
Docker 构建用 `INSTALL_EMBED=0/1` 控制，缺省不装。

这与 C-34 配套：不装向量依赖时系统是**降级可用**而不是不可用。

## 6. 用户实测反馈的修复（阶段 C 交付后）

以下四个问题都由用户真机实测发现，全部确认为真实缺陷并修复。
另有一个在排查过程中定位到的、阻塞验证的严重问题（C-40）。

### C-36 端到端测试绝不能删除用户的数据（真实缺陷修复）

**症状**：跑 `npm run test:e2e` 会把用户自己上传的资料全部删掉。
`frontend/e2e/fixtures.ts` 当时拉一次资料列表就删除每一条，而且挂在 page 夹具上、
每个用例前后各执行一次；`scripts/e2e_materials_check.py` 也断言「资料列表已清空」。

**根因**：为了让断言简单（「上传前必须是空库」），测试直接清空了整个资料库。
这等于把「验收命令」变成了破坏性操作 —— 用户不敢跑自己的验收脚本。

**修法**：
1. 前端夹具只清理标题带 `E2E-` 前缀的资料，并按「用例开始时的 id 基线」做差集，
   只删除本次用例**新建**的那些；`fixtures.ts` 里**不再提供**「清空资料库」这种函数，
   测试根本不应该有这个能力；
2. 清理放在 `finally` 里，用例失败（含超时、浏览器崩溃）时同样执行，
   否则测试资料会留在库里、甚至卡在 indexing 状态；
3. 断言改为相对断言，不再依赖「资料库为空」；
4. 验收脚本改成：先记录基线 → 上传 → 验证 → 只删自己创建的那一条 →
   逐条核对用户原有资料的 id 与状态都没变；
5. 新增一条用例专门验证「跑完资料页用例后，用户自己的资料一份都不能少」。

### C-37 上传与解析必须共用唯一的大小上限（真实缺陷修复）

**症状**：传一个 11 MB 的 md 文件，上传返回 201、用户看到进入队列，随后异步失败，
错误提示是「文件超过 20 MB 上限」——对一个 11 MB 的文件来说这是**假话**。

**根因**：上传上限 20 MB（`file_storage.MAX_UPLOAD_BYTES`）与解析上限 5 MB
（`source_io.MAX_SOURCE_BYTES`）是两个独立常量，中间有 15 MB 的「先成功后失败」地带。

**修法**：合并为唯一常量 `source_io.MAX_FILE_BYTES`（10 MB），
上传与解析都引用它，从根上消除中间地带；前端也用同一个值在上传**前**拦截，
错误文案不再写死数字（写死数字正是当初说假话的原因）。
回归测试直接断言三个常量相等 —— 只要它们还能分别调整，这个缺陷就会回来。

### C-38 解析失败必须给稳定业务码，不能是 Python 异常类名（真实缺陷修复）

**症状**：损坏的 PDF 让界面显示 `unexpected:PdfReadError`。

**根因**：`worker.py` 的兜底分支用 `f"unexpected:{type(error).__name__}"` 当错误码；
前端 `MATERIAL_ERROR_LABELS` 没有这个键，于是原样显示。

**修法**：
1. 解析层新增 `DocumentParseError(code, detail)`，pypdf / python-docx 的异常
   统一收敛为稳定码 `document_parse_failed`（已登记进 `SAFE_MESSAGES`）；
   真实异常类型只进日志（`detail`），不进接口；
2. worker 兜底错误码改为 `internal_error`，异常类型写进日志摘要。

### C-39 `indexing` 中间态必须对 API 可见（真实缺陷修复）

**症状**：用 400 块的大文档、50 毫秒轮询，状态轨迹始终是 `['pending','ready']`，
`indexing` 永远观察不到。后果是前端的「建立索引中」标签与样式成了死代码，
验收步骤里「观察 排队中 → 建立索引中 → 可检索」根本做不到。

**根因**：worker 设置 `material.status = "indexing"` 后只 `flush()`，
而 `runner.run_once()` 是**整批任务结束后才 commit 一次**。
PostgreSQL 默认 READ COMMITTED 下未提交的行对外不可见。

**修法**：设置 `indexing` 后显式 `session.commit()`。
任务此时已带租约（`running` + `lease_until`），因此进程若在这时崩掉，
会被 `recover_expired_jobs` 回收重试；同时补了一个 `SQLAlchemyError` 分支 ——
显式 commit 之后，提交失败不再由外层捕获，必须自己把任务落到 retry，
否则会卡在 `running` 直到租约过期。

新增测试钩子 `_after_indexing_committed()`：测试在「中间态刚提交」这一刻用
**独立数据库连接**读状态，验证它对 API 真的可见。该用例已验证「改回 flush 就会红」。

### C-40 向量索引损坏会让后端进程无 traceback 消失（严重问题，排查中定位）

**症状**：上传资料后，worker 加载完 embedding 模型，**整个 Python 进程直接消失**，
日志里连一行 traceback 都没有，uvicorn 也没有任何异常输出。
表现为「后端跑着跑着就没了」，所有依赖后端的测试与页面一起失败。

**根因**：Chroma 的 HNSW 索引文件损坏。在 `storage/chroma` 上直接读计数会报：

```
chromadb.errors.InternalError: Error executing plan: Error sending backfill request
to compactor: Error creating hnsw segment reader: Error loading hnsw index
```

损坏的来源是**反复强制终止后端进程**（排查过程中多次 `Stop-Process`），
向量写入被中断导致段文件不一致。

**修法**：
1. `ChromaVectorStore` 构造时立刻读一次计数（真正打开 HNSW 段文件），
   损坏时抛出带行动指引的 `VectorStoreError`，而不是等到后台线程碰到才崩；
2. `_try_build_retrieval_stack` 增加兜底 `except Exception`：
   宁可「检索不可用（503）」，也不能让一个原生库异常把启动流程带走；
3. 新增 `scripts/rebuild_all_indexes.py` 与一键入口 `.cmd`：
   向量库是**可重建的派生索引**，正文与分块都在 PostgreSQL 里完好，
   重跑索引即可完整恢复，不需要重新上传。

这条也验证了 C-23 的设计选择是对的：如果正文权威放在 Chroma，
这次损坏就是**数据丢失**而不是「重建索引」。

### C-41 块列表不随轮询刷新（真实缺陷修复）

**症状**：资料处理完成后，详情里已经显示「块数 15」，块列表却一直写着
「这份资料还没有块」，必须手动再点一次列表里的这条资料才刷新。

**根因**：页面的轮询只刷新资料列表与详情（`listMaterials` + `getMaterial`），
不刷新块列表；块列表只在 `selectMaterial` 时请求。

**修法**：轮询里发现「状态为 ready 但块列表还是空」时补一次 `listChunks`。
判据用「块列表是否已有内容」而不是「状态是否刚变化」——
后者需要额外记录上次状态，容易在别的代码路径上漏记而失效（已踩过）。

### C-42 测试的后端依赖必须是明确的（工程约定）

**症状**：后端没起或中途退出时，所有用例以同一个 `fetch failed` 失败，
看起来像测试代码坏了，实际只是环境没就绪。

**修法**：
1. `e2e/fixtures.ts` 先显式检查后端可达性，失败时抛出**能直接照做的指引**
   （现改为要求启动 `APP_ENV=test` 的 8001 隔离后端），而不是让 16 个用例各报一次网络错误；
2. 测试进程的 HTTP 调用统一走带重试 + `Connection: close` 的封装：
   uvicorn 的 keep-alive 默认 5 秒，而夹具里的 `execFileSync` 可能阻塞更久，
   Node 会从连接池复用到已被服务端关闭的连接，抛 `ECONNRESET`，且连接池
   可能**反复**复用同一条坏连接、连重试都不管用；
3. 后端**不由 Playwright 托管**。曾尝试用 `webServer` 自动启动后端，
   结果是被管道托管的 Python 进程会被杀掉，而 Playwright 的 url 健康检查
   是「只在没有实时读取输出时才发现」，于是启动看起来是成功的 ——
   这类问题极难排查，不如明确要求独立启动。

### C-43 用例超时必须覆盖真实流程耗时

Playwright 默认单个用例 30 秒，而「上传 → 后台加载 embedding 模型 → 建索引 →
状态变可检索」在冷启动时可能接近 1 分钟。默认值会让用例在断言等待期间被整体砍掉，
报错看起来像断言失败。已把用例超时提到 3 分钟。

### C-44 测试资料用唯一标题

固定标题会与「上一次失败留下的同名资料」混淆，让 `detail-title` 断言有机会匹配到
旧的那一条。改为每次上传带随机后缀，标题即可唯一标识本次上传的资料。

### C-45 删除资料必须先删数据库记录、再清向量（真实竞态修复）

**症状**：每跑一次浏览器端到端测试，向量库就多出一个孤儿向量（15 条）。
`scripts/check_vector_orphans.py` 能稳定看到「<已删除> | 某 id: 15 条」。
数据库侧完全干净（0 孤儿块），只有向量库留下残影。

**根因**：删除资料原本的顺序是「先清向量、再删数据库记录」，两步不在同一个
事务里；而后台索引任务可能正在处理同一份资料（e2e 里「重建索引」用例之后
紧接着删除）。任务在它自己的检查点看到的资料**仍然存在**，于是继续往下写，
等数据库记录被删掉时，向量已经写进索引了。

这个竞态窗口宽达「解析文件 + embedding 编码」的耗时，所以不是偶发，
而是稳定复现 —— 这也是它值得单独记录的原因：看起来像「偶发脏数据」的问题，
其实有一个确定性成因。

**修法（顺序调整 + 两道检查）**：
1. `delete_material` 改为**先删数据库记录并立即提交**，再清向量、再刷新关键词索引。
   记录一消失，任务在写库前的检查就会看到资料不存在而直接收尾；
   即使任务已经开始写，这次向量清理也会把刚写的删掉；
2. `run_job` 在写库前加检查（挡掉「解析前被删」）；
3. `run_job` 在 `parse_material` 之后再加一次检查（挡掉「解析期间被删」），
   并回滚事务、清掉已写入的版本，避免留下「块在、资料不在」的残留。

**为什么可以接受这个顺序**：极端情况下（清向量时进程被杀）仍可能留下孤儿向量，
但那是**可恢复的**（`check_vector_orphans.py --clean` 能清掉，且它们不会被检索到，
因为检索层查不到正文会丢弃）。反之，原顺序会**稳定产生**孤儿。

**验证**：修复后 e2e 16 项通过，向量库 35 条 = 15 + 20，零孤儿。

### C-46 任务状态写入必须容忍「任务行已被级联删除」

**症状**：资料被删除后，后台线程报
`StaleDataError: UPDATE statement on table 'document_jobs' expected to update 1 row(s); 0 were matched`。

**根因**：`document_jobs.material_id` 是 `ON DELETE CASCADE`，删除资料会把任务行一起删掉。
任务随后写状态时更新了一个不存在的行。

更麻烦的是它的连锁反应：`StaleDataError` 是 **flush 期**抛出的，
失败后 session 进入「待回滚」状态，如果不立刻 rollback，
调用方后续任何查询都会抛 `PendingRollbackError` —— 一串看不懂的错误。

排查过程中还踩到两个衍生坑，都值得记下来：
- `rollback()` 会让对象**整体过期**，之后访问 `job.id` / `job.attempts`
  会触发刷新并抛 `ObjectDeletedError`。所以回滚前必须先把需要的字段取出来，
  而且**不能用 `session.get` 判断行是否还在** —— 它会命中身份映射里的陈旧对象，
  查出来「存在」并不代表行真的还在。
- 正确的形状是「直接 flush，捕获 `StaleDataError`，立刻 rollback，然后收尾」。

**修法**：抽出 `_flush_job_tolerating_deleted()`，成功返回 True；
捕获 `StaleDataError` 时记日志并 rollback。`_settle_success` 与 `_settle_failure`
都走它；`run_job` 里「资料不存在」的分支也先把 `job.id` 取出来再调用，
避免回滚后访问过期属性。

### C-47 验收脚本的轮询间隔必须小于中间态寿命

**症状**：`scripts/e2e_materials_check.py` 报「观察不到 indexing 中间态」，
但后端测试用独立数据库连接已经证明它对 API 可见。

**根因**：脚本原来的轮询间隔是 2 秒（后来是 0.5 秒），而 15 个块的资料
从 `pending` 到 `ready` 只需要约 0.35 秒 —— 整个 `indexing` 中间态都在两次
采样之间过去了。**这不是「中间态不可见」，而是根本没采样到。**

**修法**：轮询间隔改为 0.1 秒。修正后状态轨迹稳定输出 `indexing → ready`。

这条与 C-39 是配套的：C-39 修的是真正的不提交缺陷，C-47 修的是观测手段本身
不可靠 —— 后者如果不修，会让人误以为 C-39 没修好。

### C-48 资料页不做检索：页面职责边界（修正我越界添加的功能）

**问题（由用户指出）**：资料页上有一个「检索自测」面板 —— 输入问题、显示命中块、
并列出向量名次与关键词名次。**它不是设计文档里的功能，是我自己加进去的。**

当时的理由是「阶段 C 需要验证检索链路，做在页面上便于验收」。
这个理由站不住：验收需要的是脚本与测试，不是把开发调试工具塞进产品界面。
结果是资料页承担了问答页的职责，两个页面的边界被我自己搞模糊了。

**设计文档怎么写**：

- 资料页（§2.3）只提供：上传、扩展名与大小提示、列表与状态、
  `QUEUED → PARSING → CHUNKING → INDEXING → READY` 进度、失败原因/重试/重新索引、
  删除，以及最后一条 **「READY 后限定这份资料进入问答」**；
- 问答页（§2.4）才负责检索与回答，而且**两个模式严格隔离**：

| 模式 | 检索范围 | matched_kp | 推荐练习 | 产生学习事件 |
|---|---|---|---|---|
| 知识库 | 内置考研内容 | 可以 | 可以 | 只记弱信号；只有完成练习并自评才写毕业证据 |
| 我的笔记 | 用户资料 | 固定为空 | 不可以 | 不产生 |

也就是说：**检索属于问答页；资料页的职责是"把资料变成可检索"，
并把选中的资料带入问答。**

**修法**：
1. 删掉资料页的检索面板（模板、脚本、样式、`searchMaterials` 封装与相关类型）；
2. e2e 增加一条防回归断言：`search-panel` 必须不存在 ——
   防止以后又被加回来造成职责重叠；
3. 后端 `POST /api/materials/search` **保留**：它是服务端检索能力的直连入口，
   `scripts/e2e_materials_check.py` 与 e2e 的确定性断言都依赖它。
   但要在注释里说清它是**诊断/验收接口，不是产品功能**。

**认知教训**：开发期为了「看得见」而加进界面的东西，很容易留下来变成产品的一部分。
判断标准不是「它有没有用」，而是「设计文档有没有要求它出现在这个页面」。

## 7. 阶段 D 的审查与修复（实现来自另一份工作）

阶段 D 的问答实现由另一份工作提供，本会话按契约
（`01-按顺序开发/15-问答回流SSE与前端顺序.md`）逐项审查并补全。
以下记录审查结论与修复理由 —— 这些都是**实际踩到或测出来的问题**。

### D-01 数据完整性：CHECK 约束只写在模型里、迁移里没有

`chat_sessions.mode`、`chat_messages.role`、`chat_messages.status` 三个 CHECK
只在 ORM 模型里声明，建表迁移完全没有它们，也没有任何列 `server_default`。

影响不是「不够严谨」而是**实际可被绕过**：数据库层拦不住非法取值，
一条写错 `mode` 的会话会用错误的 `source_types` 去检索 —— 静默跨库，
不报错但结果错。

**为什么 `alembic check` 没发现**：Alembic 的 autogenerate 默认**不比较
CHECK 约束**。所以「迁移与模型一致」不能靠它验证，必须用真实的约束存在性测试
（本项目在 `tests/integration/test_chat_flow.py` 里有对应用例）。

### D-02 约束命名：Base 的命名约定会让显式名再加一次前缀

修 D-01 时踩到一个真实陷阱：`Base` 配置了
`ck_%(table_name)s_%(constraint_name)s`，而 Alembic 生成 DDL 时**也会套用**
这套约定。于是迁移里传 `chat_session_mode_valid` 落库成
`ck_chat_sessions_chat_session_mode_valid`，与模型算出的名字不一致 ——
数据库里出现**两个等价约束**，而且 `downgrade` 引用旧名字必然失败。

**处理**：迁移改用**纯 SQL**（`ALTER TABLE ... ADD CONSTRAINT`）而不是
`op.create_check_constraint`，让落库名字完全确定；并在迁移里顺手清掉
历史遗留的错名约束。这条经验对后续所有涉及约束的迁移都适用。

### D-03 消息顺序：同事务写入导致排序不确定（真实缺陷）

**症状**：刷新问答页后，「回答」可能出现在「问题」前面，而且时有时无。

**根因**：`user` 消息与 `assistant` 占位是在**同一个事务**里写入的，
`created_at` 的 `server_default=now()` 在事务内取同一个值 —— 两条消息时间完全相同。
旧排序只有 `created_at`，于是先后成了数据库的偶然结果。

**为什么用 `id` 兜底不够**：`id` 是随机 UUID，加上它只能保证「稳定」，
不能保证「正确」——它可能稳定地把 assistant 排在 user 前面（实测就是如此）。

**修法**：给 `chat_messages` 加 `seq`（identity 列，迁移 `7d2e5a9c4b31`），
排序改为 `ORDER BY seq`：既确定，又符合「先问后答」的业务语义。
另外 `_create_pending` 改为**分两次 flush**（先 user 后 assistant），
因为一次提交多条时 INSERT 的先后由 SQLAlchemy 内部顺序决定，不保证 user 在前。

**用 `Identity()` 而不是 `autoincrement=True`**：后者在 PostgreSQL 下仍会把
`seq` 写进 INSERT 且值为 `NULL`，直接撞 NOT NULL 约束（已实测报错）。

### D-04 索引选错列

`seq` 初次只建了单列索引。但真实查询是「按 `session_id` 过滤 + 按 `seq` 排序」，
单列 `seq` 索引对这类查询没有帮助，而且模型里没有对应声明（`alembic check` 报差异）。
已改为 `(session_id, seq)` 复合索引，并删掉冗余的单列 `session_id` 索引
（复合索引的最左前缀已覆盖它）。

### D-05 matched_kp 归因缺少阈值与领先度

原实现只判断「第一块是否恰好有一个 kp」，**没有阈值、也没有领先度**。
契约 §5 明确要求「第一名必须高于阈值且明显领先第二名，否则 null」。

影响：会把无关问题硬归因到某个知识点，进而给用户推荐无关的追练题 ——
比「不推荐」更糟。重写为按名次累积计分 + 阈值 + 相对领先度。

**用相对领先度而不是绝对分差**：RRF 融合分的量级与查询相关，
绝对差会随量级漂移（分数普遍偏低时几乎永不归因，偏高时又滥归因）。

### D-06 归因结果依赖块的排列顺序

初版按「累积分」排序，于是同一个知识点挂在第 1 位得 5 分、挂第 2 位只得 2.5 分 ——
「哪个知识点更突出」会随检索顺序漂移。

已改为**最佳名次优先、累积分作次判据**：名次是离散且稳定的信号。
名次与分数结论**冲突**时返回 None（两者都源自 RRF，冲突说明这次检索本身不够确定）。

### D-07 无 kp 关联时索引越界崩溃

`ranked[0]` 在没有任何知识点关联时直接 `IndexError` ——
一次正常的问答会变成 500。已显式判空返回 None。

### D-08 引用：不该因「模型没写引用」判失败

原实现在「有检索结果但模型一个 `[C#]` 都没写」时抛
`generation_failed`，把整次回答丢掉。契约要求的是：
**正文可以保留，`[C99]` 不映射来源，并在 metadata 记 `unknown_citation_labels`**。

把「模型忘了引用」当成生成失败，会让用户看到与事实不符的错误。
已改为保留回答并记 `citation_warning`（一个待排查信号，不是失败）。

### D-09 引用未校验是否仍可检索

来源卡片必须指向**当前可检索**的 chunk。资料在问答过程中可能被重建或删除，
旧 chunk 已不该被引用；直接落库会留下指向死数据的来源。
已新增活跃版本校验，失效引用被丢弃并记入 `dropped_citation_labels`。

### D-10 取消时丢弃已生成的文本

契约 §3：「用户取消 SSE：关闭上游流，保存已收到文本可选，但 status 必须是 cancelled」。
原实现只改状态、丢掉文本。已改为保留已收文本并标记 `cancelled`；
完全没收到内容时则**不留空消息**（否则用户看到一条无意义的「已取消」）。

### D-11 前端 SSE 尾帧丢失

服务端发出的最后一帧**没有结尾空行**（发完就不再写数据）。
原前端实现按「空行分帧、把剩余部分留到下一轮」，于是最后一帧永远留在缓冲区里 ——
`done` 事件永远到不了前端，页面**卡在「正在生成」**。

已修：流结束时把缓冲区剩余内容作为最后一帧处理，并补上单帧解析失败的容错
（一帧坏掉不该中断整条流）。

### D-12 流式失败的异常被吞掉

`stream_answer` 的 `except AppError` 分支只把状态置为 `failed` 并回一个
`generation_failed` 帧，**没有记录任何原因**。排查时只能看到「生成失败」，
连是模型超时还是落库失败都分不出。

已补日志（含错误码与已收文本长度）。这条是排查 D-11 时被自己踩到的：
一开始完全无法定位，只能靠缩小范围逐个排除。

### D-13 模型注册的导入顺序脆弱性

只导入 `backend.chat.service` 时，SQLAlchemy 解析
`chat_messages.matched_kp_id` 的外键会报 `NoReferencedTableError` ——
因为 `knowledge_points` 表还没被注册。真实应用路径恰好经由 `backend.models.learning`
注册了它，所以「碰巧」能跑；但任何新的入口（脚本、后台任务）都可能踩到。

已改为：导入 `backend.models` 即调用 `import_models()` 完成全部注册。

## 8. 阶段 D 之后：三个遗留风险的收口

这三条是阶段 D 交付时明确挂账的风险，本轮逐条收口。

### D-14 内存压力：数据库参数与「跑测试前先停后端」

本机总内存 15.8 GB。实测「后端（嵌入模型约 1 GB + Chroma + 连接池）
与完整测试套件同时运行」会把 PostgreSQL 挤到被系统杀掉，
日志留下 `database system was not properly shut down; automatic recovery in progress`，
之后表现为大面积 `connection refused` 与超时（曾出现 7 failed / 117 errors）。

两件事都做了：

1. **数据库侧限流**：项目自带的 PostgreSQL 集群
   （`D:\考研跑通项目\.pgdata`，端口 5433）用 `ALTER SYSTEM` 收紧
   `shared_buffers=32MB`、`work_mem=1MB`、`maintenance_work_mem=32MB`、
   `effective_cache_size=128MB`、`max_connections=30`，
   写入 `.pgdata/postgresql.auto.conf` 后重启生效（已核对 `pg_settings` 里的实际值）。
   这是**项目自带集群**的参数，不影响机器上其它 PostgreSQL 实例。

2. **流程侧前置检查**：新增 `scripts/check_test_env.py`，三种模式：
   - 默认只提醒；
   - `--strict` 要求后端**未**运行（pytest 的前提，后端只会抢内存）；
   - `--need-backend` 要求后端**已**运行（Playwright e2e 的前提，它要真实调 `/api/*`）。

   `scripts/test.cmd` 在第 0 步调用 `--strict`；若后端在跑就**跳过 pytest 并最终以非零码退出**，
   明确打印 `PARTIAL: ... 本次运行不能证明测试套件通过`。
   为什么不是「检测到就自动杀掉后端」：擅自结束用户正在用的服务，比资源竞争更糟。

### D-15 `scripts/test.cmd` 混用 `chcp 65001` 与中文（真实隐患）

该脚本原先既有 `chcp 65001` 又有中文 `echo`。这正是在 `alembic.ini` 上踩过的同一个坑：
cmd.exe **一边读文件一边切换控制台代码页**，含中文的批处理会解析失败。
它此前没炸只是运气。现已改为**纯 ASCII**（中文提示全部移到 `.py` 辅助脚本里），
并把行尾统一为 CRLF（`.gitattributes` 已声明 `.cmd` → CRLF，此前是 LF）。

### D-16 Playwright 偶发失败：整页闪回 loading + 自评把用户弹回专注（真实缺陷）

**现象**：`navigation.spec.ts` 的「准备页、生成练习卷、专注模式、查看答案后自评、全卷回看」
偶发在 `paper-list` 不可见处失败（首轮红、单跑绿、连续两轮全绿）。

**定位**：不是测试写法的问题，是前端两个真实缺陷叠在一起：

1. `load()` 第一行就是 `state.value = "loading"`，而 `study-active`（含全卷 `paper-list`）
   只在 `state === "success"` 时渲染。自评提交成功后会 `await load()` 重新拉取今日学习，
   于是**整块内容被从 DOM 里摘掉再装回来**。用户（或自动化）在这个窗口里点「全卷模式」，
   卷子就不存在。
2. `grade()` 成功后**无条件** `mode.value = "focus"`：正在全卷里逐题自评的用户会被弹回专注。

**修复**：

- `load()` 只在首次加载时进 loading 态；已有数据时刷新在后台完成，视图不闪；
- `load()` 增加请求令牌，丢弃过期响应（连点自评/切模式会并发触发，晚发的请求可能先返回）；
- `grade()` 记住当前模式，只在**专注模式**下才自动跳下一题。

**顺带修掉证据留存**：`playwright.config.ts` 的 `preserveOutput` 默认为 `"on-first-retry"`，
而本项目没开 `retries` —— 结果是**所有失败产物都被丢掉**，
`test-results` 里空空如也，只剩终端一行断言信息，根本无法复盘。
现已改为 `"always"`。

**回落测试**：新增用例「自评刷新期间整卷始终在场，且不会把用户从全卷弹回专注」，
用 `page.route` 把 `/api/plans/today` 延迟 1.5 秒，把那个刷新窗口放大到必然可见。
修复前该断言必然失败，修复后通过。

### D-17 测试库建表职责错位（工程隐患）

给测试库建表这件事，原先是由
`test_alembic_upgrade_head_creates_learning_tables_from_empty_database`
（先 `downgrade base` 再 `upgrade head`）顺手承担的。这带来两种糟糕情况：

- 模型加了新列后直接跑集成测试，会报 `column "xxx" does not exist`
  —— 看起来像代码 bug，实际只是测试库没迁移；
- 单独运行某一个集成测试文件时，测试库可能一张表都没有，直接大面积报错。

两者都是「必须先按特定顺序跑某个测试」的脆弱依赖。
现已在 `tests/conftest.py` 增加会话级 autouse 夹具，显式 `alembic upgrade head`；
迁移测试仍然各自验证「空库重建」与「模型/迁移一致」。

### D-18 归因依据：`matched_kp` 不能只给结论（产品要求落地）

**背景**：`matched_kp` 决定「推荐哪些追练题」。只给结论时，用户无法判断归因对不对；
事后排查也只能靠重跑检索 —— 而重跑并不等于当时的检索（资料可能已重建索引）。

**已实现**（用户选择的方案 A：显示归因依据）：

- 新增 `chat_messages.matched_kp_basis`（JSON，非空，默认 `{}`），迁移 `e54f60dca851`；
  存量消息补空对象，读取端按「无依据」处理。
- 归因计算重构为 `matched_kp_attribution()`，产出 `Attribution`
  （`kp_id` / `source_chunk_id` / `source_rank` / `score` / `total` / `runner_up_total`）；
  `compute_matched_kp()` 保留为只取 id 的轻量包装，原有 19 个归因单测不变。
- 三条出口一致返回 `matched_kp`：非流式 `answers`、SSE 的 `done` 帧、消息列表。
  其中 `attribution_label` 给出依据块在本次回答里的**引用编号**（如 `C1`）——
  没有这个对应关系，「依据来自某块」对用户等于没说。
- 前端在回答下方显示归因依据（`data-testid="attribution-box"`），只显示不计算。

**顺带补一个契约漏洞**：「我的资料」模式此前不产生归因，只是因为用户资料
**恰好没有** `<!-- kp: -->` 标记——那是数据的巧合，不是被强制的契约。
用户上传的讲义只要出现一行 `<!-- kp:xxx -->`，就会凭空产生归因与追练推荐。
现已在 `_search_pending` 里按模式显式清空。

**已知产品局限（不修，改为如实展示）**：`seed/materials/gaoshu-lecture-01.md` 中
「加减结构为什么不能直接替换」这段内容位于 `## 第一章 洛必达法则` 之下，
并被标了 `<!-- kp:math.calculus.limit.lhopital -->`。因此问「等价无穷小加减替换」
会被归到「洛必达法则」。这是**种子资料的标注位置**决定的，不是归因算法的问题。
改为让用户看到依据（哪一节、哪一个引用），从而能自己判断这次归因是否符合预期。

### D-19 e2e 会在开发库留下空会话（已知问题，未擅自清理）

**现象**：聊天页每新建一次会话就落一行 `chat_sessions`，而 e2e 里多处用例
都要先「新建一个干净会话」再断言。跑得越多，侧栏历史里的「新对话」越多 ——
本轮实测开发库里已有 **35 个「新对话」且完全没有消息的空会话**
（另有 7 个含真实提问但当时没有回答的会话，那属于真实使用痕迹）。

**已采取的隔离**：资料库那边有严格的测试隔离（只碰 `E2E-` 前缀的资料，
并在 `finally` 里按 id 基线做差集清理，见 C-36）。会话这边**没有**做对应清理。

**为什么没有顺手加清理**：`chat_sessions` 会级联删除 `chat_messages`
与 `message_citations`，而「哪些会话是测试产生的」在数据上**无法可靠区分** ——
按标题「新对话」删会误伤用户自己新建后还没提问的会话。
为了让侧栏干净一点而冒删掉用户数据的风险，是不划算的。

**留给阶段 E/G 的决定**：可选方案是
（a）e2e 记录基线会话 id、只清理「运行期间新增 且 零消息 且 标题仍是『新对话』」的会话；
（b）保持现状，把测试库与开发库分开跑聊天 e2e；
（c）接受开发库里累积空会话。当前选择是（c）+ 如实记录。

### D-20 模型偶发返回空回答时重试一次（真实缺陷修复）

**怎么发现的**：给聊天页补了 `preserveOutput: "always"` 之后，全量 e2e 留下一份
失败快照，页面上的错误提示是 `answer generation failed`。再结合后端日志
`code=generation_failed detail=provider returned an empty answer 已收文本=0 字`，
确认是**真实模型偶发返回空回答**（一次 delta 都没有）。

这也解释了此前那类「偶发失败」的另一半原因：除了 D-16 的前端刷新竞态，
**外部模型不稳定**同样会让聊天用例间歇性失败。手动重试同一个问题即可成功。

**修复**：流式路径在读到一个新块都没有时，**重试一次**。

- 只在「本轮一块都没产出」时重试。若已经产出过内容，重试会让第二个回答
  接在残句后面，比直接失败更难懂；
- 最多重试一次（`test_two_empty_rounds_end_with_error_frame` 锁住这一点），
  两轮都空才如实报 `generation_failed`，绝不伪造回答；
- 读流的动作抽成 `_stream_deltas()`，断开事实通过 `flags["disconnected"]`
  回传。**没有**用「往流里塞哨兵值」表达结束状态 —— 那会被真的写进 SSE 流污染协议。

**为什么值得改而不是忍着**：一次可用的问答因为模型打嗝就变成「生成失败」，
对用户是明确的倒退；而重试一次的成本与收益完全不对称。

**新增测试**（`tests/integration/test_chat_stream.py`，3 条）：

- 第一轮空、第二轮正常 → 帧序仍为 `meta → delta… → done`，
  `provider.calls == 2`，且**只产生一条 assistant 消息**；
- 重试从头开始 → 最终正文不含重复前缀（不得把两轮内容拼起来）；
- 两轮都空 → 以 `error` 收尾、`calls == 2`、消息状态 `failed` 且正文为空。

### D-21 重试范围扩大到「可重试的上游故障」，并修掉一个被测试抓住的判据错误

**为什么要扩大**：D-20 只处理了「读完一轮但零内容」。而全量 e2e 复跑时
聊天用例仍然失败，手动复现得到 **HTTP 503** —— 这时 `raise_for_status()`
会把错误转成 `AppError` 在**第一轮直接抛出**，重试路径根本没机会执行。
日志只有一条 `app error generation_failed`，正是这个特征。

**现在的判据**（流式与非流式共用同一套）：

| 情况 | 处理 |
|---|---|
| 本轮读完但一个新块都没有 | 重试一次 |
| 本轮抛出 429 / 5xx / 超时、连接错误 | 重试一次 |
| 4xx（鉴权、模型名错等） | **不**重试，直接报错 |
| 已经给用户吐出过内容之后才失败 | **不**重试，直接报错 |

为此给 `AppError` 增加了显式的 `retryable` 标记，并新增 `_provider_error()`
按 HTTP 状态码分类。**没有**用「解析 detail 字符串」来判断可重试性 ——
那会让重试行为依赖于一句日志文案。`detail` 也只放状态码与异常类名，
不带上游响应正文（可能含账号信息）与本机路径。

**被测试抓住的判据错误（值得记下来）**：
第一版判据写的是「整个流开始前 `parts` 是否为空」，于是
「先吐了两块、随后失败」被误判成空回答而重试 —— 用户会看到第一轮的残句
后面又接上第二轮的完整回答。新写的
`test_retryable_error_after_output_is_not_retried` 直接失败（`calls == 2`），
用一行诊断打印定位到真实状态：

```
attempt=1 before=0 len(parts)=1 failure=generation_failed   ← 本轮已产出 1 块
```

正确判据是「**本轮失败前是否已产出内容**」（`len(parts) > before`），
而不是「整个流开始前是否有内容」。这条测试因此保留在套件里。

### D-22 空回答的真正根因：推理模型的思考与正文共享输出预算（配置问题）

重试加上之后仍然会失败，于是直接去打上游 API 才算弄清楚。**上游一直是正常的**
（HTTP 200、内容正确、流式 117 帧），真正的问题是**输出预算**：

当前配置的 `deepseek-flash` 是**推理模型**：它先输出 `reasoning_content`（思考过程），
再输出 `content`（正文），而**两者共享 `max_tokens`**。实测（同一 prompt，只改预算）：

| `max_tokens` | 正文 | 思考 | 结果 |
|---|---|---|---|
| 800 | 185 字 | 1033 字 | 正常 |
| 300 | 267 字 | 214 字 | 正常 |
| **100** | **0 字** | 152 字 | **正文为空** |
| **40** | **0 字** | 68 字 | **正文为空** |

再用项目的真实 prompt 形状（4 段证据 + 10 条历史 + 追问指令）跑三轮：

| `max_tokens` | 三轮结果 |
|---|---|
| 800 | 265 字 / 299 字 / **9 字**（思考 1217 字，正文被挤掉） |
| 3000 | 308 字 / 374 字 / 296 字，全部完整 |

结论：**prompt 越长，思考越长，800 的预算就越容易不够**，
表现为「模型偶发返回空回答」或「回答被截断」。
所以此前那些 `answer generation failed` **不是网络抖动**，而是预算不足。

**修复**：

- `llm_max_output_tokens` 默认 800 → **4000**（`.env.example` 同步，并写明原因）；
- 新增 `llm_retry_max_output_tokens = 8000`：首轮失败时**以更大预算**重试一次。
  原样重试等于再赌一次同样的额度，加大预算才对症；对 429/5xx 也无害；
- `Provider` 增加 `attempt` 参数与 `_token_budget()`，并保证
  **重试预算不会小于基础预算**（写反配置时不至于让重试更紧张）；
- 实际使用的预算记进 `usage.max_tokens_used`，事后排查「是不是额度不够」时有据可查；
- 明确**只取 `content`、绝不把 `reasoning_content` 当正文**发给用户 —— 那是草稿不是结论。

**新增测试**（`tests/integration/test_chat_flow.py`）：

- 重试确实把 `attempt=2` 传下去（漏传时不会报错、也不会有断言失败，只能这样抓）；
- `Provider` 的预算语义：首轮用基础预算、重试切到更大预算；
- 重试预算被写反成更小时，不得小于基础预算。

### D-23 归因阈值比错了量纲：`KP_MIN_SCORE` 实际上从未生效（真实缺陷）

**怎么发现的**：用户实测指出「唯一一条 FAIL」——模型明明正确拒答了
「这个软件怎么安装到手机上」，却仍然被归因到某个叶子知识点，进而给出无关的追练候选。

**根因**：归因阈值 `KP_MIN_SCORE = 0.01` 比的是 **RRF 融合分**。
而 RRF 完全按**名次**给分 —— 只要是第一名就必然拿到约 `1/(60+1) ≈ 0.0164`，
与语义相不相关毫无关系。用真实 embedding 模型实测同一批数据：

| 量纲 | 正常用例（13 条） | 越界用例（知识库里根本没有） | 可分离？ |
|---|---|---|---|
| **原始向量余弦** | 0.5673 – 0.8253 | **0.3368** | ✅ 干净分开 |
| RRF 融合分 | 0.0164 – 0.0328 | **0.0315** | ❌ 越界比正常最低值还高 |

也就是说：`0.01` 比所有实测值都低，**这个号称「弱命中则不归因」的门槛从未生效过**。
后果不是"归因不够准"，而是「越界问题照样挂上知识点并推荐追练题」，
直接违反验收文档里「只有服务端可靠匹配到叶子知识点时才显示追练候选」。

**修复**：

- `RetrievalHit` 新增 `vector_score`（原始余弦）与 `fused_score`（RRF 分）；
  `score` 明确为「排序依据分」—— 默认等于融合分，启用重排后会被改写成重排分，
  所以**不能用它做相关性判断**。检索服务不再把向量路的原始分数丢掉
  （此前 `vector_hits` 只取了 `chunk_id`），重排复制时也不再静默丢弃这两个分。
- 阈值改名为 `KP_MIN_COSINE = 0.45`，比的是**原始余弦**；
  `KP_LEAD_RATIO` 保留用累积分（它衡量「被多少条命中、排得多前」，与量纲无关）。
- 阈值取值：实测正常命中最低 0.5673、越界最高 0.3368，取 0.45 既明显高于越界，
  又给真实用户资料（比评测讲义杂）留出余量。
- 纯关键词命中（`vector_score is None`）**不归因**：没有语义支持就不硬猜。
- 融积分必须为正才归因 —— 这一条保留了旧实现「零分不归因」的契约
  （以前由 `分数 < 阈值` 顺带覆盖，阈值换量纲后必须显式写出来，否则契约会静默消失）。

**真实链路验证**（同一会话连续提问）：

| 问题 | 归因 | 知识点 | 相关度 |
|---|---|---|---|
| 洛必达法则的适用条件是什么？ | 有 | 洛必达法则 | 0.6921 |
| 加减结构里能不能直接替换等价无穷小？ | 有 | **等价无穷小替换** | 0.7439 |
| 这个软件怎么安装到手机上？ | **无** | — | — |
| 今天天气怎么样？ | **无** | — | — |
| 请推荐几部好看的电影。 | **无** | — | — |

顺带解决了一个**先前记录为「已知局限」的问题**：第二行那个问题在旧实现下会被
归因到「洛必达法则」（因为那段讲义内容标在洛必达法则小节下），
现在正确归到「等价无穷小替换」—— 阈值生效后，词面/位置噪声不再主导归因。

### D-24 追练候选会回溯历史归因（真实缺陷，`followup_candidates` 此前无测试覆盖）

修完 D-23 后在真实验证里立刻发现：越界问题的「追练候选」仍然是 4 条。原因是
`followup_candidates` 用 `matched_kp_id.is_not(None)` 查**历史上最近一条有归因的消息**
—— 用户刚问了一个答不上来的问题，系统却拿几十条之前的旧归因出题。

**修复**：改为只认**最新这一条**已完成回答的归因；它没归因就给空候选。
`mark_confused` 同样只认最新回答（学习信号记错对象比不记更糟）。
前端两个按钮的可用性也从「有没有已完成回答」改为「**当前回答有没有归因**」，
否则会出现「按钮可点、点下去 409」。

**为什么这个 bug 能活下来**：`followup_candidates` **完全没有测试覆盖**。
已补 `tests/integration/test_followup_candidates.py`（7 条）：
最新回答有归因给候选、越界回答给空（即使历史有归因）、生成中占位不遮盖、
困惑标记只认最新回答且 `changes_mastery: False`。

### D-25 会话推迟到第一条提问才落库；历史列表按资料范围过滤（收口 D-19）

**触发**：用户在验收时提出「问答页两个模式的对话历史应该分开，不然按来按去看不清楚」。

**先核对规格 —— 这件事其实分两半，性质不同：**

1. **两种模式确实「严格隔离」**：篇 01 第 95–100 行有明确的表，规定 `我的笔记` 模式
   `matched_kp` **固定为空**、**不推荐练习**、**不产生学习事件**。实测确认三条都已执行
   （`user` 模式 `matched_kp=None`、追练候选 0 条、`mark-confused` 返回 409、
   `learning_events` 计数不变）。既然两者行为完全不同，把历史混在一个扁平列表里确实不合理。
2. **但规格没有规定列表要分组**：篇 15 第 78 行只写 `mode` 用于「不能由历史消息偷偷跨库」，
   即**检索范围隔离**。所以「按模式取历史」属于产品体验增强，不是实现漏了规格 ——
   按项目规矩在此记录该决策。

**同时收口 D-19 的真根因。** D-19 已记录「每新建一次会话就落一行」，但当时的三个可选方案
（基线差集清理 / 分开跑 e2e / 接受累积）都在「**怎么清理已经产生的空会话**」上打转，
因为数据上无法可靠区分「测试建的」与「用户自己刚建、还没提问的」。
真正的根因是**页面在切换范围或点「＋」时就立刻落库**：
本轮实测开发库 147 条未归档会话中 **99 条完全没有消息**（builtin 49 / user 50）。

**改法（三步，都不引入新的删除风险）：**

1. `GET /chat/sessions` 支持可选 `mode`，且**空会话不再返回**。
   响应字段不变，`mode` 不传即原行为（向后兼容，是超集）。
2. 前端改为**懒创建**：切范围与「＋」只开一段草稿（不发任何请求），
   会话在 `send()` 里「用户真的发出第一条问题」时才创建；
   历史列表按当前范围过滤，每条仍保留模式小字（双保险）。
3. 历史空会话用**归档**（不是物理删除）一次性清理：
   新增 `scripts/archive_empty_chat_sessions.py`（默认预演，加 `--apply` 才写）。
   归档后不再出现在列表里，问答与引用记录仍可追溯 ——
   这正好绕开了 D-19 当时担心的「为了侧栏干净而冒删掉用户数据的风险」。

**实测（真实 PostgreSQL + 真实后端）：**

| 验证 | 结果 |
|---|---|
| `python -m pytest` | **380 passed**（新增 `tests/integration/test_chat_sessions.py` 8 条） |
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| `GET /chat/sessions` | 48 条（builtin 28 + user 20） |
| `?mode=builtin` / `?mode=user` | **28 / 20**，各自只含本模式；两者之和 = 不带参数的 48 |
| `?mode=x` | **422**（`Literal` 校验生效，不会被当成「不过滤」） |
| `scripts/archive_empty_chat_sessions.py` | 预演 99 条 → `--apply` 后：未归档 48 条、空会话 **0** 条 |

**测试同步**：`frontend/e2e/chat.spec.ts` 原有两条用例依赖「切换范围会新建会话」，
已改写为断言新契约（点「＋」**不**增加历史条目；发出第一条问题后才出现），
并新增一条「历史跟随当前范围、不混入另一种模式」。

**未完成项（必须由后续会话补）**：上述两条 e2e 改写**未在本会话执行过**
（`npx playwright test` 被沙箱拦截、权限被拒），需补跑
`npx playwright test chat.spec.ts` 确认后再算收口。

### D-26 问答要有教学回路：先追问讲通，确认理解之后才问要不要练

**用户指出的问题**（原话）：「问答页面的功能好像不是通过追问来解决用户的问题，
然后解决之后再问用户要不要生成题目给用户去练习的。而是直接用户自己有个按钮这样不好吧。
这样丢失了两个功能：一个追问帮助用户了解这个问题，一个知道用户解决问题之后再问你是否要生成题目。」

**核对规格 —— 这两半性质不同，不能混为一谈：**

1. **「追问建议」规格计划过，但被明确砍出八周范围**。篇 02 第 4 行原文：
   「个别模块在八周内被合并或延期（例如 repository 层内联进 07 篇、**追问建议不在八周内**）」
   → 这是**有意的范围裁剪，不是实现漏做**。篇 03 第 274 行也计划过「推荐追问」。
2. **「理解之后再询问是否出题」规格里没有**。规格只规定「困惑只触发题库追练建议」
   （篇 01 第 213 行）—— 触发源是**困惑**，不是**理解**。所以这一半属于产品增强，
   按项目规矩在此记录该决策。

**同时发现项目自己的一处文档违规**：规格那句「追问建议不在八周内」从未记进本文件；
而本文件另一处用「追问指令」描述 prompt 形状，但当时的 prompt 里**并没有**任何追问指令
（实测 `grep -c "追问|引导|先问"` = **0**），措辞会误导读者以为已经实现。

**改动一：提示词加教学约束**（`backend/chat/service.py` 的 `SYSTEM_PROMPT`，由另一份实现补上，
本会话核对）：把原来一句话的 system 指令拆成【不可违反】（只依据资料证据、
关键结论必须 `[C#]` 引用、资料不足必须说明）与【教学方式】（问题含糊先问清最关键的一点、
多步推理一次只讲一步、用户说「不懂」就**换一种讲法**而不是重讲一遍）。
其中特意写明：**即使只是澄清、只讲一步或换讲法，也必须带 `[C#]` 引用** ——
引用校验依赖正文里的 `[C#]`，教学化表达不能成为丢掉引用的借口。
SSE 与非流式共用 `_prompt()`，改一处两处生效。

**改动二：把「理解确认」变成练习入口的闸门**（`frontend/src/pages/ChatPage.vue`）：

- 原来「推荐已有追练题」与「这个知识点我不理解」是**同辈的两个按钮**，
  只要服务端归因存在，练习入口立刻可点 —— 等于跳过了「你懂了吗」。
- 现在新增「我明白了」，练习入口的可用性改为
  `canOfferPractice = 有归因 && 已确认理解`。
- 没有归因时点「我明白了」**不给练习入口**，而是如实说明原因 ——
  「我的笔记」模式按契约 `matched_kp` 固定为空、不推荐练习，这里必须解释清楚，
  不能给一个点下去会 409 的按钮。
- 「我不理解」的提示补一句「继续追问一次，我会换一种讲法」，与改动一衔接。
- 它只是**界面推进闸门**，不参与任何学习状态：掌握度、毕业证据与困惑信号
  全部仍由后端决定（前端绝不自行判断「是否已掌握」）。

**实测：**

| 验证 | 结果 |
|---|---|
| `python -m pytest` | **380 passed** |
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| 构建产物含新文案 | 是（`我明白了` 与 `先确认“我明白了”，再决定要不要练` 均在 `dist` 中） |

**测试同步**：`frontend/e2e/chat.spec.ts` 原「模式隔离」用例改写为
「练习入口必须先确认『我明白了』」——断言「无回答时三个入口都可见但禁用」，
以及（有真实回答时）**归因已存在但练习入口仍禁用 → 点「我明白了」后才启用**。

**仍未验证**：该 e2e 用例**未在本会话执行**（`npx playwright test` 被沙箱拦截、权限被拒），
与 D-25 同属待补跑项。

### D-27 删除入口从右上角移到每条会话旁边（用户要求）

**用户原话**：「帮我在每一个对话旁边弄个删除 x 的按钮，而不是在右上角弄归档」。

**改了什么**

- **模板**：会话列表由「一个 `<button>` 就是一条」改成
  「`<div class="conversation-row">` 包住『可点的会话按钮』+『× 删除按钮』」。
  **不能把 × 嵌进原来的 `<button>` 里**——嵌套 button 是非法 HTML，浏览器会拆散 DOM，
  点击行为也就不可预期。所以是同级两个按钮，天然没有事件冒泡冲突。
- **脚本**：`archiveCurrent`（只对当前会话生效）改成 `archiveSession(target)`，
  可以删列表里的**任意一条**。删的若是当前打开的那条，就自动切到下一条；一条不剩则回到草稿。
- **右上面板**：移除「归档」按钮，只留「改名」。顺带删掉随之变成死代码的
  `.danger-button` 样式（改前先确认全仓只有这一处用它）。
- **样式**：选中态/hover 从 `.conversation-item` 上移到 `.conversation-row`；
  × 默认 `#96a3b8`，hover 变 `#b42318`+浅红底，生成中 `disabled` 且降透明度。

**为什么按钮叫「删除」但后端不真删**

后端 `DELETE /chat/sessions/{id}` 是**归档**（`archive_session` 只置 `archived_at`），
不动 `chat_messages` / `message_citations`——项目既定设计，问答与引用要可追溯。
所以「删除」是交互措辞，数据仍在库里，只是不再出现在列表。
若将来真要物理删除，属于**改产品规则**，需单独决策，不能在 UI 里偷偷升级语义。

**确认框保留**：× 是个小目标，容易误点，仍弹 `window.confirm`
（文案改成「删除会话「X」？它会从列表移除，但问答与引用记录仍保留在库里。」），
让用户知道数据没丢。

**测试同步**：`frontend/e2e/chat.spec.ts` 新增两条——

1. 「删除按钮挂在每条会话旁边，右上角不再有归档入口」：纯结构断言，
   **不点任何删除**，对开发库零风险、不联网。断言右上角无归档按钮、
   每个会话行恰好一个 ×、且 × 带 `aria-label`（不能是裸 ×）。
2. 「点会话旁的 × 只删掉这一条」：**只删用例自己新建的那条会话**——
   e2e 跑在开发库上，删错一条就是删用户的真实对话。先经「新建草稿 → 发第一条问题」
   造出会话，等生成结束（删除按钮启用）后定位列表首位（按 `updated_at` 倒序），
   显式接受确认框，再断言总数只回到 `before`。当前范围无资料可检索时直接跳过。

**验证**

| 验证 | 结果 |
|---|---|
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| e2e 文件语法 | 通过（用 esbuild 转译 `.ts`，exit 0） |
| `archiveCurrent` / `.danger-button` 残留 | 无 |
| **e2e 实跑** | **未执行**——服务当时全停（PG/后端/前端均无响应），且 `npx playwright test` 在此之前已被沙箱拦截过。属待补跑项。 |

### D-28 追问引导：提示词里的教学约束（含「引用不能被省掉」这条硬约束）

**需求**：让助手更像在带学生，而不是一次倾倒答案 ——
问得含糊先澄清、需要多步时一次只给一步、用户说「不懂」就换一种讲法而不是重讲一遍。

**改法（只改一处）**：全部写进 `_prompt()` 用的 `SYSTEM_PROMPT` 常量。
因为 SSE 与非流式**共用同一个 `_prompt()`**，改这一处两处生效 ——
这也是刻意如此：如果为了某个模式单独写一份 system，两份提示词会慢慢漂移，
用户迟早会遇到「流式会引导追问、非流式不会」这类怪事。

**钉死的那条硬约束**：提示词里**显式**写明
「即使只是澄清问题、只讲一步、或换一种讲法，也必须带上 `[C#]` 引用」。

为什么必须单独点名：引用校验依赖正文里的 `[C#]`，而模型很容易认为
「我只是反问一句，不需要引用」—— 一旦省掉，那次回答就变成没有任何来源的结论，
而这正是本项目最不能接受的事。笼统写一句「关键结论要引用」在短回答里会被忽略，
所以这里把三种短回答场景（澄清 / 只讲一步 / 换讲法）**逐一列出**并要求带引用。

**两层测试锁住它**：

1. 提示词契约（`tests/unit/test_chat_followup_budget.py`）：
   引用格式与「不可违反」分区存在；三种短回答场景各自被点名要求带引用；
   三条教学约束都在；拒答底线（资料不足要说明、不能编造来源）没被挤掉；
   消息顺序仍是 system → 证据 → 历史 → 当前问题；证据仍带 `[C1]/[C2]` 编号。
   另有一条防回归断言：**整个模块里 system 消息只被构造一次**
   （防止有人再写第二份 system）。
2. 行为层（`tests/integration/test_chat_flow.py`）：
   让假 provider 只回一句澄清问句且**不带任何引用**，验证
   ——回答本身保留（不判失败）、**来源为空（绝不伪造）**、
   `metadata.citation_warning == "no_valid_citation"` 留下可排查信号；
   再验证只要引用带上了，归因与引用落库照常工作。

### D-29 多轮上下文预算：按 token 裁剪，不再写死 10 条

**需求**：规格篇 16 第 49 行把「多轮对话与上下文预算」列为 P1。
加了追问引导之后轮数会变多，写死「最近 10 条」会出问题。

**为什么固定条数真的会出事**：每轮长度差异极大 ——
短问答时本可多带几轮，而长解答时几条就能把上下文撑大，
进而把推理模型的**输出预算**挤掉。这个坑当天已经踩过一次
（`reasoning_content` 吃掉 `max_tokens` 导致正文为空，见 D-22），
所以这里不是「优化」，是消除一类已知故障。

**改法**：

- 新增配置 `llm_history_token_budget`（默认 **1200**）：够记住上几轮在聊什么，
  又不会让历史喧宾夺主（资料证据本身通常已占几百到一千多 token）。
- 新增两个纯函数：`estimate_tokens()`（CJK 约 1 字 1 token、其余约 4 字符 1 token，
  **向上取整、宁可多算**）与 `select_history_within_budget()`。
- **不引 tokenizer**：这一层只需「别把上下文撑爆」，不需要精确值；
  引 tokenizer 会给部署加依赖还要联网下载词表。估算只要偏保守就够。
- 裁剪规则：从最近往前累加，**整条**消息进或整条不进（绝不把长回答截一半，
  那会让模型看到残缺上下文）；单条超预算时**跳过它并继续往前找**
  —— 追问场景下最近那条很可能就是长解答，把更早的关键上下文一起丢掉更糟。
- `None` 语义下沉到 `_search_pending` 内部：任何调用点没传预算都等于「用配置值」。
  这是刻意的 —— 三个调用点里漏传一个，多轮上下文就会被**静默关掉**，
  那是能力缺失、不报错、最难发现。

### D-30 理解确认关卡：从「三个平级按钮」改成中性的二选一

**需求**：回答下方先给一个中性入口「我明白了，想练几道」/「还是不太懂」；
点前者才去取追练候选，点后者记弱信号并换一种讲法。

**改动前的问题**：界面把「我明白了」「这个知识点我不理解」「推荐已有追练题」
并排摆成三个同辈按钮。这暗示用户「必须选一个态度」，
并且「要不要练」与「有没有听懂」被摆在同一层，等于跳过了理解确认。

**改动后**：

- 回答下方只有一个**中性二选一**：`我明白了，想练几道` / `还是不太懂`。
- 点「我明白了」→ **直接**取追练候选并展示卡片
  （不再要求用户再点一次「推荐已有追练题」：既然已经说明白了，
  下一步自然是要不要练几道，中间不该再插一个按钮）。
- 点「还是不太懂」→ 记弱信号，并明确提示「直接继续追问一次，我会换一种讲法」。
- 两个分支**互斥**：先点过「我明白了」再点「还是不太懂」也合法，
  此时会把练习入口收起来，否则界面会同时说「你懂了」和「你不懂」。
- 没有归因时仍如实说明原因（尤其「我的资料」模式按契约不推练习），
  而不是给一个点下去会 409 的按钮。

**顺带收敛了一处脆弱点**：理解确认状态的重置原先散在 4 处，
后来加「还是不太懂」「追练候选已取过」两个状态时，任何一处漏掉都会变成
「上一条回答的『我明白了』替新回答放行练习入口」。已收敛成
`resetComprehensionGate()` 一个函数，四处调用点统一走它。

**真实链路验证**（打真实模型，四类问题各一次）：

| 场景 | 模型实际表现 | 引用 |
|---|---|---|
| 「这个怎么算？」（含糊） | 没有瞎猜：「你说的『这个』我不太确定指哪一个，先确认一下你再告诉我，我就不瞎猜了」 | C1–C4 |
| 「请详细推导」（要求多步） | 只给一步：「先说最核心的一点，别的先不铺开」 | C1–C3 |
| 「适用条件是什么？」 | 主动声明分步：「我先说清楚第一层，说完停下问你」 | C1、C3 |
| 「还是不太懂，再讲一遍」 | 换了讲法：「这次不给你列条件了，反过来讲 —— 先看不满足条件会出什么事」 | C1 |

最后一行正是要防的失败模式：回答变短、口吻口语化、内容换了个角度，
但**引用没被省掉**。这说明把三种短回答场景逐一列出并要求带引用是有效的 ——
笼统写「关键结论要引用」时，这类短回答最容易漏引用。

**e2e 覆盖**：两条用例（`chat.spec.ts`）——
「理解确认关卡：先确认『我明白了』才给练习题，选『还是不太懂』则不给」
（断言练习入口在确认前**根本不存在**、确认后出现候选卡片），
以及「选『还是不太懂』不推题，而是记弱信号并提示换一种讲法」。

### D-31 会话「删除」改为真删除（物理删除，用户要求）；并修掉一处编号撞车

**用户要求**：「直接帮我弄成删除按钮，对应后端也进行删除那份会话记录」。

D-27 那一版只是把入口从右上角搬到了每条会话旁边，后端**仍是归档**（只置 `archived_at`）。
本次把语义真的改成删除。

**后端**（`backend/api/routes/chat.py`）

- `DELETE /chat/sessions/{id}` 由归档改为**物理删除**；路由函数 `archive_session` → `delete_session`。
- 按依赖顺序逐条删：`message_citations` → `chat_messages` → `chat_sessions`。
  **没有**只删会话行、靠数据库级联：模式里虽然声明了 `ON DELETE CASCADE`
  （迁移 `9b7f1d3e2c6a` 里确实建了，之后的迁移也没动过它），但显式删除不依赖那份约束
  是否真的存在 —— 换库或重建约束时不会静默留下孤儿行。
- 随之删掉了顶层 `datetime` / `timezone` 导入（原本只有归档端点用它；
  `followup_candidates` 与 `mark_confused` 都是函数内局部导入，不受影响）。

**前端**

- `archiveChatSession` → `deleteChatSession`；`archiveSession` → `deleteSession`。
- 确认框改成把话说死：「删除会话「X」？**此操作不可恢复**：该会话的问答记录与引用会被永久删除。」
  × 的 tooltip 也加了「（不可恢复）」。

**刻意没做的三件事**

- **不删学习事件**。`learning_events.source_id` **故意没有外键**（见 `backend/models/learning.py`
  的注释），所以删会话不会连带删掉 `marked_confused` 之类的事件 —— 掌握度与弱信号是学习事实，
  不该因为用户清理了一轮对话就抹掉。代价是那几条事件的 `source_id` 变成悬空 id（可接受，schema 本就允许）。
- **保留 `GET /chat/sessions` 的 `archived_at IS NULL` 过滤**：库里还有上百条历史归档行，
  去掉过滤会让它们一次性冒出来。
- **`scripts/archive_empty_chat_sessions.py` 仍走归档**（它清的是零消息空壳，归档足够且可回溯），
  但已修正它的 docstring —— 原文写着「与 `DELETE /api/chat/sessions/{id}` 同一语义」，
  这句现在**不成立**，留着就是「文档写 A、代码是 B」。

**测试**（`tests/integration/test_chat_sessions.py` 新增 4 条）

| 用例 | 锁住的契约 |
|---|---|
| `test_delete_removes_session_messages_and_citations` | 三张表都要清空，不能留孤儿引用（引用挂真实 chunk，因为 `chunk_id` 有外键） |
| `test_delete_only_touches_the_target_session` | 删一条不能影响别的会话 |
| `test_delete_is_permanent_second_delete_is_404` | 不可逆：第二次删同一 id 必须 404，而不是「结果一样」的 204 —— 正是这一条区分了归档（幂等）与删除 |
| `test_delete_unknown_session_is_404` | 删不存在的 id 明确 404，不静默成功 |

**实测（真实后端 + 真实 PostgreSQL）**

| 步骤 | 结果 |
|---|---|
| 建会话 | 201 |
| 写入一条消息后列表可见 | 是（`true`） |
| `DELETE /api/chat/sessions/{id}` | **204** |
| 库里残留 | `chat_sessions` 行已消失、`chat_messages` **0 条** |
| 重复 `DELETE` | **404** `chat_session_not_found` |

`pytest` 全量 **407 passed**；`npm run build`（含 `vue-tsc --build`）通过。

**e2e 也补跑了**（此前多次被沙箱拦下，这次通过）：

| 命令 | 结果 |
|---|---|
| `npx playwright test chat.spec.ts -g "删除"` | **1 passed** —— 结构断言：右上角无归档入口、每行恰好一个 ×、× 带 `aria-label` |
| `npx playwright test chat.spec.ts -g "×"` | **1 passed** —— 行为断言：造会话 → 等流结束 → 点首位 × → 接受确认框 → 总数回到 `before` |

第二条在浏览器里实测走通了「前端 × → 后端真删」。注意该 e2e 的 `reset_today` 夹具会
**重置开发库当日学习数据**（既有夹具行为，不是本次改动引入）。

**顺带修掉的一处文档缺陷（编号撞车）**

同一个提交 `5bb3d2f` 里同时存在**两套** D-25/D-26/D-27：
一套是本文件 1190/1241/1296 行（会话懒创建、教学回路、删除入口），
另一套是 1343/1375/1401 行（追问引导提示词、多轮预算、理解确认关卡）。
ID 重复会让「详见 changes D-25」这种引用**同时指向两个不同的东西**，
而且 `status` / `checklist` 里的 D-25 / D-26 引用全部指向先写的那一套。
因此把后写的三节改号为 **D-28 / D-29 / D-30**（内容一字未动），本节顺延为 D-31。

### D-32 补齐 D-02 / D-03 的独立 citations 帧与资料回跳（2026-09-20）

验收复核发现旧实现只有 `meta → delta* → done`，把 citations 塞进 done；引用卡也只显示
标题路径和摘要，既没有资料名称与稳定块标识，也无法定位真实资料。这不满足验收 D-02、D-03。

- 成功流固定改为 **`meta → delta* → citations → done`**；无命中也发送空 `citations` 帧。
  失败仍为 `meta → delta* → error`。
- `citations` 与 `done.citations` 统一使用结构化卡片：`label`、`material_id`、
  `material_title`、`chunk_id`、`ordinal`、`heading_path`、`preview`。刷新恢复接口复用同一字段集。
- 引用卡是可点击按钮，跳转 `/materials?material_id=…&chunk_id=…`；资料页把目标块补进预览、
  滚动并高亮。即使目标块不在前 20 个预览中，`focus_chunk_id` 也会把它追加到返回集。
- `tests/integration/test_chat_stream.py` 逐帧锁定独立 citations 事件及全部卡片字段；资料定位
  接口和前端类型/构建纳入本次回归。


### D-39 e2e 隔离改造的收口（原误编号为「19.」，2026-09-20）

背景：另一轮工作把 e2e 改成了**隔离模式**——后端要 `APP_ENV=test`、监听 8001、
前端 5174，并且 `assertBackendReachable` 会拒绝 `environment != "test"` 的后端。
方向是对的（早先 e2e 直接打开发库，`reset_today` 会清空真实作答与掌握状态），
但改造只做了一半：**没有任何机制把测试数据准备好**，于是隔离模式下 e2e 稳定挂在 4 条上。
本节记录收口过程与踩到的坑。

> 编号说明：这一节起初写成了 `## 19.`，与本文档既有的编号体系（章节用 `## N.`、
> 变更条目用 `### D-NN`）冲突，而且当时另一个 AI 也在同一天追加了条目。
> 现统一为 `### D-39`。下面 D-33～D-38 是同一轮收口的细分条目。

### D-33 测试库没有资料：e2e 的 4 条失败来自「缺数据」，不是缺功能

**现象**：隔离模式跑 e2e 得 `24 passed / 4 failed`，失败的是
「删除资料后列表不再包含它」「超上限被拒绝」「真实提问」「归因依据」——
全是需要**资料**才能验的用例。

**根因**（实测确认，不是推测）：

- `kaoyan_test` 里 `materials = 0, chunks = 0`：pytest 夹具会 TRUNCATE 资料表，
  而 `scripts/seed.py` 只灌知识点与题库、**不含资料**；
- 于是隔离模式一上线，这些用例就没有对象可测。

**修法**：新增 `scripts/prepare_e2e_data.py`（+ `prepare-e2e-data.cmd` 包装），
把 e2e 需要的资料灌进**测试库**：

- 1 份内置资料（`seed/materials/gaoshu-lecture-01.md`）——「内置资料」模式的检索范围；
- 1 份用户资料（内容与内置讲义**不重叠**）——「我的资料」模式，模式隔离用例要用它；
- 走与生产**完全相同**的摄取管道（落盘 → 解析 → 分块 → 建向量 → 激活版本），
  不直接写库，否则向量与分块会与真实路径不一致；
- 强制 `APP_ENV=test` 且库名必须以 `_test` 结尾，否则拒绝执行 ——
  这一步决定会不会写到开发库，必须硬拦；
- 向量与上传走**测试专用目录**（`storage/chroma-test`、`storage/uploads-test`），
  不碰开发索引。

### D-34 准备脚本必须先清空资料：否则被 `message_citations` 外键挡住

第一版脚本只删「同名的两份」，遇到残留状态就失败。改成先清空测试库的**全部**资料时，
第一刀就撞上外键：

```
psycopg.errors.ForeignKeyViolation: update or delete on table "document_chunks"
violates foreign key constraint "fk_message_citations_chunk_id_document_chunks"
```

因为测试库里已有聊天记录引用了那些 chunk。修法是**按依赖顺序**先清聊天再清资料
（`message_citations` → `chat_messages` → `chat_sessions` → 资料）——
与项目里「删资料」同一条原则，也正是 D-31 里显式逐条删的理由。

### D-35 数据准备之后必须重启后端：Chroma collection 被重建会让旧进程 500

**踩了两次的坑，值得单独记**：准备脚本会 `delete_material_all_versions` 并重建
collection；如果后端进程是在**这之前**启动的，它持有的还是旧 collection 引用，
于是准备之后所有检索请求直接返回 **500**（`/api/materials/search` 实测）。

两种错误顺序都验证过：

- 先起后端 → 再准备数据 → 后端 500（陈旧引用）；
- 先准备数据 → 同时起后端 → 后端 `[Errno 10048]` 绑定失败
  （collection 正在被重建，启动过程失败），而 e2e 因此被**跳过**，
  整个流程只打印 `PARTIAL`。

**唯一可靠的顺序**：先起后端 → **等它就绪** → 再准备数据 → 跑 e2e。
`test.cmd` 已按此改成：启动后端 → 轮询 `--need-backend` 直到就绪（最多 120 秒）
→ `prepare-e2e-data.cmd` → `npm run test:e2e` → 停掉后端。

### D-36 顺手修掉的三处

1. **检索测试残留知识点污染 e2e**：`tests/retrieval/conftest.py` 只 TRUNCATE
   `RAG_TABLES`（三张资料表），而 `test_hybrid_search` 会自建
   `test.retrieval.kp.<随机>` 知识点 —— 每跑一次 pytest 就在测试库留一个可考核叶子。
   e2e 的知识树用例断言「叶子恰好 5 个」，被顶到 6 个就失败，**看起来像前端 bug**。
   已在夹具里按 `test.` 前缀清掉（前后各清一次）。
2. **新脚本缺 UTF-8 BOM，中文被按 GBK 误解码**：新写的
   `start-test-backend.ps1` 没有 BOM，PowerShell 5.1 下 `$env:APP_ENV = "test"`
   被吃掉，后端以 **dev** 环境启动（健康检查里 `environment` 是 dev），
   隔离形同虚设。项目里其它 `.ps1` 都有 BOM，只有这个漏了；已补。
3. **代码注释指向错误的记录编号**：`delete_session` 的注释写「取舍记在 D-28」，
   而 D-28 是「追问引导」，物理删除的记录实际是 **D-31**。已改为 D-31。

### D-37 引用展开断言的偶发性：是测试时序，不是前端缺陷

`回答展示归因依据` 用例里「点开引用列表后能看到 `[C1]`」偶发失败。
用最小脚本直接观察真实 DOM 后确认**前端完全正常**：

```
点击前 aria-expanded = false, .citation-list 数量 = 0
点击后 aria-expanded = true,  .citation-list 数量 = 1
点击后 code 文本 = ["[C1]","[C2]"]
```

失败的原因是展开是**纯前端本地状态**，而流结束后 `fetchChatMessages` 还会刷新一次
消息列表；点击若恰好撞上那一瞬的重渲染，展开状态会丢掉（`aria-expanded` 回到 false），
而点击本身不报错。已把「点击 → 确认」改成 `expect.poll` 里的**会重试整体**：
只在没看到编号时才补点一次（已展开时再点会收起）。连续多轮已稳定。

### D-38 用文件活动与端口排查「流程卡住」

`test.cmd` 曾整轮卡死到超时。排查手段值得记下来（当时所有服务都不响应、也没有新日志）：

- 找 cmd/powershell 进程的**启动时间**，确认是哪一轮留下的；
- 查**端口监听**（`Get-NetTCPConnection -LocalPort 8001`）确认后端是否真的起了；
- 用「最近 N 分钟改动的文件」判断流程停在哪一步；
- 前台手动跑启动脚本，才看到被隐藏窗口吞掉的真实报错
  （`[Errno 10048] ... 只允许使用一次`）。

结论：**子进程的报错必须落在可查的地方**，否则「没反应」会被误判成「还在跑」。
`test.cmd` 因此在失败路径上也停后端（`:failed_after_backend`），避免残留进程占着 8001。

### D-40 测试向量库 HNSW 损坏 → 隔离 e2e 从 28 passed 退化为 26/2（2026-09-20）

**现象**：收口之后隔离 e2e 稳定跑出 `26 passed / 2 failed`，两条失败都是
`.chat-notice--error = "retrieval failed"`。因为它们断言的是「模型/配置类错误」，
所以报错停留在措辞不匹配上 —— 掩盖了真正的事实：**检索阶段就挂了，根本没走到模型**。

**排查路径**（记录下来，因为两次都差点归错因）：

1. 先怀疑 LLM 配额：错。后端日志里没有任何模型相关失败。
2. 再怀疑孤儿向量：方向对了一半。实测向量库 **85 条**，而正常应为 17 条
   （15 + 2 块），确实在累积；但孤儿向量本身不会让检索失败（检索层查不到正文会丢弃）。
3. 直接问向量库才看到真相：

```
chromadb.errors.InternalError:
Error executing plan: Error sending backfill request to compactor:
Error constructing hnsw segment reader: Error loading hnsw index
```

**这就是 C-40 记录过的老毛病**（当时表现为后端进程无 traceback 消失）。
开发库 `storage/chroma` 完好（count=50），只有测试专用目录损坏。

**孤儿向量的成因**：`prepare_e2e_data.py` 每轮都用**新 UUID** 建资料，
而清理只按「数据库里 existing 的那几份」删 —— 上一轮那批资料的向量再无人认领。
累积到 85 条之后，「这一轮到底干净不干净」无法判断，排查时看到的数据也不可信。

**修法**：

- `ChromaVectorStore.clear()`：清空集合**内容行**、不删集合本身。
  重建集合会让已持有旧句柄的后端进程失效（实测表现为检索全 500），
  所以 `prepare` 必须**在后端启动之前**跑，`test.cmd` 的顺序即由此而来。
- `prepare_e2e_data.py`：
  1. 打开向量库失败（含 HNSW 损坏）时**自动**删除测试向量目录并重建 ——
     派生的东西坏了就重建，不该需要人肉找损坏文件；
  2. 每次彻底 `clear()`，不再按已知 material_id 逐个删；
  3. 结束时自检「向量条数 == 分块数」，不一致就非零退出并说明原因。

**验证**（同一次调用内完成，后端作为该次调用的后台进程、结束即回收）：

```
测试向量库不可用（VectorStoreError），删除 storage/chroma-test 后重建
已清空测试向量库 17 条（避免孤儿向量累积）
已摄取「高等数学核心考点讲义」：15 块 →「阶段A验收笔记」：2 块
完成：ready 资料 2 份，分块 17 个，向量库 17 条      ← 自检通过
检索自检：命中 2 条，vector_candidates=17
npx playwright test --output=...  →  28 passed (1.4m)，退出码 0
后端已停止，8001 已释放
```

**方法论教训**：两次差点归错因（先怪 LLM、再怪孤儿向量）。
真正的跳跃是**直接去问那个可疑组件**（这里就是向量库本身），
而不是从上层症状反复推测。排查记录里「怀疑 → 否证」的过程比结论更有价值。

---

### D-41 工具链的四个假象（BOM / 失败详情 / 行尾 / 并发跑测试）

这一轮有四处「看起来像产品坏了」其实都是工具与环境造成的假象。记下来是因为它们每一个都让我先往错方向找了很久。

**1. `.ps1` 丢 UTF-8 BOM → 报「字符串缺少终止符」**
用编辑器改写 `scripts\run-e2e.ps1` 后，PowerShell 5.1 按 GBK 解码含中文的脚本，
解析器直接报 `The string is missing the terminator`、`Missing closing '}'`。
报错位置全在中文注释后面，看起来像语法写错了，实际上是编码。
**判据**：`[Parser]::ParseFile()` 报的结构性错误 + 文件头三个字节不是 `EF BB BF`。

**2. 只看控制台尾部输出判断失败 → 断言猜歪**
`npx playwright test` 的 list 报告在长输出里会被截断，我据此推断失败断言，
连续两轮都推断错（真正的失败断言根本不是我以为的那条）。
**修法**：`run-e2e.ps1` 同时产出 `--reporter=list,json` + `PLAYWRIGHT_JSON_OUTPUT_NAME`，
失败断言变成可检索的事实。JSON reporter 默认写 stdout，必须显式给文件名。

**3. 混合行尾让「按行锚定」的替换静默失效**
`state-matrix.spec.ts` 同时存在 LF 与 CRLF 行。我按 `\n` 拼接做字符串替换，
结果只成功了一处，其余静默不动 —— 差点以为改好了。
**修法**：用容忍 `\r?\n` 的正则，并在替换后打印验证。

**4. 并发跑 pytest 与 e2e → 测试库被同时写入**
我为了省时间让 `pytest` 与 `run-e2e.ps1` 并行跑。两者都写测试库，
于是 prepare 一边摄取资料、另一边被清空，最后统计出「ready 资料 0 份」，
prepare 自检直接判失败。**结论：测试库相关的验证必须串行。**

---

### D-42 资料页三处真实缺陷（空态 / 错误态 / URL 只读不写）

全部由 e2e 实测暴露，不是「测试写歪了」。

**1. 加载中就渲染「还没有资料」**
空态条件原本只写 `!materials.length`。加载中、加载失败时它同样成立，
于是用户看到一句**假信息**（库里明明有资料，只是还没读回来）。
改为 `list.state.value === 'success' && !materials.length`。
e2e 断言（十态矩阵 materials/loading：加载期间 `materials-empty` 数量必须为 0）抓到它。

**2. 后端不可达时错误态根本不渲染**
原来写 `v-if="list.errorCode.value"`。`ApiError` 只在后端返回错误信封时才有 `code`；
连接被拒这类网络失败走另一分支、`errorCode` 是 null，于是页面既不报错、
也不给重试入口，只剩一个空列表。改为按 `list.state.value === 'error'` 判定。

**3. URL 只读不写：`useRoute` 有、`useRouter` 没有**
页面 `onMounted` 会用 `route.query.material_id` 恢复选择（供问答页引用反跳使用），
但写入端此前**根本不存在** —— 只 import 了 `useRoute`。于是这个 query 永远是空的：
选中资料后刷新就丢、深链接分享出去打开是空列表、浏览器前进后退恢复不了。
e2e 实测：点击资料后 `material_id` 始终为 null。

**顺带查清一个「疑似缺陷」其实是对的**：`GET /api/chat/sessions` 在库里有会话时
仍返回 0 条 —— 这是设计如此（只返回**已经有消息**的会话，避免「点一下新建」
留下的空壳污染历史）。我自己用 API 建的、没有消息的会话不返回是正确行为。

---

### D-43 知识点详情零防御导致整页白屏

模板零防御地访问 `Object.keys(detail.node.required_question_types)`、
`detail.questions.length`、`detail.node.gap_items` 等。响应里只要少任意一个集合字段，
渲染就抛 `Cannot convert undefined or null to object`。

**关键**：这是**未捕获异常**，整块详情白屏 —— 而不是「某个元素没渲染」。
e2e 的失败信息一开始只说「`knowledge-detail` 不可见」，是 fixtures 的 pageerror
检查同时报了异常文本，才把方向从「元素可见性」扭到「页面抛异常」。

**修法**：新增 `normalizeDetail()` 把集合字段兜底成 `[] / {}`，模板断言处加 `?? []`。
多字段缺失本该是一处可降级的局部问题，不该上升成整页不可用。

同时补全了 e2e mock 的契约字段（`ordinal / gap_items / required_question_types /
excluded_question_types / required_skill_tags / materials_ready / has_real_variant` 等）——
mock 缺字段会让测试在一个不存在的世界里验证。

---

### D-44 embedding 联网探测：首字延迟 20~180 秒的真凶

**症状**：e2e「发出第一条问题后会话必须出现在历史里」稳定 180 秒超时；
后端所有接口都正常，数据库完全正常，模型就在本地。

**排查路径**（这一步值得记）：怀疑过 SSE、Vite 代理、请求头、`_wait_disconnected`
误判、会话列表过滤。逐层否证的结论是：
- 浏览器内直接读流：正常（22s 内 meta→delta×131→citations→done）
- 经 Vite 代理读流：正常（3.3s）
- 后端日志里出现 `WinError 10060 ... huggingface.co`

**真因**：`SentenceTransformer(model, cache_folder=...)` 在没有 `local_files_only`
时仍会向 huggingface.co 发 HEAD（Hub 检查版本）。本机离线时不是立刻失败，
而是**卡到 TCP 超时**，单次数十秒，叠加检索路径上的多次调用把一次问答拖到分钟级。

**修法**：加 `local_files_only=True`。修复后后端日志里 huggingface 探测 **0 次**、
流 21.7s 正常结束，那条 e2e 通过。

**教训**：这次差点又归错因（先怪 SSE、再怪代理）。真正的跳跃是
**去看后端的日志**，而不是从上层症状反复推测 —— 与 D-40 是同一条方法论。

---

### D-45 前进后退与窄窗口覆盖（补齐第 17 篇 §5 的缺口）

新增两个 spec：

- `frontend/e2e/history.spec.ts`：资料页选中写入 URL、切换资料后退/前进恢复、
  刷新深链接恢复、四页互跳后按访问顺序回退、问答页后退再前进列表仍在。
- `frontend/e2e/viewport.spec.ts`：375×667 与 768×1024 下四页都不横向溢出
  （直接量 `scrollWidth > clientWidth`，不只看元素可见），
  并验证窄屏下输入框可填、文件选择与主按钮可交互。

**过程中修掉两处「自己的用例在说假话」**：
1. 用例里写了 `test.skip(count === 0, ...)`，但 was 没等列表渲染就 `count()`，
   库里有 2 份资料时也会走进 skip —— **假通过**。改成先等 `.material-item`
   或空态出现，再决定有没有数据。
2. 用例断言 `.page` 覆盖问答页，但问答页根节点是 `.chat-workspace`
   （它没有 `.page`）；另外我一度引用了**并不存在**的 `study-page` /
   `knowledge-page` 两个 testid。断言必须按各页真实标记写。

**历史栈的两个真实修正**：
- 用户点击资料用 `push`（真实导航，后退能回到上一份）。
- 页面自动代入的选中（进入页面时选第一份、深链接恢复）用 `replace`：
  实测 `onMounted → loadList()` 自动选中第一份时若用 push，
  一次访问会在同一页留下两条历史（`history.length` 从 3 跳到 5），
  用户按后退先退到「同一页的无参状态」，看起来就是后退失灵。

---

### D-46 向量维度不一致：让「资料索引永久失败」的真正原因（2026-09-21）

这一条是**排查代价最大**的一次，值得逐层记下来，因为它演示了「症状会骗人」。

#### 症状

容器化部署起来之后，读链路全部正常（页面、`/api/health`、`nginx` 反代、深链接回落），
但**写链路全错**：

- 上传资料 → 任务 `attempts` 打满 → `status=failed`
- 向量库 `count = 0`
- 检索返回 `hits=[]` / `degraded=true`

#### 被症状带偏的三次误判

| 误判 | 当时的"证据" | 为什么错 |
|---|---|---|
| 模型文件缺失 | 容器里 `storage/models` 是空的 | 补进模型后仍然失败 |
| 向量库损坏 | 宿主机 `InternalError`，删库重建也没用 | 删库只解决了另一个独立问题 |
| 外键冲突 | 复现出 `ForeignKeyViolation: fk_message_citations_chunk_id_document_chunks` | 这条是真的缺陷，但它只是**下游**：删块失败 → 走不到写向量那一步 |

真正有效的动作只有一次：**在进程内按 worker 的顺序逐步复现**
（`plan_material` → `parse_material` → `build_index` → `activate_version`），
第 3 步立刻抛了出来：

```
chromadb.errors.InvalidArgumentError:
Collection expecting embedding with dimension of 384, got 512
```

#### 根因

- 本地缓存的 `models--BAAI--bge-small-zh-v1.5` 输出 **512** 维：
  `config.json` 里 `hidden_size = 512`、`num_hidden_layers = 4`，
  `1_Pooling/config.json` 里 `word_embedding_dimension = 512`（CLS pooling）。
- 而向量库集合是历史用**另一份 384 维模型**建的，于是每一次 upsert 都被拒绝。

**⚠️ 本条曾经写错过，2026-09-21 核实后更正**：我一度判断这份 512 维/4 层是
「旧版 bge-small-zh 的替身模型」「不是 v1.5」。**这个判断是错的。**
官方 README 的规格表（该表每行**只有一个**维度列）：

    | BAAI/bge-small-zh-v1.5 | 512 | 57.82 | ...
    | BAAI/bge-small-zh      | 512 | 58.27 | ...
    | BAAI/bge-small-en-v1.5 | 384 | 512 | ...   ← 384 是 **en（英文）**版
    | bge-small-en           | 384 | 512 | ...

**中文版 `bge-small-zh-v1.5` 的官方输出维度就是 512**，本地这份与官方规格完全吻合
（我把英文版的 384 串到了中文版那一行，才得出"名字与实体不符"的错误结论）。
三处独立来源也都是这份配置：本地缓存、`hf-mirror.com`、ModelScope，
官方 [config.json](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/534b6bfaaf500e70bcb9f3771cebc940c23b219d/config.json)
及下游副本（Xenova、Qdrant）一致。

**所以真正的不一致在向量库那一侧**：384 维的集合是历史遗留（来自某个英文版或早先
配置，已无从考证）。修法就是已采取的那条 —— 清空向量目录、按当前中文模型
统一为 **512** 维重建索引。**不需要替换模型。**

#### 一个反直觉的机制（差点又踩一次）

**Chroma 的集合维度在"第一次写入"时永久固化**，删掉向量也不会改变它。
我用 3 维向量做探针验证 `embedding_dimension()`，集合维度就被钉成了 3，
之后所有 512 维写入全部失败（`expecting embedding with dimension of 3`）。
结论：**不要拿一个假维度的向量去探测真实向量库**；只能清空整个向量目录重建。

#### 修复（三处，都是产品代码）

1. `VectorStoreChroma.embedding_dimension()`：读集合真实维度 —— 先看 `hnsw:dim` 元数据
   （不是所有版本都写这个键），拿不到就读**一条真实向量**的长度，空集合返回 None。
2. `upsert` 写入前校验维度：不一致时抛
   `VectorStoreError("向量库集合维度是 384，本次要写入 512 维 —— 说明
   MODEL_CACHE_DIR 里的模型与建库时用的不是同一个…请统一后重建索引")`。
   把底层那句只讲结果、不讲原因的 `InvalidArgumentError` 换成能直接行动的说明。
3. `build_retrieval_stack` 装配时比一次「模型维度 vs 集合维度」，
   并复用既有的降级路径：不一致 → 启动日志明确 + `/api/health`
   报 `retrieval: unavailable` 并带原因，而不是等到第一次检索才炸。

#### 附带修掉的两个真实缺陷

- **向量一致性检查有假阳性**（`scripts/check_vector_orphans.py`）：原来只查
  「向量多于块」的孤儿向量，**从不查向量缺失**，而且命中「没有孤儿」就提前
  `return 0`。于是向量库整个为空、库里还有 50 个激活块时，它照样打印
  「一致性正常」——把最严重的不一致报成了健康。现在补缺失检查，检测到即返回 1。
- **重建索引对被问答引用过的资料永久失败**（`backend/services/ingestion_service.py`）：
  唯一约束是 `(material_id, index_version, ordinal)`，而重建算出的版本号与已有版本
  **完全相同**（内容哈希 + 模型名没变），所以"先删同版本旧块再插"这条路径必然撞车；
  更糟的是删块会撞上 `message_citations` 的外键 —— 只要资料被问答引用过就删不掉。
  实测任务在 `database_unavailable` / `integrity` 之间反复失败。
  修法：**版本已存在且块数一致时直接复用现有块**（保住块 id，聊天引用继续有效，
  也彻底绕开外键）；块数不一致时才清理，并先删引用再删块。

#### 结果（实测）

```
向量库：collection=kaoyan_chunks count=35 dim=512
任务：   reindex | succeeded | att=1  ×2
检索：   「洛必达法则」→ 命中=3 degraded=False vector=20
         「阶段A验收」→ 命中=3 degraded=False vector=20 keyword=3
测试侧： chroma-test count=17 dim=512（prepare_e2e_data 重建成功）
```

#### 仍未解决 / 需要用户决定

- dev 库的 `gaoshu-lecture-01` 源文件已不在 `storage/uploads`（内容相同的文件在
  另一个 uuid 目录里），任务如实报 `material_file_not_found`。
  它是用户资料，**我没有擅自造文件或删记录**，只在此记录。
- ~~环境里的模型是 512 维的 bge-small-zh，而配置里写的名字是 v1.5（384 维）~~
  **已更正：不存在这个问题。** `bge-small-zh-v1.5` 的官方输出维度就是 512，
  环境里的模型与配置名一致；向量库已按 512 维重建、链路自洽。
  （原判断是读规格表时把英文版 `bge-small-en` 的 384 串到了中文版那一行。）

---

### D-47 删除被问答引用过的资料会 500（D-46 只修了一半，2026-09-22）

#### 谁发现的、怎么发现的

由一份外部缺陷报告指出（`WorkBuddy/…/缺陷报告-删除被引用资料会失败.md`），
发现方式是"手工清理一条冗余的 failed 资料"时撞到，随后在**会回滚的事务里**复现。
我独立验证了报告里的每一条，全部成立。

#### 症状

资料页点「删除」，只要该资料**曾被问答引用过**，就返回 500、资料删不掉。
**用户可见**，且影响已冻结的 `reference-project-verified-v1`。

#### 根因：三条约束凑在一起

| 约束 | 值 | 后果 |
|---|---|---|
| `message_citations.chunk_id → document_chunks.id` | **NO ACTION**（无 ON DELETE） | 分块被引用着就删不掉 |
| `document_chunks.material_id → materials.id` | **ON DELETE CASCADE** | 删资料会**自动**去删它的分块 |
| `message_citations.chunk_id` | **NOT NULL** | 也不能置空 |

于是 `DELETE FROM materials` 的实际路径是：

    删 materials
      └─ CASCADE 删 document_chunks        ← 撞在这里
           ✗ message_citations 还引用着它 → ForeignKeyViolation → 整笔回滚

**三条约束单独看都合理，合起来就成了「被引用过的资料永远删不掉」。**

#### 为什么 72 条 e2e 一条都没抓到

`frontend/e2e/materials.spec.ts` 的删除用例删的是**刚上传、从未被问答引用过**的资料，
根本不经过那条外键。**「删除被引用过的资料」这条路径此前没有任何测试覆盖。**

这是本条的真正教训：**测试覆盖面不是看数量，而是看"每条真实路径有没有被走一遍"。**
72 条听起来不少，但一条关键路径可以完全不在里面。

#### 与 D-46 是同一个外键，当时只修了一半

`410fa6e`（D-46）的提交信息里已经写明：「`parse_material` 的『先删同版本旧块』
会撞上聊天引用外键。只要资料被问答引用过，`reindex` 就永远失败。」
那次修的是**重建索引**这条路（改成版本相同时复用块、保住块 id），
**删除资料这条路漏了** —— 同一个外键、同一个根因，只补了一半。

**「修了一个触发点就收工」是本条最该记住的错误模式。**

#### 修法（方案 A）与语义取舍

在 `material_service.delete_material` 里加**第零步**：删记录之前，先清掉
指向这份资料分块的 `message_citations`。

为什么选 A 而不是另外两条（这是产品决策，不是纯技术选择）：

| 方案 | 为什么没选 |
|---|---|
| B. `chunk_id` 改成 `ON DELETE SET NULL` | 引用记录还在但没有指向 → 卡片显示不出内容；而且会留下"指向不存在来源"的历史引用，与产品「引用必须可核验」直接冲突 |
| C. 软删除资料 | 历史引用完好、可回溯；但"删掉的资料"仍占库与向量空间，且所有查询都要加过滤条件，代价扩散到整个代码库 |

选 A 的理由：引用指向的来源已被用户**主动删除**，留着它也没有可核验的对象。
代价是历史回答正文里的 `[C1]` 标记会成为**悬空标记**（有标记、没卡片）——
这恰好如实表现了「来源已删除」这个事实。

**保留的东西有明确边界**：会话与消息本身**不动**。用户的历史回答不该因为
删了一份资料而消失。

#### 测试：4 条，每条都显式造出 `message_citations`

| 用例 | 锁住的契约 |
|---|---|
| 被引用的资料能删掉（204 而非 500） | **核心回归** |
| 引用被一并清掉，但会话与消息保留 | 方案 A 的语义边界 |
| 未引用的资料照旧能删 | 修复没弄坏常见路径 |
| **删一份资料不能误伤别的资料的引用** | 最容易写错的地方：漏了 where 条件就会清空整张引用表，表面"删除成功"、实际毁掉所有历史引用 |

最后一条尤其重要——它是"修复引入新缺陷"的典型形态，必须专门锁住。

#### 验证

```text
python -m pytest tests/materials/test_cited_material_delete.py -v   # 4 passed
python -m pytest -q                                                # 退出码 0（412 条，原 408 + 新增 4）
```

#### 顺带记一条方法论

这份报告 §8 记录了它是**怎么手工绕过**这个缺陷把冗余资料清掉的：
先删 `message_citations`、再删 `materials`（CASCADE 带走分块与任务），
残留检查 `orphan_chunks=0 / orphan_jobs=0 / dangling_citations=0`。
**那三行手工操作，就是产品代码里缺的"第零步"。** ——
遇到"某个操作手工能做、代码做不到"时，值得立刻停下来问：代码里少了哪一步？

#### e2e 覆盖补齐（2026-09-22 当天追加）

原报告指出「72 条 e2e 没抓到」，我随后补了一条 e2e：
`materials.spec.ts` → 「删除被问答引用过的资料也必须成功（此前会 500）」。

**补这条用例时我自己又踩了一个同类坑，值得记下来**：

第一版写的跳过判据是「发送按钮是否禁用」。但**空输入框时发送按钮本来就该禁用**
（`canSend` 要求 `question.trim()` 非空），所以这个判据恒为真 ——
用例每一次都走 `test.skip`，**看起来在测，其实从没测到那条路径**。

这与被测缺陷是**完全相同的毛病**：形式上有测试，实质上没覆盖。
更讽刺的是它出现在"为了修一个覆盖漏洞"而写的用例里。

发现方式：跑全量时看到 `72 passed + 1 skipped`，去查跳过原因，
但 Playwright 的动态 `test.skip` 没留下原因 —— 只能写临时诊断用例把现场条件逐条打出来。
诊断显示 `填问题后发送按钮 disabled = false`、`引用数 = 1`，即条件全满足、
资料完全可用，于是定位到判据本身写错。

修正后的判据：**先填入真实问题**，再 `expect.poll` 断言按钮可用；
不可用才跳过，并且跳过原因写在 `test.skip(true, ...)` 里（不再是无原因的静默跳过）。

修正前后：

    修正前：72 passed + 1 skipped   ← 新用例被跳过，等于没覆盖
修正后：73 passed + 0 skipped   ← 真的走完「上传 → 提问 → 拿到引用 → 删除」

## D-48 · 标签后前端缺陷与验收状态收口（2026-09-24）

外部测试报告中的设置页只读、页面标题、正文接口测试等逐项核对后，
另用浏览器故障注入确认两条遗漏的功能缺陷：

- **删除失败被当作成功。** 资料页的 `detail.submit()` 失败时返回 `null`，
  原代码却无条件进入 `.then()`，关闭阅读器并清除选择。现仅在删除确实成功
  后关闭；失败保留资料与阅读器、显示错误。新增模拟 503 的 E2E。
- **问答资料超过 50 份会误判模式不可用。** 原代码只统计列表第一页的
  `items`；现分别请求 `status=ready` 且 `source_type=user/builtin`
  的服务端 `total`。新增第 51 份才是内置资料的 E2E。
- 设置页区分 `database_unavailable` 与后端网络不可达，并测试刷新恢复。
  Web 端仍不允许写入模型密钥：项目无登录保护，用户决定把页面内配置留到桌面版。
- 页面保留无可见大标题的设计，同时提供视觉隐藏的一级标题；浏览器标题随路由
  更新，问答侧栏“对话”改为二级标题。上传文件控件补可访问名且移出 Tab 顺序。
- 搜索列表数明确写成“匹配 X 份”；资料正文接口补成功与 404 的直接测试；
  学习页去掉同一模块的动态/静态混用导入，构建不再报分块警告。

**验证边界：** `npm run typecheck` 与 `npm run build` 退出码 0；
`python -m pytest tests/materials/test_material_content.py -q` 为 2 passed；
按 `scripts/run-e2e.ps1` 先准备隔离库、再启动后端执行，结果 **77 passed，0 failed，0 skipped**。
曾直接在新增 pytest 后运行 E2E，因 pytest 夹具清空测试资料而出现前置数据缺失；
按项目规定顺序重跑后全部通过。未在本轮重跑全量 pytest 或 Docker。

## D-49 · 答案详解可收起、右栏阅读与跳过（2026-09-24）

今日学习的答案详解原来一旦读取就始终显示，第二次点击按钮直接返回；
专注与整卷模式现共用逐题展开状态。答案正文首次按需读取，再次展开使用本地缓存，
收起不删除已读取的答案；按钮文字与 `aria-expanded` 同步。

两种模式的答案按钮和正文都放在题目右侧独立区域，题目与自评保留左侧；
在容器宽度不足时改为上下排列，避免窄屏横向溢出。
原“暂不记录”改为“跳过”：保留后端 `skip` 不写掌握度的语义，
专注模式把本地焦点移动到下一道未完成题，全卷模式不改变题目顺序。

验证：前端 typecheck/build 通过；导航与窄窗口相关用例 `18 passed`，
覆盖桌面右栏、窄屏上下排列、答案开合和跳过不记录掌握度。
尝试全量 E2E 时，一条原有问答会话用例等待上游回答超出 180 秒；
单独复跑该用例 `1 passed`。因此本轮不宣称全量 78 条全部通过。

## D-50 · 根据问答评测收紧回答范围与文件细节检索（2026-09-26）

8 条 RAGAS 基准中，可回答问题的 Context Precision/Recall 均为 1.0，
Faithfulness 均值为 0.9391。详细等比级数回答用了 19.4 秒，并扩展了用户没有询问的
其它判别法；用户资料回答还添加了资料未进一步说明哪些内容的否定判断。
这批样例支持继续约束生成内容，而不是一律扩大检索量或缩减输出额度。

- 两种模式共用的回答规则现要求围绕本次对象与子问题展开，避免复述相邻主题和重复总结。
  明确区分资料原文、直接推导和说明例子；推导保留条件，自拟例子不能冒充资料例题。
  只有缺失信息影响当前答案时才说明限制，不凭未提及的内容断言资料缺少某项信息。
- 文件概述原来会锁定文件，但普通细节检索只过滤资料模式。细节问答现在也会按
  明确提到的资料名或文件名过滤 material_ids，并同时保留 source_types 隔离。
  “这份文件”等指代可从最近用户消息恢复资料名；文件不存在或名称重复时先说明范围。
- 普通知识问题不会仅因知识点恰好也是文件标题而锁定文件；书名号中的作品名称也不会
  一律被误判成不存在的文件。文件扩展名紧接中文时仍可识别。

验证：使用一次性 PostgreSQL schema 运行问答流程、会话、流式、资料范围、意图、
上下文预算和归因测试，最终为 **130 passed**。新增真实检索样例在两种模式下都验证
相互矛盾的同类资料只会选取被点名文件的证据。临时 schema 已删除，共享测试资料 ID
在运行前后保持一致。本轮使用假模型验证编排逻辑，没有重新调用真实模型或覆盖历史
RAGAS 报告；以上历史分数不能当作本轮修改后的质量或性能测量结果。

## D-51 · 四项评测、资料与通用知识分离及输出完整性（2026-09-26）

- 资料不足时允许给出明确标注的“通用知识参考”；资料依据与常识补充分段，
  补充段不能挂资料引用。纯通用回答不据无关检索结果推荐知识点。
- 文件概述补齐“概述/概括/总结”意图识别；文件不存在、重名或模式不匹配时
  仍解释范围，不能用常识编造文件正文。回答长度依本次问题调整，详细问题逐项覆盖。
- 模型 finish_reason=length 不再当作完整答案成功保存。同步回答允许一次扩大
  预算重试；已输出内容的流式回答明确提示未完成，不自动重复拼接。
- RAGAS 评估包含 Faithfulness、Answer Relevancy、Context Precision、Context Recall。
  纯通用回答的三项资料指标记为不适用；混合回答只评估资料依据段的忠实度。
  保存相关性裁判生成问题和 noncommittal 诊断，不修改原始评分公式或降低阈值。
- 通用答案的来源忠实度不适用不等于事实正确；自拟数字例子仍需公式与计算一致。

已完成两轮真实模型隔离评测，每轮 8 条、调用错误 0。第二轮四项均值分别为
Faithfulness 0.9646、Answer Relevancy 0.6341、Context Precision 0.9722、Context Recall 1.0；
资料指标样本数为 6，相关性样本数为 8。该结果暴露相关性不足与一条通用数字例子的
错误，不能宣称全项达标。后续已补提示词与诊断，最新结果以新报告为准，不能沿用旧分数。

最新代码的问答流程、会话历史、流式输出与六组单元测试在一次性 PostgreSQL schema
中全部通过，共 149 条；schema 已清理，共享资料 ID 前后相同。为避免改动共享库，
本轮使用模型建表并跳过根夹具的迁移调用，因此不是数据库迁移回归。

最后一轮真实评测保存为 `eval/reports/chat_ragas_four_metrics_20260926_213952.json`：
8 条、调用错误 0、指标错误 0、行为检查 8/8。Context Precision/Recall 均为 1.0000
（6 条资料问题），Faithfulness 为 0.9206（最低 0.75），Answer Relevancy 为 0.7896
（8 条，资料问题均值 0.8436，通用问题均值 0.6277）。相关性裁判对部分中文回答
反推了英文问题，诊断已保存；不据此擅自改分或认定所有低分都是误判。
总响应耗时均值 11.14 秒、最大 33.39 秒；检索耗时均值 30.5 毫秒。
通用知识的三个资料指标不适用，不代表事实核验通过。检索证据由搜索接口重建，
不完全等于内部最终 prompt；基准小且同模型自评，结果不能推广为所有用户问题准确。

本机原 PostgreSQL 集群已恢复，最新版开发前后端已启动；健康检查为
database=connected、retrieval=ready、worker=running，实际读取模型为 deepseek-flash。
Docker 的损坏运行 socket 目录只作可恢复备份，未重置数据库卷。

## D-52 · 大量知识节点导航与资料分页（2026-09-26）

- 今日学习调整范围改为可展开的层级树，父节点用于导航，叶节点用于选择；
  支持名称/编码搜索、保留祖先路径、无匹配空态、加载失败重试及限定高度滚动。
- 知识树默认只展开根层，支持按学科筛选和路径搜索；每个分支分批显示 20 项，
  可继续展开，避免一次渲染大量节点。详情保留路径与系统内置讲解入口。
- 资料页始终显示当前页/总页数和条目范围，支持页码、前后页及标题搜索；
  搜索重置页码，翻页关闭旧阅读器，单页与空列表也保留明确页数状态。
- 保留浅色简约设计、主要内容白底，收敛装饰与重复边框。

前端 typecheck/build 通过；三份独立 mock E2E 共 6 条通过，覆盖 120 个知识节点、
41 份资料的六页切换、搜索重置、树开合、Markdown 阅读以及 375px 不横向溢出。
这些用例不重置共享数据库，不代表全量真实后端 E2E 已重跑。

## D-53 · 本机模型设置、统一错误契约与前端单测/拆包（2026-09-26）

用户本轮明确要求设置页也可配置，替代 D-48 的“留到桌面版”决定，但不把无登录
Web 服务开放成密钥管理后台。

- `SettingsPage.vue` 增加接口地址、模型 ID、密码型密钥输入、输出上限与超时表单。
  新增 GET/PUT `/api/settings/model`，前端类型来自 OpenAPI。留空密钥保留现值，
  移除须明确勾选；成功后清空输入，失败保留表单且不误报成功。保存后下一次问答
  直接读取新配置，在途 Provider 不变；保存不代表上游连通性或余额已验证。
- 配置只允许 dev + loopback 客户端 + 本机 Host；拒绝跨站 Origin、转发头与 prod/test。
  PUT 另需进程随机 `X-Settings-Token`；GET/PUT 均 no-store，不回显密钥。
  Windows 的本机覆盖文件由当前用户 DPAPI 加密，其他系统为 0600 权限文件，
  不声称跨平台都加密。原 `.env` 不修改；覆盖文件与临时文件被 Git 忽略。
  配置损坏时保留设置页可用，但停用旧密钥并提示重新保存；写盘失败不切换运行配置。
- 错误处理覆盖 AppError、RequestValidationError、HTTPException 及未捕获异常。
  HTTP 状态与 405 Allow 等协议头保留，响应共用 error 信封。校验 details 只输出
  安全字段和规则提示，绝不直接输出 input、body、底层 msg 或异常 ctx；500 不回堆栈。
  OpenAPI 的 422 同步改成 ErrorResponse，而不是仍宣称默认 HTTPValidationError。
- 新增 Vitest 与 4 份单元测试，覆盖 client、useAsyncTask、runtimeErrors、labels。
  同时修正异步任务旧响应覆盖新结果、reset 后回写及重复提交风险；取消不当业务错误处理。
- 页面路由懒加载；`MarkdownContent.vue` 保留 marked + DOMPurify 安全净化，
  KaTeX JS/CSS 只在存在公式时动态加载，检查文本版本与卸载状态防止异步渲染串内容。
  代码块不参与公式解析、trust=false、禁止 img/iframe/style；加载失败保留原文提示刷新。
- h1 与上传可访问名本已在 D-48 修复，本轮保留，不重复删除重建。

验证：29 条新增后端专项测试通过；问答、健康、资料读取与专项测试组成的
**183 条隔离 schema 回归全部通过**（schema 清理，共享资料 ID 不变，未测试迁移）；
前端 **21 条单元测试、9 条独立 mock E2E 全通过**，含保存/失败/生产只读、密钥
不进浏览器存储、分页公式显示、树开合与 375px 布局。typecheck/build 通过，
OpenAPI 26 个路径的四项漂移校验通过。未宣称重跑全量 pytest 或全量真实 E2E。

最终生产构建另起本机 5175 preview，对上述 9 条 mock E2E 再跑一轮，9/9 通过，
实际验证懒加载页面、资料公式的 JS/CSS chunk 可用；临时 preview 已停止。

构建主入口 JS 从约 555.22 kB/gzip 181.53 kB 降到约 114.19 kB/gzip 45.24 kB；
公式库拆到约 264.12 kB 的按需 chunk。以上是主入口加载量减少，不是全部资源总体积
减少相同比例；页面内容和公式仍会按需下载。未改变 RAGAS 公式或复用旧分数当成本轮新评分。

### D-54 输出上限自动恢复及真实前端复测（2026-09-27）

- 用户报告普通概述直接收到输出上限提示。日志证实模型在已有 1144 字正文后
  finish_reason=length；旧流式逻辑仅在无正文时重试，且失败正文未保存。
- 输出上限现在允许一次扩大预算的完整重生成，delta.replace 替换半截正文；
  保留来源前缀并保持 seq 递增，普通部分输出后的网络故障仍不重放。
- 失败正文、耗时与错误代码落库，但状态保持 failed，不生成可用引用。
- 压力测试又发现固定 60 秒总生成时限不适合详细回答及扩大预算的恢复轮次；
  两者使用有界的两倍时限（最多 180 秒），网络静默超时仍遵守配置。
- 页面初始历史读取期间禁止切换范围、新建及发送，避免初始化覆盖刚选择的模式。
- 新增真实前端测试配置，使用两份获准测试讲义、当前模型和独立 schema，
  每条核对实际模式与刷新正文；明确区分真实调用、mock 回归和 RAGAS 评分。
  测试说明见 `docs/live-front-chat-check.md`，本轮最终结果见其对应 JSON 报告。

最终复验：两轮 **14 条真实前端问答全部通过**，含实际模式断言与刷新正文；
**187 条隔离后端回归、21 条前端单测、1 条 mock 流替换回归**通过，typecheck/build 通过。
真实整份内置讲义细讲两次约 2970/3254 字、16.1/15.6 秒；最终十四条无截断恢复，
此前独立真实调用另验证一次输出上限恢复。最长普通细讲约 46.7 秒，性能仍依赖上游。
未宣称全量测试或 RAGAS 新评分。用户开发 API 8000 健康检查及前端 5173 均为 200。

### D-55 · 整份资料概述与范围定位（2026-09-27）

- 实际上传《验收》已索引 20 个片段，包含 A–G；旧会话副本却只回答 A。
  根因不是片段缺失，而是旧回答错误范围和旧引用编号影响当前证据。
- 整份重读不传旧模型回答；文件指代仍由用户历史解析。普通细节问答保留上下文，
  清除旧回答引用编号；当前证据紧邻本次问题并列出章节清单。
- 补充口语概述意图；明确单阶段不强制全篇，覆盖完整与回答长短分开判断。
- 修复断连监视任务吞取消导致收尾等待；增加回归模拟该情形。
- 引用兼容层仅把当前证据中存在的 `[citation:N]` 转为 `[CN]`，未知编号移除并记录，
  代码示例不改写；核心引用验证仍只识别规范编号并检查活动索引。常识部分不生成资料引用。
- 今日学习范围树显示选中项所属路径、父节点蓝色已选计数，支持定位与移出；
  搜索不会丢失全树路径，移除最后一项时禁止生成空范围试卷。
- 验证与限制见 `docs/acceptance-chat-coverage-2026-09-27.md`；最后真实模型复验
  被安全审批阻止，未把该轮记为通过，需单独确认资料发送目的地后执行。

### D-56 · 用户授权后的多文件真实评测（2026-09-27）

- 用户明确同意验收副本和合成专用资料向当前DeepSeek端点发送；隔离环境真实上传
  8份资料，完成50条主测、6条跨文件复现、4条边界，共60次前端询问。
- 原文人工复核发现7条多文件任务未完成、1条无依据样本单位、1条错字标题澄清；
  51条未发现实质内容问题。多文件失败中另有常识条件省略，不能宣称内容全绿。
- 无SSE/浏览器错误、保存正文与终态一致、引用标签都有卡，不等于语义全部正确。
- 三批隔离进程、schema与临时索引已清理，共享资料未变化。
- 本轮未修复业务代码；评测资料、脚本、真实浏览器用例及详细报告已保存。
  见 `docs/multifile-depth-evaluation-2026-09-27.md`；含私人资料的原始JSON仅本地保留。

### D-57 · 多文件问答缺陷落实修复（2026-09-27）

- 修复全局最长标题丢失另一目标、不同文件误判同名、复数文件指代丢失。
- 对多文件概述/比较读取各目标活动正文，限制总量并拒绝悄悄忽略缺失文件。
- 文件错字仅建议候选并要求确认；明确未知目标不借其他文件代答。
- 加强样本单位、数学条件和各文件实际例子约束；兼容空格引用编号且继续验证来源。
- 跳过已确定文件范围的模型分类；增加分段耗时记录及官方 DeepSeek 推理强度参数兼容门控。
- 139条最新隔离问答回归、24条前端单测及typecheck通过；真实模型复验与限制见
  `docs/multifile-chat-fix-2026-09-27.md`，不宣称新的RAGAS评分或所有问题100%正确。

### D-58 · 安装包前全面审计（2026-09-27，仅检查）

- 隔离后端 548 条通过；前端类型检查、24 条单测及生产构建通过。
- 常规 E2E 为 88 通过、3 失败、1 跳过；原跳过用例单独重跑通过，未将整套标为全绿。
- 新增浏览器和接口边界探测复现 9 项运行/交互问题，另确认测试文件目录隔离风险。
- 本轮没有修改业务代码、没有外部真实模型调用、没有发布安装器；保留用户工作区与开发服务。
- 完整证据、修复优先级、桌面发布缺口与未验证项见
  `docs/desktop-preflight-audit-2026-09-27.md`。

### D-59 · 安装包前明确缺陷落实修复（2026-09-27）

- 修复会话读取乱序/错误边界、组合引用限额/失败草稿恢复和发送收尾竞争。
- DOCX 保留块顺序并升级解析器；二进制解析独立进程 30 秒超时，增加展开/文本/页数/chunk 限额。
- 加入跨站修改校验、dev Host 校验、数据库单实例锁、上传失败补偿、空白输入规范化。
- 测试目录采用独立默认与准备脚本保护；Docker 上下文排除凭据；配置指引指向设置页。
- 修正三项过期 E2E 与引用异步等待，补充永久异常回归。
- 最终后端 561 通过，完整 E2E 95 通过/无失败跳过，定向 4 通过；24 单测、类型/构建、契约/部署静态检查通过。
- 未发布安装器、未重跑外部语义评估、未重启用户开发后端；范围与剩余门禁见
  `docs/desktop-preflight-fixes-2026-09-27.md`。

### D-60 · 全量复核、检索超时隔离与内置复习资料（2026-09-27）

- 安装包预检后端/前端缺陷逐项修复；具体行为、风险边界和复测命令见
  `docs/desktop-preflight-fixes-2026-09-27.md` 的 D-60 增补。
- 修正检索超时测试的工作线程清理：请求包装任务超时后线程仍继续执行，测试现在等待真实 worker 结束与 semaphore 完成回调释放；失败时可区分正确的 `retrieval_busy` 保护与产品回归。
- 新增内置参考资料服务，固定扫描 `seed/materials/builtin/*.md`，不递归且验证真实路径在目录内；按原始哈希幂等导入/更新为 builtin 资料，变化时排入摄取任务。`scripts/seed.py` 同步两份原创讲义和一份历年来源索引。
- 增加数学二（微积分、线代）和 408 四科原创核心讲义，含概念、方法、原创例题与易错点；另建真题来源与年份边界索引。原卷全文未复制进公开仓库，尚不能声称逐年逐题考点映射已全部完成。
- 最终后端 **573 项通过**；全量 E2E **96 项通过**，上传取消 mock E2E 另 **1 项通过**；Vitest **25 项通过**，typecheck、build、OpenAPI 与部署静态检查通过。前端全量 E2E 与单独 mock 用例分开计数。
- 仍无桌面壳/安装器，未测清洁 Windows 安装、签名、升级/卸载、备份迁移；未新增真实模型或 RAGAS 语义评分。开发后端未重启。

### D-61 · 历年真题题号关联到知识树（2026-09-27）

- 从项目内 34 份年度索引解析数学二、408 的 2010—2026 题号、简短考点标签和来源链接；按多个分号标签将同一道题关联至多个知识点。
- 生成 249 个只读考点索引叶子和 14 个科目/分类节点，保存 1,470 条题号—考点关联（数学二 402 条、408 1,068 条；这是关联记录数，不是独立题目数）。
- 新增 `exam_question_references` 表和 `is_reference_only` 标记；原题干、答案没有复制到项目，引用节点不进掌握度、自评或今日练习。
- 知识树节点详情新增按年份分组的“历年真题”页签，展示题号、标签、可用来源链接与桌面年度目录；保留 2019 年 408 第 46 题的原始双重分类并提示第三方分类边界。
- 导入由 `python scripts/seed.py` 幂等完成；回归验证尚在执行，本节的功能描述不等于迁移、当前数据库导入或浏览器测试已经验收。

### D-62 · 历年真题作为今日任务与毕业证据（2026-09-28）

- 真题索引叶子现设为可考核节点，导入时建立 `KpState` 与来源自适应的 `KpMasteryPolicy`；每日默认推荐仍排除这些叶子，用户从知识树或组卷范围主动选取。
- 新增原卷引用型练习记录；普通 `Question` 与外部 `ExamQuestionReference` 必须且只能有一个来源，题干/答案不复制或伪造。
- 知识树可把单道原卷任务加入今日学习；专注/全卷模式显示年份、题号、标签、链接与桌面目录。自评“已掌握”的不同原卷进入与普通题共用的掌握状态机、毕业缺口、审计事件和练习历史。
- 自动门槛最多要求 3 道可用真题；来源不足时按实际数量下调，不假造原卷题型或变式配额。自定义策略不被重复同步覆盖；“跳过”不写自评，外部任务无答案接口。
- 新增数据库迁移、后端组卷/追加/自评、适配策略与节点历史；更新知识树到今日学习 E2E。
