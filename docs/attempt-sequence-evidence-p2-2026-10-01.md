# P2：同题多次作答与学习证据（2026-10-01）

## 范围与状态

本轮按用户“接着下一步”授权，继续 P2；P0 原始基线不变，不重复调用模型，不提前做 P3 能力维度、P4 新判题器或图片识别。P1 的工程测试可以复用，但 16 道黄金候选仍为 GENERATED，讲解仍待人工核验，不能把 P2 通过当作候选内容已经 VERIFIED。

复用 `QuestionAttempt`、`LearningEvent`、最终答案判题、掌握状态机和 Agent 查询工具，不新增数据库迁移。新 attempt 和事件追加写入，旧答案、判题结果、证据和当时的状态回执不覆盖。今日卷仍是一道练习项，重试不新增题目或增加完成题数。

## 前端

专注和全卷模式的错答/未判定答案增加小按钮“再试一次”，清空本次编辑内容并收起解析；“取消修改”恢复已保存答案，不写新的 attempt。成功提交仍留在当前题，不自动跳下一题，用户可以阅读解析后主动继续。

“作答记录”默认折叠，仅展开时请求历史；显示第几次、结果、证据类别和当次提交内容。打开期间发生新的提交会重新读取历史，过期请求不能覆盖新题记录。旧自述单独计数，不展示为机器判题。历史中的旧状态和确认数是当时的回执，不是当前掌握状态。

提交键绑定答案、选项、信心及预期前驱 attempt。响应丢失后原样重试使用同一个键；另一窗口已经提交时，过期请求返回冲突并刷新最新记录，不覆盖后来的作答。

## API 与证据契约

- `GET /api/practice-items/{item_id}/answer-submissions`：只读历史，返回 `practice_item_id`、`items`、`legacy_self_report_count`。
- 同路径已有 POST 新增可选 `expected_previous_attempt_id`。首次提交不传；对已完成错答/未判定的重试必须传当前最新 attempt ID。
- 响应新增可空 `attempt_number`、`previous_attempt_id`、`sequence_category`、`assistance_level` 和 `can_retry`；旧回执保留旧字段，不回填虚构的序列信息。
- 新证据 `version=3`、`sequence_version=attempt-sequence-v1`，保存题干/答案/判题配置/映射等内容哈希。题目修订后不允许在旧练习项上继续纠正，但原提交键仍可以读取原回执。
- 同题最多 20 条记录，超限拒绝新提交，不影响原回执幂等读取。跨练习项读取同题最近 64 条历史；超限、旧记录或内容版本不兼容时，首次成功归为历史未知，不冒认首次独立正确。
- 锁顺序为计划 → 练习项 → 知识点投影；知识点锁先于跨项历史读取。并发纠正只能产生一个有效后继。
- 冲突错误使用统一信封，代码为 `answer_attempt_conflict`、`answer_retry_not_allowed`、`answer_question_changed`、`answer_attempt_limit`。

| 观测情况 | 序列类别 | 独立确认 |
| --- | --- | --- |
| 无同题旧历史，本次可靠正确且未观察到辅助 | first_independent_correct | 可计入，仍受题目去重与毕业策略约束 |
| 同练习项先错后对，未看解析 | self_corrected | 不新增，不清除待复测 |
| 同练习项先未判定后正确 | correct_after_ungraded | 不新增 |
| 查看解析后正确 | solution_assisted_correct | 不新增 |
| 过程审阅后正确 | process_review_assisted_correct | 不新增 |
| 猜测/完全没思路但正确 | low_confidence_correct | 不新增 |
| 新练习项可靠正确，旧同题只有失败/未判定 | independent_retest_correct | 可计入并清除该题待复测 |
| 新练习项可靠正确，旧同题曾正确 | repeat_correct | 可计入，但同一题不累计多份确认 |
| 正确但旧历史不完整/内容版本不兼容 | independent_correct_history_unknown | 不新增 |
| 可靠判错 | incorrect | 记录失败并保留其他题的有效确认 |
| 无法可靠判题或配置未核验 | unable_to_grade | 弱记录，不冒认正确/错误证据 |

