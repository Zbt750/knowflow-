# 当前工程交接与冻结边界（2026-10-04）

本轮继续工程收口，不新增 AI 功能、不推进安装包、不调用付费模型、不自动 commit/push。工程回归通过与真实题内容通过是两道不同的门禁，当前仍为工程冻结候选。

## 工作区与验收证据

HEAD 为 `b252178fce4e7852caef5332e3e7b10bd294bbc1`，存在未提交修改；仅用 HEAD 不能复原当前工作区。逐文件 SHA256 由既有 `scripts/audit_repository_checkpoint.py` 记录在本地 `eval/reports/stage1-20261004/engineering-handoff-inventory-v2.json`，包含已跟踪及未忽略文件，不包含私有运行数据。报告不提交 Git，复查时另存新版本。

| 检查 | 结果 | 本地证据 |
| --- | --- | --- |
| 后端全量 | 1708 passed，2 skipped，0 failed/error；190.758 秒 | `eval/reports/stage1-20261004/deferred-review-full-regression-v1.xml` |
| 新场景与既有学习闭环 | 21 passed，0 skipped | `eval/reports/stage1-20261004/deferred-review-journey-v1.xml` |
| 前端类型、构建 | 通过 | 前一轮实际执行 vue-tsc / Vite，运行代码本轮未变 |
| 前端单测 | 51 passed，13 文件 | 前一轮实际执行 Vitest |
| 学习任务浏览器专项 | 11 passed，0 failed/skipped/flaky | `eval/reports/stage1-20261004/deferred-review-task-browser-v1/run-report.json` |
| 本轮全量浏览器回归 | 146 passed，0 failed/skipped/flaky；223.086 秒 | `eval/reports/stage1-20261004/engineering-handoff-browser-full-v1/run-report.json` |
| OpenAPI | 38 路径，22 必需路径；快照及类型一致 | `scripts/check_openapi_drift.py` |
| Docker 静态配置 | 通过，不等于当前容器运行通过 | `scripts/check_deploy_config.py` |

两条后端跳过是安装包相关的独立 PG18 环境用例，不计作通过。浏览器回归使用离线协议替身和隔离数据库；刻意制造的失败请求会产生已归类的资源 console 错误，不声称所有场景零 console.error。没有用这些测试证明当前真实模型的选题解释质量。

本轮另运行仓库扫描与资产边界的9条单测，全部通过。全量浏览器脚本正常回收自己启动的测试后端；开发服务健康与测试端口释放另行只读复查。本轮没有修改运行代码或开发学习数据。

## 当前闭环的真实边界

复用既有 Attempt Sequence、Evidence、Capability、Agent 和确认服务。本轮之前补齐了待核验题的来源摘要与草案提示：可练习不等于可确认掌握。数学/408 的未核验提交、解析后提交、跨天重复提交均不能累积独立确认；确认接口重放不重复加题，旧卷不被改写。

这些工程行为已通过隔离场景验证，详见 [人工审核延后时的闭环](deferred-human-review-adaptive-closeout-2026-10-04.md)。实际题目的题干、答案、来源及许可、解析、主知识映射、判题配置仍需内容审核。用户同意后续自行测试不是已完成逐题人工审核的签名，不提升 VERIFIED。

## 质量证据复用

RAG v10 的已记录生成链、Prompt/配置及评测文件离线比较没有变化，六个 Actual Context Snapshot 有效，因此保留原受限结果，不为重新跑一遍调用模型。原 Precision 均值 0.4、相关性和慢样例继续保留，见 [v10 真实评测](current-v10-real-evaluation-2026-10-03.md)。六例不是整个问答系统的准确率；供应商模型修订与历史运行环境信息不完整，也不证明现在上游服务完全相同。

Agent 主 Prompt 仍为 v7，但选题工具结果结构已经变化。旧真实 Agent 报告不能直接证明当前工具版本全部通过；新的真实场景验收需要另行确认数据范围和调用上限。

## 复跑与恢复

在已配置的隔离测试环境中，先运行后端，再运行浏览器；不要并发执行会清空同一测试库的任务。以下不调用外部模型，真实质量评测不能由离线回归替代。

```powershell
.\.venv-ragas\Scripts\python.exe -m pytest
& 'D:\应用安装包\npm.cmd' --prefix frontend run test:unit
& 'D:\应用安装包\npm.cmd' --prefix frontend run typecheck
& 'D:\应用安装包\npm.cmd' --prefix frontend run build
```

完整浏览器回归按 `scripts/run-e2e.ps1` 的隔离库流程运行；输出目录必须是新的路径，不覆盖旧报告，并确保 PATH 中 Python 来自项目测试环境。运行前核对脚本显示的目标库为 `kaoyan_test`，不能改成开发库。环境初始化参考 [README](../README.md)，已有 PostgreSQL 集群不可再次 initdb。README 已把开发数据库日志移到 `storage/postgres-dev.log`，不写入数据目录；本轮仅修正文档，没有重新初始化数据库。

源码检查点不包含数据库中的在线题、私人资料、密钥、Actual Context Snapshot、原卷和模型。恢复这些内容需要独立私有备份，不能认为 clone 就能恢复当前题库。最新内容修订前的私有备份位于 `storage/backups/pre-q011-content-correction-20261004-v1`；已验证备份目录与 pg_restore 清单，但未证明完整恢复演练。规则见 [仓库资产策略](repository-asset-policy.md)。

依赖声明与 observed-python-packages 不是严格依赖锁。干净机器安装、当前 Docker 运行、完整备份恢复演练尚未验证，不能宣称生产发布完全可复现。

## 下一道门禁

1. 人工核验两个学习切片中的真实题，保留未核验、来源冲突及不支持自动判题的状态。
2. 用核验题验收独立正确、解析后完成、同题记忆三类真实学习闭环；Agent 决策是否合理，而非强制换题。
3. 经独立授权后验证当前工具版本的真实模型解释与选择质量；不自动复跑 RAG 或扩额度。
4. 内容和质量门禁满足后形成 Final Freeze；安全审计及实际暂存核对后再按授权建立 Git checkpoint。

安装包、程序沙箱、新 Agent/RAG 技术不在本轮范围。当前没有替用户完成内容审核，也没有把工程回归冒充最终内容发布验收。
