# Phase 4.5A.1：可信答案基础激活与毕业规则兼容性

启动日期：2026-10-07；收口日期：2026-10-08（Asia/Shanghai）。结论：`INFRASTRUCTURE_ACTIVATED_WITH_POLICY_DECISION_PENDING`。文件和备份目录保留启动日标识，便于对应整轮记录。

真实本地开发库已从 `e42c7a10b9f3` 升级至 `f45a9b7e2c10`。迁移前完成预检、完整备份、隔离恢复演练；迁移前后 20 张既有业务表的内容指纹一致。核验事件和当前核验指针均为 0。第一批四节点、12 题的人工复核工作单已生成，仍是候选，不是 VERIFIED Golden Slice。

本阶段没有修改任何毕业规则或历史作答，没有模型调用、网络搜索、真题下载、题目导入、提交或推送。用户附件在 `# 13. 不要` 处截止；本报告覆盖其中完整的第 1—12 节及已明确的禁止事项，没有补猜截断后的要求。

## 1. external_exam 的真实语义

结论：`external_exam` 是旧版“外部原卷题号引用练习”的表示方式，在题型枚举、API 和毕业题型配额中作为兼容标记使用。它没有表示正式考试环境，也没有表示所有历年真题。当前存在历史建模兼容缺口，归入 CASE B；旧种子逻辑的意图本身能从历史代码证明，不是凭名称推测。

证据链：

| 位置 | 现有行为与含义 |
|---|---|
| `backend/mastery/enums.py`，`QuestionType.EXTERNAL_EXAM` | 注释明确：用户打开原卷练习的题号引用，不含题干、答案，自行对照记录。 |
| `backend/models/learning.py`，`ExamQuestionReference` | 保存科目、年份、原卷题号、知识点、来源链接和本地目录，不是完整在线 Question。 |
| `b82d4a90ce17` 迁移 | PracticeItem、QuestionAttempt 均可关联 Question 或 ExamQuestionReference；数据库 XOR 约束禁止同时关联两个来源。 |
| `backend/services/practice_service.py` | 普通生成与追加需要真实可作答 Question。原卷引用追加会先解析到唯一合法在线题；引用不能直接冒充一道有题干的练习。参考节点的选题临时策略不写回毕业规则。 |
| `backend/api/routes/study.py`、`learning_task_service.py` | 无 Question 的旧练习条目在响应/当前卷快照中使用 `external_exam`；有 Question 的真题仍使用其真实题型。 |
| `answer_submission_service.py`、答案读取路由 | 只有原卷引用的条目不能获取系统答案或提交机器判题，返回 `external_exam_has_no_embedded_answer`。 |
| `backend/mastery/evidence.py`、`transition.py` | 新自评是 `PRACTICE_SELF_REPORTED`，只记辅助反馈；客观提交才可能通过可靠性、独立性和序列规则形成确认。 |
| `backend/mastery/rules.py` | 题型配额按 Evidence 的 `question_type` 精确计数，不会把 real_exam 来源转换成 external_exam。 |
| `scripts/seed.py`、`exam_reference_service.py:sync_exam_reference_index` | 五条原始数学策略来自 syllabus；大型真题索引策略按不同引用数量生成 external_exam 配额。 |
| 历史提交 `c841adb` 的学习闭环测试 | `test_external_exam_reference_can_be_scheduled_self_assessed_and_graduate` 曾断言单引用节点自评 mastered 后毕业。 |
| 当前 `tests/integration/test_learning_loop.py` | 对应回归已断言原卷自评后仍 unseen、确认数为 0，保留引用型历史，不再毕业。 |

`Question` 的正式在线题型没有把 external_exam 当成可机器作答题型：准入集合是选择、填空、计算、证明、讨论、程序、主观题。旧枚举仍保留 external_exam，是为了读取历史引用任务。`Evidence.source`、`Evidence.question_type`、Question 的 `question_provenance`、答案来源及 EvidenceLevel 是不同字段。

纸上做一道系统 Question，然后在网页输入最终答案，仍走 Question/客观提交路径；纸张介质不会把它变为 external_exam。原卷引用的线下记录则只有引用 ID、自评和历史。现有 `observation_scope=tracked_interface_not_proctored` 也明确：系统观察界面内的辅助行为，不证明用户经历了受监考考试。

