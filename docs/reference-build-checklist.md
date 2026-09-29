# 参考项目验收清单

> 本文件是**构建记录 / 验收清单**，不是最终教学文档。
> 勾选状态只代表“已经实际运行并观测到结果”，不代表“代码看起来应该可以”。
> 最新迭代：2026-09-26，见变更记录 D-53；历史阶段状态以 reference-build-status.md 第 1 节为准，下文早期阶段结论按时间保留。

## 本轮补充验收（2026-09-26）

- [x] 本机设置页可保存模型配置；密钥不回显，留空保留、显式移除、失败不应用、重启恢复。
- [x] 跨站/远程/转发来源与 prod/test 无法读写模型配置；Windows DPAPI 加密测试通过。
- [x] 404/405/422/500 与业务错误统一 error 信封，校验提示不返回原始输入。
- [x] 前端单元测试 21 条、独立 mock E2E 9 条通过；后端隔离回归 183 条通过。
- [x] OpenAPI 快照/类型同步，typecheck/build 通过；页面和公式按需加载。
- [ ] 本轮未重跑全量 pytest、全量真实后端 E2E、数据库迁移或 Docker 验收，不据此重新冻结版本。

## 0. 使用方式

- `[x]` = 已实际执行并看到预期结果（附证据）
- `[ ]` = 尚未执行 / 尚未实现
- `[!]` = 已执行但结果不符合预期（必须修复，不允许长期保留）

## 1. 阶段 A — 工程底座、数据库与可视化验收壳

### 1.1 后端

- [x] FastAPI application factory（`create_app()`，`backend/app.py`）
- [x] lifespan（启动建目录 + `SELECT 1` 探活；`finally` 中 `engine.dispose()`）
- [x] Settings（pydantic-settings，`APP_ENV` / `DATABASE_URL` / `TEST_DATABASE_URL` + `_test` 硬保护）
- [x] `.env.example`（无真实密钥）
- [x] PostgreSQL 连接（`create_db_engine`、`create_session_factory`、请求级 `get_db`）
- [x] SQLAlchemy（DeclarativeBase + 命名约定 + TimestampMixin）
- [x] Alembic（`alembic.ini` + `migrations/env.py` 从 `get_settings()` 取 URL）
- [x] 开发库与测试库隔离（`APP_ENV=test` 时只允许 `kaoyan_test`；validator 强制 `_test` 后缀）
- [x] 健康检查 `GET /api/health`
- [x] 健康检查成功分支测试（200）
- [x] 健康检查失败分支测试（503，且不泄露驱动异常 / URL / 密码）
- [x] 从空数据库完成迁移（`downgrade base` → `upgrade head` → `current` → `check`）

### 1.2 前端

- [x] Vue3 + Vite（Vue 3.5 / Vite 6）
- [x] 相对 `/api` 请求客户端（`frontend/src/api/health.ts`，开发期 Vite 代理）
- [x] 前端构建 / 类型检查 / Playwright 基础命令（`npm run build` / `typecheck` / `test:e2e`）
- [x] `/study`、`/knowledge`、`/materials`、`/chat` 四个导航入口
- [x] 四页是真实 Vue 组件（`src/pages/*.vue`），不是截图或静态假页面
- [x] 系统状态区域（`SystemStatus.vue`）
- [x] 系统状态真实请求 `GET /api/health`
- [x] 后端与 PostgreSQL 可用时显示连接成功
- [x] 健康检查 503 时显示明确错误和重试按钮
- [x] 阶段 A 未用 mock 数据冒充学习 / 资料 / 聊天功能已完成

### 1.3 阶段 A 可访问地址

- [x] 前端 `http://127.0.0.1:5173`
- [x] 后端 `http://127.0.0.1:8000`
- [x] 健康检查 `http://127.0.0.1:8000/api/health`

## 2. 核心产品规则验收（贯穿各阶段，最终必须全部为 `[x]`）

### 2.1 知识树边界

- [ ] 父节点只汇总子节点状态
- [ ] 父节点不能直接绑定题目
- [ ] 父节点不能直接毕业
- [ ] 父节点不出现“我已掌握 / 我部分掌握 / 我未掌握”按钮
- [ ] 只有 `is_assessable=true` 叶子可绑定题目、记录练习、自评、毕业
- [ ] 大章节综合题以独立可考核叶子节点存在（如“极限综合题”）

### 2.2 查看答案（纯读取）

- [ ] 做题前 / 中 / 后均可查看答案与解析
- [ ] `GET /api/practice-items/{item_id}/answer` 不写学习数据
- [ ] 查看答案不写 `revealed_at`
- [ ] 查看答案不改变掌握度、毕业、复习计划、用户自评

### 2.3 用户自评与练习历史

- [ ] `mastered` 进入有效确认窗口
- [ ] `partial` 永久保存记录，但不增加也不清空确认窗口
- [ ] `not_mastered` 永久保存记录，清空确认窗口，状态变 `stuck`
- [ ] `skip` 不创建 `QuestionAttempt`，不改变状态
- [ ] 所有非 skip 作答永久保存在 `QuestionAttempt`
- [ ] 选择题可保存 `objective_result=right/wrong`
- [ ] 填空 / 纸笔 / 主观题可保存 `objective_result=unknown`
- [ ] `objective_result` 绝不覆盖或代替 `self_grade`
- [ ] 毕业完全以 `self_grade` 为主

### 2.4 毕业规则

- [ ] 每个可考核叶子都从自己的 `KpMasteryPolicy` / `MasteryPolicy` 读取门槛；没有单独配置时才使用默认基线
- [ ] 毕业同时满足：`min_confirmations`、`min_real_questions`、必考 `question_type` 配额、必考 `skill_tags`、`required_variant_count` 与 `min_day_span`
- [ ] 每道进入窗口的真实题都必须由 `self_grade=mastered` 产生；同题重复 mastered 只刷新最近确认时间
- [ ] `partial` 保存练习历史，但既不加入也不清空确认窗口；`not_mastered` 保存历史后清空窗口
- [ ] 叶子“我已掌握”只写入 `manual_mastered_credit` 个透明基础确认，不伪造 `QuestionAttempt`
- [ ] 基础确认只能补有效确认数，**不能**替代 `min_real_questions`、题型覆盖、考法覆盖、真实变式题或跨天要求
- [ ] 页面必须显示该叶子的策略与当前缺口，不能用固定“3 题毕业”文案覆盖不同题型知识点
### 2.5 今日学习

- [ ] 首次进入当天 `/study` 无活动练习卷时显示 `setup`
- [ ] 后端推荐叶子知识点并给出推荐理由
- [ ] 用户可勾选 / 取消推荐项
- [ ] 用户可从知识树补充当天想学的叶子
- [ ] 没有用户确认不允许自动创建计划
- [ ] 点“生成今日练习卷”后从所选叶子已有题库生成初始题目
- [ ] 同一天不能重新生成整卷
- [ ] 生成后状态为 `active`
- [ ] 专注模式一次显示一道未完成题
- [ ] 阅览全卷模式按 `ordinal` 从上到下显示全部题
- [ ] 完成题后专注模式进入下一题
- [ ] 已完成题从专注模式隐藏
- [ ] 已完成题在全卷与练习记录中永久保留
- [ ] 全部完成时计划变 `completed`
- [ ] 页面显示今日实际涉及知识点与完成数量
- [ ] 不显示题目来源标签
- [ ] “追加练习题”打开轻量知识树 / 题库选择器
- [ ] 追加只能从已有题库选题
- [ ] 追加到 `max(ordinal)+1` 卷尾
- [ ] 不允许重新洗牌 / 重新生成整卷 / 追加重复题
- [ ] 不显示“自动推荐 / 手动添加 / 问答追练”来源差异
- [ ] 所有题按 `kp_id + self_grade` 使用同一毕业规则

### 2.6 问答与追练

- [ ] 回答必须来自检索到的真实 chunk
- [ ] 引用经过服务端校验
- [ ] 刷新会话后仍可恢复引用卡
- [ ] SSE 支持正常完成 / 失败 / 取消
- [ ] SSE 的引用、`matched_kp_id`、错误码、消息状态稳定
- [ ] 问答不可直接让知识点毕业
- [ ] 提问不改变 `KpState`
- [ ] 阅读回答不改变 `KpState`
- [ ] “我不理解”只记录弱信号，不直接改 `stuck`
- [ ] 仅服务端可靠得到叶子 `matched_kp_id` 时才返回追练候选
- [ ] 追练候选只从该叶子已有题库选择
- [ ] 用户确认后才通过今日练习卷追加接口加入
- [ ] 无候选题时显示“该知识点暂无可追加练习题”
- [ ] V1 不联网搜题
- [ ] V1 不让 LLM 自动生成正式题

