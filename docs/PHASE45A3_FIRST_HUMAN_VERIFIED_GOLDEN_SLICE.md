# Phase 4.5A.3 — First Human-Verified Golden Slice

**审计日期：** 2026-10-08  
**范围：** 只读真实开发库审计 + 隔离 `kaoyan_test` 自动化回归 + 真人审核包准备。  
**最终状态： `PENDING_HUMAN_REVIEW`**

> 本阶段没有执行 A.2 迁移，没有更改真实题目/答案可信状态、用户 Attempt、LearningEvent、KpState 或毕业策略；没有模型调用。自动化测试通过不能代替真人审核或真实用户作答。

## 1. Before 基线与范围

- A.2 最终报告结论为 `POLICY_MIGRATION_PASS`；当前真实 PostgreSQL schema revision 为 `f46b2c8d901a`。本轮只读取该 revision，没有重跑迁移。
- 开发库连接为 `kaoyan` / `kaoyan`，`127.0.0.1:5433`。在 `REPEATABLE READ READ ONLY` 事务中取数。
- 284 条毕业策略的规范化 SHA-256：`ecdcf8376dca81469487f07cfc44939b66c853fdd77ea562b283c3a462dbff3d`。四个候选节点均使用 A.2 已迁移的 policy v2，没有变更策略。
- 本阶段 before 计数：knowledge_points 304、questions 518、question_attempts 28、learning_events 29、kp_states 284、daily_plans 10、practice_items 87、question source attestations 180、answer consistency runs 696、answer verification events 0。
- 20 张 public 业务表的逐行指纹保存在被 `.gitignore` 排除的 `storage/answer-trust/phase45a3-20261008/baseline-db-fingerprint.json`。全表摘要、节点候选审计及私有题面审核资料也保留在同一被忽略目录。
- Git 工作区开始时已有大量用户变更。本阶段未改动产品源码、迁移、配置或既有工作；只新增本阶段公开范围的报告，私有题面包和测试日志留在 ignored 目录。

## 2. 节点选择

本阶段选择 **“反常积分的计算与敛散性”**（`math.exam.fd2f9e3739d9`）作为首个真人审核候选，而不是宣称已完成 Golden Slice。

| 候选 | active | real_exam | 当前练习可用 | 当前可信客观题 | 来源审阅判断 |
|---|---:|---:|---:|---:|---|
| 反常积分的计算与敛散性 | 7 | 4 | 3 | 0 | 3 道题可在本机原卷文件中定位；其中 2017 PDF 位于登记 source root 之外，另做了只读核页 |
| 确定极限中的参数 | 3 | 3 | 2 | 0 | 仅 2023 原卷文件可直接定位；2019、2018 为来源元数据，且 2018 答案状态有 AI disagreement |
| B 树 | 4 | 3 | 1 | 0 | 有本地原卷页，但来源/答案均未人工核验 |
| 二叉树基础（性质+存储） | 4 | 2 | 2 | 0 | real_exam 候选少于 v2 要求的 3 道真实题 |

反常积分节点当前 A.2 policy v2 要求：至少 3 个独立可信确认、至少 3 道不同 `real_exam` Question、来源配额 `real_exam: 3`、必需技能标签“反常积分的计算与敛散性”、至少跨 2 天。策略并未因本次库存不足而放宽。候选的 `skill_tags` 与要求标签一致，但题目与节点的真实语义映射仍须人工确认。

它比“确定极限中的参数”具有更强的审核可行性：有 4 道 real_exam 候选，且 2023 Q6、2024 Q7、2017 Q11 有本机可读的原卷载体，现有代码已有精确单选与数值最终答案比较器。首批拟审核 2023 Q6、2024 Q7、2017 Q11；2022 Q5 仅作备用，不计当前可信库存。

## 3. 逐题来源、答案、grader 与映射状态

完整题干、选项、库内答案/解析、来源声明、原卷 SHA-256、答案版本哈希、机器 attestation、AI consistency 运行、尝试计数、当前 eligibility 和审核勾选项均在本机私有审核包：