## 2. Graduation Evidence Compatibility Matrix

下表描述当前代码合同。在线可信路径以题面/来源、映射、答案版本核验和支持的 grader 均有效为前提；当前生产候选尚未满足全部前提。可靠判题结果与可累计的独立确认分别说明。

| Question / Evidence path | Question authenticity | Answer trust | Grading | 实际 Evidence source / level | 满足 external_exam 配额？ | 可靠客观结果 / 独立确认 |
|---|---|---|---|---|---|---|
| 在线历年真题选择题 | real_exam，题面/来源复核及映射通过 | 当前有效 human_verified 或 verified_reference | single_choice 精确比较 | objective_final；独立正确才 confirmed | 否，题型仍 single_choice | 前提满足时可 / 前提满足且独立正确时可 |
| 在线历年真题数值题 | 同上 | 同上 | numeric_final，支持的整数、有限小数、精确分数 | objective_final；题型仍 fill_blank/calculation | 否 | 前提满足时可 / 独立正确时可 |
| 在线 AI 生成练习 | ai_generated_practice，不能自称真题 | AI 来源，即使一致也不是权威/人工核验 | 可支持低可靠性参考比较 | AI 低可靠性；weak | 否 | 不提供 VERIFIED 毕业确认 |
| 外部原卷引用后的记录 | 有原卷引用；不是完整在线 Question | 没有系统内可核验答案 | 无机器判题 | practice_item/self_report；新反馈不进入确认窗口 | 当前新记录不能；旧历史仅保留原口径 | 否 / 否 |
| 证明/讨论题过程审阅 | 题目来源与完整性另行判断 | 即使答案核验，仍需可执行 grader | 当前过程审阅不是证明判定器 | process_review / self_report | 否 | 不提供最终答案客观确认 |
| 408 程序/算法过程审阅 | 同上 | 同上 | 无执行沙箱和正式测试用例评分 | process_review / self_report | 否 | 不提供执行正确性确认 |
| 题目/节点自评 | 自述，无独立结果证明 | 不适用 | 无 | 新自述辅助信号 | 否 | 否 / 否 |
| Hint 后答对可信在线题 | 与在线可信路径相同 | 与在线可信路径相同 | 可以有可靠对错结果 | objective_final；partial | 否 | 可有可靠结果 / 不算独立确认 |
| 看 Solution 后答对可信在线题 | 与在线可信路径相同 | 与在线可信路径相同 | 可以有可靠对错结果 | objective_final；partial | 否 | 可有可靠结果 / 不算独立确认 |

同题纠错、重复正确和历史不完整也继续受 Attempt Sequence 规则约束。本阶段没有将确认来源、Question 起源或题型互相改名。

## 3. 284 条策略的根因与影响

| 当前配额 | 策略数 |
|---|---:|
| external_exam: 3 | 196 |
| external_exam: 2 | 17 |
| external_exam: 1 | 66 |
| 原始在线题型策略 | 5 |
| 合计 | 284 |

279 条 external_exam 策略的 note 都带旧索引标记，且 279/279 完整匹配现有索引生成公式：`required=min(3, reference_count)`；确认数和不同题量等于 required；题型配额为 external_exam；取消未知变式要求；考法标签取节点名；跨天要求为 `min(2, required-1)`。另外五条策略来自 `seed/syllabus.json`，没有外部引用配额。

旧种子逻辑曾明确服务于“用户打开原卷做不同题后自评累计毕业”。后来新增自评被降为辅助信号，只有可靠客观结果能形成新确认，但旧策略没有同步版本化。于是：

- 引用记录无题干、无系统答案，不能机器判题；
- 新自评不能给毕业确认；
- 完整在线真题仍使用真正题型，不能满足 external_exam 配额。

这就是当前兼容缺口。没有证据表明旧 external_exam 的含义是“必须参加独立的正式考试环境”。当前真实历史中，外部引用 Attempt 为 0；已有 7 条证据窗口项是普通练习来源、可靠性 unknown（选择 4、填空 1、计算 2），全部保留，没有改成客观确认。