## 3. 阶段 B–G 验收总览

- [x] 阶段 B：学习闭环后端 + `/study` `/knowledge` 真实页面
- [x] 阶段 C：资料上传 / 解析 / 标题树 / 分块 / 索引 / 检索 + `/materials`（详见第 7 节的真实运行记录）
- [x] 阶段 D：会话 / 引用校验 / SSE / 追练 + `/chat`（2026-09-20 完成，见 §9 验收清单）
- [x] 阶段 E：统一 API client ✅ / 错误码 ✅ / Playwright 四页真实联调 ✅（**72 passed**）/ 十态状态矩阵 ✅ / 前进后退 ✅ / 窄窗口 ✅（详见 §18）
- [x] 阶段 F：`docker compose up --build` 与数据持久化
      —— 容器内**逐项实测**通过：三容器 `Up (healthy)`、8080 可访问、nginx 反代、
      四路由回落 SPA、容器内 alembic 在 head、seed 幂等、
      **上传→可检索→检索命中（自然查询）→清理**、
      **SSE 189 个 delta 帧分 3 次到达（未被缓冲）**、
      **强杀容器后 lease 到期任务被恢复并跑完 4000 分块**、
      `down` → `up -d` 后数据仍在。判据：`docs/deploy-local-docker.md` §4 的 9 项全勾。
      ⚠️ 未覆盖：容器内的**浏览器点击式**联调（由 72 条 e2e 在隔离测试库覆盖）；
      容器内问答拿到完整带引用回答（本机无 LLM 凭据）。
      ⚠️ 另有 dev 库 `gaoshu-lecture-01` 源文件缺失（用户资料完整性问题，未擅自改动）。
- [x] 阶段 G：全量测试 + 人工验收 + 冻结 tag `reference-project-verified-v1`
      —— §4 五条必跑命令逐条执行：alembic（head / check 无差异）、pytest 408 条、
      `npm run build` + `typecheck`、e2e **72 passed (2.1m)**；
      核心产品硬规则六组取证全部通过（知识树边界 / 毕业规则 / 模式隔离与引用 /
      SSE 帧序 / 会话物理删除 / 追练预算）；
      真实 Chrome 对 Docker 部署验收四页，**零 pageerror、零 console.error**（截图留档）。
      详见状态文档 §27。
      ⚠️ **`docker compose up --build` 本轮复跑受网络限制**（拉 `node:22-alpine` 超时）：
      三容器此前已真实构建启动且逐项功能验证通过（§26），但"一条命令从零构建整套"
      在当前网络下无法复现 —— 这是环境限制，已如实记录，不是产品缺陷。
      ⚠️ 冻结 tag 的含义是「在通过上述验证的提交上打标签」，网络限制不影响已验证的内容。

## 4. 最终必跑命令（阶段 G 已执行；后续改动仍需重跑）

```powershell
python -m alembic upgrade head
python -m pytest
npm run build          # 在 frontend/
npm run test:e2e       # 在 frontend/
docker compose up --build
```

当前状态：前四条在阶段 A 已有等价执行记录（见 `reference-build-status.md` 第 4 节）；`docker compose up --build` **因本机未安装 Docker 尚不能执行**。
## 5. 阶段 A 补充验收项（真实故障验证）

- [x] 真实停掉 PostgreSQL 集群后，健康检查**快速**返回 503（不是挂起）
- [x] 503 响应体为 `{"error":{"code":"database_unavailable","message":"database unavailable"}}`
- [x] 503 响应不含驱动异常文本、`postgresql://`、密码
- [x] 经 Vite 代理访问 `/api/health` 与直连后端行为一致
- [x] 数据库恢复后无需重启后端即可重新返回 200
- [x] 上述“挂起”缺陷已有回归测试保护（`tests/unit/test_db_engine_timeouts.py`）
## 6. 阶段 B 验收清单（已实际运行验证）

### 6.1 知识树边界（全部已实测）

- [x] 父节点只汇总子节点状态（父节点 `state` 一律为 `null`）
- [x] 父节点不能直接绑定题目（种子脚本拒绝把题挂到父节点）
- [x] 父节点不能直接毕业
- [x] 父节点不出现「我已掌握 / 我部分掌握 / 我未掌握」按钮
- [x] 只有 `is_assessable=true` 叶子可绑定题目、记录练习、自评、毕业
- [x] 综合题以独立可考核叶子节点存在（`syllabus.json` 中父节点 `is_assessable: false`，叶子单独建）

### 6.2 查看答案（纯读取，已实测）

- [x] 做题前 / 中 / 后均可查看答案与解析（E2E 先查看答案再自评仍成功）
- [x] `GET /api/practice-items/{item_id}/answer` 不写学习数据（调用前后 attempt/event/kp_state/completed_at 全不变）
- [x] 查看答案不写 `revealed_at`（数据库无该列，代码无该写入）
- [x] 查看答案不改变掌握度、毕业、复习计划、用户自评

### 6.3 用户自评与练习历史（已实测）

- [x] `mastered` 进入有效确认窗口
- [x] `partial` 永久保存记录，但不增加也不清空确认窗口（`update_evidence_window` 返回原窗口）
- [x] `not_mastered` 永久保存记录，清空确认窗口，状态变 `stuck`
- [x] `skip` 不创建 `QuestionAttempt`，不改变状态，不标记完成
- [x] 所有非 skip 作答永久保存在 `QuestionAttempt`
- [x] 填空 / 纸笔 / 主观题保存 `objective_result=unknown`
- [x] 选择题保存 `objective_result=right/wrong`（用户选了选项且题目有标准答案时判定；填空/纸笔/主观题与未作答保持 `unknown`）
- [x] `objective_result` 绝不覆盖或代替 `self_grade`
- [x] 毕业完全以 `self_grade` 为主

### 6.4 毕业规则（已实测）

- [x] 无节点整体自评时，需至少 3 道不同真实题且全部 `mastered`
- [x] 无论是否有节点整体自评，至少需要 1 道真实变式题
- [x] 首尾有效确认的上海日期相差至少 2 天（01-01 → 01-03 通过，01-01 → 01-02 不通过）
- [x] 同一题重复 `mastered` 只刷新该题最近确认时间，不增加不同题数
- [x] `partial` 不加入毕业窗口也不清空
- [x] `not_mastered` 清空确认窗口
- [x] 叶子「我已掌握」只写入 2 个透明基础确认，不伪造两条 `QuestionAttempt`（实测 0 条 attempt）
- [x] 叶子「我已掌握」仍须满足 ≥1 道真实变式题与跨天确认
- [x] 页面明确显示「基础确认 +2」，不伪装成做过两题
- [x] 节点「我部分掌握」清除 2 个基础确认，保留真实题目历史与真实确认窗口
- [x] 节点「我未掌握」清除基础确认 + 清空题目确认窗口 + 状态 `stuck` + 保留历史

### 6.5 今日学习（已实测）

- [x] 首次进入当天 `/study` 无活动练习卷时显示 `setup`
- [x] 后端推荐叶子知识点并给出推荐理由（稳定理由码 + 页面中文映射）
- [x] 用户可勾选 / 取消推荐项
- [x] 用户可从知识树补充当天想学的叶子（准备页「从知识树补充」列出全部可考核叶子，勾选即加入今天的选点）
- [x] 没有用户确认不允许自动创建计划
- [x] 点「生成今日练习卷」后从所选叶子已有题库生成初始题目
- [x] 同一天不能重新生成整卷（409 `plan_already_generated`）
- [x] 生成后状态为 `active`
- [x] 专注模式一次显示一道未完成题
- [x] 阅览全卷模式按 `ordinal` 从上到下显示全部题
- [x] 完成题后专注模式进入下一题
- [x] 已完成题从专注模式隐藏
- [x] 已完成题在全卷与练习记录中永久保留
- [x] 全部完成时计划变 `completed`（数据库行也真的写入 `completed`）
- [x] 页面显示今日实际涉及知识点与完成数量
- [x] 不显示题目来源标签
- [x] 「追加练习题」打开轻量知识树 / 题库选择器
- [x] 追加只能从已有题库选题
- [x] 追加到 `max(ordinal)+1` 卷尾
- [x] 不允许重新洗牌 / 重新生成整卷 / 追加重复题
- [x] 不显示「自动推荐 / 手动添加 / 问答追练」来源差异
- [x] 所有题按 `kp_id + self_grade` 使用同一毕业规则