- `storage/answer-trust/phase45a3-20261008/human-review-package.md`
- `storage/answer-trust/phase45a3-20261008/human-review-package.json`

这些文件受 `.gitignore` 保护，不应上传公开仓库。以下仅列摘要，不复制真题全文。

| 题目 | 来源/题面 | 当前库内答案与可靠性 | 当前判题状态 | 人工/映射状态 |
|---|---|---|---|---|
| 2023 数学二 Q6，`d1691564-0c42-43c0-8ab2-b011fd88ac65` | 本机 2023 数二原卷第 2 页可定位；转录题面/选项经本轮视觉比对相符；PDF SHA-256 `e684611b4c1d9929cd79552b729d93d11e1765b226cfa40839dc569ccef5508d` | A；`ai_generated_consistent`，不是官方答案核验 | 练习可用的 AI 单选比较；无可信 grader method、无 current answer verification | source attestation 是机器记录；human content/answer reviewer 均空；待核知识点语义和技能标签 |
| 2024 数学二 Q7，`2aa85cd9-baed-493d-b79b-f3174f6016c0` | 本机 2024 数二原卷第 2 页可定位、题面可比对；索引把页码记为 2–3，需人工确认/修正；PDF SHA-256 `ee461b5589a55bb6c539638aca0f76376b2b5b84bbcba2b2f2f4e2bc77704cdd` | B；provenance/reliability 仍为 `unknown` | 当前不具备 practice/grading eligibility；只有答案经审核并配置后，单选比较器才适用 | 未有答案核验事件；重点人工确认“极限存在”含义及正确选项 |
| 2017 数学二 Q11，`ab961f2c-8e24-4068-9bfc-effc9ea876e9` | 本机合订原卷第 4 页能定位题目、所载答案与解法；PDF SHA-256 `8378a8900408578262c62b15a73ce9ac32d4e50985ce346c2c2cff2b08149a23`。该 PDF 在 source root 外且“公开仓库版”文件名本身不能证明其权威性 | 1；`ai_generated_consistent` | 练习可用的 AI 数值最终答案比较；无可信 grader method、无 current answer verification | 待真人确认原卷来源、积分解法、答案、判题适用边界和知识点映射 |
| 2022 数学二 Q5（备用），`90566e9d-9681-40d0-9168-b2cc1770b5a4` | 来源声明指向高校扫描原卷 URL，但本轮登记的本地 source root 中无该文件；自动来源检查为 `SOURCE_METADATA_ONLY` | A；`ai_generated_consistent` | AI 单选比较路径，不是可信判题 | 未核原卷，不计入首批可信库存 |

`source_attested` / `traceable` 和 AI consistency 是机器/流程记录；不是对真题原卷权威性或答案正确性的认证。2023、2024、2017 PDF 在本轮被目视比对只能算 AI 辅助检查，不能替用户写入 `HUMAN_VERIFIED`。本地原卷与整理题目的公开再分发许可也未核实。

## 4. 信任与证据链代码审计

本轮检查 `answer_verification`、`question_eligibility`、`answer_submission_service`、`question_verification_upgrade`、`question_pack`、`golden_learning_slice`、`origin_evidence`、策略投影及对应 PostgreSQL/单元测试。

- 答案核验事件通过当前 pointer、事件类型、题目 ID、答案版本 SHA、answer reliability、reviewer projection 等字段共同判断当前有效性；答案版本哈希绑定题型、题干、选项、知识点 ID 和标准答案。verification event 为追加式记录，数据库触发器拒绝修改/删除。
- source attestation 与 answer verification 是分离的；来源机器证明或 AI 一致不能产生 `verified_objective`。
- reviewed-transcription upgrade 要求精确候选、目标 Question ID 与 before snapshot hash 匹配；审核 pack 对来源、题面、答案、解析、映射、判题等方面做 hash 绑定；只更新指定题目，不重放历史 Attempt 或重算毕业状态。
- 只有当前答案核验、人工内容审核、支持的 verified grader 与合规的独立作答共同满足条件时，才能形成可信客观证据。查看解析/辅助作答、低可信或 AI-consistent 结果不会冒充独立确认。
- 撤销核验会追加 revoked event、解除当前 pointer/可信 grader；更改答案会使旧 hash 失配。系统不通过从 Question 当前状态反向补写历史 receipt。
- proof/discussion/program 的过程审阅仍为辅助证据，不会被当成客观判分；当前 Golden Slice 是单选与数值最终答案，暂不扩展到证明/程序判题。

