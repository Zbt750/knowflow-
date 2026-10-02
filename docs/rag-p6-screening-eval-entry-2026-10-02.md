# P6 筛选前后真实对照入口准备（2026-10-02）

## 本轮范围

用户要求继续下一步改造，尚未明确确认上一条付费调用预算。本轮只改评测入口和离线校验，不运行隔离真实API或RAGAS，不发送任何资料到模型端点。

受控开关接入已完成，产品默认off。本轮不再次实现筛选逻辑，不改Prompt v6、Agent v7、快照v2、私人.env、开发服务或知识资产。

## 固定对照与预算

`scripts/run_isolated_chat_ragas.py` 新参数 `--context-screening-p6 off|filter`：

- 必须单独搭配 `--baseline-v3-1 --limit 2 --output <新文件>`。
- 固定原v3.1的 `math-followup` 和 `408-page`，不新增题目或任意选例。
- 每个分支包含数学铺垫1次、数学目标1次、408目标1次，最多3次问题请求。
- 两个分支合计最多6次问题请求，4个目标各4项RAGAS，最多16个指标作业；裁判内部可能多次调用，上游有限重试仍须如实记录，不等同于最多16次HTTP调用。
- 不允许与文件定点、跨文件预算、UI/浏览器模式或旧数学追问范围混用；不接受shadow冒充filter。
- 报告文件必须显式给出且不存在，启动数据库/模型之前拒绝覆盖。一次命令只运行一个分支，没有自动跑另一分支或自动重跑整轮的功能。
- 若当前配置启用了重排模型，会绕过已接入的候选筛选，本入口在数据库启动前拒绝运行，不擅自清空重排配置、不花费问答请求再发现无效对照。

命令仅作为**获得明确授权后**的操作说明，本轮未执行：

```powershell
.venv-ragas\Scripts\python.exe scripts/run_isolated_chat_ragas.py --baseline-v3-1 --limit 2 --context-screening-p6 off --output eval/reports/<新目录>/off.json
.venv-ragas\Scripts\python.exe scripts/run_isolated_chat_ragas.py --baseline-v3-1 --limit 2 --context-screening-p6 filter --output eval/reports/<新目录>/filter.json
```

仍使用既有四份合成讲义及独立schema/索引/上传目录；不得混入私人资料或开发学习记录。不把“存在这个入口”当成调用授权。

## 实际配置与评分防误判

开关显式写入隔离子进程环境和评测有效settings，覆盖继承环境的同名值；不写父进程私人.env。现有manifest记录策略版本/门槛/模式。后端实际快照中的诊断还会在付费评分前接受 `validate_screening_snapshot` 校验：

1. 分支必须是实际off或filter，策略版本与0.50门槛必须一致。
2. 计数必须非负整数，before=after+removed，after必须等于实际上下文块数。
3. filter必须实际应用且处于eligible范围，预计删除与实际删除一致。绕过或配置未生效不能写成filter成绩。
4. off不得应用筛选或记录实际删除。

旧评测未指定对照分支时继续走原流程，不给历史报告回填诊断。实际证据快照的引用/hash校验仍先执行，不重新检索评分上下文。

这只能防止“未真正启用却算开启”的误判，不能证明答案完整或学科事实正确。真正复测时仍需保留原回答、命题方向、必要条件、引用对应、逐块有用性、低分、耗时、usage、错误、重试与截断，不能以Precision高分掩盖无关块或仅靠抽取声明判数学表达正确。

## 离线验收

原两个目标均规则分类为explain，top_k12/candidate_k36/diversify=false；数学追问复用最近一条具体用户问句补全，不增加模型改写。新增范围测试锁住这一事实。

运行：

```powershell
.venv-ragas\Scripts\python.exe -m pytest tests/unit/test_p6_eval_scope.py tests/unit/test_screening_eval_guard.py tests/unit/test_ragas_chat_eval.py tests/unit/test_isolated_ragas_cleanup.py tests/unit/test_faithfulness_diagnostics.py tests/unit/test_chat_context_screening.py
```

最终 **94 passed**，报告 `eval/reports/rag-p6-screening-20261002/arm-guard-final-junit.xml`。覆盖固定样例与请求数、拒绝混用/覆盖、实际模式/版本/门槛错误、计数异常、filter绕过、off误筛选、原评测兼容与不修改快照。先前94通过报告也保留。

本轮未更改生产业务代码或迁移，只更改评测脚本与测试，不额外重跑1283全量或前端E2E；1283是上一批最终工作区全量成绩，非本轮新增。无真实回答或RAGAS新分数，不能宣称准确率已改善。

P6尚未整体完成。真实受限对照待明确授权，文件比较坏例和独立人工复核也仍保留。