### 6.6 阶段 B 命令验收记录

```powershell
python scripts/seed.py      # 第一次：新建 11 知识点 / 15 题；第二次：全部跳过（幂等）
python -m pytest            # 62 passed
cd frontend; npm run typecheck   # 通过
cd frontend; npm run build       # 通过
cd frontend; npm run test:e2e    # 6 passed
python scripts/reset_today.py    # 需要重新演示主流程时使用
```

## 7. 阶段 C 验收清单（已实际运行验证）

> 每条都对应一次真实执行：后端 278 条 pytest、13 条 Playwright、真实模型评估脚本、
> 真实 HTTP 端到端脚本。**没有一条是「读代码推断」得出的。**

### 7.1 摄取与解析

- [x] 只接受 `.md` / `.txt` / `.docx` / `.pdf`，其余返回 422 `unsupported_type`
- [x] 空文件返回 422 `empty_file`
- [x] 超过 20 MB 返回 413 `file_too_large`
- [x] 落盘失败时**不留孤儿记录**（数据库里查不到任何 material / job）
- [x] UTF-8（含 BOM）与 GB18030 都能正确解码；无效字节明确报 `document_decode_failed`（绝不 `errors="ignore"`）
- [x] 扫描件 PDF 返回 422 `scanned_pdf`，不伪造正文
- [x] 带路径的文件名按最后一段判断后缀（`../../evil/x.md` 不会绕过白名单）
- [x] `stored_path` 逃出资料根目录时返回 `unsafe_storage_path`
- [x] 落盘用 `.part` + 原子替换；失败后目录里既没有正式文件也没有临时文件
- [x] 解析结果写入 `normalized_text`，且**与重新规范化原文逐字节一致**

### 7.2 分块与知识点关联

- [x] 每个 chunk 都满足 `content == normalized_text[start:end]`
- [x] `ordinal` 从 0 连续递增，且按原文顺序输出
- [x] 单块不超过 700 字
- [x] 内置讲义真实产生 15 个块（导言 1 + 各知识点 2~3）
- [x] `<!-- kp:code -->` 归属于**紧邻其下方**的标题，5 个知识点全部正确
- [x] 注释与标题之间隔着正文时不算紧邻（不会影响很远的标题）
- [x] 代码围栏里的 `<!-- kp:... -->` 被忽略
- [x] 显式关联写入 `chunk_knowledge_points`，`confidence = 1.0`
- [x] 标注了不存在的知识点编号时**仍能入库**（只记录，不阻断）

### 7.3 索引构建与版本

- [x] 索引版本号格式为 `v1-<16 位十六进制>`
- [x] 版本号只依赖正文 hash + 模型 + 分块算法：相同输入永远同一个版本号
- [x] 换模型或换正文都会得到不同版本号
- [x] 非法格式（`v1-`、`v1-xyz`、`v2-...`、长度不对）被 `is_valid_index_version` 拒绝
- [x] 重建索引**不产生重复块**，且分块结果（内容 hash 序列）完全一致
- [x] 失败版本的块与向量会被清理，不留半个版本
- [x] 激活一个没有任何块的版本会报 `index_version_has_no_chunk`
- [x] 向量写入前强制校验归一化；非归一化向量报 `VectorStoreError`

### 7.4 任务系统（租约 / 重试 / 恢复）

- [x] 已被领取且租约未过期的任务不会被第二个 worker 重复领取
- [x] 租约过期后可被其他 worker 回收重领
- [x] 回收不会额外消耗重试次数（崩溃一次不等于失败一次）
- [x] 失败按 `5 × 2^(n-1)` 秒指数退避
- [x] 重试次数用尽后落到 `failed` 终态，资料状态同步为 `failed`
- [x] 源文件缺失时错误码为 `material_file_not_found`，资料**不会**被标成 ready
- [x] embedding 不可用时错误码为 `embedding_unavailable`，任务进入 `retry`
- [x] 资料卡在 `indexing` 时，其 pending 任务重新可领（否则永远无法恢复）
- [x] 失败日志记录错误码与异常类型，且**不含绝对路径与密钥**

### 7.5 检索

- [x] 向量路与关键词路各自命中的块都出现在结果里，并标出 `vector_rank` / `keyword_rank`
- [x] 结果正文来自 PostgreSQL（向量库里 document 被改坏也不影响）
- [x] 向量库里有、数据库里没有的 chunk 被丢弃（索引陈旧时宁可少返回）
- [x] 只有 `status='ready'` 且命中**当前激活版本**的资料才会被召回
- [x] 旧版本向量即使内容相同也不会被召回
- [x] 数据库指向新版本但索引未更新时，结果被丢弃
- [x] 知识库为空时返回空结果，不抛错也不返回全库内容
- [x] `material_ids` / `source_types` / `index_versions` / `excluded_material_ids` 四个过滤字段全部生效
- [x] 没有任何 ready 资料时过滤条件是空元组（= 检索不到），不是 `None`（= 不过滤）
- [x] 知识点过滤只保留**显式关联**的 chunk
- [x] `top_k <= candidate_k <= 50` 的夹取规则生效
- [x] 空查询返回 422 `empty_query`
- [x] RRF：两路都进前列强于只有一路第一；同一路内重复 id 只计一次
- [x] BM25 在小语料库不会因负 IDF 截断而分数全 0

### 7.6 降级（可用性）

- [x] embedding 不可用时降级为纯关键词检索，并如实报告 `degraded_reasons`
- [x] 关键词索引为空时向量路仍然工作
- [x] 重排模型不可用时退回融合顺序，**检索本身不失败**
- [x] 未配置重排模型是**正常配置**，不算降级（`degraded=false`）
- [x] `/api/health` 报告 `retrieval` 与 `worker` 状态
- [x] 健康检查输出里不含连接串、密码与绝对路径

### 7.7 资料接口

- [x] 上传返回 201，资料状态为 `pending`，响应里**没有 `stored_path`**
- [x] 列表返回总数与分状态统计
- [x] 详情返回块数与最近任务
- [x] 块预览内容确实出现在规范化全文里
- [x] 未知资料返回 404 `material_not_found`
- [x] 删除返回 204，且**同时清理**数据库记录、磁盘文件、向量索引与关键词索引
- [x] 删除后检索不到任何内容
- [x] `source_type` 非法时返回 400（而不是 500）

### 7.8 真实模型端到端（`scripts/e2e_materials_check.py`）

- [x] 健康检查 `retrieval=ready`、`worker=running`
- [x] 上传内置讲义 → 状态 `ready`，索引版本 `v1-c502c7fbb967d91e`，块数 15
- [x] 5 个语义查询**全部命中正确章节**（不是复制原文提问）
- [x] 删除后列表清空、检索为空

### 7.9 检索质量评估（`scripts/run_retrieval_eval.py`）

- [x] 14 条用例：Hit@6 = **1.000**、Recall@6 = **1.000**、MRR@6 = **0.962**
- [x] 13 条有答案用例中 12 条排第 1，1 条排第 2
- [x] 越界用例最高相似度 **0.031**，强信号率 **0.000**（阶段 D 阈值依据）
- [x] 评估在临时库中进行，**不污染开发索引**

### 7.10 前端资料页（真实浏览器）

- [x] 四个路由都可打开，「资料」页不再是占位页
- [x] 上传真实 `.md` 文件 → 状态自动从「排队中」变为「可检索」
- [x] 索引版本展示且符合 `v1-<16 位十六进制>`
- [x] 块预览显示标题路径与知识点编号
- [x] 检索自测命中并显示向量/关键词名次
- [x] 删除需二次确认；确认后列表回到空、再检索无命中
- [x] 不支持的后缀被前端拦下并给出中文原因
- [x] 空资料库给出明确提示而不是空白页

### 7.11 阶段 C 命令验收记录

```powershell
python scripts/seed.py                      # 幂等
python -m pytest                            # 278 passed
python scripts/check_retrieval.py            # 集合/模型/向量数一致
python scripts/e2e_materials_check.py        # 端到端全部通过
python scripts/run_retrieval_eval.py         # Hit@6=1.000 MRR@6=0.962
python scripts/check_deploy_config.py        # 部署配置静态校验通过
cd frontend; npm run typecheck               # 通过
cd frontend; npm run build                   # 通过
cd frontend; npx playwright test             # 13 passed
```

### 7.12 阶段 C 明确未完成 / 未验证