### 待批准的具体迁移建议

建议把上述 279 条旧索引策略的“真题来源配额”改为一个明确的来源维度，而不是修改题型名字：保留原 quota 数值，拟表达为 `required_question_origins={real_exam: 原 quota}`；真正题型继续使用 single_choice/fill_blank/calculation 等。确认数、不同题量、考法、跨天、复测间隔和其他阈值均逐项保留。

这个来源约束需要策略版本和对应证据来源快照支持。后续实现前必须批准语义，不能先清空 external_exam 配额让现有策略过关。若产品确实要独立考试环境，应另行设计可信外部考试结果路径；当前自评引用不具备这个能力。

已经生成不可执行的完整迁移提案 `storage/answer-trust/phase45a1-20261007/policy-transition-proposal.json`：包含 279 个节点、原规则值、原来源引用数量、逐条公式匹配及拟议来源配额。其状态为 `NOT_APPROVED_NOT_APPLIED`，不是 SQL、migration 或核验清单。

下一轮经过批准后的实施边界：

1. 为来源配额建立版本化字段和明确检查，不能借用 `question_type` 或 `Evidence.source` 名称。
2. 只处理匹配已审查旧种子公式和原快照 hash 的行；自定义/后来改变的规则必须停下复核。
3. 保存旧策略快照，保留原阈值，区分新旧政策版本；不重写 Attempt、LearningEvent 或 KpState。
4. 历史缺少来源/可靠性快照的证据保持 unknown；不得用当前 Question 元数据替历史背书。
5. 仅未来满足版本、题面、来源、答案、grader 和独立性要求的证据进入新配额；旧弱信号不升级。
6. 用真实复核题再验证数量、重复题、辅助正确、错题复测、标签与跨天条件。

该提案仍需用户确认。本阶段 policy mutation = 0。

## 4. 本轮实际修改

- 增加 `answer_trust_migration_preflight.py`：限制在本地 dev/kaoyan，检查迁移链、精确 schema delta、约束、触发器及全量原业务行指纹，生成 before/after 记录。
- 增加 `activate_answer_trust_migration.py`：检查预检与匹配的恢复报告，再在一个事务中迁移；升级后指纹不符就回滚。使用受限等待时间、revision 锁及维护操作锁；不写核验事件。
- 增加 `prepare_verified_slice_candidates.py`：基于当前 Question 和已声明本地 source 路径，挑选 bounded 客观题候选，生成人工复核工作单；原卷 PDF 与答案草稿不自动变成答案依据。
- 增加 `audit_graduation_policy_compatibility.py`：审计全体策略，输出具体、不可执行的待批准提案。
- 候选及切片 CLI 增加安全本地导出；切片 CLI 支持 4—8 个明确节点，报告合同升为 v2。
- 修正旧审计中的混淆：未有答案核验事件不等于来源文件缺失。普通切片报告标记 `NOT_AUDITED`，由独立离线来源检查给出四类可用性。
- 修复完整真题在引用型节点上的准入冲突：来源绑定的有效性独立于 content trust。人工复核同一份题面后，不丢失精确来源映射；该兼容路径仍要求 real_exam、来源 verified、人工题面复核、有效来源绑定以及当前答案核验。绑定过期、只有引用、来源/答案未核验仍被拦截，题型不改名，毕业配额不改。

这项准入修复没有替任何实际题目填写人工复核，也没有给当前题库增加 VERIFIED 题。

## 5. 备份、迁移及数据完整性

备份位于 `storage/backups/phase45a1-20261007-pre-migration/`，受本地访问权限限制并由 Git ignore 排除。

- `database.dump` 是 PostgreSQL custom archive；pg_restore list 校验成功。
- DB 备份 SHA-256：`f70953b394010d0c4911dfc4f0924d8edf24351c6fd4c726fed7c42c3bd01a40`。
- 另外备份并检查了 1,484 个本地资产文件、106,509,724 字节。
- 在独立临时恢复库完整恢复成功；恢复版本 e42c7a10b9f3，题目 518、Attempt 28、计划 10；344 份资料的资产覆盖、大小、hash 检查全部通过。
- 临时恢复库已回收。它只用于演练；真正迁移发生在原来的 kaoyan 库，原库没有被替换或删除。
- 恢复记录：`eval/reports/phase45a1-20261007-restore-check.json`。