`hint_1`、`hint_2`、`hint_assisted_correct` 是保留的契约与纯分类分支。本轮没有新增分级提示按钮、提示生成服务或可靠提示事件，因此不宣称分级提示产品流程已经完成。实际可观测的辅助仍是解析暴露和已有文字/伪代码过程审阅。

“独立”只描述系统未观察到辅助，`observation_scope=tracked_interface_not_proctored`，不能证明用户未使用纸面、其他窗口或外部答案。照片转录以后只是输入渠道，必须区分单纯转录与给予解题建议。

Agent 的学习状态工具增加序列次数、类别和辅助级别，仍不导出原始作答文本。可靠状态计算继续由后端决定，模型不能改写历史、确认数或毕业结论。

## 验证

后端专项 76 条通过（45.39s）：序列分类、旧记录兼容、同题修正、解析/审阅辅助、空答、最新记录排序、原回执幂等、过期请求、并发纠正、20 次上限、题目修订、跨项复测、Agent 只读字段、黄金样例及未核验拦截。

前端类型检查、32 条单测（8 文件）、构建、OpenAPI 漂移校验通过；快照仍 36 个路径，新历史使用已有路径的 GET 方法。

后端全量 **1053 passed（158.80s），0 失败、0 跳过**；显式使用本机 PG18 二进制执行专用临时集群测试。浏览器全量 **123 passed（3.1m），0 失败、0 跳过、0 flaky**。新增 4 条 E2E 覆盖全卷自行改正与历史刷新、专注取消及解析辅助、二次提交响应丢失、跨窗口过期提交与下一次有效重试。所有原问答、资料、知识树、学习任务、窄屏和异常路径同时回归。

浏览器原始报告保存在 Git 忽略目录 `eval/reports/attempt-sequence-p2-20261001/e2e-report.json`，SHA256 为 `f2ff4b0c79133f2fc2cf83e628d90a53db96be3ed22922f8f5d6ecb04c00a37f`。本轮源代码位于 HEAD `c841adbbddf82c5da3103474e63d7889afaf9c7f` 之上的未提交工作区；不是新冻结标签，也不是对旧提交的测试结论。没有提交或推送。

环境首轮数据库未监听，测试在连接/迁移夹具处失败，不是业务断言失败；恢复现有集群、等待 `pg_isready` 接受连接后，重新运行上述专项通过。没有初始化/重置开发数据目录，没有发送私人资料或调用真实模型。

隔离测试后端已回收，8001/5174 已释放，数据库保持正常运行。收尾只读开发库计数为在线题 22、原卷引用 2673、作答 13、计划 6；未导入黄金候选。数量检查不能代替整库字节级一致性证明。

开发前后端本轮开始时也未运行，测试结束后已用当前代码启动 8000/5173（未覆盖正在运行的开发服务）。健康检查为 dev、database connected、retrieval ready、worker running；`/study` HTTP 200。可直接刷新页面检查新入口，不需要重置今日卷或重新导入题目。

## 可复现入口

```powershell
python -m pytest tests/integration/test_attempt_sequence.py tests/unit/mastery/test_attempt_sequence.py tests/integration/test_golden_learning_slice.py -q
python scripts/check_openapi_drift.py
# 前端目录
npm run typecheck
npm run test:unit
npm run build
# 项目根；仅隔离测试库，离线模型替身
powershell -ExecutionPolicy Bypass -File scripts/run-e2e.ps1
```

全量回归需要可用的本机 PostgreSQL 测试库；桌面专用 PG 集成测试另需显式 `KAOYAN_MANAGED_PG_TEST_BIN`。不要并发运行 pytest 与 E2E，两者会重置同一隔离测试库。
