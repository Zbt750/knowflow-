# 今日学习、知识树及题量查询性能修复

日期：2026-10-16

## 结论

已实际修改读取链路并完成隔离验证。问题确实存在：不是路由打不开，而是重复资格计算、ORM 懒加载和逐节点查询导致请求长时间占用 Python CPU。

本次没有增加跨请求的毕业资格/学习状态缓存，没有修改毕业算法、题目资格规则或数据库模型，也不需要数据库迁移。首次隔离验证没有重启真实服务；用户反馈实际页面仍慢并明确批准重启后，已让修复在实际 8000 后端生效，见第 9 节。

## 1. 实际根因与修复

### 批量读取代替 N+1

新增 `backend/services/study_read_context.py`，在一次请求内批量读取策略、学习状态、历史活动标识、冻结题集及题目版本身份。原来的 `policy_for_node` 和题集完整性检查仍然逐节点执行同一套判断，只是不再每次独立访问数据库。

知识树、今日推荐、题量查询均预加载题目审核事件；知识点的 children 关系也统一预加载。传入已有策略给毕业后练习读取，避免再次解析和查询。

请求上下文不用于写入或首次题集绑定；尝试在该模式绑定学习者会直接拒绝。下一个请求重新取数，新增作答、题目撤回或新学习活动不会因为全局缓存而被忽略。

### 复用纯计算，不缓存信任结论

选项重复检测会反复解析相同常数表达式并进行 SymPy 化简。现在对有长度/数量上限的完整输入添加有界 LRU 缓存，并在精确的零/非零性质可判定时省去通用化简；无法判定时仍走原来的符号化简。不采用浮点近似。

缓存键包含完整表达式、全部选项及顺序；改变选项会重新计算。缓存返回不可变内部结果，外部调用取得新的列表，不能修改共享缓存。

题量查询同一次请求复用已得到的资格评估，避免为统计 blocking reasons 再跑一次。

没有缓存 `question_eligibility` 结论，没有以时间 TTL 代替审核 hash/版本检查，也没有缓存用户证据或毕业状态。

## 2. 修改文件

生产读取路径：

- `backend/api/routes/study.py`
- `backend/services/study_read_context.py`
- `backend/services/question_availability.py`
- `backend/mastery/storage.py`
- `backend/services/policy_evidence_service.py`
- `backend/services/graduation_question_set.py`
- `backend/services/post_graduation_service.py`
- `backend/services/constant_expression.py`
- `backend/services/question_production_pipeline.py`

离线测试辅助：`scripts/run_learning_agent_eval.py`、`scripts/run_agent_evidence_journey.py`。旧协议替身把工具压缩后的 `$records` 当作普通列表，产生 TypeError 并误报 Provider 失败；现在复用现有 `expand_records` 解码。没有改真实 Agent Prompt、工具证据或评分规则。

新增回归：`tests/unit/test_study_read_performance.py`、`tests/integration/test_study_read_context.py`、`tests/unit/test_protocol_provider_context.py`。

复现工具：`scripts/benchmark_study_reads.py`、`scripts/serve_study_read_probe.py`、`scripts/probe_study_performance.cjs`。这些工具明确限制到本次所有者已核验的 59328 隔离实例，不是生产启动脚本。

## 3. 测量环境与性能结果

隔离实例：`127.0.0.1:59328`，system identifier `7697254894074424952`。从已有独立备份恢复，不读取原开发库。

副本有 1935 条 Question、2322 个 QuestionVersion、1804 个正式审核事件，28 个 Attempt、29 个 LearningEvent、284 个 KpState、10 个 DailyPlan、87 个 PracticeItem。接口扫描 1913 道活跃题。冻结题集版本表 254 行包含历史版本，不等同于当前题集数量。

同一副本、固定时间、同样开启 cProfile 的前后比较：

| 接口 | 修复前 SQL 次数 | 修复后 SQL 次数 | 修复前耗时（含分析器） | 修复后耗时（含分析器） |
| --- | ---: | ---: | ---: | ---: |
| knowledge/tree | 4256 | 16 | 13.41 s | 3.44 s |
| plans/today（无当日卷的推荐路径） | 3257 | 14 | 12.37 s | 2.24 s |
| question-availability | 3333 | 16 | 19.31 s | 2.39 s |