- [ ] `docker compose up --build` 真实启动（**本机无 Docker，从未执行**）
- [ ] `docker compose config` 语法校验（同上）
- [ ] 容器内四页可达与主流程（同上）
- [ ] `/chat` 页面（阶段 D）
- [ ] 启用重排模型后的效果对比（当前 `RERANKER_MODEL` 为空）

## 8. 用户实测反馈的验收（阶段 C 交付后）

> 四个问题都由用户真机实测发现。以下每条都已修复并**实际运行验证**。

### 8.1 P1 端到端测试不得破坏用户数据

- [x] 夹具只删除带 `E2E-` 前缀的资料，不提供清空资料库的能力
- [x] 清理按「用例开始时的 id 基线」做差集，只删本次新建的资料
- [x] 清理放在 `finally`，用例失败/超时时同样执行
- [x] 资料页用例不再依赖「资料库为空」，可在有资料的库上通过
- [x] 新增用例：跑完用例后用户自己的资料一份都不能少（已通过）
- [x] `scripts/e2e_materials_check.py` 记录基线并逐条核对用户资料未被动过
- [x] 实测：跑完全部 16 条用例后，「验收」「提示词」两份资料完好、零残留

### 8.2 P2 文件大小上限唯一且提示真实

- [x] 上传上限与解析上限是同一个常量（`MAX_FILE_BYTES`）
- [x] 超限文件在上传阶段就返回 413，不产生任何资料或任务记录
- [x] 上传响应里不出现「先 201 后异步失败」
- [x] 前端在上传前用真实上限拦截，文案不再写死数字
- [x] 边界：刚好在上限内的文件能正常上传

### 8.3 P3 解析失败给稳定业务码

- [x] 损坏的 PDF 返回 `document_parse_failed`，不是 `unexpected:PdfReadError`
- [x] 损坏的 .docx 同样返回 `document_parse_failed`（底层抛 zipfile 异常）
- [x] 合法但无文本层的 PDF 仍返回 `scanned_pdf`（包装没有吞掉具体错误码）
- [x] 未预期异常的错误码是 `internal_error`，异常类型只进日志
- [x] 所有错误码都在 `SAFE_MESSAGES` 中登记
- [x] 前端对 `document_parse_failed` 与 `internal_error` 都有中文说明

### 8.4 P4 indexing 中间态对 API 可见

- [x] 设置 `indexing` 后显式提交，另一个数据库连接能读到
- [x] 回归测试做了反向验证：改回 `flush()` 时该用例立刻失败
- [x] 实测状态轨迹包含 `indexing`（验收脚本会打印轨迹并断言）
- [x] 提交后进程崩溃时任务能被租约回收（不会被永久卡住）
- [x] 提交失败会落到 retry，不会留在 running

### 8.5 严重问题：向量索引损坏不再导致进程消失

- [x] 向量库构造时读一次计数，索引损坏时抛带行动指引的错误
- [x] 检索栈装配有兜底，原生库异常不会带走启动流程
- [x] 一键重建脚本可完整恢复索引（实测恢复 15 块 + 20 块）
- [x] 恢复后检索、页面、测试全部正常

### 8.6 顺带修复的可用性缺陷

- [x] 处理完成后块列表由页面轮询自动刷新（不需要手动再点一次）
- [x] 后端不可达时测试给出可照做的指引，而不是 16 个 `fetch failed`
- [x] 测试 HTTP 调用禁用 keep-alive 复用并带重试
- [x] 用例超时提到 3 分钟，覆盖冷启动建索引的耗时

### 8.7 竞态与数据一致性验收

- [x] 删除资料必须先删数据库记录、再清向量（顺序由测试锁定）
- [x] 删除一份测试资料后，数据库记录、块、向量全部清理，不留孤儿
- [x] 删除测试资料不影响另一份「用户资料」（记录、块都在）
- [x] 索引任务在资料已删除时不得写入块或向量（两类时机都覆盖）
- [x] 任务行被级联删除时，写状态不报 `StaleDataError` / `PendingRollbackError`
- [x] 存在反向保护：资料还在时必须能正常建索引（没把正常路径挡掉）
- [x] `scripts/check_vector_orphans.py` 报告一致（向量数 = 激活块数之和）
- [x] 实测：修复后跑完整 e2e，向量库 35 条 = 15 + 20，零孤儿
- [x] 验收脚本能采样到 `indexing` 中间态（轮询间隔小于中间态寿命）

### 8.8 本轮命令验收记录

```powershell
python -m pytest                            # 293 passed
cd frontend; npm run typecheck              # 通过
cd frontend; npx playwright test            # 16 passed
python scripts\e2e_materials_check.py        # 全部通过，用户资料未被动过
python scripts\check_deploy_config.py        # 通过
python scripts\rebuild_all_indexes.py        # 成功恢复索引
python scripts\check_vector_orphans.py       # 一致性正常：零孤儿向量
```

## 9. 阶段 D 验收清单（可信问答、SSE 与题库追练）

> 每条都对应一次真实执行：后端 pytest、Playwright、以及直接打真实模型与真实接口的验证。

### 9.0 删除被引用过的资料（2026-09-22 补，见 changes D-47）

- [x] **被问答引用过的资料必须能删掉**：此前返回 500 ——
      `message_citations.chunk_id`(NO ACTION) + `document_chunks.material_id`(CASCADE)
      + `chunk_id NOT NULL` 三条凑成「永远删不掉」。修法：删记录前先清掉指向该资料分块的引用
- [x] 引用被清掉，但**会话与消息保留**（历史回答不该因为删资料而消失）
- [x] 删一份资料**不误伤别的资料**的引用（漏 where 条件会清空整张引用表）
- [x] 新增 `tests/materials/test_cited_material_delete.py`（4 条，每条都显式造 `message_citations`）
- [x] **已知覆盖缺口（原报告的教训）**：`materials.spec.ts` 的删除用例只覆盖
      「刚上传、未被引用过」的资料，所以 72 条 e2e 一条都没抓到这个缺陷 ——
      测试覆盖面要看「每条真实路径有没有被走一遍」，不是看数量

### 9.1 会话与消息

- [x] 可创建会话并指定模式（`builtin` / `user`）
- [x] 会话列表按更新时间倒序，只列未归档会话
- [x] 归档会话后禁止继续写消息（返回 404 `chat_session_not_found`）
- [x] 消息顺序确定：`user` 一定在 `assistant` 之前（按 `seq` 排序）
- [x] 刷新页面后历史消息与引用仍然完整
- [x] 无命中时给出明确标识的通用知识参考，也留下完整的 user + assistant 两条消息（2026-09-26 用户变更，见 D-51）

### 9.2 引用校验

- [x] 只有本次检索命中的 `[C#]` 能成为来源
- [x] `[C99]` 这类未知编号不进来源，但记入 `unknown_citation_labels`
- [x] 重复编号按首次出现去重
- [x] 非契约形式（小写、前导零、带空格、圆括号等）一律不认
- [x] 引用必须仍属于**当前激活版本**的资料，失效引用被丢弃并记录
- [x] 模型没写引用时：回答仍可用，只记 `citation_warning`（不判失败）

### 9.3 matched_kp 归因

- [x] 只由 hits 的显式关联计算，不取用户问题、前端字段或 LLM 文本
- [x] 第一名低于阈值 → 不归因
- [x] 第一名未明显领先第二名 → 不归因（返回 null）
- [x] 无任何关联 → 返回 None，且**不崩溃**
- [x] 结果不随块顺序漂移，同一输入结果稳定
- [x] 无命中时不归因

### 9.4 学习回流（不伪造证据）

- [x] 普通提问只保存会话与弱信号，不改 `KpState`
- [x] 「我不理解」写入 `marked_confused` 弱事件，返回 `changes_mastery: false`
- [x] 追练候选只从**已有题库**取，不联网、不让模型造题
- [x] 候选按 `unseen → partial → not_mastered → due → mastered` 排序
- [x] 追练候选不创建 `PracticeItem`（只回答「还有哪些题可练」）
- [x] 未归因或该叶子没有在用题目时返回 `{"candidates": []}`

### 9.5 SSE 协议

> 帧序在 2026-09-20 变过一次（D-32）：原先把 citations 塞在 `done` 里，
> 现改为**独立 `citations` 帧**，因为引用卡要能定位真实资料（D-02/D-03 的验收要求）。
> 失败路径不变，仍是 `meta → delta* → error`。