迁移前后和全部工具运行后的最终检查：

| 项目 | 前 | 后 |
|---|---:|---:|
| Alembic revision | e42c7a10b9f3 | f45a9b7e2c10 |
| Question | 518 | 518 |
| Attempt | 28 | 28 |
| LearningEvent | 29 | 29 |
| KpState | 284 | 284 |
| DailyPlan | 10 | 10 |
| PracticeItem | 87 | 87 |
| PracticeRequest | 0 | 0 |
| 答案一致性记录 | 696 | 696 |
| 来源 attestation | 180 | 180 |
| Mastery policy | 284 | 284 |
| 证据窗口项 | 7 | 7 |
| 新核验事件 | 表不存在 | 0 |
| 当前核验指针 | 列不存在 | 全部 null |

20 张既有 public 业务表的逐行 JSON 内容摘要一致，包含题干、答案、历史与资料；新指针列及 Alembic 版本是比较中明确排除的新 schema 部分。策略原始 canonical SHA-256 仍为 `c18ed340601b260f8ea1cc2a08b20a2379d9940d70da1bca9fd88a6437cff28c`。

新表、索引、检查约束、idempotency 唯一约束、当前事件 FK 与 RESTRICT 行为已检查。实际安装的 append-only 函数在 session 临时表中执行 UPDATE/DELETE 均返回拒绝；临时表整事务回滚，前后真正核验表仍为 0，没有创建假的生产核验数据。

可复现记录：`before.json`、`activation.json`、`after.json`、`trigger-check.json`、`after-final.json`，均在 `storage/answer-trust/phase45a1-20261007/`。

### 恢复过程

备份复验可重复运行现有工具，输出使用新的文件名：

```powershell
python -X utf8 scripts/verify_checkpoint_restore.py `
  --backup storage/backups/phase45a1-20261007-pre-migration `
  --pg-bin "C:/Program Files/PostgreSQL/18/bin" `
  --admin-user postgres `
  --output eval/reports/phase45a1-restore-check-new.json
```

该命令验证归档/资产并建立独立临时恢复库，完成后回收临时库，不覆盖开发库。真实故障恢复应先停写、保留故障库备份，再恢复到经过明确确认的目标并核对记录；不能直接对正在使用的库执行清空/覆盖。当前迁移的普通 downgrade 只允许核验事件、human_verified 状态和当前指针都不存在；一旦核验历史产生，代码会拒绝丢弃历史，应使用备份恢复流程。downgrade 未在开发库执行，只在隔离迁移测试验证过空历史路径。

## 6. 第一批真实候选与来源可用性

活跃候选清单已导出：数学 204 条、408 292 条，共 496 条；其余 22 条 Question 不在活跃节点/题目范围。这是候选查询数量，不是可信答案或可客观毕业题量。

第一批选择了四个节点。每个节点最多列四道复核题，优先已有来源路径、真实来源身份及支持的选择/精确数值比较器：

| 科目 | 节点 | 活跃在线题 | 本批复核题 | 当前可练习题 | Verified objective |
|---|---|---:|---:|---:|---:|
| 数学二 | 反常积分的计算与敛散性，`math.exam.fd2f9e3739d9` | 7 | 4 | 3 | 0 |
| 数学二 | 确定极限中的参数，`math.exam.e90535214807` | 3 | 3 | 2 | 0 |
| 408 | B 树，`cs408.ds.topic.ee1ca2a45d19` | 4 | 3 | 1 | 0 |
| 408 | 二叉树基础（性质+存储），`cs408.ds.topic.1efaf3d00b50` | 4 | 2 | 2 | 0 |

本批合计 12 道选择/数值填空题。在线题总库存 18 道包括没有纳入第一批的其他题型；当前练习准入仍可能使用 AI 参考答案，不能解释为已核验。证明、讨论、程序执行、复杂符号判等与明显不完整转录没有纳入第一批。