关闭 cProfile 后，在新 Python 进程执行三个真实路由函数的终测：知识树 **1.87 s**，今日学习 **1.42 s**，题量查询 **1.40 s**。另一轮测得 1.82/1.11/1.16 s。不同运行轮次存在正常波动。

不能把含分析器的旧值与不含分析器的新值直接相除宣称加速倍数；也不能将上述服务函数计时当作浏览器完整首屏耗时。未宣称三个接口均低于 1 秒。

## 4. 真实浏览器结果

系统 Chrome 155，经实际 Vue 前端 5176 → 实际应用路由 18086 → 隔离恢复库，完成：

今日学习 → 打开范围选择器 → 知识树 → 返回今日学习，并请求题量 API。

- 页面均可正常渲染，已保存截图。
- 控制台错误 0、未捕获异常 0、请求失败 0、4xx/5xx 0。
- 页面 ready：首次今日学习 3.12 s、知识树 2.44 s、返回今日学习 2.46 s。
- 对应主要 API：2.40/1.81/1.88 s；题量接口 1.74 s，返回 1804 道可练题。
- 测试期间有并行回归负载，不据此声称空载首屏指标已达标。

浏览器后端不运行 lifespan、后台任务或模型加载；每个 Session 使用外层回滚事务。原因是现有 GET `/practice-requests` 使用行锁维护请求，严格 READ ONLY 会拒绝该查询；首次严格只读探测因此出现 500，证据保留。修正探测会话隔离后原产品接口正常，不为探测修改产品行为。

本轮是相关页面和接口性能烟测，不是重跑全部 Playwright，不包含创建学习卷、提交作答、RAG 或真实 AI 验收。

## 5. 语义与历史数据保护

同一副本中，三个接口修复前后的完整 JSON 响应 SHA-256 分别完全一致：

| 接口 | SHA-256 |
| --- | --- |
| 知识树 | `5d86eaf0d47a4a527174e8615e3cefab6cda705eb2d635a9e974d8dd1d175f5d` |
| 今日学习 | `6f2826b6ccf6327f22b98f32079ce23cbbbb08a1b45d8592f94e746b51b0f2b4` |
| 题量查询 | `b987c3b0214783096cfad381273bd73f35a3d447a7937caaa5086971d6c75c8e` |

浏览器测试后再次执行只读终测，上述 hash、全部九张所核对表的行数、Attempt/LearningEvent/KpState/DailyPlan/PracticeItem 全行排序指纹仍与修复前一致。

与现有源码基线核对，以下文件未变：`question_eligibility.py`、`mastery/rules.py`、`mastery/transition.py`、`question_versions.py`、`models/learning.py`。策略解析与题集校验文件只有请求内预加载兼容改动，原有失败关闭保护保留。

## 6. 测试结果及未掩盖的失败

- 初次相关定向：49 passed。
- 完整后端：**2761 passed、7 failed、2 skipped，622.13 s**。
- 修复测试替身并使用正确临时路径后的相关复测：**68 passed，52.09 s**，覆盖自适应学习、选项精确比较、资格、v3 题集、历史版本及毕业后练习。
- 本轮未删除测试、增加 skip/xfail 或放宽业务断言。
- 未在后续修复后再跑第二遍全量，因此不能宣称全量全绿。

7 项失败的处置：

1. `test_p5_adaptive_journey.py` 的 corrected-math2、corrected-408、too_short_budget、malformed_legacy_sequence 共 4 项：离线 EvidencePlanner 不支持现有压缩工具协议；修复后该文件全 15 项通过。
2. `test_private_output_does_not_overwrite_history`：完整测试把 pytest basetemp 放在 `storage/quality-audits` 内，恰好是被测函数允许的私有目录，原测试的“临时路径不应允许”前提不成立。使用默认独立临时路径复测通过；没有修改原测试或安全函数。
3. `test_policy_origin_semantics.py` 的 guarded_apply/recovery 与 changed_policy 两项：旧的 `migrate_graduation_policy_semantics.py` 显式只接受到 f54，当前隔离测试 Schema 为 f55，所以其 Schema preflight 按设计拒绝。未为追求全绿扩大旧迁移工具白名单或执行策略转换。这两项仍属未解决的历史工具兼容问题，不应误写成已通过。