本轮没有发现需要修改产品代码才能通过上述既有契约的工程缺陷，因此没有改源码。核验到的边界：reviewer 字符串是维护者声明，不是身份认证；人工审核包必须由真人实际检查。系统的流程不能证明填入的人名一定是本人。

## 5. 隔离自动化测试

在 `tests/conftest.py` 明确指定的独立 PostgreSQL `kaoyan_test` 上运行，未对开发数据库执行测试写入：

```text
tests/integration/test_answer_verification.py
tests/integration/test_answer_submissions.py
tests/integration/test_policy_origin_semantics.py
tests/integration/test_learning_loop.py
tests/integration/test_learning_tasks.py
tests/unit/test_policy_origin_semantics.py
tests/unit/test_evidence_pool.py
tests/unit/mastery/test_objective_evidence.py
```

可复现命令：

```powershell
python -m pytest tests/integration/test_answer_verification.py tests/integration/test_answer_submissions.py tests/integration/test_policy_origin_semantics.py tests/integration/test_learning_loop.py tests/integration/test_learning_tasks.py tests/unit/test_policy_origin_semantics.py tests/unit/test_evidence_pool.py tests/unit/mastery/test_objective_evidence.py -v --no-header --tb=short
```

本机 pytest 完整摘要保存在 ignored 路径 `tmp/pytest-phase45a3-summary.log`；开发库前后只读指纹分别保存在 `storage/answer-trust/phase45a3-20261008/baseline-db-fingerprint.json` 与 `post-tests-final-fingerprint.json`。

结果：**219 passed，85.19s，退出码 0**。覆盖真实 verification event 的合成夹具、hash 绑定/idempotency、答案换版失效、撤销不重新认证旧 receipt、只支持的判题器可输出 verified objective、solution/AI-consistent 不能提供来源配额、错误后辅助再答、独立作答、重复题去重、跨天/复测、proof/discussion/program 的过程审阅隔离、Planner 工具状态/候选约束与学习计划事务约束。

这些是真实执行的自动化回归，但其中 `human_verified` 数据明确属于测试 fixture，不是开发库人工审核；它证明代码分支/契约可以工作，不证明某个真题答案已经由真人审过。

## 6. 真实开发库迁移前后保护

测试前后重新对开发库 20 张 public 表做整行 SHA-256 指纹比较：**20/20 表完全一致，无变化表、无新增表**；schema revision 始终为 `f46b2c8d901a`。verification event 数量前后为 0；current pointers 仍为 0。

关键历史数据指纹：

| 数据 | rows | SHA-256 |
|---|---:|---|
| `kp_mastery_policies` | 284 | `5705bc0dc57622f57519ad88938e0c78c6eac9e5e9ff5e72e767fde7611ce4ba` |
| `questions` | 518 | `eabf46fc1fa94d640ac6c8c569fe4a625b3d7c01d35eeabf3f906071af8bd9c4` |
| `question_attempts` | 28 | `6af9666f8aa88f6aca49647d51993646defb9c768ff73e7d9539c3b03012c997` |
| `learning_events` | 29 | `86439c0e4a8c996985570d7b4323c8fc608dd2c48f33ffc49b880268f86d6dae` |
| `kp_states` | 284 | `4d1c2ad98ba6a267b20b91c6a5e6310de4cbec9300ee5a33dffcfe8211a05e68` |
| `question_answer_consistency_runs` | 696 | `d97e21dff4529eaea5e7e74d915efbfc2557885f9c4d909708a23c4dd1d1d52e` |
| `question_source_attestations` | 180 | `3ff0d9309dfa0eb853caa6fb83a9bf65947a8fd5f7e4fb8465ef445b8053417a` |