- [x] 成功帧序为 `meta → delta… → citations → done`
- [x] 无命中时同样发一帧**空** `citations`（帧序不因分支而变）
- [x] `delta.seq` 从 1 递增
- [x] `citations` 帧可独立解析，每项含 `chunk_id` 等可定位字段
- [x] `done` 保留 `message_id`、`matched_kp`、`usage`、`followups`，并带**同一份** citations
- [x] `matched_kp` 归因依据随 `done` 下发（含 `attribution_label` 与 `cosine`）
- [x] 失败以 `error` 收尾，带 `code` 与 `retryable`
- [x] `error` 帧不含堆栈、绝对路径、连接串
- [x] 客户端断开：不发 `done`/`error`，消息标记 `cancelled` 并保留已收文本
- [x] 取消且完全无内容时不留空消息
- [x] 前端解析处理：汉字跨包、一帧多包、不完整尾帧、abort
- [x] 前端处理 `citations` 帧并在 `done` 到达后解除输入锁（不再卡在「正在生成」）
- [x] 引用卡点击可跳转 `/materials?material_id=…&chunk_id=…`，资料页把目标块补进预览并高亮
      （即使它不在前 20 块内，靠 `focus_chunk_id` 追加）

### 9.6 模式隔离

- [x] `user` 模式只检索用户上传资料，不得引用内置资料
- [x] `builtin` 模式检索内置资料
- [x] 会话的 mode 在创建时固定，不由历史消息跨库

### 9.7 数据库约束与迁移

- [x] `chat_sessions.mode` CHECK 生效（非法值被拒）
- [x] `chat_messages.role` CHECK 生效，且 `system` 被允许
- [x] `chat_messages.status` CHECK 生效
- [x] 列默认值与模型一致（`title`/`mode`/`content`/`status`/`metadata`）
- [x] `alembic check` 无差异；`alembic current` 在 head
- [x] 索引为 `(session_id, seq)`，无冗余单列索引

### 9.8 真实链路验证（打真实模型与真实接口）

- [x] 非流式 `/answers` 返回 `message_id/answer/citations/matched_kp_id`
- [x] 内置模式命中讲义：`matched_kp` 归因成功，引用带标题路径
- [x] 追问到「我的资料」范围时模型**明确说明资料未覆盖**，不编造
- [x] SSE 流式连续 3 次通过，帧序与 seq 均正确
- [x] 刷新页面后回答与来源仍在

### 9.9 阶段 D 命令验收记录

**最早一轮（非隔离，直接打开发库，已作废）**：

```powershell
python -m pytest                    # 353 passed
cd frontend; npm run typecheck      # 通过
cd frontend; npm run build          # 通过
cd frontend; npx playwright test    # 22 passed   ← 打开发库，会重置真实学习数据，不能再作为验收依据
alembic check                       # 无差异
```

**当前一轮（隔离模式，2026-09-20 实测）**：

```powershell
# 后端在同一次调用内启停；灌数据会彻底清空测试向量库并自检
python scripts\prepare_e2e_data.py --apply
#   完成：ready 资料 2 份，分块 17 个，向量库 17 条
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001   # APP_ENV=test
#   /api/health → {"environment":"test", ...}
python -m pytest                    # 408 passed（exit 0）
cd frontend; npm run typecheck      # 通过
cd frontend; npm run build          # 通过
cd frontend; npx playwright test --output=<临时目录>
#   28 passed (1.4m)，退出码 0
alembic check                       # 无差异
```

### 9.10 阶段 D 已知限制

- [x] 归因粒度受讲义标记影响（「等价无穷小」问题可能归因到「洛必达法则」）
      —— 阈值改为比**原始余弦**后该问题已消失：实测正确归因到「等价无穷小替换」；
      同时前端如实展示归因依据（见第 10.4 节）
- [ ] SSE 服务端主动超时的中间态未覆盖
- [ ] Docker 容器内验证仍未执行（本机无 Docker）
- [x] ~~e2e 直接打开发库~~ —— 已改隔离模式：后端必须 `environment == "test"`，
      否则夹具在任何业务请求前直接拒绝（见第 20 节）

## 10. 阶段 D 之后：三个遗留风险的收口（已实际运行验证）

### 10.1 内存压力（问题 1）

- [x] 项目自带 PostgreSQL（`.pgdata`，端口 5433）用 `ALTER SYSTEM` 收紧内存参数，
      并核对 `pg_settings` 中的**实际生效值**：
      `shared_buffers=4096`(×8KB=32MB)、`work_mem=1024`(1MB)、
      `maintenance_work_mem=32768`(32MB)、`max_connections=30`、`effective_cache_size=16384`(128MB)
- [x] 参数写入 `.pgdata/postgresql.auto.conf`，重启后用真实查询确认**数据完好**
      （资料 2 份 / 块 35 个 / 知识点 11 个 / 题库 22 题 / 会话 65 个，`alembic current` = head）
- [x] 新增 `scripts/check_test_env.py`，三种模式（默认提醒 / `--strict` / `--need-backend`）
- [x] `scripts/test.cmd` 第 0 步接 `--strict`；后端在跑时**跳过 pytest 并以非零码退出**，
      打印 `PARTIAL: ... 本次运行不能证明测试套件通过`（不允许把跳过当成通过）
- [x] 不自动杀进程（擅自结束用户正在用的服务比资源竞争更糟），只给明确指引

### 10.2 批处理脚本的中文与代码页（顺带修复）

- [x] `scripts/test.cmd` 改为**纯 ASCII**（原来同时有 `chcp 65001` 和中文，是解析隐患）
- [x] 行尾统一为 CRLF（`.gitattributes` 已声明 `.cmd` → CRLF）

### 10.3 Playwright 偶发失败（问题 2）

- [x] 定位到根因是前端两个真实缺陷，不是测试写法：
      `load()` 每次刷新都把整页切回 loading（`study-active` 被摘出 DOM）、
      `grade()` 无条件把用户从全卷弹回专注
- [x] 修复：`load()` 只在首次加载进 loading + 请求令牌丢弃过期响应；
      `grade()` 只在专注模式下才自动跳下一题
- [x] `playwright.config.ts` 的 `preserveOutput` 改为 `"always"`
      （默认 `on-first-retry` 且未开 retries ⇒ 失败产物全被丢掉，无法复盘）
- [x] 新增回落用例：用 `page.route` 把 `/api/plans/today` 延迟 1.5 秒放大刷新窗口，
      断言「刷新期间整卷始终在场」「不被弹回专注」——修复前必然失败
- [x] 原有用例在自评与切视图之间加入显式同步点，不再依赖默认 5 秒断言超时

### 10.4 归因依据展示（问题 3a）

- [x] 新增列 `chat_messages.matched_kp_basis`（JSON / NOT NULL / 默认 `{}`），
      迁移 `e54f60dca851`；存量 79 条消息全部补空对象
- [x] 归因重构为 `matched_kp_attribution()`，保留依据
      （来源块 / 命中名次 / 分数 / 累积分 / 次名累积分）
- [x] 三条出口一致返回：非流式 `answers`、SSE `done` 帧、消息列表
- [x] `attribution_label` 给出依据块的**引用编号**（如 `C1`），用户能在正文里对得上
- [x] 前端显示归因依据（`data-testid="attribution-box"`），只显示不计算
- [x] 真实链路验证：`kp_name` 为「洛必达法则」、`attribution_label` 为 `C1`、
      命中第 1 位；消息列表返回一致内容；**「我的资料」模式归因为 `None`**
- [x] 补契约漏洞：「我的资料」模式不再依赖「用户资料恰好没有 `<!-- kp: -->`」，
      而是在 `_search_pending` 里按模式显式清空归因

### 10.5 顺带修复的工程隐患

- [x] 测试库建表不再依赖「先跑迁移测试」：`tests/conftest.py` 增加会话级 autouse 夹具
      显式 `alembic upgrade head`（此前单独跑集成测试会大面积 `column does not exist`）

### 10.6 本轮命令验收记录

```powershell
python -m pytest                                        # 359 passed
python -m alembic upgrade head                          # b58f3c7e91a4 -> e54f60dca851
python -m alembic check                                 # No new upgrade operations detected
python scripts\check_test_env.py --strict               # 后端在跑时返回 1（用于 pytest 前置）
python scripts\check_test_env.py --need-backend         # 后端未跑时返回 1（用于 e2e 前置）
cd frontend; npm run typecheck                          # 通过
cd frontend; npm run build                              # 通过
cd frontend; npm run test:e2e                           # 24 passed（连续两次稳定）
```

### 10.7 本轮 e2e 结果

- [x] 新增用例「回答展示归因依据」（内置资料模式）通过
- [x] 回落用例「自评刷新期间整卷始终在场，且不会把用户从全卷弹回专注」通过
- [x] 学习流程用例改用「后端真实落库」作为同步点后不再偶发失败
- [x] 全量 `npx playwright test`：**24 passed**（54.1 秒，连续两次稳定）