另一次完整回归的前置尝试在旧 ProtocolProvider 压缩协议处停止（266 passed、1 failed），已保留日志；该问题已在上述 68 项复测范围内验证。

## 7. 原始证据与复现

目录：`storage/quality-audits/study-read-performance-20261016/`。

主要文件：

- `before-summary.json`、`release-profile-summary.json`：同分析器前后比较。
- `final-wall-summary.json`：最后一次无分析器计时、响应 hash、历史指纹。
- `browser-smoke.json`、`browser-smoke-release-inventory-attempt.json` 及对应 PNG：真实页面证据。
- `pytest-full-final.log`、`full-final.xml`：完整测试的真实失败和耗时。
- `targeted-final.log`、`targeted-final.xml`：最终 68 项通过。
- 各轮失败/中断日志保留，不用后续通过结果覆盖。

复现时须自行创建并核验隔离实例，恢复副本到 `kaoyan_perf_clone_test`；破坏性测试 fixtures 只能使用独立 `*_test` 空测试库，不能对恢复副本运行。原开发库 5433 不在这些脚本允许范围。

## 8. 使用与边界

生产后端重新加载修复代码即可，无新增配置、迁移、seed 或题库导入要求。第一轮隔离验证未访问真实库；随后经用户授权重启真实后端并只读核验历史指纹，没有修改正式题或历史学习记录，没有收费模型请求，没有 Git 提交、重置或清理。

不要为使代码生效而重新执行可能迁移/seed 的整套初始化流程。实际后端生效与页面复核记录如下。

## 9. 实际运行实例修复生效（用户另行批准后）

用户反馈今日学习仍慢、知识树仍打不开。再次检查发现：实际 8000 后端 PID 31784 于 20:36 启动，而性能改动于 21:26—21:31 保存。原进程没有自动重载，知识树接口仍耗时 5.85 s。实际浏览器先显示“正在加载知识树”，等待后才显示内容。

用户明确批准“现在重启后端”后：

1. 核对真实实例地址 `127.0.0.1:5433/kaoyan` 及 system identifier `7686825087296682120`，仅开启只读事务。
2. 确认 generating 聊天数 0、running 资料任务数 0；记录五张学习历史表的指纹。
3. 只向核验过的旧后端专用控制台发送退出信号。日志确认 `Application shutdown complete` 和 `Finished server process [31784]`，未强杀 PostgreSQL。
4. 确认 8000 端口释放后，仅运行现有 `scripts/run-backend.cmd`；不运行完整 start-dev，不执行 migration、seed 或数据库启动。
5. 新后端 PID 23432，22:15 启动；启动清单的题量服务源码 hash 与工作区一致，日志显示正常启动完成。

实际 8000 后端重启后的测量：

| 读取接口 | HTTP | 耗时 |
| --- | ---: | ---: |
| health | 200 | 0.197 s |
| knowledge/tree | 200 | 1.842 s |
| plans/today | 200 | 0.129 s |
| question-availability | 200 | 1.593 s |

此时真实用户已有今日试卷，`plans/today` 的 0.129 s 是恢复已有试卷，不是无卷时推荐路径；不与第一轮隔离库的推荐计时混为一谈。

实际浏览器访问当前 `5173 → 8000` 服务，确认知识树 253 个学习节点显示；展开“极限与连续”成功；“洛必达法则”详情及系统讲解成功；今日学习恢复已有 30 道题的试卷；随后返回知识树成功。只做读取和导航，没有点击答案、提交、计划生成或模型调用。另核验 1440×900 桌面尺寸下树形画布正常显示。

重启前后真实历史表的数量及完整行排序指纹全部一致：Attempt 28、LearningEvent 30、KpState 284、DailyPlan 11、PracticeItem 117。这是用户后续使用后的当前数据，不回退到早期验收报告的旧数量。

PostgreSQL 原实例及 5173 前端未重启。修复已在实际后端生效；用户原有页面刷新即可使用，无需重新初始化项目。

## 10. 第二轮安全提速（2026-10-16）

继续检查后，发现当前正式自动审核题在每次知识树读取时，都会重复验证已经由同一内容哈希绑定审核收据证明的结构与选项完整性。对 v8 收据，只有当 Question 内容哈希、答案哈希、审核快照哈希及映射均匹配，且收据内结构阶段明确为 PASS、规则版本为 `distinct-choice-content-v1` 时，才复用审核时已经完成的结构检查；旧版收据仍执行原来的实时结构检查，所有哈希、映射和资格判断仍保留。

