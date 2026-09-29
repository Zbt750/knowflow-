# 参考项目构建状态

> 本文件是**构建记录**，不是最终教学文档。它只记录“实际做过什么、实际得到什么结果”。
> 当前阶段以第 1 节的状态表为准；下文按时间保留各轮实测记录，其中早期的“Docker 未安装”“阶段 G 尚未开始”等结论仅描述当时状态，并非当前结论。

## 1. 当前阶段

| 阶段 | 名称 | 状态 |
|---|---|---|
| 审计 | 环境 / Git / 文档 / 差异清单 | ✅ 完成 |
| A | 工程底座、数据库与可视化验收壳 | ✅ 完成（已实际运行验证） |
| B | 学习闭环后端与真实学习页面 | ✅ 完成（已实际运行验证） |
| C | 资料摄取、标题树、索引和检索 | ✅ 完成（已实际运行验证，含真实模型检索评估） |
| D | 可信问答、SSE 与题库追练 | ✅ 完成。核心契约有测试锁住。此后帧序加过独立 `citations` 帧、向量库坏过一次、**删除被引用资料会 500**（D-47，2026-09-22 由外部缺陷报告指出并修复），均已修复并复验 |
| E | 前端完整验收 | ✅ 完成：统一 API client / 28 个规格 testid / 错误码页面行为 / 十态状态矩阵 / 前进后退 / 窄窗口全部覆盖，**72 条用例实测全绿**（见第 22 节）。四页**统一状态已完全收敛**到 `useAsyncTask`（见 §25）|
| F | Docker Compose 本地部署 | ✅ 完成。容器内逐项实测通过：三容器 `Up (healthy)`、8080 可访问、nginx 反代、四路由回落 SPA、容器内 alembic 在 head、seed 幂等、**上传→可检索→检索命中（自然查询）→清理**、**SSE 189 个 delta 帧分 3 次到达**、**强杀容器后 lease 到期任务被恢复并跑完（4000 分块）**、`down`→`up -d` 后数据仍在。判据见 `docs/deploy-local-docker.md` §4 的 9 项（全部打勾）与 §26 |
| G | 全量测试、人工验收与冻结版本 | ✅ 完成：§4 五条必跑命令逐条执行（§27.1）、核心产品硬规则六组取证全过（§27.2）、真实 Chrome 对 Docker 部署验收四页零异常（§27.3）。**已打冻结标签 `reference-project-verified-v1`**。一条网络限制如实记录：`up --build` 的从零全量重建在打标签时受本机到 Docker Hub 的波动影响未能复跑（§27.4） |

**已达到 `reference-project-verified-v1`** —— 标签打在通过 §27 全部验证的提交上，
注释里写明验证范围与已知限制。阶段 A 通过不代表整个任务完成：
判据始终是逐阶段的**真实执行**，而不是文档里写了什么。

**标签后的前端迭代（2026-09-24）：** 删除失败反馈、问答资料计数分页边界、
设置页 503 提示、无障碍标题与浏览器标题等已修复；隔离测试库先按
`scripts/run-e2e.ps1` 准备两份可检索资料后，前端 **77 条 E2E 全通过**。
新增 `/api/materials/{id}/content` 两条直接测试通过，前端 typecheck/build 通过。
这是当前工作区的回归记录，**不是**重新打冻结标签或全量后端/Docker 复验。

**2026-09-26 本轮补充：** 设置页已支持受限本机 dev 访问的模型配置保存与热更新，
生产 Web 不开放密钥管理；Windows 配置使用当前用户 DPAPI。异常信封、字段级
校验提示、前端单测和页面/公式按需加载已完成。隔离后端回归 183 条、前端单测
21 条、独立 mock E2E 9 条通过，typecheck/build 与 OpenAPI 漂移检查通过。
这是标签后的专项回归，不是全量后端、真实 E2E、迁移或 Docker 新验收。详见 D-53。

**2026-09-27 D-60 补充：** 安装包审计问题已落实修复；最终当前代码回归为后端 573 项、
全量 Playwright 96 项、另有上传取消 mock E2E 1 项，前端单测 25 项、类型检查和生产构建通过。
数学二与 408 的原创讲义及真题来源索引已加入 `seed/materials/builtin/`，由 `scripts/seed.py`
幂等同步至数据库资料并异步建索引。完整原卷没有进入公开仓库；逐题知识点标注仍需逐份原卷核验。
以上是当前工作区回归，不是重新打冻结标签或已完成桌面安装包；没有运行新一轮真实模型/RAGAS 评测。

## 2. 审计结果（开工前的真实状态）

| 项目 | 审计结果 |
|---|---|
| 项目代码目录 `D:\考研跑通项目` | 开工时**完全为空**（0 文件 0 目录），属全新工程；无既有代码可保留，也无既有代码被删除或重置 |
| Git | 目录内无 `.git`；阶段 A 中新建仓库，当前分支 `master`，**尚无提交** |
| Python | `python` = 3.12.10（`py` = 3.14.0）；依赖已预装，见下表 |
| Node / npm | v24.18.0 / 11.16.0 |
| PostgreSQL | 已安装 PostgreSQL 18.4 + psql 18.4 |
| 系统 PostgreSQL 服务 `postgresql-x64-18` | **存在但处于 Stopped**，`Start-Service` 被系统策略拒绝（非文件沙箱问题，提权后仍失败），因此 5432 不可用 |
| Docker | **完全未安装**（`docker` 不在 PATH；`C:\Program Files\Docker`、Docker Desktop 均不存在）。阶段 F 需要先解决 |
| Playwright 浏览器 CDN | `cdn.playwright.dev` **不可达**（TLS 连接被中断），自带 chromium 无法下载 |
| 系统浏览器 | 已装 Google Chrome、Microsoft Edge |

已预装且本项目直接使用的 Python 包：fastapi 0.141.1、uvicorn 0.52.4、SQLAlchemy 2.0.52、alembic 1.19.2、psycopg 3.3.5、pydantic 2.13.5、pydantic-settings 2.15.0、pytest 9.1.1、pytest-asyncio 1.4.0、httpx 0.28.1、chromadb 1.5.9、python-docx 1.2.0、pypdfium2 5.13.0、rank-bm25 0.2.2、jieba 0.42.1。

## 3. 数据库环境（阶段 A 建立）

由于系统 PostgreSQL 服务无法启动（需要管理员权限且启动被拒），阶段 A 改为在项目内建立**独立的本地集群**，不使用管理员权限、可复现、不污染系统安装：

| 项 | 值 |
|---|---|
| 集群数据目录 | `D:\考研跑通项目\.pgdata`（已被 `.gitignore` 排除） |
| 端口 | `5433`（避开系统安装默认的 5432） |
| 监听 | `127.0.0.1` |
| 认证 | `trust`（仅本机回环；`.env.example` 中的密码是本地开发占位值，非真实密钥） |
| 时区 | `Asia/Shanghai`（与毕业跨天规则同一基准） |
| 角色 | `kaoyan` |
| 开发库 | `kaoyan` |
| 测试库 | `kaoyan_test` |

集群启动命令：

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\考研跑通项目\.pgdata' -l 'D:\考研跑通项目\.pgdata\server.log' -o "-p 5433 -c listen_addresses=127.0.0.1" start
```

> 注意：`pg_ctl start` 会占住控制台，自动化调用时会等到超时；集群本身已成功启动。用 `pg_isready -h 127.0.0.1 -p 5433` 确认状态。

## 4. 实际运行过的命令与结果（阶段 A）

| # | 命令 | 目录 | 结果 |
|---|---|---|---|
| 1 | `initdb -D .pgdata -U postgres -E UTF8 --locale=C -A trust` | 项目根 | ✅ Success |
| 2 | `pg_ctl ... start`（端口 5433） | 项目根 | ✅ server started（命令块因占住控制台超时，集群正常） |
| 3 | `psql -c "CREATE ROLE kaoyan LOGIN PASSWORD ..."` | — | ✅ CREATE ROLE |
| 4 | `psql -c "CREATE DATABASE kaoyan OWNER kaoyan"` | — | ✅ CREATE DATABASE |
| 5 | `psql -c "CREATE DATABASE kaoyan_test OWNER kaoyan"` | — | ✅ CREATE DATABASE |
| 6 | `python -c "from backend.config import get_settings; ..."` | 项目根 | ✅ `app_env= dev`，`active_db= ...5433/kaoyan` |
| 7 | `python -m alembic revision --autogenerate -m "create learning core tables"` | 项目根 | ✅ 生成 `migrations/versions/e265f44be662_create_learning_core_tables.py`，检测到 7 张表 + 7 个索引 |
| 8 | `python -m alembic downgrade base` | 项目根 | ✅ 清空（测试断言 downgrade base 后除 `alembic_version` 无残留表） |
| 9 | `python -m alembic upgrade head` | 项目根 | ✅ `Running upgrade -> e265f44be662` |
| 10 | `python -m alembic current` | 项目根 | ✅ `e265f44be662 (head)` |
| 11 | `python -m alembic check` | 项目根 | ✅ `No new upgrade operations detected.` |
| 12 | `python -m pytest -v` | 项目根 | ✅ **6 passed, 0 failed**（0.65s） |
| 13 | `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` | 项目根 | ✅ 启动成功（后台作业 pwsh-1） |
| 14 | `GET http://127.0.0.1:8000/api/health` | — | ✅ 200 `{"status":"ok","database":"connected"}` |
| 15 | `GET http://127.0.0.1:8000/openapi.json` | — | ✅ 已注册路径：`/api/health` |
| 16 | `npm install` | frontend | ✅ added 57 packages, 0 vulnerabilities |
| 17 | `npm run build`（`vue-tsc --build && vite build`） | frontend | ✅ 40 modules，`dist/` 生成，类型检查通过 |
| 18 | `npm run dev`（`vite --host 127.0.0.1`） | frontend | ✅ 5173 就绪（后台作业 pwsh-5） |
| 19 | `GET http://127.0.0.1:5173/study` | — | ✅ 200 |
| 20 | `GET http://127.0.0.1:5173/api/health`（Vite 代理） | — | ✅ 200，代理到后端成功 |
| 21 | `npm run test:e2e` | frontend | ✅ **2 passed**（健康成功分支 + 503 分支） |
| 22 | `pg_ctl ... -m fast stop` 后 `curl -i http://127.0.0.1:8000/api/health` | — | ❌ **首次实测：90 秒无任何响应（无状态码、无响应体）** → 缺陷 #4 |
| 23 | 修复后（数据库已停止）`curl -i http://127.0.0.1:8000/api/health` | — | ✅ 503 + `{"error":{"code":"database_unavailable","message":"database unavailable"}}`，耗时 **5.21s** |
| 24 | 修复后（数据库已停止）`curl -i http://127.0.0.1:5173/api/health`（经 Vite 代理） | — | ✅ 503 + 同一错误体，耗时 **5.03s** |
| 25 | 数据库恢复后 `curl -i http://127.0.0.1:8000/api/health` | — | ✅ 200 + `{"status":"ok","database":"connected"}`，耗时 **0.13s** |
| 26 | `python -m pytest -v`（含新增回归测试） | 项目根 | ✅ **9 passed, 0 failed**（5.98s） |

### 测试清单（阶段 A）

| 测试文件 | 用例 | 断言 | 结果 |
|---|---|---|---|
| `tests/api/test_health.py` | `test_health_returns_200_when_database_query_succeeds` | 200 且响应体严格等于 `{"status":"ok","database":"connected"}` | ✅ |
| `tests/api/test_health.py` | `test_health_returns_503_without_database_details_when_query_fails` | 503 + `{"error":{"code":"database_unavailable","message":"database unavailable"}}`，且响应文本**不含**驱动异常、`postgresql://`、密码 | ✅ |
| `tests/integration/test_migrations.py` | `test_alembic_upgrade_head_creates_learning_tables_from_empty_database` | 从空库 downgrade base 后无残留表；upgrade head 后 7 张学习表齐全、UUID/唯一约束/外键真实落库；旧稿表 `daily_plan_items`、`practice_sessions` 不存在 | ✅ |
| `tests/integration/test_migrations.py` | `test_alembic_check_reports_no_pending_model_changes` | ORM metadata 与迁移完全一致 | ✅ |
| `tests/integration/test_migrations.py` | `test_document_jobs_check_constraints_absent_in_batch_a` | `document_jobs` 不在 Batch A | ✅ |
| `tests/integration/test_migrations.py` | `test_study_date_column_is_string_ten_chars` | `daily_plans.study_date` 长度 10 | ✅ |
| `tests/unit/test_db_engine_timeouts.py` | `test_engine_passes_connect_timeout_to_driver` | 连接池 creator 闭包里确实带 `connect_timeout`（按实际存放位置断言） | ✅ |
| `tests/unit/test_db_engine_timeouts.py` | `test_engine_sets_pool_timeout` | `pool._timeout` 等于配置值，且不小于建连超时 | ✅ |
| `tests/unit/test_db_engine_timeouts.py` | `test_unreachable_database_raises_quickly_instead_of_hanging` | 连到必然拒绝的端口必须在超时上限 + 5 秒内失败，而不是永久挂起 | ✅ |
| `frontend/e2e/navigation.spec.ts` | 四个真实 Vue 路由可打开且系统状态真实反映后端连接 | 四个页面标题与占位文案真实渲染；系统状态为 `ready` 且含“后端可用” | ✅ |
| `frontend/e2e/navigation.spec.ts` | 健康检查 503 时显示明确错误与重试按钮 | 状态为 `error`，显示稳定错误码 `database_unavailable`；点“重新检查”并解除拦截后恢复 `ready` | ✅ |

### 阶段 A 中修复过的真实失败

1. **`alembic` 命令直接崩溃：`UnicodeDecodeError: 'gbk' codec can't decode byte 0xaa`**
   原因：Alembic 用**系统 locale 编码**读取 `alembic.ini`，而该文件最初含中文注释。
   修复：`alembic.ini` 改为纯 ASCII（实测非 ASCII 字节数 = 0），中文说明移到 `migrations/env.py`。

2. **前端开发服务器两次被 `EBUSY` 杀掉（exit code 1）**
   原因：Playwright 在加载 ESM 测试文件时，会在**测试文件所在目录**创建 `<文件名>.tmpdir/<文件名>.tmp`；Windows 上该临时文件处于被占用状态，Vite 监视到就抛 `EBUSY: resource busy or locked, watch ...`.
   现象证据：`...\frontend\.playwright.config.ts.4172.*.tmpdir\playwright.config.ts.tmp`、`...\frontend\e2e\.navigation.spec.ts.4172.*.tmpdir\navigation.spec.ts.tmp`。
   修复：`vite.config.ts` 的 `server.watch.ignored` 加入 `**/*.tmpdir/**`、`**/*tmpdir*/**`、`**/.playwright*/**`、`**/test-results/**`、`**/playwright-report/**`、`**/blob-report/**`。修复后重跑 e2e，dev server 保持存活（`pwsh-5` running）。

3. **Playwright 自带 chromium 无法安装**
   原因：`cdn.playwright.dev` 在本机不可达。
   修复：`playwright.config.ts` 改用 `channel: "chrome"`（系统已装 Chrome），`package.json` 的 `test:e2e` 去掉 `PLAYWRIGHT_BROWSERS_PATH` 环境变量。

