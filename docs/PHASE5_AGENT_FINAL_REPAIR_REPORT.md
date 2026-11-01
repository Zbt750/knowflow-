# Phase 5 — Agent 最后三项阻塞修复报告

日期：2026-10-15（Asia/Shanghai）。修复状态：`PHASE5_AGENT_FINAL_REPAIRS_OFFLINE_VERIFIED_REAL_RETEST_PENDING`。

## 结论

本轮完成了工具上下文、正式证据读取和来源纠正后任务安排三项最小修复。相关后端回归 **214项通过，0失败、0错误、0跳过**；最终两处收口调整又完成 **20项针对性复测通过**。本轮新增真实模型请求 **0次**。

真实效果尚未重新测量。此前40案例的原始输出、评分和计费记录保持原样，不能将本轮离线通过转写为真实模型复测通过。产品状态仍为 `PHASE5_PRODUCT_ACCEPTANCE_INCOMPLETE`。没有访问5433真实开发库，没有修改正式题库、用户历史数据或毕业算法。

## 1. 实际读取的证据

读取 `storage/quality-audits/phase5-ai-real-retest-20261015-v1/` 的 Provider ledger、实际模型回答、Agent任务与完整工具轨迹、前后学习事实；读取冻结案例/rubric及现有代码差异。

该轮实际61次物理请求中有50次Agent请求。A01/A08/A11/A14/A15/A16/A19/A20的后续轮在发送前被单次输入预留拦截，A04/A09/A13暴露正式证据投影不一致，A18的原始“全部AI题”断言被拦截后丢失具体安排。

再次验证原始冻结哈希未变化：

- `cases.json`：`ca05b1758f8f946c9cd679e15c6c1eb3f111d1349d67d1fafb80bad5b610df4e`
- `fixtures.json`：`97fd401c2cfd94311a61757fdf81b449449c569d66516d945eca5b81c073b6db`
- `rubric.md`：`906219799c5167541fe94cf8a91f8598bee265949dc2128ece98d3bea3b9c713`

本轮派生证据单独保存在 `storage/quality-audits/phase5-agent-final-repair-20261015/`，没有覆盖原始测评记录。

## 2. 工具上下文过大

### 根因

真实 `find_questions` 单次结果最大约33KB；每道题重复返回大部分相同的资格字段。`validate_plan` 又同时包含相等的 `question_trust` 和 `eligibility_snapshot`。多轮工具结果继续累积，重复查询还会再次展开相同事实。服务端此前按字符长度检查，而费用守卫按完整UTF-8请求字节数加余量预留，两者不一致。

另一处错误是：Provider把评测BudgetStop包装成AppError后，任务服务只检查直接异常类型，导致发送前预算停止仍被记录为通用Provider失败。

### 修复

- 新增轻量模型载荷转换 `learning_task_context.py`，仅在送模副本中提取每组题目共有的资格字段为 `question_trust_defaults`，每题保留差异字段；相同的资格快照使用明确引用。
- 题目ID、不可变版本、审核事件和hash、来源、库存数字、辅助记录及范围约束均保留；完全相同的重复工具结果指向最新完整结果，不折叠事实已变化的结果。
- 完整原始工具结果、服务端草案及确认用的资格快照仍保留在任务轨迹和数据库中；没有删减审计证据或确认校验数据。
- Prompt升级为 `learning-task-v18-evidence-context`，明确共有字段合并与重复结果引用的含义。
- 对消息和工具定义序列化后的UTF-8体积作检查，60,000字节以上明确返回 `context_limit`，为Provider字段和原有2,048预留余量留空间。原64,000保守输入预留、Agent输出上限、轮数与时间上限没有提高。
- 检查异常cause/context链，包装后的预算停止仍分类为 `evaluation_budget_stop`，不可重试，不冒充模型正常回答或普通网络故障。

### 离线证据

对50次历史Agent真实请求重放送模载荷；只计算新载荷，不重新调用模型。总字节量由1,605,966降到1,478,798，减少约7.92%。这个数字是序列化字节统计，不是实测Token或费用下降率。

根据原响应和工具轨迹重建8个当时受阻的下一轮，结果如下。重建不是原始出站请求，不计入真实请求或成功回答：

| 案例 | 重建原体积（字节） | 压缩后体积（字节） |
|---|---:|---:|
| A01 | 63,598 | 51,203 |
| A08 | 64,136 | 53,253 |
| A11 | 62,730 | 50,305 |
| A14 | 69,194 | 57,933 |
| A15 | 62,020 | 54,149 |
| A16 | 67,406 | 58,706 |
| A19 | 70,663 | 53,280 |
| A20 | 68,675 | 58,356 |