### 10.8 两条偶发失败的真实来源（都已修）

用 `preserveOutput: "always"` 抓到失败现场后，确认「偶发失败」其实是两个独立原因：

- **前端刷新竞态**（D-16）：`load()` 每次刷新都把整页切回 loading，
  `study-active`（含全卷 `paper-list`）被摘出 DOM；`grade()` 又把用户从全卷弹回专注。
- **上游模型不稳定**（D-20 / D-21）：失败快照上的提示是 `answer generation failed`，
  后端日志为 `provider returned an empty answer`，手动复现还拿到 **HTTP 503**。
  同一请求手动重试即可成功。

重试策略（流式与非流式同一套判据）：

- [x] 本轮读完但一个新块都没有 → 重试一次
- [x] 本轮抛 429 / 5xx / 超时等可重试故障 → 重试一次
- [x] 4xx（鉴权、模型名错）→ **不**重试
- [x] **已经吐过内容之后失败 → 不重试**（否则残句后面会接上第二个完整回答）
- [x] `AppError` 增加显式 `retryable` 标记，不靠解析日志文案判断
- [x] `detail` 只放状态码与异常类名，不带上游响应正文与本机路径
- [x] 6 条测试锁住上述行为（含"已产出内容后不重试"这条曾抓住真实判据错误的用例）

**真正的根因（D-22）：推理模型的思考与正文共享输出预算**

直接打上游 API 才弄清楚：上游一直是好的（HTTP 200、内容正确、流式 117 帧），
问题是当前模型 `deepseek-flash` 会把**思考**（`reasoning_content`）与**正文**（`content`）
一起算进 `max_tokens`。实测：

- [x] `max_tokens=800`：三轮里有一轮**正文只剩 9 字**（思考 1217 字）
- [x] `max_tokens=100 / 40`：正文**恒为空**
- [x] `max_tokens=3000`：三轮正文全部完整
- [x] prompt 越长思考越长 ⇒ 这表现为「偶发」，其实**不是网络抖动**

已修：

- [x] `llm_max_output_tokens` 默认 800 → **4000**（`.env` 与 `.env.example` 同步）
- [x] 新增 `llm_retry_max_output_tokens = 8000`，首轮失败**以更大预算**重试一次
- [x] `Provider` 增加 `attempt` 与 `_token_budget()`；**重试预算不得小于基础预算**
- [x] 实际预算记进 `usage.max_tokens_used`，便于事后判断「是不是额度不够」
- [x] 只取 `content`，**绝不**把 `reasoning_content`（草稿）当正文发给用户
- [x] 3 条测试锁住预算语义（含「重试必须把 attempt=2 传下去」——
      漏传时不会报错、也不会有断言失败，只能显式检查）
- [x] 真实链路验证：连续 5 次问答 **5/5 成功**，回答字数 **362–399 字**，无截断

### 10.9 本轮明确未做 / 未验证

> ⚠️ **本小节写于第 10 节那一轮，其中「阶段 E 尚未开始」随后已被推翻**：
> 阶段 E 已完成收口（见 **第 18 节「阶段 E 验收清单」**）。保留原文以说明演进。

- [ ] Docker 容器验证（本机无 Docker，阶段 F）
- [ ] SSE 服务端主动超时的中间态
- [ ] 聊天 e2e 在开发库留下的空会话未清理（见 `reference-build-changes.md` D-19，
      不擅自删用户数据）
- [x] ~~阶段 E（前端完整验收）与阶段 G（冻结版本）尚未开始~~
      → **阶段 E 已完成（见第 18 节）**；**阶段 G（冻结版本）仍未开始**
- [ ] 上游模型配额/限流的**长期**稳定性不在本项目控制范围内：
      重试一次能吸收偶发抖动，但持续 503 时接口会如实返回 `generation_failed`

## 11. 用户指出的三条残留问题

### 11.1 归因阈值必须建在原始余弦上（D-23）

- [x] 实测确认 RRF 融合分**无法区分**相关与不相关：
      正常 0.0164~0.0328，越界 0.0315（越界比正常最低值还高）
- [x] 实测确认原始余弦**可以干净分开**：正常最低 0.5673，越界最高 0.3368
- [x] 确认旧阈值 `KP_MIN_SCORE = 0.01` 比所有实测值都低 ⇒ **从未生效过**
- [x] `RetrievalHit` 增加 `vector_score` / `fused_score`；检索服务不再丢掉向量原始分
- [x] 重排复制时不再静默丢弃这两个分（此前 `score` 被改写成重排分，融合分就没了）
- [x] 阈值改名 `KP_MIN_COSINE = 0.45`，比原始余弦
- [x] 纯关键词命中（无向量分）不归因
- [x] 融积分为正才归因（保留旧实现「零分不归因」的契约）
- [x] 归因依据落库并对外返回 `cosine`，前端显示「语义相关度 0.69」

### 11.2 非流式与流式的重试对称性（D-21 缺口）

- [x] `finalize_answer` 的空回答 `AppError` 补 `retryable=True`
- [x] `_complete_with_retry` 重试耗尽后的 `AppError` 同样补上
- [x] 同一原因不再出现「流式 503 / 非流式 500」的不对称

### 11.3 固定 sleep 换成真实同步点

- [x] `navigation.spec.ts` 逐题自评循环里的 `waitForTimeout(400)` 已删除
- [x] 改为 `page.waitForResponse(...)` 等那次真实刷新（GET `/api/plans/today`）

### 11.4 顺着发现的第四条：追练候选回溯历史归因（D-24）

- [x] `followup_candidates` 只认**最新这一条**回答的归因（此前会回溯历史）
- [x] `mark_confused` 同样只认最新回答（学习信号记错对象比不记更糟）
- [x] 前端按钮可用性由「有没有已完成回答」改为「**当前回答有没有归因**」
- [x] 补上此前**完全缺失**的测试：`tests/integration/test_followup_candidates.py`（7 条）

### 11.5 本轮验收记录

```powershell
# pytest 前置：先停后端（scripts\check_test_env.py --strict 会替你把关）
python -m pytest                        # 372 passed
cd frontend; npm run typecheck          # 通过
cd frontend; npm run test:e2e           # 24 passed
```

真实验证（打真实模型与真实库）：

- 越界问题「这个软件怎么安装到手机上 / 今天天气怎么样 / 推荐几部好看的电影」
  → 归因**无**、追练候选 **0 条**、困惑标记 **409**；
- 正常问题「洛必达法则的适用条件」→ 归因 0.6921、候选 5 条、可标记；
- 「加减结构能否替换等价无穷小」→ 归因**等价无穷小替换**（0.7439），
  第 12.5 节那条「会归到洛必达法则」的已知限制随之消失。

## 12. 问答页会话历史按资料范围分开（收口 D-19，见 changes D-25）

### 12.1 后端

- [x] `GET /chat/sessions` 新增可选 `mode`（`Literal["builtin","user"]`）
- [x] 响应字段未变（仍为 `session_id` / `title` / `mode`），不传 `mode` 即原行为
- [x] **空会话不再返回**（没有任何消息的会话不出现）
- [x] 非法 `mode` 返回 **422**，不会被当成「不过滤」
- [x] 归档语义不变（归档会话仍不出现，无论有没有消息）
- [x] 排序仍按 `updated_at` 倒序

### 12.2 前端

- [x] 切换资料范围与「＋」**不再立刻创建会话**，只开一段草稿
- [x] 会话推迟到 `send()` 里「用户真的发出第一条问题」时才创建
- [x] 创建失败时保留输入框内容，用户可直接重发，不用重打问题
- [x] 历史列表按当前范围过滤，每条仍保留模式小字（双保险）
- [x] 刷新页面回到「最近用过的那条会话的模式」，没有历史时停在草稿（不建会话）

### 12.3 数据清理

- [x] 新增 `scripts/archive_empty_chat_sessions.py`（默认**预演**，`--apply` 才写）
- [x] 用**归档**而非物理删除：归档后不在列表里，问答与引用记录仍可追溯
- [x] 一次性清理历史积压：预演 99 条 → 执行后未归档 48 条、**空会话 0 条**

### 12.4 本轮命令验收记录

```powershell
python -m pytest                                        # 380 passed（新增 8 条）
cd frontend; npm run build                              # 通过（含 vue-tsc） 
python scripts\archive_empty_chat_sessions.py           # 预演：99 条空会话
python scripts\archive_empty_chat_sessions.py --apply   # 归档 99 条
```

真实后端验证：