为避免每次页面返回都重做同一份不可变收据校验，增加了有界正向缓存。缓存只针对 v8、已存在 `QuestionVersion` 的正向匹配，键包含题目版本、更新时间、当前审核事件与审核哈希、可见状态及节点映射状态；Question/节点/审核事件存在未提交 ORM 改动时不命中。缓存最多 8192 项，缓存未验证资格结果或内容。题目版本、事件或节点状态变化都会重新核验。

复测结果：

| 条件 | 结果 |
| --- | ---: |
| 新进程首次请求（冷缓存） | 1.650 s |
| 同进程后续 5 次请求中位数 | 1.153 s |
| 同进程后续最佳请求 | 1.119 s |
| 响应 JSON 大小 | 847,289 bytes |
| 所有响应 HTTP 状态 | 200 |
| 响应 SHA-256 | 与修改前完全相同：`a4fd1f73c020f5a8fc0b4cd173d02cb517852372929c74aae3a520fd96885da2` |
| 返回树节点数 | 304 |

这是同一台机器、同一真实数据、同一路由的短样本实测；实际加载仍受本机并发和冷启动影响，不能保证每次固定在 1.15 秒。首个冷请求没有变快，收益主要体现在同一后端进程内再次打开/刷新知识树。修改未触碰数据库结构或数据，没有执行迁移、seed、题目导入或 AI 调用。

## 11. 启动预热与低于 1 秒读取（2026-10-16）

为覆盖“后端刚启动后用户第一次打开知识树”的场景，应用启动时现在会在只读 Session 中预先构建同一份 `KnowledgeTreeResponse`。启动预热不依赖模型、不会提交学习数据；若预热失败，服务仍正常启动，首个请求退回原计算路径。进程内缓存最多保留一份约 850 KB 的响应，按上海自然日隔离，TTL 为 1 小时。

缓存仅在影响知识树投影的 ORM 写入或 `Session.execute/Query.update` 变更成功提交后失效：知识节点、掌握状态、策略、冻结题集、公共题及内容版本、审核/答案核验凭据、练习项、作答和学习事件。资料处理线程的空轮询提交不再冲掉缓存。并发构建期间若发生相关提交，旧世代结果不会被重新写入缓存。数据库外部直接 SQL 写入不会触发应用内失效；本机单用户管理操作如直接改库，应重启后端，TTL 也限制了最长陈旧时间。

最后一次使用现有 `run-backend.cmd` 优雅重启项目 8000 后端后的真实开发库只读测量：

| 请求 | HTTP | 耗时 | 响应字节 |
| --- | ---: | ---: | ---: |
| 启动预热后的第一次知识树请求 | 200 | 345 ms | 847,289 |
| 同进程后续请求 | 200 | 41–63 ms | 847,289 |

响应 SHA-256 为 `a4fd1f73c020f5a8fc0b4cd173d02cb517852372929c74aae3a520fd96885da2`，与优化前一致；304 个节点、3 个根节点。业务结果未变。本轮只执行 GET 和健康检查，没有触发真实学习写入、数据库迁移、seed、题目导入或付费模型调用。后端已运行新代码；PostgreSQL 与前端未重启。

缓存单元行为通过 Python 直接隔离验证：响应副本不会污染缓存；与题树无关的资料任务提交保留缓存；题库表提交会立即清除缓存。`compileall` 通过。完整 pytest 未运行：测试仓库的 `tests/conftest.py` 强制要求明确拥有的隔离 PostgreSQL 测试 URL，本轮未配置，也没有绕过守卫或指向真实开发库执行测试。

当前后端再次经正常 Ctrl+C 优雅关闭后，以项目现有 `scripts/run-backend.cmd` 重启，PID 3588，启动时间 22:34；`/api/health` 返回正常。用户只需刷新知识树页面。响应内容哈希一致证明节点及业务统计未改变；针对本次逻辑的 6 个现有纯计算/收据行为检查及 Python 编译检查通过。由于测试夹具强制要求显式隔离 PostgreSQL URL，本轮没有为跑测试而连接或写入真实库；没有运行全量 pytest。
