# 工程验收缺口补验报告

日期：2026-10-18  
范围：只补验上一轮跳过项、隔离生题持久化、隔离角色读取权限与部署环境状态。  
结论：`ENGINEERING_GAPS_CLOSED_WITH_EXTERNAL_ENV_LIMITS`

## 结论摘要

- 两个原后端 skip 已在明确的 PostgreSQL 18 环境和新建临时集群中实际执行，所在两个测试文件合计 **34 passed，0 skipped**。
- 原 7 个浏览器 skip 的行为覆盖已补齐：6 个需要数据回放的场景通过；1 个旧“在问答页显示资料归因片段”的契约与当前产品决定相反，因此保留旧 skip，并以新的主动回归验证“引用证据仍由接口传递/保留、问答页不展示资料片段”。
- 奶蛙生题的 Vue → FastAPI → 隔离 PostgreSQL 持久化闭环通过。Provider 使用冻结离线响应，**真实收费请求 0 次**。
- 在隔离桌面运行角色 `kaoyan_app` 下，对 5 张关键表的 SELECT 能力检查通过。没有连接或修改真实开发库；因此本轮不宣称已确认真实库当前权限。
- Docker Engine 不可连接，本轮未执行 Compose build/up。
- 工作区原本有大量未提交及未跟踪文件。本轮没有清理或覆盖它们；报告落盘后的精确 `git status --short --untracked-files=all` 统计为 3087 条状态项，其中 2660 条为未跟踪项、427 条为其他状态项。

## 1. 上轮报告与基线

已读取并以实际产物为准：

- `storage/quality-audits/project-repair-20261018/backend/full-final-confirmed/junit.xml`
- `storage/quality-audits/project-repair-20261018/browser/20261018-091110/summary.json`
- `storage/quality-audits/project-repair-20261018/browser/20261018-093903/summary.json`
- 对应 Playwright `run-report.json`
- 历史只读权限记录 `storage/quality-audits/phase5-closeout-execution-20261015/real-readonly/permission-and-readonly-result.json`

基线后端为 2812 passed、0 failed/error、2 skipped；基线完整浏览器为 227 passed、0 unexpected、7 skipped。现有权限记录只证明 2026-10-15 曾完成四张表的 SELECT 授权，不能替代本轮对真实库的检查。

## 2. 原 7 个浏览器 skip 的逐项处理

| 原跳过用例 | 原因 / 代码位置 | 本轮处理与结果 |
|---|---|---|
| `资料检索回答展示归因依据：知识点名 + 引用编号` | `frontend/e2e/chat.spec.ts` 原用例约第 421 行；旧测试要求问答页显示引用片段，与用户当前要求移除资料依据面板和片段展示冲突 | 原 skip 保留，不伪造可见归因。新增 `RAG检索证据由服务端保存，但问答页不展开引用片段`，主动验证 SSE/会话恢复和“不展示片段”的现行 UI 契约；Chat 专项浏览器结果 13 passed、此旧 skip 仍为 1。真实持久化引用由此前后端 chat 集成回归覆盖，本轮新浏览器测试本身是协议/UI 回归，不冒称真实资料库写入测试。 |
| `explicit five-item request reports actual saves and supports study/history without paid calls` | `frontend/e2e/phase45i-close-live.spec.ts:3`；要求专用隔离库及冻结 Provider | 已通过 Phase45I 专用隔离浏览器运行器执行，**7 passed**（含该场景），冻结 Provider 5 次、真实收费调用 0 次。 |
| `模拟生成真实业务捕获：original来源与专注全卷` | `frontend/e2e/question-generation-pilot.spec.ts:12`；依赖本地 C1 捕获报告 | 使用已有 `phase45c1-20261008/validated-replay/report.json` 回放，最终 **passed**。断言改为调用当前 `questionSourceLabel()`，验证现行“原创”标签，而不是过时的长标签。 |
| `模拟生成真实业务捕获：adapted来源与专注全卷` | 同上 | 使用原捕获回放，最终 **passed**，现行来源显示与“真题改编”规则一致。 |
| `模拟生成真实业务捕获：completion来源与专注全卷` | 同上 | 使用原题 `parent_question_id` 回放；旧测试错误寻找不存在的 `ISOLATED_COMPLETION_APPLIED` 状态。修正对象 ID 后最终 **passed**。 |
| `隔离真实题API回放：有界客观反馈与专注全卷` | `frontend/e2e/question-repair-pilot.spec.ts:12`；依赖本地私有 B3 捕获 | 使用已有 `phase45b3-20261008/validated-replay/report.json`，最终 **passed**。 |
| `隔离真实题API回放：参考用途未判定与专注全卷` | 同上 | 使用原捕获回放，最终 **passed**；参考用途继续显示未判定，没有变成正确/错误判定。 |