注意：SHA 指纹证明本轮测试前后开发库的行值一致，不证明学习数据本身正确；测试库 `kaoyan_test` 是隔离测试环境，和此处指纹分开。

## 7. 当前毕业可达性

策略语义上，候选节点保留了 v2 policy；但当前实际可信库存尚**不可达毕业**：四节点的 verified objective question 都是 0，current answer verification events 为 0。反常积分节点虽然有 3 道当前可练习题，但其中的 AI consistency/AI final comparison 不能满足真实来源/人工答案/可信 grader/独立确认要求。它当前 evidence pool 为 `INSUFFICIENT`。

当真人审核与升级成功后，只有至少三道不同 real_exam 题通过完整来源/答案/题面/映射审核，并由独立作答在至少两天形成合规证据，才可能满足现有阈值。错题后看解析再答对仍属于辅助序列；复测间隔由已有策略继续约束。此处是对未来可达条件的说明，不是保证库存一定足够，也不是用户已掌握判断。

## 8. 未解决项与状态理由

状态为 **`PENDING_HUMAN_REVIEW`**：工程审计、审核工作包、隔离测试已准备完成；真人审核尚未发生，不能宣称 Human-Verified Golden Slice 完成。

具体待办：

1. 用户对首批三题逐题核对原卷权威性、题干/选项/公式、答案和完整解析；尤其确认 2017 文件的来源权威性与 2024 Q7 页码/原文。
2. 对每题分别确认判题器是否适用于题型及其输入边界；2024 Q7 当前 answer reliability 为 unknown、当前不能判题。
3. 真人确认题目确实映射到该知识点及必需 skill tag。
4. 如果任一题不通过，保持未核验并换用有本地原卷的候选；2022 Q5 在定位到原卷之前不作为替代可信题。
5. 审核完成后，依据审核后的 exact content hash 走现有 reviewed-transcription upgrade 工作流；需再次独立检查其 dry-run 与受保护变更清单。此报告没有执行该写入。
6. 后续还需真实用户按独立作答完成题目并观察 Attempt → Evidence → KpState → Planner → policy 的实际端到端变化。自动化 fixture 不代替真实作答。

## 9. 下一步最小人工审核清单

先打开 ignored 目录中的 `human-review-closeout.md`（逐题确认表），再用 `human-review-package.md` 查看完整审核材料，逐项审核首批候选：

- 2023 数学二 Q6：`d1691564-0c42-43c0-8ab2-b011fd88ac65`，单选，库内答案 A，AI-consistent。
- 2024 数学二 Q7：`2aa85cd9-baed-493d-b79b-f3174f6016c0`，单选，库内答案 B 但 reliability unknown；请独立判断原题命题与答案。
- 2017 数学二 Q11：`ab961f2c-8e24-4068-9bfc-effc9ea876e9`，填空，库内答案 1，AI-consistent；本机第 4 页可查，但请确认文件来源。

每题分别给出：来源/题面通过或不通过、答案/解析通过或不通过、判题器适用性通过或不通过、知识点映射通过或不通过，以及任何修正内容。仅填写真实审阅人的身份与日期。任何一项无足够依据即不签核；届时由用户决定是否替换候选。

## 10. 约束遵守记录

- 未重跑 A.2 迁移，未改 policy v2 阈值。
- 未更改真实答案、来源状态、current pointer、verification event 或历史 Attempt/LearningEvent/KpState。
- 未新增/批量扩题，未调用模型，未伪造人工审阅或真实用户作答。
- 未 commit、push、reset、clean；未触碰 PostgreSQL 进程或 `.pgdata`。
- 本阶段到此停止，不自动进入 A.4、A.5、4.5B 或 Phase 5。

## 11. Human Review Closeout：逐题复核与升级预检

本轮没有把用户此前笼统的“感觉这几道题没问题”视作任何一题、任何审核维度的正式批准。没有写入真人身份、审核日期、`HUMAN_VERIFIED`、`VERIFIED_REFERENCE`、current answer verification 或 verified grader。

### 三题当前实况（开发库只读复核）