50次历史请求及8个重建轮次均通过新的服务端体积检查和原费用预留边界。保留超限拒绝行为；这不能保证未来任意范围的工具结果均适配，更不能证明DeepSeek已理解新载荷格式。

## 3. 正式学习证据读取

### 根因

`capability_service.py`中的可靠性分支仍仅接受v4、`content_trust=verified`及人工/参考核验来源。当前正式自动审核题的合法作答收据是v5/v6、`auto_verified`。于是同一工具同时返回 `recent_attempts.evidence_reliability=verified_objective`，却又在 `learning_progress` 中把它降为不可靠参考答案。

毕业后表现读取也有同类v4限定，已一并复用修复后的绑定检查，避免同一正式证据在两条读取路径中被不同解释。

### 修复边界

继续复用 `question_for_attempt`、现有 `question_eligibility`、内容/答案hash比较、自动审核事件及当前策略快照。读模型支持与现有正式证据路径一致的v5/v6绑定，核对：

- Attempt和QuestionVersion确实属于同一道题、同一节点；历史实例读取其绑定版本。
- 作答保存的内容/答案hash与绑定版本一致。
- 审核事件ID、审核版本、snapshot hash和资格类别匹配；v6保持既有变式类别约束。
- 原收据确实为可靠客观证据，并保存结果、作答ID、题型和技能等必要字段。
- 仅公共正式路径可进入该分支；个人题和生成批次不能因当前资格或模型名被提升。

旧v4规则保留，缺失字段、旧弱证据、版本或hash不匹配仍不升级。可靠答案比较、独立作答、真正完成与节点毕业继续分别由原序列和有效策略快照解释。没有改写原收据，没有新增证据，没有修改毕业要求。

### 原隔离学习数据的只读核对

对之前真实测评的5个隔离案例数据库，以数据库只读连接读取新投影，未写入：

| 案例 | 新读取结果 | 历史保护 |
|---|---|---|
| A04 | 可靠错误2、参考错误0，待巩固 | KpState、Attempt收据、毕业进度均不变 |
| A09 | 可靠错误3、参考错误0，待巩固；仍为一道题的3次作答 | 同上 |
| A10 | 不再把先前可靠错误当参考结果；后续独立正确历史保留 | 同上 |
| A12 | 提示辅助正确保留，仍建议复测 | 同上 |
| A13 | 后续独立正确和有效题目完成仍由原快照保留，不再给参考错误说明 | 同上 |

这些是旧隔离数据的新读取结果，不是新的模型回答。A10/A13仍可显示“正在练习”，因为整个节点适用题集没有全部完成；并未将单题完成误当节点毕业。

## 4. 来源纠正后的任务安排

### 根因

原来源保护在发现错误来源断言时，用通用文字替换整段回复，强制把任务设为answered，只在ready时保存的有效草案因此丢失。A18虽然保住来源真实性，却失去已校验的填空题与时间安排。

### 修复

- 来源按真实工具返回类别统计，并按Question ID跨重复查询去重；未知来源明确为未知，不推断整库来源。
- 发生来源纠正时，若已有当前服务端校验通过、可确认的计划草案，保留ready、原题目成员、题型、时间、预算及确认入口；回复附上服务端摘要。
- 草案不存在时只展示已读取库存中符合题型和时间的起步候选，不捏造题目或声称已完成校验。
- 已校验方案不再同时提示“仍需校验”；所有路径仍说明尚未加入今日学习，必须用户确认才创建或追加试卷。
- 保持原计划校验与确认时再校验：来源修正不放宽预算、库存或资格要求。

集成测试分别模拟模型最终needs_clarification为true/false的来源错误，均验证来源被纠正、有效草案仍可见、总时间不超预算、没有新增DailyPlan或PracticeItem。

## 5. 实际修改文件

| 文件 | 本轮用途 |
|---|---|
| `backend/services/learning_task_context.py` | 新增送模副本去重/共有字段提取 |
| `backend/services/learning_task_service.py` | 接入载荷压缩、体积守卫、包装预算异常分类、来源纠正保留有效草案；Prompt v18 |
| `backend/services/capability_service.py` | 读取当前正式自动审核收据，保留旧版本及弱证据边界 |
| `backend/services/post_graduation_service.py` | 复用同一正式收据绑定检查；毕业事实和原表现规则不变 |
| `tests/unit/test_agent_tool_context.py` | 新增压缩事实保持、重复结果、超限拒绝、包装预算停止测试 |
| `tests/integration/test_agent_final_repairs.py` | 新增真实服务产生收据后的投影、历史版本、负例和来源/计划确认测试 |
| `scripts/phase5_agent_final_offline.py` | 历史载荷重建及隔离库只读证据核对，无Provider调用 |