5 个 C1/B3 回放总计 **5 passed，0 failed**；使用旧资料但校验现行来源标签映射，没有生成、导入或修改题目。问答页原旧 skip 仍留在报告中是有意的产品契约替换，不是未处理的功能缺口。

## 3. 原 2 个后端 skip 的逐项处理

原因均为测试要求显式 Windows PostgreSQL 18 二进制路径，上一轮 runner 未给到该专用环境。

| 用例 | 原位置 | 本轮结果 |
|---|---|---|
| `test_owned_pg_first_boot_restart_preservation_and_backup` | `tests/integration/test_managed_postgres.py:22` | 用 `C:\Program Files\PostgreSQL\18\bin` 在 OS 临时目录创建自有集群，执行首次启动、重启、备份与恢复路径，最终所在测试文件通过。 |
| `test_managed_cli_preflight_with_real_binaries_remains_readonly` | `tests/unit/test_desktop_server.py:155` | 在 OS 临时根目录用同一 PG18 二进制完成只读 preflight，不创建用户数据目录，最终所在测试文件通过。 |

明确指定两个测试文件后的最终记录：**34 passed in 25.87s，0 skipped**。runner 报告 `original_cluster_touched=false`、`temporary_postgres_stopped=true`、`owned_temporary_data_removed=true`。因此这两项不再是环境阻塞。

根因及最小修复：

- 桌面数据目录放在仓库资源根目录下会被安全校验拒绝。测试夹具现将可变数据放在 OS 临时目录。
- Windows PostgreSQL 对中文数据路径的文本输出可能与 Python UTF-8 解码不一致。`desktop/postgres.py` 现在严格尝试 UTF-8 与 Windows 本地代码页解码 `postmaster.pid` 并验证 PID、标准化数据目录、端口；建库前复核已捕获的同一实例身份，不再通过解码 `SHOW data_directory` 来判定。拒绝替换字符或不匹配身份，未弱化目录归属检查。

## 4. 奶蛙生题持久化闭环

在新的隔离浏览器数据库 `phase45i_close_browser_cc09e50f_test` 中通过真实 Vue 页面、真实 FastAPI 路由和真实 PostgreSQL 表执行。服务端生成器使用冻结 Provider；外网守卫记录 0 次网络尝试。

| 验收点 | 隔离执行结果 |
|---|---|
| 明确请求生题、先选并确认知识节点 | 通过。测试实际点选“确认知识点并生成”；未把自然语言请求当作确认。 |
| Question / QuestionVersion 持久化 | 通过。Question 的 `kp_id` 有值；QuestionVersion 内容 hash 有效。5 次冻结 Provider 调用最终保存 1 道通过检查的个人题。 |
| 生题成功不自动追加 | 通过。生成后个人题已保存，PracticeItem 仍只有预置的一项，个人题 PracticeItem 绑定数为 0。 |
| 用户明确加入后才创建 PracticeItem | 通过。按钮点击返回 `added=1`；新 PracticeItem 绑定生成题当时的 QuestionVersion 与同一 `kp_id`。 |
| 重复加入幂等 | 通过。再调用追加接口返回 `added=0`，PracticeItem 总数不增加。 |
| 重放相同生成请求 | 通过。冻结 Provider 调用仍为 5 次，Question 仍为 1 道，没有重复生成。 |
| 判题与历史 | 通过。提交答案结果为正确；QuestionAttempt、LearningEvent 均引用练习实例所绑定的版本；LearningEvent 为 weak evidence。刷新页面后全卷仍能读到提交状态。 |
| 版本保护 | 通过。隐藏题目后当前 Question 进入 v2，但原 PracticeItem、Attempt、LearningEvent 仍指向作答时 v1，v1 内容版本仍存在。 |
| 毕业资格隔离 | 通过。该题 `evidence_capability=personal_practice_only`；节点仍为 `unseen`，无 `mastered_at`、strict evidence 为 0。 |
| 节点题库统一展示 | 通过。节点题库显示“AI练习”来源标签；隐藏操作后列表消失。其他前端题库测试同时覆盖恢复、搜索和显式加入。 |

结果文件显示：后端针对性用例 **35 passed in 23.18s**；专用浏览器 **7 passed in 12.2s**；`new_paid_calls=0`、`blocked_network_attempts=0`、`development_5433_touched=false`。这是真实业务代码和真实隔离 DB 的持久化验收，但不是 DeepSeek 内容质量验收。

## 5. 关键数据权限

新增/运行的 `test_runtime_role_can_read_question_versions_reviews_sets_and_personal_batches` 在隔离桌面运行角色 `kaoyan_app` 下，以 `has_table_privilege(current_user, ..., 'SELECT')` 检查：

- `question_versions`
- `question_auto_review_events`
- `question_answer_verification_events`
- `kp_graduation_question_set_versions`
- `personal_generation_batches`

五表都存在且 `current_user` 有 SELECT，权限专项文件 **35 passed in 25.09s**。该 runner 的连接串来自 `ManagedPostgres.database_url`，其账号是 `kaoyan_app`，不是 postgres 超级用户。