| 请求 | 结果 |
|---|---|
| `GET /api/chat/sessions` | 48 条（builtin 28 + user 20） |
| `GET /api/chat/sessions?mode=builtin` | 28 条，只含 builtin |
| `GET /api/chat/sessions?mode=user` | 20 条，只含 user |
| `GET /api/chat/sessions?mode=x` | **422** |

### 12.5 本轮明确未验证

- [ ] `npx playwright test chat.spec.ts` —— 本会话**未能执行**（命令被沙箱拦截、权限被拒）。
  `chat.spec.ts` 里两条依赖旧行为的用例已改写为新契约，并新增一条范围过滤用例，
  但**必须由后续会话补跑**后才算收口。

## 13. 问答的教学回路（见 changes D-26）

### 13.1 追问引导（提示词）

- [x] `backend/chat/service.py` 的 `SYSTEM_PROMPT` 分【不可违反】与【教学方式】两段
- [x] 问题含糊时先问清最关键的一点，不凭猜测长篇作答
- [x] 多步推理一次只讲一步，讲完停下问是否继续
- [x] 用户说「不懂」时**换一种讲法**（换例子、换对比、拆更小的子问题），不原样重讲
- [x] **硬约束**：澄清 / 只讲一步 / 换讲法时**仍必须带 `[C#]` 引用**（引用校验依赖它）
- [x] SSE 与非流式共用 `_prompt()`，教学约束只写一处

### 13.2 理解确认闸门（前端）

- [x] 新增「我明白了」；练习入口改为 `有归因 && 已确认理解` 才可用
- [x] 归因已存在但未确认理解时，练习入口**禁用**（不再刚看完讲解就能推题）
- [x] 确认理解后，练习入口才可用，并显示「要不要从已有题库里挑几道练一下？」
- [x] 没有归因时点「我明白了」不给练习入口，而是**如实说明原因**
      （「我的笔记」模式按契约不推荐练习，不能给一个点下去会 409 的按钮）
- [x] 「我不理解」提示补「继续追问一次，我会换一种讲法」，与追问引导衔接
- [x] 换会话 / 开新草稿 / 提新问题时重置「已确认理解」
- [x] 闸门**只是界面推进**，掌握度、毕业证据、困惑信号仍全部由后端决定

### 13.3 本轮命令验收记录

```powershell
python -m pytest              # 380 passed
cd frontend; npm run build    # 通过（含 vue-tsc --build）
```

- [x] 构建产物中可检索到新文案（`我明白了`、`先确认“我明白了”，再决定要不要练`）

### 13.4 本轮明确未验证

- [ ] `npx playwright test chat.spec.ts` —— 与 12.5 同因**未能执行**。
  已把原「模式隔离」用例改写为「练习入口必须先确认『我明白了』」，
  断言「无回答时三个入口可见但禁用」+「归因已存在时练习入口仍禁用 → 确认后才启用」。

## 14. 删除入口移到每条会话旁边（2026-09-20）

### 14.1 契约与实现

- [x] 每个会话行旁边有 × 删除按钮（`button.conversation-delete`），右上角不再有「归档」。
- [x] 未把 × 嵌进原会话 `<button>` 内（嵌套 button 属非法 HTML）——
      改为同级：`div.conversation-row` 下并排放「会话按钮」与「× 按钮」。
- [x] `archiveSession(target)` 可删**任意一条**；删的是当前打开的那条 → 自动切下一条，
      无剩余则回到空白草稿。
- [x] 生成中（`sending`）删除按钮禁用，避免删到正在写入的会话。
- [x] 误点保护：保留 `window.confirm`，文案明确「会从列表移除，但问答与引用记录仍保留在库里」。
- [x] 死代码清理：`.danger-button` 样式删除前已确认全仓仅此一处引用。

### 14.2 语义边界

- [x] 前端按钮叫「删除」，后端当时仍是**归档**（`DELETE /chat/sessions/{id}` 只置 `archived_at`）。
- [ ] ⚠️ **本节写作时的这句话当天即被推翻**：用户随后明确要求「后端也把会话记录删掉」，
      后端已改为**物理删除**。以 **§16（D-31）** 为准，本节仅作历史记录保留。

### 14.3 本轮命令验收记录

```powershell
cd frontend; npm run build    # 通过（含 vue-tsc --build）
npx esbuild e2e/chat.spec.ts  # 转译成功（exit 0），确认 e2e 语法无误
```

### 14.4 本轮明确未验证

- [ ] `npx playwright test chat.spec.ts` —— 本机服务当时全停（PG/后端/前端均无响应），
      且该命令此前已被沙箱拦截，**未能执行**。本轮新增两条 e2e 已写好但未跑：
      (1) 结构断言：右上角无归档入口、每个会话行恰好一个 ×、× 带 `aria-label`；
      (2) 行为断言：**只删用例自建的会话**（造会话 → 等生成结束 → 点首位 × → 接受确认框
          → 断言总数回到 `before`），避免误删开发库里用户的真实对话。
      补跑状态见 §16.4。



## 15. 教学能力三处改动（追问引导 / 理解确认关卡 / 多轮预算）

### 15.1 追问引导（只改提示词）

- [x] 教学约束写进 `SYSTEM_PROMPT`，由 `_prompt()` 统一使用
      （SSE 与非流式共用同一处，改一次两处生效）
- [x] 问得含糊先澄清：提示词含「先用一句话问清最关键的那一点」
- [x] 长解答只给一步：「一次只讲一步，讲完明确停下问一句是否继续」
- [x] 说「不懂」换讲法：「不要原样重讲一遍」，改为换例子/对比/更小的子问题
- [x] **引用硬约束**：显式写明「即使只是澄清问题、只讲一步、或换一种讲法，
      也必须带上 `[C#]` 引用」
- [x] 拒答底线未被挤掉（资料不足要说明、不能编造来源）
- [x] 防回归：整个模块里 system 消息只被构造一次（不容许再写第二份）
- [x] 行为测试：模型只回澄清问句且不带引用时，回答保留、**来源为空**、记
      `citation_warning = no_valid_citation`（绝不伪造来源）
- [x] 反向测试：澄清式回答只要带了引用，归因与引用落库照常工作

### 15.2 理解确认关卡（只改前端时序）

- [x] 回答下方由三个平级按钮改为**中性二选一**：`我明白了，想练几道` / `还是不太懂`
- [x] 点「我明白了」→ 直接取追练候选并展示（不再要求多点一次）
- [x] 点「还是不太懂」→ 记弱信号 + 提示「换一种讲法」
- [x] 两个分支互斥；先确认理解后又点「不太懂」时收起练习入口
- [x] 没有归因时如实说明原因，不给点了会 409 的按钮
- [x] 后端**未改动**（两个接口都已在跑）
- [x] 重置逻辑收敛为 `resetComprehensionGate()`，4 个调用点统一
      （原先散在 4 处，加状态时漏一处就会串状态）
- [x] e2e：干净会话上二选一禁用且练习入口不存在 → 确认后卡片出现、入口退场
- [x] e2e：选「还是不太懂」不推题、提示换讲法、练习入口不出现

### 15.3 多轮上下文预算

- [x] 新增 `llm_history_token_budget`（默认 1200），替换写死的「最近 10 条」
- [x] `estimate_tokens()`：CJK≈1 字 1 token、其余≈4 字符 1 token，**向上取整**
- [x] `select_history_within_budget()`：最近优先、整条进或整条不进、返回正序
- [x] 单条超预算时**跳过它继续往前找**（不截半、也不因此丢掉更早的上下文）
- [x] 不引 tokenizer（避免部署依赖与联网下载词表）
- [x] 「未传预算即用配置值」下沉到 `_search_pending` 内部，调用点漏传不会静默关掉历史
- [x] 测试：超预算丢最旧、单条超预算跳过、顺序正序、0 预算关闭历史、配置默认值为正

### 15.4 本轮验收记录

```powershell
# 前置：先停后端（scripts\check_test_env.py --strict 会把关）
python -m pytest                        # 403 passed
cd frontend; npm run typecheck          # 通过
cd frontend; npm run test:e2e           # 28 passed
```

## 16. 会话删除改为物理删除（见 changes D-31，2026-09-20）

### 16.1 后端语义

- [x] `DELETE /chat/sessions/{id}` 由**归档**改为**物理删除**（用户明确要求）。
- [x] 按依赖顺序逐条删：`message_citations` → `chat_messages` → `chat_sessions`。
- [x] **不依赖数据库级联**：模式里声明的 `ON DELETE CASCADE`（迁移 `9b7f1d3e2c6a`）虽在，
      但显式删除换库/重建约束时不会静默留孤儿行。