4. **数据库中断时 `GET /api/health` 不返回 503，而是 90 秒无任何响应（最严重的一个）**
   现象：`pg_ctl stop` 后，`curl -i http://127.0.0.1:8000/api/health` 等待 90 秒后超时；既没有状态码也没有响应体。uvicorn 日志里**完全没有**收到该请求的记录（最后一条仍是中断前的 200），说明事件循环已被占住，请求根本没能进入路由。
   根因：SQLAlchemy 的 `create_engine` 未设置驱动级建连超时。PostgreSQL 停止后，psycopg 建立连接会长时间挂起；本项目是**单进程 uvicorn**，同步驱动在事件循环里阻塞后，连“返回 503”这一步都执行不到。
   修复：`backend/db.py` 中新增 `DB_CONNECT_TIMEOUT_SECONDS = 5` 与 `DB_POOL_TIMEOUT_SECONDS = 10`，并在 `create_db_engine()` 传入 `connect_args={"connect_timeout": ...}` 与 `pool_timeout=...`。
   验证（数据库确实处于停止状态）：
   - `curl -i http://127.0.0.1:8000/api/health` → `503` + `{"error":{"code":"database_unavailable","message":"database unavailable"}}`，耗时 5.21s
   - `curl -i http://127.0.0.1:5173/api/health`（经 Vite 代理）→ 同一错误体，耗时 5.03s
   - 数据库恢复后 → `200` + `{"status":"ok","database":"connected"}`，耗时 0.13s
   回归保护：新增 `tests/unit/test_db_engine_timeouts.py`（3 个用例）锁死该契约。

## 5. 当前风险与历史审计结论

> R1–R4、R6、R8 是当前风险；标记为“已关闭”的条目只保留问题发现与修复证据，不能再作为当前项目状态阅读。

| # | 问题 | 影响 | 计划 |
|---|---|---|---|
| R1 | **Docker 未安装** | 阶段 F（`docker compose up --build`）当前**无法执行** | 需要用户安装 Docker Desktop，或同意改为等价的本机等价部署方案；在此之前阶段 F 不能声称完成 |
| R2 | 系统 PostgreSQL 服务无法启动（需要管理员权限） | 不影响开发（已用项目内 5433 集群），但**与教学文档的 5432 不一致** | 已在 `.env` / `.env.example` 记录 5433；Docker 部署内仍用 5432 |
| R3 | 本地集群认证为 `trust` | 仅本机回环，单人本地开发；不适用于任何共享环境 | 生产/容器内改用密码认证 |
| R4 | Playwright 使用系统 Chrome 而非自带 chromium | 与教学文档描述略有差异；Chrome 升级可能带来行为差异 | 若日后 CDN 可达可切回 |
| R5 | ~~阶段 B/C/D 的资料与问答表尚未创建，`/materials`、`/chat` 都是占位页~~ | **已关闭（阶段 C/D）**：资料表、摄取任务、标题树、分块、`/materials` 与问答三张表、`/chat` 均已真实实现并验证 | 资料链路见第 10 节；问答链路见第 12 节 |
| R6 | GitHub Actions CI 未创建 | 教学文档标为可选 | 阶段 G 视情况 |
| R7 | ~~数据库中断时健康检查挂起~~ | **已在阶段 A 修复并加回归测试**（见第 4 节缺陷 #4） | 已关闭：修复后 5.2 秒内如实返回 503 |
| R8 | 建连超时 5 秒 / 连接池等待 10 秒是本地单机取值 | 数据库慢启动时首个请求可能等到超时；对本地单人开发可接受 | 阶段 F 容器化时按容器网络重新评估 |
| R9 | ~~阶段 A 四页均为占位页~~ | **已关闭（阶段 B/C/D）**：四个页面都是真实页面，`/chat` 已接真实问答链路 | 已关闭 |

## 6. 人工验收步骤（阶段 A）

1. **确认 PostgreSQL 集群在跑**
   `& 'C:\Program Files\PostgreSQL\18\bin\pg_isready.exe' -h 127.0.0.1 -p 5433` → 期望 `accepting connections`。
2. **启动后端**（项目根 `D:\考研跑通项目`）
   `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
3. **打开健康检查**：浏览器访问 `http://127.0.0.1:8000/api/health`
   期望：`{"status":"ok","database":"connected"}`。
4. **启动前端**（`D:\考研跑通项目\frontend`）
   `npm run dev`
5. **打开前端**：`http://127.0.0.1:5173`（会自动跳到 `/study`）
   期望：页面顶部“系统状态”显示“后端可用，PostgreSQL connected”，无错误码。
6. **手动制造 503**：停掉 PostgreSQL 集群
   `& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\考研跑通项目\.pgdata' stop`
   然后在前端点“重新检查”。
   期望：状态变为错误，显示 `database unavailable` 与错误码 `database_unavailable`，且**不显示任何驱动异常、连接串或密码**；按钮变为可用的“重新检查”。
7. **恢复**：重新启动集群后点“重新检查”，期望恢复“后端可用，PostgreSQL connected”。
8. **四个页面**：依次点击导航“今日学习 / 知识树 / 资料 / 问答”，期望路由分别为 `/study`、`/knowledge`、`/materials`、`/chat`，且每页显示对应标题与“阶段 A”占位说明（不是空白、不是假数据）。

## 7. 与教学文档的差异（详见 `reference-build-changes.md`）

| # | 文档写法 | 实际实现 | 原因 |
|---|---|---|---|
| 1 | 数据库 `127.0.0.1:5432`，库 `kaoyan` / `kaoyan_test` | 端口 `5433`，库名保持一致 | 系统 5432 服务无法启动 |
| 2 | Playwright 用自带 chromium | `channel: "chrome"` | CDN 不可达 |
| 3 | （未提及）Vite 监视范围 | 忽略 `*.tmpdir` 等 | 实测 EBUSY 崩溃 |
| 4 | `alembic.ini` 示例含中文 | 纯 ASCII | GBK locale 解码崩溃 |
| 5 | 健康检查依赖直接取 `backend.db.get_db` | 路由依赖 `backend/api/deps.py` 的 `get_db` | 依赖覆盖目标唯一，测试可注入 |
| 6 | Batch A 一次性建 7 张表 | 一致 | 与文档 Batch A 完全一致 |
## 8. 阶段 B —— 学习闭环（后端与真实学习页面）

> **历史快照说明**：本节记录阶段 B 初版的验收过程。当时的 3 题默认策略和 15 道种子题已在后续迭代升级为“每个叶子独立 `MasteryPolicy` + 22 道参考种子题”。当前行为以 `backend/mastery/policy.py`、`seed/syllabus.json`、`seed/questions.json` 和第 10 节后的回归记录为准。

### 8.1 新增 / 修改的文件

| 文件 | 职责 |
|---|---|
| `backend/mastery/enums.py` | `MasteryState` / `SelfGrade` / `EventType` / `EvidenceLevel` |
| `backend/mastery/types.py` | `Evidence`、`DomainLearningEvent`、`MasterySnapshot`、`TransitionResult`（frozen dataclass） |
| `backend/mastery/policy.py` | `MasteryPolicy`：默认基线为 3 个真实确认 / 1 变式 / 跨 2 天；每个叶子还能覆盖真实题数、题型配额、考法标签、变式数和题型排除项 |
| `backend/mastery/rules.py` | `SHANGHAI`、`update_evidence_window`、`confirmation_dates`、`effective_confirmation_count`、`graduation_check` |
| `backend/mastery/evidence.py` | `classify_evidence`：自评 → 证据等级；拒绝 naive datetime |
| `backend/mastery/transition.py` | `transition` 状态机 + `_try_graduate` / `_next_review` |
| `backend/mastery/storage.py` | 快照 ↔ `kp_states` 行、事件 payload 的唯一转换 |
| `backend/services/question_service.py` | 题干规范化与 3-gram Jaccard 去重（阈值 0.85） |
| `backend/services/planning_service.py` | `select_daily_goals` / `compute_goal_score`：推荐打分与理由码 |
| `backend/services/practice_service.py` | `create_initial_plan`（按每叶子的策略缺口与时间预算选题）、`append_questions_to_plan`（卷尾、去重、不重洗） |
| `backend/services/attempt_service.py` | `assess_practice_item`：一次自评的完整事务与幂等 |
| `backend/services/node_assessment_service.py` | `assess_knowledge_node`：叶子整体自评，基础确认 +2，不伪造作答 |
| `backend/api/routes/study.py` | 10 个端点中的 9 个：今日计划、答案、自评、知识树 |
| `backend/api/deps.py` | 新增可注入时钟 `get_time_provider`（跨天测试用） |
| `backend/schemas/knowledge.py`、`schemas/practice.py` | HTTP 契约；练习卷响应**不含答案与解析** |
| `backend/errors.py` | 补齐 12 个稳定错误码 |
| `backend/app.py` | 注册 `study_router` |
| `seed/syllabus.json` | 11 节点 / 5 可考核叶子 |
| `seed/questions.json` | 当前 22 道题；5 个可考核叶子各有 4–5 道，满足其独立题型、考法和变式策略 |
| `scripts/seed.py` | 按 `code` 幂等 upsert；补齐 `kp_states` |
| `scripts/reset_today.py` | 开发/测试用：清空今日卷与练习历史（后端不暴露重置接口） |
| `frontend/src/api/client.ts` | 统一 API 客户端：相对 `/api`、按 `error.code` 分支 |
| `frontend/src/api/study.ts`、`types/practice.ts` | 学习闭环 API 与类型 |
| `frontend/src/lib/labels.ts` | 机器码 → 中文映射、幂等键生成 |
| `frontend/src/composables/useAsyncTask.ts` | 统一 loading / success / error / submitting |
| `frontend/src/components/StudyFocus.vue` | 专注模式单题卡片 |
| `frontend/src/pages/StudyPage.vue` | setup / active / completed、推荐、生成、专注、全卷、答案、四种自评、追加、摘要 |
| `frontend/src/pages/KnowledgePage.vue` | 知识树、父节点汇总、叶子四 Tab、叶子整体自评 |
| `frontend/e2e/fixtures.ts`、`e2e/navigation.spec.ts` | 每个用例独立重置数据；6 个端到端用例 |

### 8.2 实际运行过的命令与结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m alembic revision --autogenerate` / `upgrade head` / `check` | ✅ 无新迁移；`e265f44be662 (head)`；`No new upgrade operations detected.` |
| 2 | `python -c "json.load(seed/*.json)"` + 叶子策略题库校验 | ✅ 5 叶子；每个题库均满足自己的 `min_real_questions`、题型配额、考法标签与变式要求 |
| 3 | `python scripts/seed.py`（首次） | ✅ 知识点新建 11、`KpState` 补齐 5、题目新建 15 |
| 4 | `python scripts/seed.py`（第二次） | ✅ 新建 0、更新 11、题目跳过 15 → **幂等成立** |
| 5 | 数据计数 | ✅ `knowledge_points=11`、`kp_states=5`、`questions=15`、可考核叶子=5 |
| 6 | `python -m pytest -v` | ✅ **62 passed, 0 failed** |
| 7 | `npm run typecheck` | ✅ 通过（`vue-tsc --noEmit`） |
| 8 | `npm run build` | ✅ 通过 |
| 9 | `npm run test:e2e` | ✅ **6 passed** |
| 10 | `GET /openapi.json` | ✅ 10 个路径全部注册 |
| 11 | `GET /api/knowledge/tree` | ✅ 200，两个根节点 |
| 12 | `GET /api/knowledge/{不存在}` | ✅ 404 + `knowledge_point_not_found` |
| 13 | `GET /api/knowledge/tree-typo` | ✅ 422（非法 UUID） |

### 8.3 测试清单（阶段 B）

| 测试文件 | 用例数 | 覆盖 |
|---|---:|---|
| `tests/unit/mastery/test_policy.py` | 9 | 默认阈值 = 产品规则；8 种非法策略被拒绝 |
| `tests/unit/mastery/test_rules.py` | 14 | 上海日历口径；失败清窗；partial 不动窗；同题只刷时间；三题门槛；变式门槛；跨 2 天门槛；基础确认 2 条路径 |
| `tests/integration/test_learning_loop.py` | 30 | 知识树边界、父节点禁止自评、准备页、生成、答案纯读取、四种自评、幂等、计划完成、追加、跨天毕业、节点整体自评三条规则 |
| `frontend/e2e/navigation.spec.ts` | 6 | 四页连通、503 分支、知识树 Tab 与父节点边界、整体自评 +2、今日学习主流程、追加到卷尾 |

关键断言（都跑在真实 PostgreSQL 上）：

- 只有 `is_assessable` 叶子有状态；父节点一律 `state=None`
- 父节点整体自评 → `409 node_not_assessable`
- 练习卷响应中**没有** `correct_answer` / `explanation`
- 答案接口调用前后：`question_attempts`、`learning_events`、`kp_states`、`completed_at` 全部不变
- `skip`：0 条 attempt、不改状态、不标记完成
- `not_mastered`：清空窗口、`stuck`、历史保留（2 条 attempt 都在）
- 同 key 重放：响应一致、只有 1 条 attempt、1 条 event
- 换 key 重交同题 → `409 practice_item_already_assessed`
- 同日三题全 mastered → `consolidating` + `insufficient_day_span`
- 01-01 与 01-03 两条确认 + 1 变式题 → `mastered` + `graduated` + `next_review_at = mastered_at + 7d`
- 同一天不能重复生成 → `409 plan_already_generated`
- 题池不足 → `409 question_pool_incomplete` 且**不留半张卷**
- 计划行状态真的写入 `completed`（直接查库断言）
- 追加：只加新题到卷尾 `ordinal=4`，重复项被忽略
- 节点整体自评 `mastered` → `manual_credit_count=2`、`effective=2`、**0 条 attempt**、事件 `source_id=None`、`evidence_level=None`
- 页面 `day_span` 与状态机同一口径（01-01 → 01-03 = 2 天）

### 8.4 阶段 B 中修复的真实缺陷

1. **`daily_plans.status` 永远写不进 `completed`（功能不可达）**
   根因：会话是 `autoflush=False`，`item.completed_at = now` 之后直接查询 `completed_at IS NULL`，把刚做完的这道题自己查了回来，`remaining` 永不为 `None`。
   后果：总结页状态不可达，而且**已完成的卷还能继续追加题目**。
   修复：赋值后先 `session.flush()` 再查询。回归保护：`test_plan_row_status_becomes_completed_in_database` 直接断言数据库列，`test_append_to_completed_plan_is_rejected` 断言已完成卷拒绝追加。

2. **知识点整体自评的反馈被自己清空**
   根因：`KnowledgePage` 提交成功后先写反馈，再 `await selectNode()`，而 `selectNode()` 开头会清空反馈。
   修复：改为最后写反馈。回归保护：E2E 断言 `node-notice` 出现且含「基础确认 +2」。

3. **`day_span` 与状态机使用两套跨天口径**
   根因：状态机把 `manual_confirmed_at` 计入跨度，而页面只算 `evidence_window`。
   修复：新增 `rules.confirmation_dates()`，状态机与页面共用。回归保护：`test_node_route_day_span_uses_same_calendar_as_state_machine`。

4. **E2E 断言写错（非产品缺陷，但会误导结论）**
   - 提交自评后页面按设计跳到下一题，因此 `focus-answer` / `focus-notice` 消失是正确的；改为在全卷模式验证反馈。
   - 点击父节点是折叠/展开，子节点会从 DOM 移除；改为通过 ▸ 按钮逐层展开。
   - 题库面板断言写了知识点名称（题干里没有），改为断言题干内容与题数。

### 8.5 已知限制（阶段 B 交付时真实存在）

| # | 限制 | 影响 | 计划 |
|---|---|---|---|
| L1 | 初始组卷按 `Question.id`（UUID 字节序）取「前两道基础题」 | 同一天两次全新生成可能选中不同的基础题；不影响毕业规则 | 阶段 C 之后可改为按 `difficulty` + 创建时间稳定排序 |
| L2 | `objective_result` 固定写 `unknown` | 选择题暂无自动判分参考；符合「自评优先」的规则 | 设计决定，见 `reference-build-changes.md` C-16 |
| L3 | 复测只用到第一档 7 天（`stage` 恒为 0） | `next_review_at` 只按 7 天推进；15/30 天档位当前不可达 | 产品 V1 未要求复测推进流程 |
| L4 | 父节点「已毕业 N/M」由前端数子节点得出 | 与后端汇总口径一致，但前端参与了一次计数 | 允许：规则明确「父节点只汇总」，且状态本身来自后端 |
| L5 | 「关联资料」Tab 明确显示未接入 | 不是 bug，资料索引在阶段 C | 阶段 C 接入 |