仅检查项目现有来源 metadata 声明的本地文件；根目录为用户已有桌面真题目录。文件没有改动、复制或上传，没有访问 metadata 中的网页链接。结果：

| 来源状态 | 本批题数 | 解释 |
|---|---:|---|
| SOURCE_AVAILABLE_FOR_REVIEW | 0 | 没有找到明确声明且可读取的独立答案依据。 |
| SOURCE_METADATA_ONLY | 4 | 保存了来源名称/年份/题号/链接，未有足够本地答案依据。 |
| SOURCE_MISSING | 0 | 本批筛选已经排除不完整来源身份。 |
| SOURCE_AMBIGUOUS | 8 | 有本地原卷或逐题草稿，但它们不能明确证明当前答案正确。 |

存在原题 PDF 可以帮助复核题面；它不自动成为标准答案。逐题草稿、AI 答案和只记录的“答案交叉核对 URL”也不是已取得的权威答案文件。人可以独立推导并形成 human_verified 声明，但本轮没有代填任何人的审核结论。

`review-worklist-final.json` 含每题的当前题面/答案、版本 hash、当前准入理由、文件定位/hash、拟用比较器和留空的审核结论。格式刻意不是可直接执行的 VerificationManifest，防止把准备工作误当作审批。

四个节点的当前策略仍要求 external_exam:3，因此在答案人工复核之外，也必须完成上一节的政策语义批准及后续版本化实现，才能做毕业闭环验收。不能宣称 Golden Slice 已经激活为可毕业。

## 7. 验证与版本

- 最终定向单测：215 passed。
- 最终隔离集成回归：200 passed，覆盖可信答案、导入/升级/撤销、提交、迁移、学习闭环、Planner、Phase 4C API、来源工作单不修改数据以及实际函数在临时表上的拒绝行为。
- 变更模块 compileall、差异 whitespace 检查通过。
- 最终独立连接读取 after-final：schema、数据及迁移链检查通过；生产核验数 0。
- 后端只读 health 检查：status=ok、database=connected。运行服务没有主动重启；本报告不把 health 响应当成进程已加载全部新源码的证明。
- 真模型/裁判/视觉/搜索调用：0。

这是本阶段针对所改合同的回归，没有把它报告成全量前端 E2E 或全项目压力测试。

仓库 HEAD 仍为 `b252178fce4e7852caef5332e3e7b10bd294bbc1`，branch=master。工作区已有大量未提交改动，已保留，没有切换、reset、clean、commit 或 push。HEAD 本身不包含本阶段工作区内容。

关键工作区源码 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `backend/services/question_eligibility.py` | `1e9798f86a0c0ea72b2734943f6b2dff8c41806543e363a4fc341a0fa623dcb7` |
| `scripts/answer_trust_migration_preflight.py` | `7d80768d3153c006cd02b71680f03dd3430c2ad0cc8852f1fe94d21ae64641da` |
| `scripts/activate_answer_trust_migration.py` | `c0d60447f70b1ad3768a34a4eaae3ca62932c44504839e69a3286843a10f2645` |
| `scripts/prepare_verified_slice_candidates.py` | `4645cf966945354b85cd6aa19a86e4591564fd4d1b218354233445b7f066c4d8` |
| `scripts/audit_graduation_policy_compatibility.py` | `2ac98fe73eb5ea0c41d36cfd198401053aa7a4b78904128537084cf48f238a48` |

备份、完整题面/答案候选表、source 工作单和提案明细都在 `storage/`，被 ignore；恢复评测记录在 `eval/`，也被 ignore。这份报告仅保留聚合事实与实现边界，没有复制原卷或题干答案。

## 8. 阶段停止点

本轮已完成可自主执行的预检、恢复备份、真实库迁移、合同修复、全策略审计和候选准备。剩余的必须决策事项是：是否批准旧 external_exam 配额迁移到版本化“真实题来源配额”的具体语义；用户方案第 6 节要求在此等待批准。答案/题面人工复核结论也不能由工具代填。

Phase 4.5B/5 未开始；没有批量修改这 279 条政策，没有真实题 VERIFIED 声明，没有历史证据升级。