本轮没有新增migration、API端点、学习状态表或新业务功能。工作区原有大量未提交变更保留；上表只说明本轮改动内容，不把整个Git差异归为本轮成果。

## 6. 自动化验证

先运行新增及直接相关测试，20项通过。首次扩大回归共198项中191通过、7项setup错误：Windows沙箱临时目录无法创建，均发生在测试准备阶段。未修改或跳过失败测试，改用工作区内新的 `--basetemp` 后重跑。

完整相关回归命令（环境变量显式指定59271、`phase5_repair_20261015_test`）：

```text
pytest -q --tb=short --basetemp=<工作区新的测试临时目录> --junitxml=storage/quality-audits/phase5-agent-final-repair-20261015/regression.xml tests/unit/test_agent_tool_context.py tests/unit/test_learning_task_evidence_guards.py tests/unit/test_post_graduation_practice.py tests/integration/test_agent_final_repairs.py tests/integration/test_learning_tasks.py tests/integration/test_learning_assistant.py tests/integration/test_learning_progress_profiles.py tests/integration/test_question_immutable_versions.py tests/integration/test_auto_question_review.py tests/integration/test_personal_question_bank.py tests/integration/test_post_graduation_practice.py
```

结果：**214 passed、0 failed、0 errors、0 skipped，323.029秒**。覆盖原审核资格、个人题隔离、Question不可变历史、学习进展、毕业后表现、预算与确认边界。

随后对预算异常不可重试标记、来源纠正后不再提示重复校验两处最终收口，再运行20项直接相关测试：**20 passed、0 failed、0 errors、0 skipped，11.752秒**。最终两处调整后未再次运行214项整组。这20项包含在上述相关范围内，不与214简单相加宣称234个不同测试。所有本轮Python文件编译检查通过。

机器证据：

- `storage/quality-audits/phase5-agent-final-repair-20261015/regression.xml`
- `storage/quality-audits/phase5-agent-final-repair-20261015/final-targeted.xml`
- `storage/quality-audits/phase5-agent-final-repair-20261015/offline-evidence.json`

没有重跑无关浏览器或后端全量测试，也没有将旧模型输出回放计为新模型质量结果。

## 7. 数据保护

实时只读确认测试集群system identifier为 `7696773489828724208`，端口59271；真实开发库5433未访问。会写入的回归仅使用独立测试库。旧真实测评的隔离案例库仅只读读取，KpState、Attempt证据、原毕业进度比较一致。

没有修改封版题库、QuestionVersion机制、历史学习数据或毕业算法。测试用题仅在测试夹具中通过已有服务建立，不作为新增正式内容。原始Provider ledger和40案例评分保留，本轮真实模型请求0次，没有收费裁判、自动生题或额外计费。

## 8. 尚未解决与真实复测准备

三项问题已完成离线修复。仍需真实调用确认DeepSeek对共有字段/引用格式的理解以及最终回答表现；离线体积适配不能替代真实质量验收。

建议重点重测原始冻结Agent案例：**A01、A04、A08、A09、A10、A11、A12、A13、A14、A15、A16、A18、A19、A20**，共14例。不得修改原输入、夹具规范或rubric。A07原夹具真实性阻塞仍保留，本轮没有扩展为夹具重建任务。上一轮未执行的RAG引用等案例仍无新的通过结论；部分重测不能签发完整40例通过。

这14例预估约40–70次物理请求，取决于工具轮次、分类和已有有界恢复；估算输入约250k–600k、输出15k–40k tokens。按本日此前核对的官方峰时未缓存价格输入¥2/百万、输出¥8/百万计算约¥0.62–¥1.52，考虑波动的规划范围约 **¥0.7–¥1.8**。[官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

这是待审阅估算，不是本次授权或供应商硬金额锁。执行前还需重新核价、明确批准物理请求/Token/金额上限；不能继承上一轮未用额度。本轮未发送任何复测请求。

### ConnectError处理建议

- 保留第61次请求的原始异常、无HTTP/usage状态和费用预留，不假定它零费用或零消耗。
- 下次授权前检查本机网络、DNS、代理和TLS连接，区分连接阶段失败与已发送后的超时；避免把连接错误归为学科回答错误。
- 每次实际出站请求及恢复都计数。没有usage时停止并核对，不能因还有剩余额度就无限重试。
- 若未来得到明确的计费核对证据，追加独立说明，不改写原始ledger。下一轮使用新run ID并保存新Prompt/代码hash。

本轮完成后停止，等待用户审阅；不自动启动付费复测或其他开发阶段。