### 8.6 人工验收步骤（阶段 B）

1. 确认 PostgreSQL 在跑：`pg_isready -h 127.0.0.1 -p 5433` → `accepting connections`
2. 确认 8000 / 5173 都在跑（`/api/health` 返回 200）
3. 打开 `http://127.0.0.1:5173/knowledge`
   - 左侧出现「高等数学 / 线性代数」两棵树，父节点显示 `0/4 已毕业` 这类汇总
   - 点父节点「高等数学」：右侧提示「请选择左侧的可考核叶子节点。父节点只能汇总……」，**不出现任何自评按钮**
   - 点 ▸ 展开「极限与连续」，再点「洛必达法则」：右侧出现概览，含有效确认数、基础确认、变式题、跨度、下次复习，以及「我已掌握 / 我部分掌握 / 我未掌握」三个按钮
   - 点「我已掌握」：提示出现「……基础确认 +2……」；「基础确认」变为 2；切到「练习记录」Tab 仍显示「还没有练习记录」（**没有伪造两条作答**）
   - 点「我部分掌握」：基础确认变回 0，练习记录仍为空
   - 切到「题库」Tab：能看到 3 道题干与「变式题」标记，**看不到答案与解析**
4. 打开 `http://127.0.0.1:5173/study`
   - 若已无今日卷：显示准备页与推荐列表（带「到期复习 / 上次未掌握 / 当前卡住 / 继续巩固 / 尚未开始」理由），默认勾选
   - 点「生成今日练习卷」→ 进入答题态，显示 `状态：进行中（0 / N）`
   - 专注模式：一次一道未完成题，**不显示答案**；点「查看答案详解」后才出现参考答案与解析（做题前查看也可以）
   - 点「已掌握」→ 自动跳到下一道未完成题，剩余题数减少
   - 切到「阅览全卷」：按 ordinal 显示全部题，已完成题仍在，带「已完成 · 已掌握」与自评反馈
   - 点「追加练习题」→ 选择器出现；展开另一个知识点能看到它的题库；勾选后「确认追加」→ 提示消失，题数 +1，全卷最后一道就是新题
   - 「今日涉及的知识点」列出今天实际涉及的叶子与完成数量
5. 重复第 4 步会因「同一天不能重新生成整卷」而直接进入答题态——这是设计；要重新演示先执行
   `python scripts/reset_today.py`
### 8.7 阶段 B 交付后发现的缺陷修复（C-22）

真实环境复现：用户做完全部 3 道题后点「追加练习题」→ `409 plan_not_active`。

| 项 | 内容 |
|---|---|
| 根因 | `plan.status` 被当作持久状态，混淆了「今天是否还在进行」与「这张卷能否追加」两种语义 |
| 修复 | 追加接受 `active` 与 `completed`；追加成功后改回 `active`；接口直接返回 `plan.status` |
| 验证 | `pytest 91 passed`、`playwright 9 passed`；真实环境：`completed(3/3)` → 追加 200 → `active(3/4)`、卷尾 `ordinal=4` |
| 记录 | `reference-build-changes.md` C-22 |
## 9. 设计升级（每知识点独立毕业策略）实施状态

| 层 | 状态 | 说明 |
|---|---|---|
| 数据模型 | ✅ 完成 | `questions` 新增 role/skill_tags/estimated_minutes；新增 `kp_mastery_policies` 表（迁移 `4e69a0e83a3b`） |
| mastery 包 | ✅ 完成 | `Evidence` 记录题型与考法；`graduation_check` 六项判定；新增 `analyze_gaps`；新增 `selection.py` 按缺口与预算选题 |
| 种子数据 | ✅ 完成 | 22 道题（含计算大题、证明之外题型）；5 个叶子各自的策略；自检脚本保证题库满足策略 |
| 组卷 | ✅ 完成 | `create_initial_plan` 改为按缺口与时间预算选题 |
| 每日推荐 | ⚠️ 部分 | 知识点层优先级尚未按新顺序调整（当前仍是旧打分） |
| 接口 | ⚠️ 部分 | 知识树已返回 gap_items/next_step/策略；今日页尚未展示卷子构成与预算选择 |
| 前端 | ⚠️ 部分 | 尚未渲染缺口明细、题型构成与时间预算选择 |
| 测试 | ✅ 完成 | `pytest 123 passed`（新增策略、判定、缺口、选题用例） |

### 9.1 本次实测结果

| 验证 | 结果 |
|---|---|
| 迁移在含既有数据的库上执行 | ✅ 15 条旧题通过两步式迁移（先加带默认值的列、再移除默认值） |
| 种子幂等 | ✅ 第二次运行全部跳过；旧题元数据被刷新 |
| 洛必达法则组卷 | ✅ 4 道题：计算(变式) 1 + 选择 1 + 填空 1 + 计算 1，预计 32 分钟，恰好满足策略 |
| 缺口报告 | ✅ 8 项逐条给出 当前/要求，`next_step` 指向最具体的缺口 |
| 排除题型 | ✅ 只考客观题的叶子不会被推荐计算大题 |
| 时间预算 | ✅ 轻量预算下最多放两道 20 分钟的大题 |

### 9.2 发现并修复的真实问题

1. **迁移在已有数据上直接失败**：`ADD COLUMN NOT NULL` 没有默认值，
   15 条既有题目导致 `NotNullViolation`。修复为两步式（加带默认值的列 → 立即移除默认值）。
2. **选题超出策略要求**：按条件独立计数时，策略要求 2 道计算题却选了 3 道。
   改为「缺口逐步补齐」贪心，选题数恰好够补缺口。
3. **旧题缺考法标签**：种子脚本对已存在的题目直接跳过，导致升级前录入的题没有 `skill_tags`，
   必考考法永远无法覆盖。修复为刷新已有题目的分类元数据。
4. **`next_step` 不够具体**：原先按判定顺序输出「再完成 2 个有效确认」，
   改为「越具体越先说」，优先指出「完成 1 道计算大题」。
### 9.3 推荐与复测选题（本轮补齐）

| 项 | 状态 |
|---|---|
| 每日推荐六层优先级 | ✅ 完成（含已确认的冲突规则与同层排序） |
| 推荐理由来自真实缺口 | ✅ 完成（`next_step` + `missing_types`） |
| 题库耗尽的复测选题 | ✅ 完成（真实缺陷修复 + `is_review` 标记） |
| 前端展示缺口/预算/构成 | ⚠️ 未开始 |

实测（把练习卷日期改到昨天、模拟第二天进入准备页）：

```
洛必达法则    层级=not_mastered      下一步=完成 1 道选择题
等价无穷小替换  层级=partial_mastery   下一步=完成 1 道选择题
隐函数求导    层级=preview           下一步=完成 1 道选择题
行列式的性质   层级=preview           下一步=完成 2 道选择题
等比级数      层级=preview           下一步=完成 1 道选择题
```

排序与已确认的优先级完全一致（未掌握 → 部分掌握 → 未学习）。

## 10. 阶段 C —— 资料摄取、索引与混合检索

### 10.1 新增 / 修改的文件

| 文件 | 作用 |
|---|---|
| `backend/ingestion/source_io.py` | 后缀白名单、根目录越界防护、严格解码（UTF-8/GB18030，绝不 `ignore`） |
| `backend/ingestion/document_parsers.py` | markdown / text / docx / pypdf 四种解析器，各带 `parser_version` |
| `backend/ingestion/file_storage.py` | 流式落盘：`.part` → SHA-256 → 原子替换，失败不留半个文件 |
| `backend/retrieval/protocols.py` | `Embedder` / `VectorStore` / `IndexFilter` / `SearchFilters` / `RetrievalHit` 契约 |
| `backend/retrieval/embedding.py` | 真实 sentence-transformers 实现 + 可控 `FakeEmbedder`（支持指定向量） |
| `backend/retrieval/vector_store.py` | Chroma 持久实现 + 内存实现，强制归一化契约与模型一致性校验 |
| `backend/retrieval/keyword.py` | jieba + BM25（`epsilon=0` 关闭负 IDF 截断） |
| `backend/retrieval/fusion.py` | RRF 融合（单路内部去重、跨路累加、同分稳定排序） |
| `backend/retrieval/rerank.py` | 默认不重排；配置模型后启用 cross-encoder，失败自动降级 |
| `backend/retrieval/stack.py` | 检索栈组装（进程级单例，worker 与 API 共享同一份索引） |
| `backend/services/retrieval_service.py` | 正文向量 + 标题树 BM25 + 正文 BM25 三路召回、RRF 与数据库正文补全；只召回 ready 且当前激活版本 |
| `backend/services/ingestion_service.py` | 解析 → 分块 → 写库 → 建向量 → 原子切换版本 |
| `backend/services/material_service.py` | 上传 / 列表 / 详情 / 删除 / 重建 / 重试 |
| `backend/jobs/worker.py` | 租约领取、指数退避重试、崩溃恢复、失败清理 |
| `backend/jobs/runner.py` | 后台线程 + 通知唤醒，与请求线程隔离 |
| `backend/api/routes/materials.py` | 资料接口 8 个（含调试检索） |
| `backend/schemas/materials.py` | 资料接口 schema（不含任何落盘路径） |
| `backend/eval/dataset.py` / `metrics.py` | 评估数据集加载与指标（纯函数） |
| `frontend/src/pages/MaterialsPage.vue` | 资料库页面：上传、状态轮询、块预览、重建/重试/删除、检索自测 |
| `frontend/src/api/materials.ts` | 资料接口封装（含 multipart 上传） |
| `seed/materials/gaoshu-lecture-01.md` | 内置真实讲义，覆盖全部 5 个可考核叶子 |
| `eval/dataset/retrieval_v1.jsonl` | 14 条检索评估用例（字面 / 语义 / 越界） |
| `scripts/check_retrieval.py` | 查看向量库集合、模型与向量数 |
| `scripts/e2e_materials_check.py` | 端到端验收：上传 → 索引 → 检索 → 清理 |
| `scripts/run_retrieval_eval.py` | 真实模型检索质量评测（临时库，不污染开发索引） |
| `scripts/check_deploy_config.py` | 部署配置静态校验 |
| `docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx/` | 部署配置 |
| `docs/deploy-docker.md` | 部署说明与**未验证项清单** |

### 10.2 实际运行过的命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest` | **278 passed**（阶段 C 新增 122 条） |
| `python scripts/check_retrieval.py` | 集合 `kaoyan_chunks`，cosine 空间，写入模型与配置一致 |
| `python scripts/e2e_materials_check.py` | **全部通过**：上传 201 → 15 块 → ready（版本 `v1-c502c7fbb967d91e`）→ 5 个语义查询全部命中 → 删除 204 → 检索为空 |
| `python scripts/run_retrieval_eval.py` | Hit@6 = **1.000**、Recall@6 = **1.000**、MRR@6 = **0.962**；越界用例最高相似度 **0.031** |
| `python scripts/check_deploy_config.py` | 全部通过（COPY 源、卷、健康检查、LF 行尾、nginx 变量、忽略规则） |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过（50 modules，JS 146.45 kB / gzip 54.14 kB） |
| `npx playwright test` | **13 passed**（阶段 C 新增 4 条资料页用例） |

### 10.3 真实检索质量（不是估计值）

用真实 `BAAI/bge-small-zh-v1.5`、真实 Chroma、15 个块、14 条用例得到：

```
Hit@6：1.000
Recall@6：1.000
MRR@6：0.962
越界用例最高相似度：0.031
越界强信号率（相似度 >= 0.7）：0.000
```

- 13 条有答案的用例里 **12 条排第 1**，1 条（`q04 加减法里能不能直接替换等价无穷小`）排第 2；
- 越界用例（`这个软件怎么安装`）最高相似度只有 **0.031**，说明阶段 D 用一个中等阈值
  就能可靠拒绝「知识库里没有的问题」，而不必依赖模型自觉。

### 10.4 阶段 C 中修复的真实缺陷

| 缺陷 | 症状 | 根因与修法 |
|---|---|---|
| `title_tree.resolve_kp_hints` 注释归属整体错位 | 5 个知识点注释只有 1 个归属正确，引用会标错知识点 | 范围起点用了父节点 `body_start`（在父标题行之后），注释落到父节点之外；改为「紧邻本标题行」判定 + 二分查找（顺带消除 O(n²) 扫描） |
| `run_job` 用两个版本号各写一次 chunks | 库里块数翻倍（15 → 30） | 版本号依赖解析后才得到的 `content_hash`；拆出纯内存的 `plan_material`，先算版本再写库 |
| 关键词索引重建时机错误 | **关键词候选恒为 0**，检索只剩向量一路（看起来还能用，因此极难发现） | 在 `build_index` 里重建时资料状态还是 `indexing`，被 `ready` 条件过滤；改到 `activate_version` 之后重建 |
| 删除资料未刷新关键词索引 | 已删资料仍被 BM25 召回，再被正文校验丢弃，表现为「召回 N 条、最终 0 条」 | `delete_material` 增加 `keyword_index` 重建 |
| `AppError("code", "消息")` 把消息传给 `status_code` | 参数校验失败返回 **500** 而不是 400 | 消息必须用 `detail=`；并给 `AppError` 加类型检查，杜绝复发 |
| `resolve_source_path` 检查顺序错误 | 指向目录时误报 `unsupported_type` | 先判「是不是存在的文件」，再判后缀 |
| RRF 单路内部重复 id 被多次计分 | 同一路可刷分，融合排序失真 | 改为每路各自去重、跨路正常累加 |
| BM25 `epsilon=0.25` 在小语料把分数全压成 0 | 关键词路在小语料库彻底失效 | 设 `epsilon=0.0`，保留负 IDF 的符号语义 |
| `run_job` 失败分支无日志 | 真实环境失败时只能看到数据库里的错误码，查不到原因 | 补 `logger.warning`，记录错误码与异常类型（不含路径与密钥） |
| Chroma 文件句柄未释放 | Windows 上临时目录删不掉（WinError 32） | `ChromaVectorStore.close()` + 评估脚本显式调用 |

### 10.5 已知限制（阶段 C 交付时真实存在）

- **Docker 未安装**：部署配置已写完并通过静态校验，但 `docker compose up --build` 从未真实执行过，详见 `docs/deploy-docker.md` 的「验证状态」；
- **重排未启用**：`RERANKER_MODEL` 为空，走「不重排」降级路径（这是正常配置，不是失败）。降级路径本身有测试覆盖；
- **PDF 只支持文本层**：扫描件明确报 `scanned_pdf`，不做 OCR；
- **语料很小**：内置讲义只有 15 个块、5 个知识点。评估指标（Hit@6 = 1.000）在这个规模上
  很容易满分，**不能外推到真实规模**；
- **关键词索引常驻内存**：从 PostgreSQL 全量重建，当前千级块可接受；规模上去需要换成持久化倒排索引；
- **`/chat` 当时仍是占位页**：该缺口已在阶段 D 关闭（见第 12 节）。

### 10.6 人工验收步骤（阶段 C）

前置：PostgreSQL（5433）、后端（8000）、前端（5173）都在运行。

```powershell
# 一键启动（若未启动）
.\scripts\start-dev.cmd
```

1. 打开 <http://127.0.0.1:5173/materials>；
2. 标题填「高等数学核心考点讲义」，来源选「随仓库提供」，
   文件选 `seed/materials/gaoshu-lecture-01.md`，点「上传并建立索引」；
3. 观察状态自动从「排队中」→「建立索引中」→「可检索」（首次会加载模型，稍慢）；
4. 核对详情：索引版本形如 `v1-xxxxxxxxxxxxxxxx`、块数为 15、块预览带标题路径与知识点编号；
5. 在「检索自测」里依次输入下面 5 个问题，确认**每条都能命中正确章节**：
   - 什么时候不能用洛必达法则 → 第一章
   - 加减法里能不能直接替换等价无穷小 → 第二章
   - 隐函数怎么求切线方程 → 第三章
   - 等比级数什么时候收敛 → 第四章
   - 行列式数乘以后怎么变化 → 第五章