- [x] 路由函数 `archive_session` → `delete_session`。
- [x] 删掉随之无用的顶层 `datetime` / `timezone` 导入。
- [x] **不删学习事件**：`learning_events.source_id` 故意无外键，掌握度/弱信号不因会话删除而消失
      （代价：那几条 `source_id` 变悬空 id，schema 本就允许）。

### 16.2 前端

- [x] `archiveChatSession` → `deleteChatSession`；`archiveSession` → `deleteSession`。
- [x] 确认框把话说死：「**此操作不可恢复**：该会话的问答记录与引用会被永久删除。」
- [x] × 的 tooltip 加「（不可恢复）」。

### 16.3 测试与实测

- [x] 新增 4 条后端测试（见 `tests/integration/test_chat_sessions.py`）：
      三张表清空不留孤儿引用 / 不误伤别的会话 / 第二次删返回 404（不可逆） / 删不存在的 id 返回 404。
- [x] 真实后端 + 真实 PostgreSQL 实测：建会话 201 → `DELETE` **204** →
      库里 `chat_sessions` 行消失且 `chat_messages` **0 条** → 重复 `DELETE` **404**。
- [x] `python -m pytest` 全量 **407 passed**。
- [x] `npm run build`（含 `vue-tsc --build`）通过。

### 16.4 e2e 状态

- [x] `npx playwright test chat.spec.ts -g "删除"` → **1 passed**（结构断言：右上角无归档入口、
      每个会话行恰好一个 ×、× 带 `aria-label`）。
- [x] `npx playwright test chat.spec.ts -g "×"` → **1 passed**
      （行为断言：造会话 → 等流结束 → 点首位 × → 接受确认框 → 总数回到 `before`）。
      即在浏览器里确认真删除链路成立。
- 说明：该 e2e 的 `reset_today` 夹具会**重置开发库当日学习数据**（这是既有夹具行为，非本次改动引入）。

### 16.5 顺带修掉的文档缺陷（编号撞车）

- [x] 同一提交 `5bb3d2f` 产生了**两套** D-25/D-26/D-27（changes 文档）与**两个 §12**（本文件）。
      已把后写的那套改号为 **D-28~D-30**，本节checklist的小节改号为 **§15**，内容一字未动。
      原因：ID 重复会让「详见 D-25」同时指向两个不同条目。

## 17. D-02 / D-03 引用帧与可定位引用卡（2026-09-20）

- [x] 成功 SSE 顺序锁定为 `meta → delta* → citations → done`；无命中同样发空 citations 帧。
- [x] `citations` 帧 JSON 可独立解析，且每项含 `chunk_id`。
- [x] `done` 保留 `message_id`、`matched_kp`、`usage`、`followups` 与同一份结构化 citations。
- [x] 引用卡展示资料名称、标题路径、块序号、摘要、稳定 chunk 标识和引用编号。
- [x] 点击引用卡可进入资料页并定位/高亮真实 chunk；不依赖摘要反查。
- [x] 刷新会话后，消息接口恢复同一份结构化引用字段。

## 18. 阶段 E 验收清单（前端完整验收，2026-09-21）

### 18.1 规格第 17 篇 §5 的覆盖情况

- [x] **统一 API client**：`src/api/client.ts` 一处收口（含 `signal` 透传与
      `AbortError` 原样抛出）；`health.ts` 复用它，不再自带第二套 fetch/解包。
- [x] **28 个规格 testid**：四个页面按 §5 命名，`navigation.spec.ts` 逐页断言。
- [x] **错误码页面行为（§2.5）**：`error-codes.spec.ts` 7 条，覆盖
      `plan_already_generated` / `question_pool_incomplete` / `kp_state_not_found` /
      `practice_item_already_assessed` / `practice_item_not_found` /
      `plan_not_active` / 未列出 code 的兜底。
- [x] **十态状态矩阵**：`state-matrix.spec.ts` 27 条，四页 × 十态
      （initial / loading / empty / success / validation-error / server-error /
      network-error / retrying / submitting / refreshed），全部 `page.route` mock，
      不依赖后端数据。
- [x] **浏览器前进后退**：`history.spec.ts` 4 条。
- [x] **窄窗口**：`viewport.spec.ts` 6 条（375×667 与 768×1024）。
- [x] **OpenAPI 类型生成 + 漂移校验**：`scripts/export_openapi.py` →
      `frontend/openapi.json`（23 端点）→ `src/api/types.ts`；
      `scripts/check_openapi_drift.py` 3 项检查全通过。

### 18.2 本轮修掉的真实缺陷（由 e2e 实测暴露）

- [x] 资料页加载中就渲染「还没有资料」空态（空态条件没考虑 loading）。
- [x] 资料页后端不可达时错误态不渲染（只看 `errorCode`，漏了网络失败的 `null`）。
- [x] 资料页 URL **只读不写**（有 `useRoute` 没有 `useRouter`）：选中后刷新丢失、
      深链接失效、前进后退恢复不了。
- [x] 知识点详情缺字段 → `Object.keys(undefined)` 抛未捕获异常 → **整块白屏**。
- [x] embedding 模型已缓存却仍联网探测 → 问答首字延迟 20~180 秒
      （`local_files_only=True` 修复；修复后日志里 huggingface 探测 0 次）。

### 18.3 命令验收记录（都是本轮真实执行）

```text
python -m pytest                          # 408 passed（25 个文件，退出码 0）
python scripts\check_openapi_drift.py     # 3 项检查通过（23 个端点）
cd frontend; npm run typecheck            # 通过（vue-tsc --noEmit，退出码 0）
powershell -File scripts\run-e2e.ps1      # 72 passed (2.5m)，退出码 0
```

e2e 报告里被点名的关键条目：

```text
ok  2 chat.spec.ts:42  新建对话先只开一段草稿，发出第一条问题后才进入历史 (25.2s)
ok 18 history.spec.ts  选中资料写入 URL，切换资料可后退回去，后退离开页面、前进再恢复详情
ok 52 state-matrix     /knowledge success：树渲染出节点，点击叶子打开详情
ok 56 state-matrix     /materials loading：显示加载态，不先闪空态
ok 60 state-matrix     /materials network-error：后端不可达时报错，不卡在加载中
ok 72 viewport.spec    768×1024：四个页面都不横向溢出
```

### 18.4 本轮明确未做 / 未验证

- [ ] **阶段 F（Docker Compose）未真实启动过**：本机没有 Docker，
      配置只做过静态校验。`docker compose up --build` 必须由后续会话补跑。
- [ ] **阶段 G 未开始**：全量回归 + 人工浏览器验收 + 冻结 tag
      `reference-project-verified-v1`。
- [x] **统一状态完全收敛**：四页（`/study` `/knowledge` `/materials` `/chat`）的异步动作
      全部走 `useAsyncTask`，页面不再各自维护 state/errorCode/errorMessage 三件套。
      详见状态文档 §25。`/chat` 的 `sending` 例外保留为页面状态 —— 它是 SSE 流的过程标志，
      与「一次请求的 submitting」语义不同。
- [ ] **窄窗口只验到 375×667**：没有覆盖真机（iOS Safari / Android Chrome）
      与横屏；也没有做触控手势相关的验证。
- [ ] **e2e 存在基础设施级偶发，「72 passed」不是每轮都能复现**（2026-09-21 独立复核补充）。
      复核者在没有并发进程的情况下连跑两轮：一轮 **71/72**、一轮 **72/72**；
      加上本轮提交时那一轮，三轮里有一轮带假失败。失败始终是同一类：

      ```text
      Error: browserContext.close: ENOENT: no such file or directory, open
        '...kaoyan-e2e-output\.playwright-artifacts-0\traces\...-recording104.trace'
      ```

      `error-context.md` 里**没有任何断言失败**，只有这一条 —— 产品行为是对的，
      失败发生在「关闭浏览器上下文并落 trace」这一步。可疑原因是
      `playwright.config.ts` 的 `preserveOutput: "always"` 叠加
      `trace: "retain-on-failure"`：它为**每个**用例保留产物，加剧
      `.playwright-artifacts-N` 目录轮转，而轮转会清掉仍在写入的 trace 目录
      （沙箱的删除实现是「移入回收站」而非真删，可能加重这个竞争）。
      **收口前应连跑 3 轮报出真实波动，并把 trace/preserveOutput 调稳**；
      若要吸收此类 flake 而开 `retries`，必须在记录里写明「发生了重试」，
      不能让它悄悄改变结论。