| 题目 | source/题面 | answer/explanation | grader | mapping | 当前状态 |
|---|---|---|---|---|---|
| 2023 数学二 Q6 (`d1691564-0c42-43c0-8ab2-b011fd88ac65`) | 本机 2023 数二扫描件第2页视觉对照；source attestation 为机器记录 | A；`ai_generated_consistent`，非权威答案核验；要求真人独立确认极值与全局最小 | 现有 AI 单选比较；verified method/current answer event 均无 | 当前映射与 skill tag 指向反常积分，尚无真人映射签核 | `source_attested` / traceable；内容和答案未人工核验；目前可练习但不具可信毕业证据 |
| 2024 数学二 Q7 (`2aa85cd9-baed-493d-b79b-f3174f6016c0`) | 本机 2024 扫描件第2页视觉对照；原索引页码记为2–3，需更正/确认 | B；answer provenance/reliability 为 `unknown`，真人需独立判断三个命题；尤其核定“极限存在”是否为有限实数语义 | 当前 unsupported，没有可用 comparator/verified method；不得默认自动判题 | 当前映射与 skill tag 指向反常积分，尚无真人映射签核 | 不可作答/判题；无 current answer event |
| 2017 数学二 Q11 (`ab961f2c-8e24-4068-9bfc-effc9ea876e9`) | 本机合订 PDF 第4页有题、答案/解法；文件名“公开仓库版”不证明权威性，真人需确认来源 | 1；`ai_generated_consistent`，非真人答案核验；真人需确认分部积分及边界项 | 现有 AI numeric-final 比较；无 verified method/current answer event，只判最终数值、不判推导 | 当前映射与 skill tag 指向反常积分，尚无真人映射签核 | `source_attested` / traceable；内容/答案未人工核验；目前可练习但不具可信毕业证据 |

2023、2024、2017 PDF 在本轮复核时的 SHA-256 与审核包原记录一致。机器来源 attestation 只证明导入流程绑定的来源快照，不证明扫描件权威性、授权或答案正确。完整题干、选项、库内答案/推导、原卷文件路径、SHA、逐项真人确认框及签核空栏保存在 ignored 本机文件：

- `storage/answer-trust/phase45a3-20261008/human-review-closeout.md`（逐题人工确认表及本轮预检摘要）
- `storage/answer-trust/phase45a3-20261008/human-review-package.md` / `.json`（已有完整候选包）

不将这些真题全文复制到公开报告。2017 PDF 的来源/公开再分发权未核实；三个原卷来源都不能仅凭文件可读就推定获得公开传播许可。

### 受保护升级工具与 dry-run 能力

检查了 `scripts/upgrade_reviewed_transcriptions.py`、`backend/services/question_verification_upgrade.py` 和 `docs/reviewed-transcription-upgrade-2026-10-03.md`。CLI 默认预览，写入必须显式 `--apply`；目标快照生成走 `build_targets()`，其匹配条件要求在同一活动可考核节点上找到唯一的 active `Question`，来源身份相同，当前 grading config 为未验证且 `content_status=source_transcribed`。应用过程按节点/Question 加锁、核对完整 before-snapshot hash，并在完整批次验证后一次性变更。

但 CLI 的 `--snapshot-only` 及正式 preview 都先运行严格 `prepare()`：需提供真人已批准的审核决策、exact pack fingerprint、source/stem/answer/explanation/mapping/grading 六项均为 `VERIFIED` 的逐项签核。当前没有这些决策，本轮不伪造它们。因此**没有声称执行正式 CLI dry-run**。本轮实际完成的是：

