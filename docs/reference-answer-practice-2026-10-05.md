# 2026-10-05 题库答案比较与空题面修复

用户要求完整题目和答案入库后即可用于练习。练习判断现在依据已存答案；内容来源核验仍独立记录，不再用核验状态阻断选择题或已支持最终答案的提交。

## 作答行为

- 已支持比较的原卷转录题，提交后返回 right / wrong 并显示 ✓ / ×，保留当前题与解析入口。
- 已支持选择题、精确整数/小数/分数、有限自然对数，以及由有理数、π、e、平方根和四则运算构成的常量答案。
- 常量表达式使用受限 AST 构建 SymPy 对象，不执行 eval 或通用字符串表达式解析；限制字符长度、AST 节点、指数、整数大小和运算复杂度。
- `reference_*` 方法表示按题库答案比较。原始 `verified`、内容核验记录及已提交历史均不被改写。是否构成独立掌握或毕业确认，仍由已有证据规则计算。
- 证明、讨论、算法过程、多问计算和未支持的公式答案保留过程审阅/对照或作答保存。不同写法无法确定等价时返回未判定，不猜测错误。
- Agent 工具同时报告题库答案比较方式与核验过的证据判题方式，避免把可以练习判题的题目解释成没有题或无法提交。

## 空题面入口

- 普通组卷不再用 `ExamQuestionReference` 填充练习。没有活动在线题时返回 `question_pool_incomplete`，事务回滚。
- 原卷引用追加接口先按科目、年份、原题号解析唯一的活动完整题目；解析不到或版本歧义时拒绝追加。匹配后追加真实 `Question`，同一张卷幂等去重。
- 知识树接口新增 `online_question_count`。今日学习范围树与追加树只保留通向真实题目的分支。知识树本身仍保留全部节点用于阅读。
- 知识树来源索引只有对应完整题目时显示加入按钮，其他索引保持可查看来源。
- 历史来源引用作答继续可读，学习记录不作追溯改写。

## 本机数据处理

2026-10-05 当前卷中有 3 个未作答来源引用项。维护脚本先保存恢复回执，再把 2 个转换为对应完整题目、移除 1 个没有完整题面的空项。当前卷剩余 6 项，来源引用空项为 0。

回执（本地、Git 忽略）：`storage/question-intake/pending-reference-repair-20261005.json`。

题库总数仍为 518，活动题数 496。其中 383 道支持题库答案比较：选择题 345、精确数值 28、常量表达式 10。当天导入的 444 道中支持 340 道：选择题 309、精确数值 24、常量表达式 7。

## 验证

- 162 项相关后端比较、提交、原卷引用解析、旧历史兼容、学习证据和 Agent 工具回归通过。
- 前端 67 项单元测试、类型检查和构建通过。
- 7 项浏览器合成场景验证提交反馈、停留当前题看解析、空节点过滤、知识范围路径与搜索。
- `scripts/run-e2e.ps1 -TestFile answer-submissions.spec.ts` 的 13 项真实前后端回归通过，覆盖持久化、重试、响应丢失、并发窗口和查看解析。运行使用隔离 `kaoyan_test`、8001 和离线模型替身；测试后端已回收。
- OpenAPI 快照与生成类型一致，38 个路径通过漂移检查。
- 当前本机开发接口 health 正常，返回 `online_question_count` 与 `reference_*` 判题方式；今天卷子无空来源项。

可复现检查：

```powershell
.\.venv-ragas\Scripts\python.exe -m pytest tests/unit/grading/test_reference_practice.py tests/unit/grading/test_answer_grading.py tests/integration/test_answer_submissions.py tests/integration/test_learning_loop.py tests/integration/test_unverified_adaptive_journey.py tests/integration/test_online_reference_resolution.py tests/integration/test_learning_tasks.py
npm --prefix frontend run test:unit
npm --prefix frontend run build
.\.venv-ragas\Scripts\python.exe scripts/check_openapi_drift.py
```

维护脚本仅支持本机开发库，按明确日期工作，默认 dry-run；只有 `--apply` 且指定新的本地回执路径才提交修改。已有作答、揭示答案或学习事件的项目会被保留。