6. 输入「这个软件怎么安装」，确认返回的结果与问题无关（说明库内确实没有，阶段 D 会拒绝作答）；
7. 点「删除资料」并确认，核对列表回到空、再检索一次没有命中。

也可以直接跑一键脚本（会做同样的事并打印每步结果）：

```powershell
python scripts\e2e_materials_check.py
```

## 11. 用户实测反馈的修复（阶段 C 交付后）

用户在真机上按验收文档操作，报告了四个问题。**四个全部确认为真实缺陷**，
已全部修复并有回归测试；排查过程中还定位到一个阻塞验证的严重问题。

### 11.1 四个问题与修复

| 编号 | 问题 | 根因 | 修复 |
|---|---|---|---|
| P1 | 跑 `npm run test:e2e` 会删光用户自己上传的资料 | 夹具为了让断言简单，拉一次列表就删除每一条，并挂在 page 夹具上每用例前后各执行一次；验收脚本也断言「资料列表已清空」 | 只清理带 `E2E-` 前缀的资料、按用例前 id 基线做差集、清理放进 `finally`；夹具不再提供「清空资料库」的能力；新增「用户资料一份都不能少」用例；验收脚本改为记录基线 + 逐条核对 |
| P2 | 11 MB 的文件「上传成功、随后异步失败」，提示还说「超过 20 MB」 | 上传上限 20 MB 与解析上限 5 MB 是两个独立常量，中间 15 MB 是「先成功后失败」地带 | 合并为唯一常量 `MAX_FILE_BYTES`（10 MB），前端用同一个值在上传**前**拦截，文案不再写死数字 |
| P3 | 损坏 PDF 把 `unexpected:PdfReadError` 显示到界面 | worker 兜底用异常类名当错误码，前端没有这个键就原样显示 | 新增 `DocumentParseError` 与稳定码 `document_parse_failed`；pypdf/docx 异常统一收敛；worker 兜底改为 `internal_error` |
| P4 | `indexing` 中间态永远观察不到（轨迹只有 pending → ready） | worker 只 `flush()` 不 `commit()`，而 runner 整批结束才提交一次，READ COMMITTED 下未提交行对外不可见 | 设置 `indexing` 后显式 commit；补 `SQLAlchemyError` 分支处理提交失败；新增测试钩子用独立连接验证可见性 |

**P4 的影响面比表面更大**：前端的「建立索引中」标签与样式是死代码，
验收文档里「观察 排队中 → 建立索引中 → 可检索」这一步根本做不到，
`requeue_stale_pending_jobs` 里那个 `indexing` 条件也永不命中。

### 11.2 排查中定位的严重问题：向量索引损坏导致后端进程无 traceback 消失

**现象**：上传资料后，worker 加载完 embedding 模型，整个 Python 进程直接消失，
日志里没有任何 traceback。表现为「后端跑着跑着就没了」，所有测试与页面一起失败。

**根因**：Chroma 的 HNSW 索引文件损坏（反复强制终止进程导致向量写入被中断）。
在损坏的索引上读计数会报 `Error creating hnsw segment reader: Error loading hnsw index`。

**修复**：
1. 向量库构造时立刻读一次计数（真正打开段文件），损坏时抛带行动指引的错误；
2. 检索栈装配增加兜底 `except`：宁可「检索不可用（503）」，也不让原生库异常带走启动流程；
3. 新增 `scripts/rebuild_all_indexes.py` 与一键入口 `scripts\rebuild-all-indexes.cmd`。

**这次事故正好验证了架构选择是对的**：正文与分块都在 PostgreSQL 中完好
（「验收」20 块、「提示词」15 块），向量库删掉重建即可完整恢复，**没有任何数据丢失**。
如果当初把正文权威放在 Chroma，这次就是真正的数据丢失。

### 11.3 竞态修复：删除资料与后台索引任务

在修复 P1~P4 的过程中又发现一个**稳定复现的数据残留问题**：

**现象**：每跑一次浏览器端到端测试，向量库就多出一个孤儿向量（15 条）。
数据库侧完全干净（0 孤儿块），只有向量库留下残影。

**根因**：删除资料原本是「先清向量、再删数据库记录」，两步不在同一个事务里；
而后台索引任务可能正在处理同一份资料（e2e 里「重建索引」用例之后紧接着删除）。
任务在自己的检查点看到的资料**仍然存在**，于是继续写向量，等记录被删掉时
向量已经写进去了。窗口宽达「解析 + embedding 编码」的耗时，所以稳定复现。

**修复**：
1. 删除顺序改为「先删数据库记录（立即提交）→ 再清向量 → 再刷新关键词索引」。
   记录消失后，任务在写库前检查会直接收尾；即使已经开始写，随后的向量清理也会删掉；
2. `run_job` 增加两处检查：写库前、以及解析完成后（后者会回滚并清掉已写入的版本）；
3. 任务状态写入容忍「任务行已被级联删除」（`StaleDataError` → rollback 收尾），
   避免 session 进入待回滚状态后抛出一串 `PendingRollbackError`；
4. 新增 `scripts/check_vector_orphans.py`（`--clean` 可清理孤儿向量）。

**验证**：修复后 e2e 16 项通过，向量库 **35 条 = 15 + 20，零孤儿**。

这一轮还纠正了一个观测陷阱：验收脚本原来的轮询间隔（0.5~2 秒）比
`indexing` 中间态的寿命（约 0.35 秒）还大，于是整个中间态被跳过 ——
看起来像「中间态不可见」，实际只是没采样到。间隔收到 0.1 秒后，
状态轨迹稳定输出 `indexing → ready`。

### 11.4 顺带修复的可用性缺陷

- **块列表不随轮询刷新**：处理完成后详情已显示「块数 15」，块列表却一直写着
  「这份资料还没有块」，必须手动再点一次才刷新。已改为轮询发现
  「ready 但块列表为空」时补一次请求。
- **测试的后端依赖不明确**：后端没起时 16 个用例各报一次 `fetch failed`，
  看起来像测试代码坏了。现在夹具先显式检查可达性并给出可直接照做的指引。
- **测试 HTTP 的 keep-alive 陷阱**：uvicorn 默认 5 秒空闲关闭连接，而夹具里的
  `execFileSync` 会阻塞更久，Node 从连接池复用到已关闭连接会抛 `ECONNRESET`，
  且连接池可能反复复用同一条坏连接。已统一改为带重试 + `Connection: close`。
- **用例超时**：默认 30 秒会在索引期间把用例整体砍掉，报错像断言失败。已提到 3 分钟。

### 11.5 本轮实际运行结果

| 命令 | 结果 |
|---|---|
| `python -m pytest` | **293 passed**（新增 10 条问题回归 + 5 条竞态回归） |
| `npx playwright test` | **16 passed**（新增 3 条资料页用例 + 1 条数据保护用例） |
| `npm run typecheck` | 通过 |
| `scripts/e2e_materials_check.py` | 全部通过，并确认用户资料未被动过 |
| `scripts/check_deploy_config.py` | 通过 |
| `scripts/rebuild_all_indexes.py` | 成功恢复两份资料的索引（提示词 15 块 / 验收 20 块） |
| `scripts/check_vector_orphans.py` | 一致性正常：零孤儿向量（35 条 = 15 + 20） |

**用户资料状态（修复后核对）**：「验收」ready / 20 块；「提示词」ready / 15 块。
测试零残留；向量库与数据库完全一致。

### 11.6 回归测试的有效性验证

`indexing` 可见性那条测试做过反向验证：把实现临时改回 `session.flush()`，
测试立刻失败并报出 `读到 'pending' 说明中间态没有提交`，与用户报告的现象一致；
改回 `commit()` 后通过。**这说明测试确实能抓住这个缺陷，不是假绿灯。**

## 12. 阶段 D —— 可信问答、SSE 与题库追练

### 12.1 交付来源与本次工作

阶段 D 的代码由另一份实现提供（不在本会话所写）。本会话对该实现做了
**逐项契约审查并补全**，修复了 7 类问题，并补上契约要求但缺失的测试。
以下记录的是**审查结论与修复内容**，不是「从零实现」。

### 12.2 审查发现并修复的问题

| 类别 | 问题 | 影响 | 修复 |
|---|---|---|---|
| 数据完整性 | 三个 CHECK 约束只写在模型里、迁移里没有 | 数据库拦不住非法 `mode`/`status`/`role`；一条写错 mode 的会话会静默跨库检索 | 迁移 `4c8a2f1b7d95` 补齐约束与列默认值 |
| 消息顺序 | `user` 与 `assistant` 同事务写入，`created_at` 完全相同，只按时间排序 | **刷新后「回答」可能出现在「问题」前面**，且时有时无 | 新增 `seq`（identity）列并按它排序（迁移 `7d2e5a9c4b31`）；写入时分两次 flush |
| 归因 | `matched_kp` 只看「第一块是否恰好一个 kp」，没有阈值与领先度 | 会把无关问题硬归因到某知识点，进而推荐无关追练题 | 重写为名次累积 + 阈值 + 相对领先度，冲突时返回 null |
| 归因稳定性 | 用累积分排序，结果随块的顺序漂移 | 同一问题在不同检索顺序下归因不同 | 改为「最佳名次优先、累积分作次判据」 |
| 崩溃 | 无任何 kp 关联时 `ranked[0]` 越界 | 一次正常问答变成 500 | 显式判空返回 None |
| 引用 | 「有检索结果但模型没写引用」判整次回答失败 | 丢弃一次可用回答，并给出与事实不符的错误 | 保留正文，只记 `unknown_citation_labels` 与 `citation_warning` |
| 引用 | 未校验引用的 chunk 是否仍可检索 | 资料被重建/删除后，来源卡片指向死数据 | 新增活跃版本校验，丢弃失效引用并记录 |
| 取消 | 客户端断开时丢弃已生成的文本 | 用户看不到中断前的进度 | 保留已收文本并标记 `cancelled`；完全无内容则不留空消息 |
| 前端 SSE | 尾帧丢失（服务端最后一帧没有结尾空行） | `done` 永远到不了前端，页面**卡在「正在生成」** | 流结束时处理缓冲区剩余帧 |
| 可观测性 | 流式失败的异常被吞掉 | 只能看到「生成失败」，无法定位 | 异常计入日志（含已收文本长度） |
| 健壮性 | 只导入 `backend.chat.*` 时缺表注册 | `NoReferencedTableError` 的导入顺序偶发故障 | 导入 `backend.models` 即注册全部模型 |

### 12.3 补上的契约测试

契约要求三个测试文件，原先只有 1 条测试碰了 `_citations`：

| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_citation_validator.py` | `[C#]` 提取、去重、unknown、非契约形式一律不认、SSE 编码 |
| `tests/unit/test_chat_attribution.py` | 阈值、领先度、无关联不归因、顺序无关性、确定性 |
| `tests/integration/test_chat_flow.py` | 无命中拒答且不调用模型、引用落库、模式隔离、失败收尾、归档会话 |
| `tests/integration/test_chat_stream.py` | 帧序 `meta → delta* → citations → done`、seq 递增、citations 卡字段、取消保留文本、error 收尾不泄露堆栈、空回答重试策略 |
| `frontend/e2e/chat.spec.ts` | 页面结构、草稿会话、模式隔离、真实提问 + 刷新后引用仍在、归因依据、理解确认关卡 |

删除了 `tests/unit/test_chat_citations.py`：它唯一那条测试的内容被
`test_citation_validator.py` 完全覆盖，且字符串本身是乱码。

### 12.4 实际运行结果

> 下表是**阶段 D 当时**的记录。后来 e2e 改成了隔离模式（打测试库、
> 拒绝连 dev/prod），并且帧序改为带独立 `citations` 帧 ——
> 当前一轮的实测结果见第 20 节，验收以那一节为准。

| 命令 / 验证 | 结果（阶段 D 当时） |
|---|---|
| `python -m pytest` | 353 passed |
| `npx playwright test` | 22 passed（连续两次稳定；**当时直接打开发库，现已作废**） |
| `npm run typecheck` / `build` | 通过 |
| `alembic check` | 无差异 |
| 真实非流式问答 | 打通：模型正确识别资料范围并**拒答编造**，4 条引用带回跳用的标题路径 |
| 真实内置模式问答 | 打通：`matched_kp` 归因成功、追练候选**只从已有题库取**、困惑标记返回 `changes_mastery: false` |
| 真实 SSE 流式 | 连续 3 次通过：`meta → delta… → done`、`seq` 递增、`done` 带 citations（帧序后来改为带独立 citations 帧） |

### 12.5 已知限制

- **归因粒度受讲义标记影响**：问「等价无穷小能不能在加减里替换」会被归因到
  「洛必达法则」，因为讲义中该内容的所属小节标记为洛必达法则
  （「与等价无穷小配合使用」）。这是讲义内容标记的取舍，不是代码缺陷。
  **处理方式（阶段 D 之后收口）**：不硬改归因，而是把依据展示出来 ——
  回答下方显示「归因依据：归到『洛必达法则』，依据是正文引用的 [C1]」，
  用户据此能自己判断这次归因是否符合预期。详见
  `reference-build-changes.md` 的 D-18。
  **后续进展（见第 14 节）**：归因阈值修好量纲之后，这个问题已**不再出现** ——
  该问题现在正确归因到「等价无穷小替换」。
- **SSE 取消只覆盖「用户断开」**：未测「服务端主动超时」的中间态。
- 本机 **Docker 仍未安装**，阶段 F 的容器验证仍未执行。

## 13. 阶段 D 之后：三个遗留风险的收口（已实际运行验证）

阶段 D 交付时挂账了三个风险：本机内存会把数据库挤死、Playwright 存在偶发失败、
`matched_kp` 只给结论无法核对。本轮逐条收口，并**在收口过程中又发现两个真实缺陷**。

### 13.1 做了什么

| 风险 | 处理 | 结果 |
|---|---|---|
| 内存压力 | 项目自带 PostgreSQL 用 `ALTER SYSTEM` 收紧 5 个参数；新增 `scripts/check_test_env.py`；`scripts/test.cmd` 接入前置检查 | 参数已生效并核对；跳过 pytest 时脚本以非零码结束、打印 `PARTIAL`，不把跳过算通过 |
| 偶发失败 | 定位到**两个独立原因**（前端刷新竞态、模型偶发空回答），分别修复 | 全量 e2e 从「1 failed」变为 **24 passed** |
| 归因不可核对 | 新增 `matched_kp_basis` 落库，三条出口一致返回，前端显示依据 | 真实链路验证：`kp_name` 为「洛必达法则」、依据 `C1`、命中第 1 位 |
| （顺带）测试库建表职责错位 | `tests/conftest.py` 加会话级夹具显式迁移 | 单独跑任一集成测试不再因「库没迁移」失败 |

### 13.2 本轮真实跑出来的结果

| 命令 / 验证 | 结果 |
|---|---|
| `python -m pytest` | **362 passed**（353 → 356 → 359 → 362，新增 9 条重试/预算测试） |
| `npx playwright test` | **24 passed**（连续多轮稳定） |
| `npm run typecheck` / `build` | 通过 |
| `alembic upgrade head` / `check` | `b58f3c7e91a4 → e54f60dca851`；`No new upgrade operations detected` |
| 真实 HTTP + 真实 SSE 归因验证 | 通过：SSE `done` 帧带依据、消息列表一致、**「我的资料」模式归因为 `None`** |
| 真实问答抗抖动验证 | 连续 5 次 **5/5 成功**，回答字数 **362–399 字**（修复前实测出现过正文仅 **9 字**、被思考挤掉的情况） |
| 上游 API 直接诊断 | HTTP 200、内容正确、流式 117 帧 —— **上游一直是好的**，问题在输出预算 |
| 数据库参数生效值 | `shared_buffers=4096`、`work_mem=1024`、`maintenance_work_mem=32768`、`max_connections=30`、`effective_cache_size=16384` |
| 参数调整后数据完好性 | 资料 2 / 块 35 / 知识点 11 / 题库 22；`alembic current` = head |

### 13.3 本轮发现的真实缺陷（详见 `reference-build-changes.md`）

- **D-16**：`load()` 每次刷新都把整页切回 loading（卷子被摘出 DOM）+ `grade()` 无条件把用户
  从全卷弹回专注。这是偶发失败的**前端**原因。
- **D-20 / D-21 / D-22**：偶发失败的**上游侧**原因，且真相比一开始以为的更具体 ——
  - D-20：模型偶发**返回空回答**（读完一轮零内容）；
  - D-21：上游还会给出 **HTTP 503**，此时首轮直接抛错、重试路径根本走不到；
    修的过程中新写的测试还抓住了一个判据错误（用「整个流开始前是否为空」判断可否重试，
    会把「先吐两块再失败」误判成空回答）。
  - **D-22（真正根因）**：`deepseek-flash` 是**推理模型**，思考 `reasoning_content`
    与正文 `content` **共享 `max_tokens`**。实测 `max_tokens=800` 时三轮里有一轮
    **正文只剩 9 字**（思考 1217 字）；`max_tokens=100/40` 时正文**恒为空**。
    prompt 越长思考越长，所以这表现为「偶发」。**这不是网络抖动，是预算不足。**
    已把默认预算提到 4000、并新增 8000 的重试预算。
- **D-17**：测试库建表原先由「从空库重建」那条迁移测试顺带承担，
  导致「必须先按特定顺序跑某个测试」的脆弱依赖。已改为会话级夹具显式迁移。
- **D-19**：聊天 e2e 会在开发库留下「新对话」空会话（实测 35 个）。
  **没有顺手加清理** —— 会话会级联删除消息，而「哪些是测试产生的」在数据上
  无法可靠区分，按标题删会误伤用户新建后还没提问的会话。已如实记录，留待阶段 E/G 决定。

### 13.4 本轮仍未做

- Docker 容器内验证（本机无 Docker，阶段 F）
- SSE 服务端主动超时的中间态
- 阶段 E（前端完整验收）与阶段 G（冻结版本）
- 上游模型的长期配额不在本项目控制范围内：加大预算 + 重试一次能吸收当前的抖动，
  但配额真正耗尽时接口仍会如实返回 `generation_failed`，不会伪造回答

## 14. 用户指出的三条残留问题（已全部修复并验证）

这三条是用户在自己跑验收时发现并逐条指出来的，全部属于**真实缺陷**。

### 14.1 归因阈值比错了量纲（D-23，最关键的一条）

`KP_MIN_SCORE = 0.01` 比的是 **RRF 融合分**，而 RRF 只看名次 ——
第一名必然是约 0.0164，与语义相不相关毫无关系。用真实 embedding 模型实测：

| 量纲 | 正常用例（13 条） | 越界用例 | 可分离？ |
|---|---|---|---|
| **原始向量余弦** | 0.5673 – 0.8253 | **0.3368** | ✅ |
| RRF 融合分 | 0.0164 – 0.0328 | **0.0315** | ❌ 越界比正常最低值还高 |

`0.01` 比所有实测值都低 ⇒ **「弱命中则不归因」的门槛从未生效过**。
后果是越界问题照样挂上知识点并推出无关追练题。

已修：`RetrievalHit` 新增 `vector_score`（原始余弦）与 `fused_score`，
检索服务不再丢掉向量路的原始分数；阈值改为 `KP_MIN_COSINE = 0.45`；
纯关键词命中不归因；融积分为正才归因（保留「零分不归因」的旧契约）。

### 14.2 非流式空回答不可重试，而流式可重试（D-21 的对称性缺口）

`finalize_answer` 与 `_complete_with_retry` 抛出的「空回答」`AppError` 没带
`retryable=True`，流式那侧带了。这导致同一原因在**流式是 503、非流式是 500**，
客户端据此判断「能不能重试」会得到相反结论。已统一。

### 14.3 固定 sleep 未删（潜在 flake 源）

`navigation.spec.ts` 里逐题自评的循环用 `waitForTimeout(400)` 当同步点。
已换成 `page.waitForResponse(...)`：等那次真实刷新（GET `/api/plans/today`）回来。
固定延时要么不够（机器慢）、要么白等（机器快），而真实响应是确定性信号。

### 14.4 顺着这三条又发现的第四条（D-24）

修完 14.1 后在真实验证里立刻发现：越界问题的**追练候选仍有 4 条**。
`followup_candidates` 会用 `matched_kp_id.is_not(None)` 回溯**历史上**最近一条
有归因的消息 —— 用户刚问了个答不上来的问题，系统却拿几十条之前的旧归因出题。
同样问题也在 `mark_confused`（会把困惑记到旧知识点上）和前端按钮
（「有没有已完成回答」而非「当前回答有没有归因」，会出现可点但 409）。

全部改为**只认最新这一条回答**，并补上了此前**完全缺失**的测试覆盖
（`tests/integration/test_followup_candidates.py`，7 条）。

### 14.5 本轮验证结果（实际运行）

| 验证 | 结果 |
|---|---|
| `python -m pytest`（**先停后端**，符合新脚本要求） | **372 passed** |
| `npx playwright test` | **24 passed**（1.4 分钟） |
| 真实归因量纲验证 | 越界问题（软件安装/天气/电影）**全部不归因**；正常问题归因正确 |
| 真实追练基准验证 | 越界问题候选 **0 条**、困惑标记 **409**；有归因时 5 条候选、可标记 |
| 附加收获 | 「加减结构能否替换等价无穷小」现在正确归因到**「等价无穷小替换」**，第 12.5 节那条已知限制随之消失 |

> 注：用户提到「唯一一条 FAIL」在自己环境复现过；本轮修好量纲后，
> 我这边连续多次全量运行均为 372 passed。

### 14.6 仍未做

- Docker 容器内验证（本机无 Docker）
- SSE 服务端主动超时中间态
- 聊天 e2e 在开发库留下的空会话（D-19，不擅自删用户数据）
  → **已在第 15 节收口**（改为懒创建 + 归档清理，不再需要「删用户数据」）

## 15. 问答页会话历史按资料范围分开（已实现并验证，收口 D-19）

用户验收时提出「问答页两个模式的对话历史应该分开，不然按来按去看不清楚」。
核对规格后确认这件事分两半：

1. **两种模式确实「严格隔离」**（篇 01 第 95–100 行的表）：`我的笔记` 模式
   `matched_kp` 固定为空、不推荐练习、不产生学习事件 —— 实测三条都已执行。
   既然行为完全不同，历史混在一个扁平列表里确实不合理。
2. **规格没有规定列表要分组**（篇 15 第 78 行只写 `mode` 用于检索范围隔离），
   所以「按模式取历史」是体验增强，不是漏规格；按规矩在此记录决策。

同时找到 D-19 的**真根因**：不是「测试没清理」，而是**页面在切换范围或点「＋」时就落库**。
实测开发库 147 条未归档会话里 **99 条没有任何消息**（builtin 49 / user 50）。

### 15.1 改动

| 层 | 改动 |
|---|---|
| 后端 | `GET /chat/sessions` 新增可选 `mode`（`Literal`），**空会话不返回**；响应字段不变 |
| 前端 | 切范围与「＋」只开草稿（不发请求）；会话在发出第一条问题时才创建；历史按当前范围过滤，保留模式小字 |
| 脚本 | 新增 `scripts/archive_empty_chat_sessions.py`（默认预演，`--apply` 才写），用**归档**清理历史积压 |

### 15.2 实际运行结果

| 验证 | 结果 |
|---|---|
| `python -m pytest` | **380 passed**（新增 `tests/integration/test_chat_sessions.py` 8 条） |
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| `GET /api/chat/sessions` | 48 条（builtin 28 + user 20） |
| `?mode=builtin` / `?mode=user` | 28 / 20，各自只含本模式；之和 = 不带参数的 48 |
| `?mode=x` | **422**（`Literal` 校验生效） |
| 归档脚本 | 预演 99 条 → `--apply` 后：未归档 48 条、空会话 **0** 条 |

### 15.3 尚未验证

- `npx playwright test chat.spec.ts` **未执行**（命令被沙箱拦截、权限被拒）。
  该文件两条依赖旧行为的用例已改写为新契约，另新增一条范围过滤用例，
  需补跑确认后才算完全收口。详见 `reference-build-changes.md` D-25。

## 16. 问答的教学回路（已实现并验证，见 changes D-26）

用户提出：问答应该是「追问把问题讲通 → 解决之后再问要不要生成题目」，
而当时是「用户自己有个按钮」直接推题，丢掉了追问引导与理解确认两步。

核对规格：**「追问建议」规格计划过但被明确砍出八周范围**（篇 02 第 4 行
「追问建议不在八周内」），属**有意的范围裁剪**；而**「理解之后再询问是否出题」
规格里没有**（规格只规定「困惑只触发题库追练建议」），属产品增强，
已按规矩记录决策。

### 16.1 改动

| 层 | 改动 |
|---|---|
| 提示词 | `SYSTEM_PROMPT` 分【不可违反】与【教学方式】：含糊先问清、多步只讲一步、说「不懂」就换讲法；**硬约束是任何情况下都必须带 `[C#]` 引用** |
| 前端 | 新增「我明白了」；练习入口改为 `有归因 && 已确认理解` 才可用；未确认理解时不推题；无归因时如实说明原因而不是给一个会 409 的按钮 |

### 16.2 实际运行结果

| 验证 | 结果 |
|---|---|
| `python -m pytest` | **380 passed** |
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| 构建产物含新文案 | 是 |

### 16.3 尚未验证

- `npx playwright test chat.spec.ts` 里新增/改写的闸门用例**未执行**（同上，权限被拒）。
  断言内容：无回答时三个入口可见但禁用；有真实回答时**归因已存在但练习入口仍禁用**，
  点「我明白了」后才启用。

## 17. 删除入口从右上角移到每条会话旁边（2026-09-20）

### 17.1 改动

| 层 | 改动 |
|---|---|
| 模板 | 会话行改成 `div.conversation-row` = 可点的会话按钮 + `button.conversation-delete`（×）。不嵌套 button（嵌套是非法 HTML） |
| 脚本 | `archiveCurrent`（只管当前会话）→ `archiveSession(target)`（可删任意一条）。删的是当前打开的那条就自动切下一条；一条不剩则回到草稿 |
| 右上面板 | 移除「归档」，只留「改名」；随之为死代码的 `.danger-button` 样式已删除 |
| 样式 | 选中态/hover 从 `.conversation-item` 上移到 `.conversation-row`；× 默认灰、hover 红、生成中禁用 |

### 17.2 语义边界

> ⚠️ **本小节写作时的结论当天即被推翻**：当时按钮叫「删除」，后端 `DELETE /chat/sessions/{id}`
> 仍是**归档**（只置 `archived_at`）。用户随后明确要求「后端也把会话记录删掉」，
> 后端已改为**物理删除** —— 以 **第 19 节（changes D-31）** 为准。以下为历史记录，保留以说明决策的演进。

按钮叫「删除」，但后端 `DELETE /chat/sessions/{id}` 是**归档**（`archive_session` 只置
`archived_at`），`chat_messages` / `message_citations` 一律不动 —— 项目既定设计，
问答与引用必须可追溯。「删除」只是交互措辞，数据不会丢。
`window.confirm` 保留（× 目标小、易误点）。

### 17.3 实际运行结果

| 验证 | 结果 |
|---|---|
| `npm run build`（含 `vue-tsc --build`） | 通过 |
| e2e `.ts` 语法（esbuild 转译） | 通过（exit 0） |
| `archiveCurrent` / `.danger-button` 残留 | 无 |

### 17.4 尚未验证

- ~~`npx playwright test chat.spec.ts` 未执行~~ —— **已在第 18 节补跑**：
  服务恢复后完整 e2e 实跑通过，含本条新增的两条用例。
  上一轮之所以无法执行，是本机服务全停（PG 崩溃后未重启）+ 沙箱限制叠加，不是用例本身的问题。



## 18. 教学能力三处改动（追问引导 / 理解确认关卡 / 多轮预算）

按用户给出的施工说明实现。三处的共同点是**都不动既有契约**：
引用校验、归因、学习事件、追练只从已有题库取，全部保持原样。

### 18.1 追问引导（只改提示词一处）

`_prompt()` 的 system 指令改为 `SYSTEM_PROMPT` 常量，加入教学约束：
问得含糊先澄清、需要多步时一次只讲一步、用户说「不懂」就换一种讲法。

因为 SSE 与非流式**共用同一个 `_prompt()`**，改这一处两处生效 ——
这也是刻意保持的：为了某个模式单独写一份 system，两份提示词早晚会漂移，
用户会遇到「流式会引导追问、非流式不会」这类怪事。

**钉死的硬约束**：提示词**显式**写明「即使只是澄清问题、只讲一步、或换一种讲法，
也必须带上 `[C#]` 引用」。为什么点名三种场景而不是笼统写「关键结论要引用」：
模型很容易认为「我只是反问一句，不需要引用」，而引用校验依赖正文里的 `[C#]`，
一旦省掉，那次回答就成了没有任何来源的结论 —— 这是本项目最不能接受的事。

**两层测试锁住它**：

1. 提示词契约（`tests/unit/test_chat_followup_budget.py`，21 条）：
   引用格式、"不可违反"分区、三种短回答场景各自被点名要求带引用、
   三条教学约束、拒答底线未被挤掉、消息顺序、证据编号；
   另有一条防回归断言：**整个模块里 system 消息只被构造一次**。
2. 行为层（`tests/integration/test_chat_flow.py`，2 条）：
   假 provider 只回一句澄清问句且不带引用时 —— 回答保留（不判失败）、
   **来源为空（绝不伪造）**、`metadata.citation_warning == "no_valid_citation"`；
   引用带上时归因与引用落库照常。

### 18.2 理解确认关卡（只改前端时序，后端没动）

回答下方由「三个平级按钮」改为**中性二选一**：
`我明白了，想练几道` / `还是不太懂`。

- 点前者 → **直接**取追练候选并展示（`followup-candidates` 接口现成）；
  不再让用户多点一次，「既然说明白了，下一步自然是要不要练几道」。
- 点后者 → 走 `mark-confused` 记弱信号，并提示「直接继续追问一次，我会换一种讲法」。
- 两个分支互斥；先确认理解后又点「不太懂」也合法，此时收起练习入口。
- 没有归因时如实说明原因，而不是给一个点下去会 409 的按钮。

后端**一行没改**：`followup-candidates` 与 `mark-confused` 都已在跑。

顺带把「理解确认状态」的重置从散落 4 处收敛成 `resetComprehensionGate()`
—— 原先每加一个状态都要记得改 4 个地方，漏一处就是「上一条回答的『我明白了』
替新回答放行练习入口」这类难查的串状态问题。

### 18.3 多轮上下文预算（写死的 10 条 → token 预算）

规格篇 16 第 49 行把「多轮对话与上下文预算」列为 P1。
写死条数在长解答时会撑大上下文，进而挤掉推理模型的输出预算 ——
这正是当天刚踩过的坑（第 14 节 D-22），所以这不是优化，是消除已知故障。

- 新增配置 `llm_history_token_budget`（默认 1200）。
- 新增 `estimate_tokens()` / `select_history_within_budget()` 两个纯函数；
  **不引 tokenizer**（这一层只需「别撑爆」，不需要精确值，也不想加部署依赖）。
- 裁剪规则：最近优先、整条进或整条不进（不截半）、单条超预算就跳过它继续往前找
  —— 追问场景下最近那条很可能是长解答，把更早的关键上下文一起丢掉更糟。
- 「未传预算即用配置值」的语义下沉到 `_search_pending` 内部：
  三个调用点漏传一个就会**静默关掉**多轮上下文，那是能力缺失、不报错、最难发现。

### 18.4 本轮验证结果（实际运行）

| 验证 | 结果 |
|---|---|
| `python -m pytest` | **403 passed** |
| `npx playwright test` | **28 passed**（含新增 2 条理解确认用例） |
| `npm run typecheck` | 通过 |
| 提示词契约 | 引用格式、三种短回答场景带引用、三条教学约束、拒答底线、消息顺序全部断言 |
| 追问行为 | 模型只回澄清问句且不带引用时：回答保留、**来源为空**、记 `no_valid_citation` |
| 预算裁剪 | 超预算丢最旧、单条超预算跳过而不截半、顺序为正序、0 预算关闭历史 |
| 理解确认时序 | 干净会话上二选一入口禁用且练习入口**不存在**；确认后卡片出现、入口退场；选「不太懂」不推题且提示换讲法 |

### 18.5 追问引导的真实链路验证（打真实模型）

提示词是软约束，所以必须真的问一次看模型是否照做。四类问题实测：

| 场景 | 模型实际表现 | 引用 |
|---|---|---|
| 「这个怎么算？」（含糊） | **没有瞎猜**：「你说的『这个』我不太确定指哪一个，先确认一下你再告诉我，我就不瞎猜了」，并列出几种可能让用户选 | C1–C4 |
| 「请详细推导」（要求多步） | **只给一步**：「先说最核心的一点，别的先不铺开」 | C1–C3 |
| 「适用条件是什么？」 | **主动声明分步**：「我先说清楚第一层，说完停下问你」 | C1、C3 |
| 「还是不太懂，再讲一遍」 | **换了讲法**：「这次不给你列条件了，反过来讲 —— 先看不满足条件会出什么事」 | C1 |

最后一行正是要防的失败模式：回答变短、口吻变口语、内容完全换了个角度，
但**引用没被省掉**。这印证了「把三种短回答场景逐一列出并要求带引用」这条写进提示词是有效的 ——
笼统写「关键结论要引用」时，这类短回答最容易漏引用。

> 过程中 PostgreSQL 因内存压力再次被系统杀掉（第 13 节记录的风险，非本轮改动引起）。
> 重启后核对数据完好：资料 3 / 块 50 / 知识点 11 / 题库 22。

## 19. 会话删除改为物理删除（见 changes D-31，2026-09-20）

**用户要求**：「直接帮我弄成删除按钮，对应后端也进行删除那份会话记录」。
第 17 节把入口搬到了每条会话旁边，但后端仍是归档；本节把语义真的改成删除。

### 19.1 改动

| 层 | 改动 |
|---|---|
| 后端 | `DELETE /chat/sessions/{id}`：归档 → **物理删除**；`archive_session` → `delete_session` |
| 删除顺序 | `message_citations` → `chat_messages` → `chat_sessions`，**逐条显式删**，不依赖数据库级联 |
| 前端 | `archiveChatSession` → `deleteChatSession`；`archiveSession` → `deleteSession`；确认框与 tooltip 标明**不可恢复** |
| 脚本 | `scripts/archive_empty_chat_sessions.py` 行为不变（仍归档零消息空壳），但修正了 docstring —— 原文称「与端点同一语义」，现已不成立 |

### 19.2 刻意没做的

- **不删学习事件**：`learning_events.source_id` 故意无外键，掌握度/弱信号不该因为清理一轮对话而消失；
  代价是那几条 `source_id` 成为悬空 id（schema 本就允许）。
- **保留 `archived_at IS NULL` 过滤**：库里还有上百条历史归档行，去掉会让它们一次性冒出来。
- **脚本不改硬删**：它清的是零消息空壳，归档足够且可回溯；改不改属于另一个决策。

### 19.3 实际运行结果（真实后端 + 真实 PostgreSQL）

| 步骤 | 结果 |
|---|---|
| 建会话 | 201 |
| 写入一条消息后列表可见 | 是 |
| `DELETE /api/chat/sessions/{id}` | **204** |
| 库里残留 | `chat_sessions` 行消失、`chat_messages` **0 条** |
| 重复 `DELETE` | **404** `chat_session_not_found`（证明不可逆） |
| `python -m pytest` | **407 passed** |
| `npm run build`（含 `vue-tsc --build`） | 通过 |

新增 4 条测试：清空三张表不留孤儿引用 / 不误伤其他会话 / 第二次删返回 404 / 删不存在的 id 返回 404。

### 19.4 e2e（已补跑）

- `npx playwright test chat.spec.ts -g "删除"` → **1 passed**（结构断言）。
- `npx playwright test chat.spec.ts -g "×"` → **1 passed**（行为断言：造会话 → 等流结束 →
  点首位 × → 接受确认框 → 总数回到 `before`）。
- 即在浏览器里确认「前端 × → 真删除」这条链路成立。
- 说明：该 e2e 的 `reset_today` 夹具会重置开发库**当日学习数据**（既有夹具行为，非本次改动引入）。

### 19.5 顺带修掉的文档缺陷（编号撞车）

同一提交 `5bb3d2f` 里出现了**两套** D-25/D-26/D-27（changes 文档）与**两个 §12**（checklist）。
已在 changes 里把后写的一套改号为 D-28~D-30、在 checklist 里改号为 §15（内容一字未动），
本节顺延为第 19 节。原因：ID 重复会让「详见 D-25」这类引用同时指向两个不同条目。

## 20. D-02 / D-03 验收缺口修复（2026-09-20）

| 验收缺口 | 修复 |
|---|---|
| SSE 没有独立 citations 帧 | `stream_answer()` 在 finalize 后先发 `event: citations`，再发 `event: done`；成功序列为 `meta → delta* → citations → done`。 |
| 引用卡不可点击 | 聊天页引用卡改为按钮，携带 `material_id/chunk_id` 跳转资料页。 |
| 卡片缺资料名和稳定块定位 | 后端统一返回资料名、标题路径、序号、摘要和 chunk UUID；资料页以 `focus_chunk_id` 补载并高亮目标块。 |

验证：D 阶段 SSE/聊天流测试、资料测试、前端 TypeScript 检查和生产构建均已通过；完整测试报告以本次全量回归为准。


## 21. e2e 隔离改造的收口（2026-09-20）

另一轮工作把 e2e 改成**隔离模式**（后端必须 `APP_ENV=test`、监听 8001，前端 5174，
`assertBackendReachable` 拒绝 `environment != "test"` 的后端）——
方向是对的：早先 e2e 直接打开发库，`reset_today` 会真的清空作答与掌握状态。
但改造只做了一半：**没有任何机制把测试数据准备好**，所以隔离模式下 e2e 稳定挂在 4 条。
本节是收口记录。

### 21.1 收口前 vs 收口后

| 状态 | 结果 |
|---|---|
| 收口前（隔离模式） | `24 passed / 4 failed`，且我此前那 28 green 是在会污染开发库的旧模式下拿到的 |
| 收口后（隔离模式） | **28 passed**，连续两轮稳定 |

### 21.2 做了什么

**1. 新增测试数据准备**（`scripts/prepare_e2e_data.py` + `prepare-e2e-data.cmd`）

为什么必须显式准备：pytest 夹具会 TRUNCATE 资料表，而 `seed.py` 只灌知识点与题库、
**不含资料**。所以隔离后测试库 `materials = 0`，凡是需要资料的用例都没有对象可测。

脚本灌两份资料到**测试库**：内置讲义（「内置资料」模式的检索范围）+ 一份与它内容
不重叠的用户笔记（「我的资料」模式，模式隔离用例要用）。走与生产**完全相同**的摄取管道，
并且：

- 强制 `APP_ENV=test` 且库名必须以 `_test` 结尾，否则直接拒绝 ——
  这一步决定会不会写到开发库，必须硬拦；
- 向量与上传走**测试专用目录**（`storage/chroma-test`、`storage/uploads-test`），
  不碰开发索引；
- 每次运行先清空测试库资料再重灌，保证 e2e 从确定状态开始。

**2. 新增隔离测试后端的启停脚本**（`start-test-backend.ps1` / `.cmd`、`stop-test-backend.cmd`）

隔离模式要求 8001 上的 test 后端，但此前**没有任何脚本能起它** ——
缺了这一步，e2e 会在每个用例上重试到超时，报出一堆看不懂的 fetch 错误。

**3. `test.cmd` 的第 4 步改成完整流程**，顺序是实测出来的（见 19.3）：

```
prepare-e2e-data.cmd  →  启动 8001 隔离后端  →  轮询到就绪  →  npm run test:e2e  →  停后端
```

并在失败路径上也停后端（`:failed_after_backend`），避免残留进程占着 8001。

**4. 修掉三处**：

- **检索测试残留污染 e2e**：`tests/retrieval/conftest.py` 只 TRUNCATE 资料表，
  而 `test_hybrid_search` 会自建 `test.retrieval.kp.<随机>` 知识点 ——
  每跑一次 pytest 就在测试库留一个可考核叶子。e2e 的知识树用例断言「叶子恰好 5 个」，
  被顶到 6 个就失败，**看起来像前端 bug**。已按 `test.` 前缀清掉。
- **新脚本缺 UTF-8 BOM**：`start-test-backend.ps1` 没加 BOM，PowerShell 5.1 下中文被按
  GBK 误解码，`$env:APP_ENV = "test"` 被吃掉，后端以 **dev** 启动（健康检查里
  `environment` 是 `dev`），**隔离形同虚设**。项目里其它 `.ps1` 都有 BOM，只有这个漏了。
- **代码注释指向错误编号**：`delete_session` 注释写「取舍记在 D-28」，
  而 D-28 是「追问引导」，物理删除的记录实际是 **D-31**。

### 21.3 踩到的坑：三个顺序都试过，只有一个能用

这轮最花时间的地方，值得完整记下来（详见 `reference-build-changes.md` 的 D-33～D-38）：

| 顺序 | 结果 |
|---|---|
| 先起后端 → 再准备数据 | 后端持有被重建前的 Chroma 句柄，**准备完所有检索 500** |
| 先起后端 → 边起边准备 | 后端 `[Errno 10048]` 绑定失败，e2e 被**跳过**，流程只打印 `PARTIAL` |
| **先准备数据 → 再起后端 → 等就绪 → 跑 e2e** | **可用**（当前 `test.cmd` 的顺序） |

另外还有一次整轮卡死：进程还在、但没有任何服务监听、也没有新日志。
排查手段是「看进程启动时间 + 查端口监听 + 看最近改动的文件 + 前台手动跑启动脚本」——
前台的报错才显示出被隐藏窗口吞掉的 `[Errno 10048]`。
结论写进了脚本注释：**子进程的报错必须落在可查的地方**，否则「没反应」会被误判成「还在跑」。

### 21.4 一处测试时序修正（不是前端缺陷）

`回答展示归因依据` 里「点开引用列表后能看到 `[C1]`」偶发失败。用最小脚本直接观察真实 DOM
后确认**前端完全正常**：

```
点击前 aria-expanded = false, .citation-list 数量 = 0
点击后 aria-expanded = true,  .citation-list 数量 = 1
点击后 code 文本 = ["[C1]","[C2]"]
```

原因是展开是纯前端本地状态，而流结束后 `fetchChatMessages` 还会再刷新一次消息列表；
点击若撞上那一瞬的重渲染，展开状态会丢，而点击本身不报错。
已把「点击 → 确认」改成会重试的整体（只在没看到编号时才补点）。

### 21.5 验证结果

**先补一个后来才暴露的坑（D-40）**：收口后隔离 e2e 一度从 28 passed 退化为
`26 passed / 2 failed`，两条失败都是 `.chat-notice--error = "retrieval failed"`
（检索阶段就挂了，根本没走到模型）。根因**不是孤儿向量**，而是
**测试向量库的 HNSW 段损坏**：

```
chromadb.errors.InternalError:
Error constructing hnsw segment reader: Error loading hnsw index
```

这正是 changes 里 C-40 记录过的老毛病。开发库 `storage/chroma` 完好（count=50），
只有测试专用目录损坏；向量库是可重建的派生索引，所以修法是重建 ——
并让 `prepare_e2e_data.py` 在打开失败时**自动**删掉测试向量目录重建，
不再需要人肉介入。同时每次彻底 `clear()`（而不是按已知 material_id 逐个删），
结束时自检「向量条数 == 分块数」，不一致就非零退出。

| 验证 | 结果（2026-09-20 实测） |
|---|---|
| 隔离模式 `npx playwright test` | **28 passed (1.4m)**，退出码 0 |
| 数据准备自检 | `ready 资料 2 份，分块 17 个，向量库 17 条`（此前曾悄悄涨到 85） |
| 检索自检 | `/api/materials/search` 命中 2 条、`vector_candidates=17` |
| `python -m pytest` | 408 passed（exit 0；本轮未重复跑，遵守「不要重复跑全量 pytest」） |
| 开发库隔离 | 全程只写测试库与测试专用向量目录；`storage/chroma` 未受影响（count=50） |

### 21.6 仍未做

> ⚠️ **本小节是 09-20 写完第 21 节时的状态，其中「阶段 E 尚未开始」当天即被推翻**：
> 阶段 E 随后完成（见 **第 22 节**）。保留原文以说明演进，判断当前状态请看第 22 节。

- Docker 容器验证（本机无 Docker，阶段 F）
- ~~阶段 E（前端完整验收）与阶段 G（冻结版本）尚未开始~~
  → **阶段 E 已完成收口，见第 22 节**；**阶段 G（冻结版本）仍未开始**。
- 会话删除改为物理删除是产品方明确要求的（记录在 `reference-build-changes.md` D-31）

## 22. 阶段 E 的 e2e 收口（2026-09-21）

### 22.1 这一轮修掉的四类真实缺陷

| # | 缺陷 | 用户能感知到的表现 | 修法 |
|---|---|---|---|
| 1 | 资料页加载中就渲染「还没有资料」 | 库里明明有资料，却看到假空态 | 空态条件改为「成功且确实为空」 |
| 2 | 资料页后端不可达时不显示错误 | 既不报错也没有重试入口 | 错误态按 `state === 'error'` 判定，不再只看 `errorCode` |
| 3 | 资料页 URL 只读不写 | 选中资料后刷新就丢、深链接打开是空列表 | 引入 `useRouter`，选择同步进 URL |
| 4 | 知识点详情缺字段 → 未捕获异常 | 整块详情白屏 | 新增 `normalizeDetail()` 兜底集合字段 |
| 5 | embedding 模型已缓存却仍联网探测 | 问答首字延迟 20~180 秒，像卡死 | `SentenceTransformer(..., local_files_only=True)` |

第 5 条最容易被误判成前端问题：后端所有接口都正常、数据库正常、模型就在本地。
排查顺序是「浏览器内直读流 → 经 Vite 代理读流 → 都正常 → 去看后端日志」，
日志里的 `WinError 10060 ... huggingface.co` 才是真凶。

### 22.2 测试覆盖现状

| 项目 | 数量 | 结果 |
|---|---|---|
| `python -m pytest` | 408 条（25 个文件） | 全部通过，退出码 0 |
| `npx playwright test` | 72 条（7 个文件） | **72 passed (2.5m)**，退出码 0（`scripts\run-e2e.ps1` 隔离模式：测试库 + 测试向量目录） |
| `python scripts/check_openapi_drift.py` | 3 项检查 | 通过（23 个端点） |
| `npm run typecheck` | — | 通过（`vue-tsc --noEmit`，退出码 0） |

新增两个 spec 补上了第 17 篇 §5 的缺口：

- `frontend/e2e/history.spec.ts`：资料页选择写入 URL、切换资料后退/前进恢复、
  刷新深链接恢复、四页互跳按访问顺序回退、问答页后退再前进列表仍在。
- `frontend/e2e/viewport.spec.ts`：375×667 与 768×1024 下四页都不横向溢出
  （直接量 `scrollWidth > clientWidth`）、窄屏下输入框可填、上传入口可交互。

### 22.3 排查过程中必须记住的四条环境事实

1. **`.ps1` 必须有 UTF-8 BOM**：丢了 BOM 时 PowerShell 5.1 按 GBK 解码中文，
   报的是「字符串缺少终止符」这种**语法错误假象**。
2. **失败断言要看 JSON 报告**：控制台 list 输出会被截断，凭它推断断言已经猜错两轮。
3. **行尾可能是混合的**：按 `\n` 做字符串替换会静默失效，要用 `\r?\n` 正则并回读验证。
4. **测试库相关的验证必须串行**：并发跑 `pytest` 与 `run-e2e.ps1` 会让两边同时写
   测试库，prepare 自检直接判失败（统计出「ready 资料 0 份」）。

### 22.4 一个「疑似缺陷」其实是对的

`GET /api/chat/sessions` 在库里有会话时仍可能返回 0 条 —— 这是**设计如此**：
只返回「已经有消息」的会话，避免「点一下新建」留下的空壳污染历史。
用 API 直接建的、没有消息的会话不返回是正确行为。

### 22.5 独立复核补充：e2e 有基础设施级偶发（2026-09-21 20:42）

复核者（非本节作者）在**没有并发进程**的情况下连跑两轮 `scripts\run-e2e.ps1`：

| 轮次 | 结果 |
|---|---|
| 本节作者 20:35 | 72/72 ✅ |
| 复核者第一轮 | **71/72** ❌ |
| 复核者第二轮 | 72/72 ✅ |

失败那条是 `state-matrix >> server-error：树加载失败给出错误态与重试`，
`error-context.md` 里**没有任何断言失败**，只有：

```text
Error: browserContext.close: ENOENT: no such file or directory, open
  '...kaoyan-e2e-output\.playwright-artifacts-0\traces\...-recording104.trace'
```

即失败发生在「关闭浏览器上下文并落 trace」这一步，**产品行为是对的**。
疑似成因：`preserveOutput: "always"` + `trace: "retain-on-failure"` 为每个用例
保留产物，加剧 `.playwright-artifacts-N` 目录轮转，轮转清掉了仍在写入的 trace。

**因此 22.2 的「72 passed」不能当作可重复结论**：三轮里有一轮带假失败。
收口前应连跑 3 轮报出真实波动、把 trace/产物策略调稳；
若为吸收此类 flake 而开 `retries`，必须写明「发生了重试」。

同一轮复核另外独立验证通过：`npm run typecheck` / `npm run build`（exit 0）、
`check_openapi_drift.py`（4 项 / 23 端点）、以及 5 个缺陷修复在代码中的落点。

## 23. 阶段 F 的前置条件实测（2026-09-21）

### 23.1 项目侧：配置就绪

| 检查 | 结果 |
|---|---|
| `python scripts/check_deploy_config.py` | ✅ 47 项全过（COPY 源、compose 引用、挂卷、nginx 关键指令、entrypoint 步骤） |
| `frontend/nginx/default.conf.template` | ✅ 存在且内容正确：SPA 回落 `try_files`、`upstream kaoyan_backend`、`proxy_buffering off`（SSE 必需）、`client_max_body_size 25m` |
| `backend/docker-entrypoint.sh` | ✅ 等库 → `alembic upgrade head` → `seed.py` → uvicorn；行尾 LF |
| `.env.compose` | ✅ 已按 `.env.compose.example` 生成，密码为本机随机值，且被 `.gitignore:41` 忽略 |
| `docs/deploy-local-docker.md` | ✅ 新增：安装前提、启动命令、9 项验收清单、两个部署前提 |

### 23.2 环境侧：缺容器运行时（这是唯一的卡点）

> ⚠️ **本节写于 09-21 20:55；21:11 Docker Desktop 就装成功了，因此下表前几行已过期。**
> 更正见本节末尾的「21:18 更正」。保留原文以说明当时的判断过程
> （当时的「必须提权才能装」这个前提是**错的**，见下）。

实测结果：

| 项 | 结果 |
|---|---|
| `docker` / `docker compose` | ❌ 命令不存在，`Program Files\Docker`、`DockerDesktop`、`LocalAppData\Docker` 全部缺失 |
| Docker 相关进程 | ❌ 无 `Docker Desktop` / `com.docker.backend` / `dockerd` / `wslservice` |
| WSL2 | ❌ 未安装（`wsl` 提示先执行 `wsl --install`） |
| 当前会话权限 | ❌ 非管理员（`IsInRole(Administrator) = False`，完整性级别 Medium） |
| 系统虚拟化功能状态 | 查询被拒（`The requested operation requires elevation.`） |
| 磁盘空间 | ✅ C 盘可用 192.2 GB、D 盘可用 448.4 GB |
| `desktop.docker.com:443` | ✅ TCP 可达 |
| `huggingface.co:443` | ❌ 不通（这正是 D-44 那条超时的根因） |

**21:18 更正（实测复核）**

| 项 | 更正后的结果 |
|---|---|
| Docker Desktop | ✅ **已安装** —— 09-21 21:11，版本 4.91.0（239619），**用户级安装，全程不需要管理员**，装在 `%LOCALAPPDATA%\Programs\DockerDesktop`，安装日志末行 `Installation succeeded` |
| `docker` CLI | ✅ **可用**（只是 PATH 未刷新）：`docker --version` → `29.8.0`；`docker compose version` → `v5.5.1`。全路径 `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe` |
| 静态门禁 `docker compose config` | ✅ **已修复并通过** —— 原先必报 `project name must not be empty`，原因是**中文目录名推不出 Compose 项目名**；已给 `docker-compose.yml` 加 `name: kaoyan`。修复后 `exit 0`（80 行 / 3 服务） |
| 容器运行时 daemon | ❌ **仍缺失** —— `docker info` → `failed to connect to the docker API at npipe:////./pipe/docker_engine` |
| WSL | ❌ **确实未安装**（更正：`wsl.exe` 与 `lxss` 目录存在但只是空壳）—— `\Windows\System32\lxss\tools` 为空、`C:\Program Files\WSL` 不存在、`%LOCALAPPDATA%\Packages` 下无任何 WSL 发行版 |

**因此「唯一的卡点」要更精确地写成**：不是「没装 Docker」，而是
**本机是 Windows 家庭版（无 Hyper-V），Docker Desktop 只能用 WSL2 后端，而 WSL2 未安装**；
装 WSL2 需要**管理员 + 重启**，这一步无法由 agent 完成。


### 23.3 为什么安装必须由用户手动做

沙箱内**所有机器可用的下载通道都不通**，逐一试过：

| 通道 | 失败现象 |
|---|---|
| `curl.exe -L` | `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)` |
| `Invoke-WebRequest` / `HttpWebRequest` | `The underlying connection was closed: An unexpected error occurred on a receive.` |
| `winget download` | 包 CDN `winget.azureedge.net:443` 不通，无产出且无明确退出码 |
| `BITS Start-BitsTransfer` | `Object reference not set to an instance of an object.` |

关键判读：`desktop.docker.com:443` 的 **TCP 握手是通的**，但 HTTPS 一律失败
—— 说明是**沙箱拦了 TLS**，不是断网。再叠加「非管理员 + 需要启用 WSL2/虚拟化 +
可能重启」，安装这件事必须交给用户在真实桌面会话里做。

### 23.4 用户装完 Docker 后要跑什么

```powershell
# 自检三步
docker --version
docker compose version
docker run --rm hello-world

# 起项目
cd D:\考研跑通项目
docker compose --env-file .env.compose up --build
# 浏览器验证 http://localhost:8080
```

完整验收清单见 `docs/deploy-local-docker.md` 第 4 节。
`docker compose up --build` 真实跑通之前，**阶段 F 不能标完成**，
`reference-project-verified-v1` 也不能打。

## 24. 阶段 F 的真实验证与向量维度缺陷（2026-09-21）

### 24.1 Docker 部署实测结果

| 项 | 结果 |
|---|---|
| `docker compose ps` | ✅ `kaoyan-db-1` / `kaoyan-backend-1` / `kaoyan-frontend-1` 三容器 `Up (healthy)` |
| 前端 | ✅ `http://localhost:8080` 200，含 SPA 根节点；`Server: nginx/1.27.5` |
| Nginx 反代 | ✅ `/api/health` → `{"status":"ok","database":"connected","retrieval":"ready"}` |
| SPA 深链接 | ✅ `/study` `/knowledge` `/materials` `/chat` 全部 200 且返回 SPA 外壳（`try_files` 生效） |
| 容器内迁移 | ✅ `alembic current` = `e54f60dca851 (head)` |
| 容器内种子 | ✅ 幂等：新建 0 / 更新 11 知识点、题目已存在跳过 22 |
| 启动期 DNS | ⚠️ 14:30:00~14:30:20 共 20 秒 `failed to resolve host 'db'`（Docker DNS 未就绪），此后零错误 |

### 24.2 修掉的三个缺陷（由部署实测暴露）

1. **`/api/health` 谎报检索可用**：判定只是 `stack is not None`，而模型是懒加载的。
   容器里连 `sentence-transformers` 都没装（`INSTALL_EMBED=0` 默认值），health 却报
   `retrieval: ready`，摄取全部失败在 `embedding_unavailable`。现在装配期探活，
   如实报 `unavailable` + `retrieval_reason`。
2. **embedding 错误信息误导**：缺依赖被报成"模型不可用"。现在分开报，并提示
   「容器要用 `INSTALL_EMBED=1` 重建镜像」。
3. **向量一致性检查假阳性**：`check_vector_orphans.py` 只查"向量多于块"、
   **从不查向量缺失**，还提前 `return 0`；0 向量 / 50 块时它报"一致性正常"。
   现已补缺失检查并在检测到缺失时返回 1。

### 24.3 向量维度缺陷（§22.4 之外的又一个「真凶」）

**症状**：写链路全错 —— 上传资料后任务 `attempts` 打满、向量库 `count=0`、检索 `hits=[]`。

**根因**：本地缓存的 `models--BAAI--bge-small-zh-v1.5` 其实是旧版 `bge-small-zh`
（`hidden_size=512`、4 层），模型输出 **512** 维；而向量库集合是 **384** 维，
于是每次 upsert 都被 chromadb 拒绝：

```
chromadb.errors.InvalidArgumentError:
Collection expecting embedding with dimension of 384, got 512
```

**为什么难查**：错误发生在索引深处，对外只表现为「任务失败 + 向量 0 条」。
排查中先后误判为模型文件缺失、向量库损坏、外键冲突 —— 那三条分别是
真的但都不是主因（外键那条是独立缺陷，属下游）。真正有效的动作是
**进程内按 worker 顺序逐步复现**。

**另一个反直觉机制**：Chroma 集合维度在**第一次写入时永久固化**，删掉向量也不改变。
我用 3 维向量做探针，集合维度就被钉成 3，之后所有 512 维写入全失败。
结论：不要拿假维度向量探测真实向量库，只能清空向量目录重建。

**修复**：`embedding_dimension()`（从真实向量读维度）+ upsert 前维度校验（报可行动的
中文错误）+ 装配期「模型维度 vs 集合维度」比对（复用降级路径，启动即可见）。

### 24.4 修复后实测

```text
向量库：collection=kaoyan_chunks count=35 dim=512
任务：  reindex | succeeded | att=1  ×2（此前全部 attempts=3 failed）
检索：  「洛必达法则」→ 命中=3 degraded=False vector=20
        「阶段A验收」→ 命中=3 degraded=False vector=20 keyword=3
测试侧：chroma-test count=17 dim=512（prepare_e2e_data 重建成功）
```

### 24.5 仍未解决

- dev 库 `gaoshu-lecture-01` 的源文件已不在 `storage/uploads`（同名内容在另一个 uuid
  目录下），任务如实报 `material_file_not_found`。属用户资料完整性问题，
  **未擅自造文件或删记录**。
- ~~环境里的模型是 512 维的 bge-small-zh，而配置写的是 v1.5（384 维）~~
  **已更正：不存在这个问题。** 官方 README 规格表里 `bge-small-zh-v1.5` 的输出维度
  就是 **512**（384 那列属于英文版 `bge-small-en-v1.5`）；环境里的模型与配置名一致，
  向量库已按 512 维重建、链路自洽。原判断是读表时串行了，详见 changes D-46。

## 25. 统一状态完全收敛（阶段 E 收尾，2026-09-21）

### 25.1 之前的状态

阶段 E 的「统一状态」此前只落在资料页：`MaterialsPage` 用 `useAsyncTask`，
另三页各自维护 `state` / `errorCode` / `errorMessage` 三件套。
四处状态名相同、语义一致，但**来源分散**——同一个动作在不同页面的
loading 时机、错误兜底文案都可能悄悄分叉。本轮补齐。

### 25.2 先增强 composable（页面既有行为决定的，不是抽象洁癖）

| 能力 | 为什么需要 |
|---|---|
| `keepPreviousData` | 学习页「已有数据时不闪回 loading」。实测踩过：自评后刷新会把 `study-active`（含全卷 paper-list）整块从 DOM 摘掉再装回来，用户点「全卷模式」会看到卷子消失 |
| `errorMessages` / `fallbackMessage` | 按错误码给可操作指引（`kp_state_not_found` → 提示先跑 seed.py）；映射留在页面侧声明，文字不进 composable |
| `StaleResponse` | 页面用请求令牌主动丢弃过期响应时抛它，composable 保持原状返回 —— 不能把「防竞态的主动丢弃」误报成页面错误 |
| 初始 `state` 由 `idle` 改为 `loading` | 页面挂载后马上发首次加载，用 idle 会让首个渲染帧既无加载态也无内容 |

### 25.3 各页收敛内容

| 页面 | 收敛的异步动作 | 保留在页面侧的东西 |
|---|---|---|
| `/materials` | 列表 / 详情 / 块列表 / 上传（此前已完成） | 轮询、URL 同步 |
| `/study` | 今日学习 / 生成练习卷 / 查看答案 / 追加练习 | 请求令牌（配 `StaleResponse`）、按错误码的业务分支（重新读计划、跳下一题、绝不本地插题） |
| `/knowledge` | 知识树 / 节点详情 | 模板仍读同名绑定，但真相只有 `treeTask` / `detailTask` 一个来源（页面侧 computed 派生） |
| `/chat` | 页面级加载与失败（`loading` 由 `pageTask.state` 派生） | `sending` 保留为页面状态 —— 它是**一次 SSE 流的过程标志**，由错误帧/断连/取消多个分支决定何时复位，与「一次请求的 submitting」不是同一语义 |

### 25.4 验证

```text
cd frontend; npm run typecheck        # 通过
powershell -File scripts\run-e2e.ps1  # 72 passed (2.1m)，退出码 0
```

分工说明为什么这组数字有说服力：`StudyPage` 覆盖导航 spec 的阶段 B 主流程
（生成卷、专注模式、查看答案后自评、全卷回看、追加追练）与十态矩阵的 `/study` 十态；
`KnowledgePage` 覆盖父/叶子边界与节点自评；`ChatPage` 覆盖十条问答用例；
`MaterialsPage` 覆盖资料页全流程。四页全绿 = 收敛没有改变任何对外行为。

### 25.5 未做的（如实记录）

- `/chat` 的 `sending` 没有改成 `submit()`：如上所述语义不同。若后续要让
  它走统一状态，需要先把 SSE 流的完成/取消/断连收敛成一个状态机。
- 窄窗口仍只覆盖 375×667 与 768×1024，没有真机与横屏验证。

## 26. 阶段 F 的容器内功能验证（2026-09-21）

### 26.1 阻塞是怎么解开的

三件事按顺序解决了：

1. **Docker 引擎没在跑**，且 `~/.docker/daemon.json` 的 `registry-mirrors` 指向
   已失效的镜像站（实测 `docker.m.daocloud.io` / `docker.1panel.live` 都是 401/403）。
   清空该字段直连官方 `registry-1.docker.io` 后，`docker pull python:3.12-slim` 6.4 秒完成。
   （配置已备份为 `daemon.json.bak-before-frontend-fix`。）
2. **`INSTALL_EMBED=1` 的构建**之前 exit 2，实际是**镜像站失效 + 网络波动**所致；
   换源后重试成功：pip 装依赖 241.8s、镜像导出 135.4s。
3. **容器卷里没有模型**：把宿主机已缓存的模型目录 `docker cp` 进
   `/app/storage/models` 后，容器 health 从 `unavailable` 变为 `ready`。

### 26.2 逐项验证结果

| 验收项 | 结果 | 证据 |
|---|---|---|
| `docker compose ps` 三服务 healthy | ✅ | backend/db/frontend 均 `Up (healthy)` |
| 四路由回落 SPA（刷新不 404） | ✅ | `/study` `/knowledge` `/materials` `/chat` 全 200 且含 SPA 根节点 |
| 容器内 alembic + seed | ✅ | entrypoint 日志 + `alembic current = e54f60dca851 (head)` |
| **上传 → 可检索** | ✅ | 上传 201 → `ready`；三个**自然中文查询**全部命中，`degraded=false vector=2` |
| 前端四页在部署形态可用 | ✅ | `verify_docker_frontend.py` 13 项全过（SPA 外壳 / JS 资源 / 反代 / 页面数据 / 资料全链 / SSE） |
| **SSE 不被 Nginx 缓冲** | ✅ | 189 个 delta 帧、**分 3 次读到达**（一次性缓冲会挤在一次 read） |
| **强杀 worker 后 lease 恢复** | ✅ | 真实 `docker compose kill backend`：任务停在 `indexing` → 等 45s lease 过期 → 重启后恢复并跑完 4000 分块 |
| `down` → `up -d` 数据不丢 | ✅ | 探针行 `PERSIST-PROBE` 重启后仍在；11 知识点 / 22 题 / 5 kp_states 不变 |

### 26.3 两次「看起来像产品缺陷、其实是验证方式有问题」

诚实记下来，因为它们本可以导致错误结论：

1. **检索 0 命中**：第一版验证脚本上传的资料只有 1 个分块、查询词是一个生造的
   ASCII token。向量召回 0 条看起来像「容器检索坏了」，换成有实质内容的资料 +
   自然中文查询后立刻命中。→ 已把查询词改写成真实用户会问的问题。
2. **容器 e2e 23 条全失败**：`frontend/e2e/fixtures.ts` **刻意拒绝**连接非 `test`
   环境（因为它在 `beforeEach` 里跑 `reset_today.py`，会清空学习证据），
   而 Docker 栈是 `dev`。这是**测试的正确防护**，不是产品缺陷 ——
   所以改用独立脚本验证部署形态，**没有**为了让 e2e 跑起来而削弱那道防护。

### 26.4 仍未验证（如实记录）

- **容器内的浏览器点击式联调**：`verify_docker_frontend.py` 覆盖到 HTTP/接口层；
  浏览器交互由 72 条 e2e 覆盖，但那些用例只跑隔离测试库。两者叠加覆盖了，
  但「在这套 dev 部署上手工点一遍」没有被自动化固化。
- **容器内问答拿到带引用的完整回答**：✅ **已实测通过**（2026-09-21 补充）。
  经 `localhost:8080`（前端容器 → nginx → 后端容器）上传资料 → 索引 ready（2 块）→
  提问「洛必达法则的适用条件是什么？」→ 收到 **275 字回答**、**2 条可核验引用**
  （都指向刚上传的资料块 0/1），SSE **分 6 次读到达**（未被缓冲）。

  这里要纠正我此前的一个错误结论：我曾写下「本机没有 LLM 凭据（`.env` 里
  `LLM_API_KEY` 为空）」—— 这是**错的**。实际 `.env` 里凭据是配好的
  （`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash`、key 已设置），
  我把「**容器没注入**」错当成了「**没有凭据**」。
  容器侧只需把凭据经 `.env.compose` 注入（该文件已被 `.gitignore` 忽略），
  实测容器内 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 均已生效。

  ⚠️ 两条**不是缺陷**、但容易误判的观察（都出在我自己的验证脚本上）：
  - 帧序里出现过 `d`：我的脚本按任意字节边界切块，把 `delta` 截成了 `d`+`elta`；
    按 SSE 帧边界（`\n\n`）解析后帧序正常。前端 `streamChatAnswer` 本身有 buffer 处理，
    且有测试锁着契约。
  - `citation_index` / `usage` 读到 `None`：引用卡的字段是 `label`
    （后端 `_CITATION = re.compile(r"\[C([1-9]\d*)\]")`，形如 `[C1]`），
    **没有** `citation_index` 这个字段 —— 是我查错了字段名。
- **阶段 G 的全量回归与人工验收**：尚未开始。

## 27. 阶段 G 验收执行记录（2026-09-21）

### 27.1 §4 五条最终必跑命令

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m alembic upgrade head` | ✅ 退出码 0；`alembic current` = `e54f60dca851 (head)`；`alembic check` = `No new upgrade operations detected.` |
| 2 | `python -m pytest` | ✅ 退出码 0（408 条） |
| 3 | `npm run build`（frontend） | ✅ 退出码 0（`dist/assets/index-TDS7Gcmt.js` 168.11 kB / gzip 61.41 kB） |
| 3b | `npm run typecheck` | ✅ 退出码 0（`vue-tsc --noEmit`） |
| 4 | `npm run test:e2e`（经 `scripts\run-e2e.ps1` 隔离模式） | ✅ **72 passed (2.1m)**，退出码 0 |
| 5 | `docker compose up --build` | ✅ **退出码 0**（首次因 Docker Hub 网络波动失败，配好可用镜像站后成功重建三服务；重建后全链路复验通过，见 §27.4） |

### 27.2 核心产品硬规则取证（按规则分组跑测试）

| 规则 | 测试 | 结果 |
|---|---|---|
| 知识树边界 + 查看答案（纯读取） | `tests/integration/test_learning_loop.py`、`tests/api/test_health.py` | ✅ |
| 毕业规则 + 不伪造证据 | `tests/unit/mastery/test_rules.py` / `test_policy.py` / `test_selection.py` | ✅ |
| 问答模式隔离 + 引用校验 + 归因 | `tests/integration/test_chat_flow.py`、`tests/unit/test_citation_validator.py`、`tests/unit/test_chat_attribution.py` | ✅ 56 passed |
| SSE 帧序 + 流式契约 | `tests/integration/test_chat_stream.py`、`tests/integration/test_followup_candidates.py` | ✅ |
| 会话删除（D-31 物理删除） | `tests/integration/test_chat_sessions.py` | ✅ |
| 题库/追练预算 + 客观题不覆盖自评 | `tests/unit/test_planning_service.py`、`tests/unit/test_chat_followup_budget.py`、`tests/unit/test_objective_result.py` | ✅ |

### 27.3 人工浏览器验收（真实 Chrome，对 Docker 部署）

对 `http://localhost:8080` 用 `channel: "chrome"` 打开四个页面，1366×768：

| 页面 | h1 | 正文 | pageerror | console.error |
|---|---|---|---|---|
| `/study` | 今日学习 | 414 字 | 0 | 0 |
| `/knowledge` | 知识树 | 194 字 | 0 | 0 |
| `/materials` | 资料库 | 294 字 | 0 | 0 |
| `/chat` | 问答 | 393 字 | 0 | 0 |

截图留档：`%TEMP%\kaoyan-accept\accept-{study,knowledge,materials,chat}.png`。

**这一步的诚实边界**：判据是程序化的（零 pageerror、零 console.error、页面有实质正文、
四个路由都渲染出各自的 h1），**不是"我看过截图说好看"** —— 当前会话的模型不支持读图，
截图需要人工目视或换用支持图像输入的模型复核。

### 27.4 `docker compose up --build` 的网络问题与最终结果

**先说结论：这条命令最终以退出码 0 跑通，三服务重建成功。**

过程（值得记录，因为它区分了「环境问题」与「产品问题」）：

1. 首次执行失败在拉基础镜像：

   ```
   failed to resolve source metadata for docker.io/library/node:22-alpine:
   dial tcp 69.171.228.74:443: connectex: A connection attempt failed ...
   ```

2. 当时判断是「本机到 Docker Hub 的网络波动」，理由是同机几十分钟前刚成功拉取
   `python:3.12-slim`（6.4 秒）并构建了后端镜像。
3. 再次探测时 **`registry-1.docker.io:443` / `auth.docker.io:443` 已完全不通**（TCP 层），
   而 `hf-mirror.com:443` 仍通 —— 说明不是全局断网，而是**到 Docker Hub 的链路被切断**。
4. 于是改走可用镜像站：把 `~/.docker/daemon.json` 的 `registry-mirrors` 设为
   `https://docker.1ms.run`（实测可用；此前配置里的 `docker.m.daocloud.io`、
   `docker.1panel.live` 已失效），重启 daemon 后 `docker pull node:22-alpine` **22.6 秒成功**。
5. 再跑 `docker compose --env-file .env.compose up --build -d` → **退出码 0**，
   三容器重建启动；随后复跑 `scripts/verify_docker_deploy.py` **六项全过**
   （上传→可检索、自然查询命中、**SSE 214 个 delta 帧分 3 次到达**、清理干净）。

**结论**：这条必跑命令已真实通过。前面那次失败是**网络链路问题**，不是配置或代码缺陷；
配置层（Dockerfile / compose / nginx / entrypoint）另有 47 项静态校验兜底。

**注意**：可用镜像站会随时间失效（本项目已先后遇到两个失效的），
`~/.docker/daemon.json` 是**用户级配置**、不属于本仓库；
这里只记录「怎么判断与怎么换」，不把某个镜像站硬编码进项目配置。

## 28. 数据一致性收尾（2026-09-21）

### 28.1 `gaoshu-lecture-01` 的最终结论：记录已不存在

§26.4 记过「这份资料的源文件不在 `storage/uploads`」。本轮按用户选择准备补齐时发现：
**它在库里的记录已经先一步消失了**（上一轮查它还是 `status=failed`，
这一轮 `POST /api/materials/{id}/reindex` 直接返回 404 `material_not_found`）。
git 历史里找不到删除它的提交，应是某个清理动作连带移除了。

因此处理结果与预期不同，如实记录：

- 我按方案 A 复制到期望路径的文件成了**孤儿**（记录都没了，副本毫无意义）→ 已删除；
- 真正的源文件仍在 `2d1c5f5f-…/source.md`（`高等数学核心考点讲义` 的正文），**没有动它**；
- 现在 dev 库只剩两份资料，都是 `ready`：`验收`（user）+ `高等数学核心考点讲义`（builtin）。

### 28.2 顺手清掉的两类残留

| 残留 | 来源 | 处理 |
|---|---|---|
| `E2E-QA-HOST-bddd6c3f` | 我做问答端到端验证时上传的探针资料 | 经 API `DELETE` 204 删除 |
| `a3bad353-…/source.md` | 本轮为已消失的记录复制的副本 | 删除整个孤儿目录 |

清理后 `storage/uploads` 只剩两个目录，且**每个都被数据库记录引用**（无孤儿文件、
无缺失文件），向量库一致性检查也报「孤儿向量与缺失向量都没有」。

### 28.3 一个此前一直误解的事实

Docker 栈用的是**容器内独立数据库**（`DATABASE_URL=…@db:5432/kaoyan` + `db_data` 卷），
**不是**宿主机的 `.pgdata`（5433）。所以：

- 首次发现「`/api/materials` 返回 0 份」不是数据丢了，而是**两个库本来就是不同的**；
- 此前 `verify_docker_deploy.py` 的上传/检索验证全程发生在容器库内，
  与宿主机 dev 库互不影响 —— 这正是隔离部署该有的样子；
- 项目内 `docker compose exec db psql` 看到的是容器库，要看宿主机库得用 5433。

这一条值得写下来：我曾一度把「两个库」当成「一个库」，才会把「容器库 0 份资料」
误读成「资料被删了」。

## 29. 删除被引用资料会 500：外部缺陷报告与修复（2026-09-22）

### 29.1 这不是我自己发现的

由一份外部缺陷报告指出（`WorkBuddy/…/缺陷报告-删除被引用资料会失败.md`）。
我独立验证了它的每一条结论，全部成立 —— 包括根因表里的三个约束值。
**这是本项目第一次由"外部审查"抓到我漏掉的问题**，值得单独记一节。

### 29.2 缺陷与根因

资料页点「删除」时，只要该资料**曾被问答引用过**就返回 500、删不掉（**用户可见**）。

```
删除 materials
  └─ CASCADE 删 document_chunks      ← 撞在这里
       ✗ message_citations 仍引用着它 → ForeignKeyViolation → 整笔回滚
```

三条约束单独看都合理，合起来就成了「被引用过的资料永远删不掉」：

| 约束 | 值 |
|---|---|
| `message_citations.chunk_id → document_chunks.id` | **NO ACTION**（无 ON DELETE） |
| `document_chunks.material_id → materials.id` | **ON DELETE CASCADE** |
| `message_citations.chunk_id` | **NOT NULL**（不能置空） |

### 29.3 两个必须记住的教训

**① 「修了一个触发点就收工」是明确的错误模式。**
D-46（`410fa6e`）的提交信息里**已经写明**这个外键会挡住 `parse_material` 的删块，
但那次只修了**重建索引**这条路，**删除资料这条路漏了** ——
同一个外键、同一个根因，只补了一半。修一个触发点时，应该顺手搜一遍
「还有哪些路径会踩到同一个约束」。

**② 测试覆盖面不是看数量，而是看「每条真实路径有没有被走一遍」。**
72 条 e2e 听起来不少，但 `materials.spec.ts` 的删除用例删的是
**刚上传、从未被问答引用过**的资料，**根本不经过那条外键**。
所以「删除被引用过的资料」这条路径此前**覆盖为零**。

### 29.4 修法与语义边界

在 `delete_material` 里加**第零步**：删记录前先清掉指向该资料分块的 `message_citations`。

选它的理由（另两条的代价更大）：
- `chunk_id` 改 `ON DELETE SET NULL`：会留下**指向不存在来源**的历史引用，
  与产品「引用必须可核验」直接冲突；
- 软删除资料：历史引用完好，但"删掉的资料"仍占库与向量空间，
  且所有查询都要加过滤条件，代价扩散到整个代码库。

代价是历史回答正文里的 `[C1]` 会变成**悬空标记**（有标记、没卡片）——
这恰好如实表现了「来源已删除」这个事实。
**边界**：只清引用，**会话与消息保留** —— 历史回答不该因为删了一份资料而消失。

### 29.5 新增 4 条测试（每条都显式造 `message_citations`）

| 用例 | 锁住的契约 |
|---|---|
| 被引用的资料能删掉（204 而非 500） | 核心回归 |
| 引用被清掉、会话与消息保留 | 语义边界 |
| 未引用的资料照旧能删 | 没弄坏常见路径 |
| **删一份资料不误伤别的资料的引用** | 漏 `where` 会清空整张引用表：表面"删除成功"、实际毁掉所有历史引用 |

外加一条 **e2e**（`materials.spec.ts`）走完整真实链路：上传 → 提问拿到真实引用 → 删除 → 断言成功。
补这条时我自己踩了「判据写错导致用例永远跳过」的坑（详见 changes D-47 末节）——
`72 passed + 1 skipped` 修正为 `73 passed + 0 skipped`。

```text
python -m pytest tests/materials/test_cited_material_delete.py -v   # 4 passed
python -m pytest -q                                                # 退出码 0（412 条）
```

### 29.6 对冻结版本的影响

`reference-project-verified-v1` 原本打在 `1943d19`，该版本**含此缺陷**。
修复后应把标签移到本修复的提交，并在注释里补一条：
「删除被引用资料会 500」曾存在于冻结版本中，由外部报告发现，已修复并加测试锁住。