- 在真实 `kaoyan` 开发库中以 `REPEATABLE READ READ ONLY` 执行 `build_targets()` 只读目标预检。三题均唯一匹配到原 Question ID，当前状态满足 source-transcribed 前置条件，并生成了以下 before snapshot hash：2023 `5af31092ab47506c687133aedcc812291872645e2e8aab5303d290f4459ff49d`；2024 `90a2aa9b84bb6653457ef612590cf583c44330e159024602d9cef9817b7cbf53`；2017 `84fca2fd798d4bcd7cd506e2693aa5f1f86cc8557f87d826f308e55f83b1e9c4`。
- 每题 answer version SHA 与上一节候选包一致；三题当前 answer verification event 均为 0，current pointer 均为空，开发库现有 Attempt 计数均为 0。测试前后再次计算的 Question snapshot hash 完全一致，revision 仍为 `f46b2c8d901a`。
- 在 `tests/conftest.py` 固定的隔离 `kaoyan_test` 执行 `tests/integration/test_question_verification_upgrade.py`：**17 passed，exit 0**。该套件包含 `SIMULATED` 人工签核夹具，验证真实 service dry-run 不变更快照、冲突保护、整批失败不部分升级、升级只应用一次、旧回执不追溯认证、并发重放，以及无 grader 时不启用自动确认。它证明测试数据库中的代码行为，不是这三道开发题的实际升级或人工核验。

### 若未来逐题明确批准，预期差异、保护与回滚

以下是基于当前工具实现的**条件式预期**，不是本轮已执行变更。实际批准 pack 可因真人发现问题而不同；若题干、选项、题型或节点需要修正，现有升级器明确拒绝，必须另走版本化内容修正流程。

- 仅触及获准题目的 `questions` 行：答案、解析及审核 pack 中明确批准的题目字段；`grading_config` / `grading_mode`；`content_trust`、`source_status`、真实内容/答案 reviewer 字段及当前 answer-verification pointer。题目 ID、来源身份、题干、选项、题型、节点映射不能由该升级器静默替换。
- 对每一题追加 hash-bound、append-only `question_answer_verification_events`；若逐题审核没有批准可用 grader，必须保持 self-assessed/不支持自动判题。2024 当前无比较器，不可因为可能上线而预先宣称支持。source attestation 不能替代真人来源和 mapping 签核。
- 预期保持不变：schema/Alembic、毕业策略/阈值、节点、`question_attempts`、`learning_events`、`kp_states`、`daily_plans`、`practice_items`、历史 receipts 与既有 verification events；不追溯重判，不重算毕业，不合成真实作答证据。
- 并发保护依赖升级时重新读取并锁定行、核验 snapshot hash；本轮 hash 只在当前版本有效，正式应用前必须新备份、重新读取 hash 并重新 preview。
- **非一键可逆**： verification events 追加后不可删除。正式 revoke 只能追加撤销事件并使当前核验失效，不会自动复原其余 Question 内容；如发现内容错误，应立即停止使用该题，保留审计记录，通过受控版本化修正/前滚流程处理，不得直接删除事件或改写历史 Attempt/Evidence。CLI 的输出文件与 DB 事务不原子；若出现 `prepared_outcome_not_confirmed`，应先只读核对数据库状态。

## 12. 下一步人工确认边界与后续阶段（本轮不实现）

人工审核包要求真人对三题分别判断来源身份/题面、答案/解析、grader 能力边界、知识点及 skill tag 映射；审核者姓名/日期只能由真实审核者填写。若任一题需更正题干、选项、题型或映射，先停止该题升级，不套用现有 review-only upgrade。

- **A.3**：真人完成首批题目核验后，再依 exact content hash 执行获批升级；随后以真实新作答验证 Attempt → Evidence → KpState → Planner → policy 闭环。自动化 fixture 不能代替真人审核/真实用户作答。
- **A.4**：单独审计毕业、复测策略对不同题型及无真题知识点是否适用；不预先改变 policy v2。
- **Phase 4.5B**：未来如经批准再做两类 AI 题：①依据历年真题生成变式；②依据知识树生成原创练习。AI 题必须清楚标记为 generated practice，不能冒充 `real_exam`。没有历年真题的知识点需要独立、可信的考核策略，不得绕过/降低当前 policy v2。

**本轮最终状态仍为 `PENDING_HUMAN_REVIEW`。** 仅完成人工确认材料、真实开发库只读预检与隔离升级测试；未执行任何真实升级，A.3 仍未达成 Human-Verified Golden Slice。到此停止，等待真人逐题审核。
