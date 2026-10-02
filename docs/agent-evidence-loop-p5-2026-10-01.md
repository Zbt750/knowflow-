# P5：证据驱动的下一次学习安排

## 范围和当前结论

本轮复用已有学习任务 Agent、只读工具、后端校验、确认、幂等回执、今日卷追加，以及 P2 Attempt Sequence、P3 Capability。没有新增另一套 Agent、掌握度算法或固定流程作为线上规划器。

工程验证新增了“Agent 安排 → 确认 → 真实提交 → 次日再次运行 Agent → 读取新的证据 → 新草案”的测试。协议替身按工具返回的事实选择题目，而不是在第二次调用中直接指定预先写死的题号。它验证数据交付与事务边界，不证明真实模型会作出相同决策，也不证明 Agent 优于既有规则推荐。

P5本次工程交付与约定的复验坏例已完成：v7全量回归1169通过，最后辅助完成场景真实2任务定点通过。Golden Slice人工核验、独立教学审核、全场景v7重新实测与长期效果仍未证明。此前v5实测说明坏例及v6的1/2失败均保留，详见 [真实复测及说明坏例](agent-evidence-live-review-p5-2026-10-01.md)。不把不同版本拼成当前全量质量通过；P0 RAG分数不是Agent评分。本轮不自动进入P6。

## 核查发现及修复

1. `get_learning_state` 和 `find_questions` 原来直接读旧 `pending_review_question_ids`，与 P3 只认可 objective_v1 待复测的边界不一致。现在仅 objective_v1 记录作为客观待复测输出、选题排序与建议依据；旧自评数据仍原样保留，不修改数据库历史。
2. 同题连续作答可以具有相同 submitted_at。此前按随机 UUID 排序，偶尔把首次答错展示在即时纠正之前。现在时间相同时使用回执 attempt_number 倒序；历史缺失或损坏的序号保守按 0 处理，防止数据库整型转换异常。该排序不声称能推断不同题在同一时间戳下的精确因果顺序。

没有改写已完成作答、毕业规则、题目核验状态、RAG Prompt、模型配置或 P0 报告。

## 隔离闭环场景

`tests/integration/test_p5_adaptive_journey.py` 新增 15 条：

- 数学定积分和 408 二叉树各六类：首次独立答对、答错、同题自行纠正、看解析后答对、猜对、无法判定。
- 第二次任务实际读取 recent_attempts、capability_profile 和客观待复测信息。
- 独立证据后补充不同题；客观错题与即时纠正继续复测；解析辅助、猜测和未知不晋级独立证据。
- 对错题/即时纠正继续确认新的练习项并独立答对，再进行第三次任务，核对待复测清除和下一份草案变化。
- 证明与算法过程维度不会被最终数值答案确认。
- 生成草案前后业务快照相同；确认重放不重复加题；旧卷及提交回执保持不变。
- 旧自评待复测不冒充客观错题、预算不足不写入、历史损坏序号不阻断工具。

数学实验只启用 M01/M03，408 只启用 T01/T02，明确是有限协议实验，不宣称全部题库覆盖。核验模拟仅存在于隔离测试库；16 道源候选仍 GENERATED，讲解仍 UNVERIFIED，测试通过不等于人工审核。

## 测试记录及复现

初次新增测试有探测错误：使用不存在的 `/api/plans/{id}` 读取路线，以及低于 TaskInput 最小 5 分钟的预算。按现有契约改成 `/items` 与合法预算，不修改接口迁就测试。另发现上述真实同时间戳排序问题并修复。

首次全量报告 `eval/reports/agent-evidence-p5-20261001/backend-junit.xml` 保留：1161 passed、1 failed、2 skipped。失败是损坏序号测试误把可能选到的单选题 raw_answer 提交预期写成 wrong；该接口应返回 unknown。改为核对真实提交结果，没有放松其他独立证据与待复测断言。

第二次全量 `backend-rerun-junit.xml`：1162 passed、0 failed、2 skipped，155.468 秒。两条跳过是需要显式 PG18 二进制的桌面独立集群测试，另行提供正确的 `KAOYAN_MANAGED_PG_TEST_BIN` 补测：2 passed、0 failed/skip，11.338 秒，报告 `managed-pg-junit.xml`。不把分次运行描述成一次无跳过全量。

前端 typecheck、35 条 Vitest（9 文件）、生产 build 和 36 路径 OpenAPI 漂移检查通过。本轮浏览器重跑 128 passed、0 failed/skipped/flaky，188.507 秒，报告 `eval/reports/agent-evidence-p5-20261001/e2e-report.json`。测试后端仅回收本次进程，8001/5174 释放，开发8000/5173保持可用。未把刻意模拟请求失败的资源加载 console 噪声表述成“零 console error”。

```powershell
$env:KAOYAN_MANAGED_PG_TEST_BIN='C:\Program Files\PostgreSQL\18\bin'
python -m pytest tests/integration/test_p5_adaptive_journey.py tests/integration/test_agent_learning_journey.py tests/integration/test_learning_tasks.py
python -m pytest --junitxml=eval/reports/p5-reproduction/backend-junit.xml
python scripts/check_openapi_drift.py
# 不要与 pytest 同时使用 kaoyan_test
powershell -ExecutionPolicy Bypass -File scripts/run-e2e.ps1
```

来源为 HEAD `c841adbbddf82c5da3103474e63d7889afaf9c7f` 之上的当前未提交工作区。
工具文件 SHA256：`9062a7aeecf874065fc3e734215e89c4c50cb451beb3537a6dcf7ff5713e077d`。
新增闭环测试 SHA256：`acfb289689957fc1dd154db4a7d12d7be879a504c7df59e50bc6adf862242413`。