本轮没有连接 `127.0.0.1:5433/kaoyan`，也没有执行真实库 GRANT。2026-10-15 历史权限报告只记载当时四表 SELECT 授权；真实开发库当前角色和第五张关联表的实时权限仍需在另行授权的只读窗口确认。本轮没有发现需要数据库迁移或改 API 契约的问题。

## 6. 用户旅程复核

- 问答页在隔离 PG18 下针对运行：**13 passed、1 个旧展示用例 skipped**；新增当前契约用例通过，回答和会话刷新恢复正常，页面不展示引用片段。
- C1/B3 捕获页面回放：**5/5 passed**，覆盖原创、真题改编、完成题、受限判题和参考用途未判定的来源/反馈呈现与专注全卷。
- 今日学习与奶蛙助手专用隔离浏览器：**7/7 passed**，覆盖确认知识点、生题保存与预览、显式加入、判题、版本绑定、历史恢复和题库入口。
- 其余知识树、资料库、设置、通用聊天等整站场景沿用上一轮完整浏览器基线 227 passed；本轮没有重复无差别跑整套。新增测试在可疑边界上补验；本轮没有用离线回放冒充真实资料库、真实模型质量或真实开发库写入。

问答引用方面，本轮新加的是浏览器展示边界回归（用完整 SSE 引用字段夹具），并非新的真实资料索引问答；此前后端数据库/RAG 集成测试结果沿用既有报告。资料检索质量和 DeepSeek 回答质量不在本轮离线验收结论内。

## 7. Docker 与部署

只读探测结果：Docker daemon pipe `npipe:////./pipe/dockerDesktopLinuxEngine` 不存在，`docker info` 连接失败。标记为 **`DOCKER_DEPLOYMENT_NOT_VERIFIED`**；没有安装、启动服务或尝试绕过权限。

## 8. 本轮修改及工作区保护

本轮验收相关改动：

- `desktop/postgres.py`：严格支持 Windows 本地代码页读取 Postmaster 身份，并复核实例身份。
- `tests/integration/test_managed_postgres.py`：测试数据目录移出仓库资源根，保证临时目录清理。
- `frontend/e2e/phase45i-close-live.spec.ts`：生题闭环实际点击知识节点确认、等待追加响应、按无障碍状态验收、检查各历史实体绑定。
- `scripts/phase45i_close_browser_backend.py`：只在测试 stats 中列出全部个人题版本，避免隐藏操作推进 current version 后漏查历史事件版本。
- `scripts/run_phase45i_close_tests.py`：只读兼容查看 f49 前版本测试账本，避免以当前 ORM 查询旧 schema 时误报列不存在。
- `frontend/e2e/chat.spec.ts`：新增现行问答展示边界的主动回归；保留相反的历史用例 skip。
- `frontend/e2e/question-generation-pilot.spec.ts`、`frontend/e2e/question-repair-pilot.spec.ts`：沿用实际来源标签映射，修正旧快照长标签及 completion parent ID。
- `tests/integration/test_personal_question_bank.py`：增加 `kaoyan_app` 五表只读权限回归。

工作区状态很大（全量 porcelain 3087 条，2660 条未跟踪）；多个相关测试/运行器本身显示为未跟踪文件，不能据此认定它们是本轮新建或归属本轮。没有 reset、clean、强制覆盖、commit 或 push；除上面列出的验收点外均未整理或删除工作区文件。

## 9. 剩余交付风险与下一步优先级

1. **真实库权限的实时确认仍未完成**：本轮按约束没有连接 5433。历史授权记录 + `kaoyan_app` 隔离权限回归提供了证据，但不等同于当前真实开发角色实时权限。
2. **Docker 部署未验证**：当前机器的 Docker Engine 不可用；需要在 Engine 可用时再做最小 Compose health check。
3. **真实 DeepSeek 生题质量未测**：本轮是冻结 Provider 和离线网络守卫；生题持久化、版本绑定与业务控制通过，不证明在线模型答案质量。
4. **题目内容回放范围有限**：5 个 C1/B3 浏览器回放只检查前端业务呈现与判题反馈，不重新审查、扩充或导入题库内容。

除以上外，本轮要求中可在隔离环境安全完成的跳过项、持久化链路与角色权限检查均有通过证据。没有发现需要新迁移、真实数据库变更或毕业规则改动的阻塞问题。

## 证据目录

- `storage/quality-audits/phase5-skip-followup-20261018/backend-skips-explicit-final/`
- `storage/quality-audits/phase5-skip-followup-20261018/app-role-permissions/`
- `storage/quality-audits/phase5-skip-followup-20261018/personal-generation-persistence-final6/`
- `storage/quality-audits/phase5-skip-followup-20261018/chat-browser/`
- `storage/quality-audits/phase5-skip-followup-20261018/captured-question-replays-final2/`