## 必要的真实模型补证（未运行）

只使用隔离合成数学/二叉树题、合成学习记录与内置讲解；拟 4 场景共最多 8 次任务，作答前后各一次。每次继续沿用 6 轮、10 次工具调用、60 秒任务预算，轮次可能有有限重试；任务次数不是模型请求次数。不发送私人资料、标准答案或开发学习记录，不自动重跑失败整轮。

检查目标满足、真实工具读取、状态与证据解释、约束与校验、确认前无写入、确认幂等、再次安排变化；保留失败、耗时、重试和 observed usage。上游不返回 usage 记未观测，不记零。工具证据一致性与人工解释核查不能用 RAGAS 问答四项替代。

任何真实调用均须新的用户确认。当前真实模型/裁判调用为 0，当前没有新的教学效果分数。

## 发布与数据边界

本轮没有数据库迁移、自动题包导入、提交或推送，也没有 reset/clean/checkout。P1 原文件 SHA256 仍 `23afaed03155afdf20bd792c21c311ba9b2ace52cf2b3124bd9d200703f3b575`，审核检查 verified_questions=0、release_ready=false。

开发库只读检查：22 活动 Question、2673 ExamQuestionReference、13 QuestionAttempt、6 DailyPlan，与本轮前一致。服务中断后复用原 PG 集群恢复，没有初始化/重置开发数据库；开发后端加载本轮代码，health 显示 database connected、retrieval ready、worker running。

报告哈希：

- `backend-rerun-junit.xml`：`532b56a5a6980a12e8d699de21a60c920d66a1fc14a8de17fca6871860cf87ee`。
- `managed-pg-junit.xml`：`6a0a1998488ef28c9683bbfa0dd9a01ea695b7d86d6860f99683db47fe2b2e5f`。
- `e2e-report.json`：`c8958e20affd152fb60af6bc3052fc19316fd9a473ab8e59105acd6a1a48da27`。

## P5 后续：统一的作答前后评测入口

新增 `scripts/run_agent_evidence_journey.py`，默认离线。复用现有 `isolated_factory`、隐私哨兵、调用汇总、任务与确认服务、实际判题/解析揭示服务，而不是另造线上 Agent。原 P5 测试的条件式 EvidencePlanner 移至此入口共用；这是评测替身，不成为产品规划规则。

四个场景：数学独立正确、数学答错、408 看解析后完成、408 无法可靠判定。每个场景首次安排一题，确认后真实提交，再推进至次日运行第二次任务；确认仅在隔离 schema 中模拟。首次独立正确请求另一道题，其余请求重新验证原题，以用户明确要求核对适应变化，不把“草案随意不同”当 Agent 成功。

报告记录八次任务的真实工具 trace、草案、只读检查、实际答案回执（排除 raw_answer/selected_option）、幂等、各调用耗时/usage/失败/重试/结束原因、代码文件哈希、数据哈希、Prompt 哈希/版本、工具定义哈希和任务限制。usage 缺失保持 null。合成标准答案只用于本地提交，不放入模型工具上下文；原始作答哨兵一旦进入请求即阻断。

源候选仍 GENERATED；评测中的 verified grading config 明确标记 SIMULATED，不伪造真人核验声明，不改源文件、不导入开发库。清空 fixture 前还必须核对实际 `_test` 库、随机评测 schema 格式与脚本标记，直接传 public 工厂也会在任何 DELETE 前拒绝。正常退出回收自己的 schema；复用已有活跃锁与中断残留回收机制。

离线最终报告：`eval/reports/agent-evidence-protocol-20261001T120523-62ee50.json`，4/4、8 tasks；40 次是协议替身请求，不是外部付费模型调用。每条人工审阅字段仍 pending，不据此宣称真实教学质量通过。

该报告 SHA256 `9510e9ba12a928dccc7a2970a3769e79ae7383f9ad8ff618afbb8e3a4497a20b`；评测入口 SHA256 `733164ceee8bc9aa943a1b6a56bbc20e0ec7ed7540a2146b5649ad82eedcf79f`。共用替身后的 P5 测试文件 SHA256 为 `261e88f3bddbe02b5ed46dd55ac937ff10bae19e56b2325e975b2a2f3ae64faf`，前文旧哈希保留为前次全量运行的来源记录，不冒充本次文件哈希。

验证分两次：P5 闭环与旧评测专项 28 passed（30.307秒），其后增加 public-schema 与未授权 live CLI 两条安全断言，评测专项再次 15 passed；结果保存在 `agent-evidence-p5-followup-20261001/targeted-junit.xml` 与 `eval-safety-junit.xml`。后续只改评测脚本、共用测试替身和记录，没有改产品前后端，不把上一轮1164条分次后端与128浏览器记录冒充此次新增脚本的全量重跑。

```powershell
# 不调用外部模型
python scripts/run_agent_evidence_journey.py
# 只有获得新的明确数据/费用授权后才能执行；固定最多4场景/8任务
python scripts/run_agent_evidence_journey.py --live --allow-synthetic-data
```

该后续离线入口交付时真实调用为0。此后在已明示数据/费用/上限的问询下根据用户继续应答完成一次8任务实测，发现解释坏例，详见独立实测记录；不把分轮或版本不同的结果拼成当前质量全通过。修后v6真实补证待新的确认，不自动进行P6或修改普通RAG基线。
