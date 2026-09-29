# 问答 RAGAS 四项评测

本目录评测实际应用 SSE 回答，而非另写一套问答。固定问题、参考答案、检索证据、RAGAS 评分与用户行为检查都可重复运行。评测依赖仅供开发使用。

## 四项指标和边界

- **Faithfulness**：答案中的资料结论是否受到检索上下文支持，发现无依据扩写。混合回答只对“通用知识参考”标题之前的资料部分评分；通用知识部分不能伪装成资料结论。
- **Answer Relevancy**：裁判根据回答生成问题，再以本机真实 BGE embedding 比较生成问题与原问题的相关程度。资料内和通用参考问题都评分。它不等于事实正确率或完整率。
- **Context Precision**：与参考答案相关的片段是否排在前面，检测召回噪声和排序问题。
- **Context Recall**：检索片段是否覆盖人工参考答案的关键事实，检测证据遗漏。

另记录必要要点覆盖、引用 chunk 核对、首 token/总耗时和可观测的 token 用量。概述检查逐个要求三个健康字段和四个页面名称，不能只出现其中之一就算完整。常见 LaTeX `\frac` / `\dfrac` / `\tfrac` 及 `\infty` 会规范化，避免正确数学结果被误报。

资料外问题按当前产品要求给**明确标记的通用知识参考**，不是继续硬拒答。它们的三个资料指标不适用（不是 0 分或 1 分）；相关性与要点覆盖仍评分。这四项无法验证通用常识的全部事实，尤其是具体年代、人物、实时信息，仍须独立事实核验或人工抽查。

默认使用应用模型自评，报告标记 `self_judged`，存在同模型偏差。基准只有 8 条，分数是回归信号，不能推断为所有问题都正确。相同问题也存在生成和裁判波动，不以一次分数升降声称确定改进。

## 安全范围

对外模型只接触已获准的《高等数学核心考点讲义》《阶段A验收笔记》两份测试资料及对应问题、参考答案、生成回答。API 必须是本机、`environment=test` 且数据库/检索已就绪；资料白名单不匹配时停止。脚本不输出密钥，报告不包含完整检索正文，仅保留有限回答摘录与引用、章节和评分。

`scripts/run_isolated_chat_ragas.py` 自动创建随机 PostgreSQL schema、临时上传目录与向量索引，启动独立测试 API，导入 `eval/fixtures/` 的两份快照，完成后停止自己的进程并清理该 schema/目录。共享资料 ID 运行前后核对一致。它不测试 Alembic 迁移，也不重置用户的学习记录。本机 API 请求绕过 Windows 系统代理，外部模型连接策略不变。

真实问答和裁判调用会产生费用。使用前须取得相应数据外发和费用授权，不要把用户真实资料混入。

## 安装与运行

在项目根目录准备隔离环境；应用依赖与评测可选依赖都需要，但不修改应用的 `requirements.txt`：

```powershell
python -m venv .venv-ragas
.\.venv-ragas\Scripts\python.exe -m pip install -r requirements.txt -r requirements-ragas.txt
.\.venv-ragas\Scripts\python.exe scripts/run_isolated_chat_ragas.py --limit 8
```

前提：`.env` 的 `TEST_DATABASE_URL` 指向专用测试数据库、已缓存可用的真实检索模型、配置了 OpenAI 兼容回答模型。评测采用本地真实 sentence-transformers embedding，不使用随机或假向量。

若已有专用测试 API（含且仅含获准的两份资料），也可直接运行：

```powershell
.\.venv-ragas\Scripts\python.exe scripts/run_ragas_chat_eval.py --api-base http://127.0.0.1:8001/api --limit 8
```

默认数据为 `dataset/chat_ragas_v2.jsonl`。`v1` 保留旧“资料外拒答”的历史策略，不与当前通用参考策略混算通过率。第 9 条检查内置模式不能读取用户文件；单独运行 `--scope-guard-only` 不创建裁判，但保护失效时应用自身可能调用模型。

可用 `--judge-model` / `RAGAS_LLM_MODEL` 指定独立裁判；`RAGAS_BASE_URL` / `RAGAS_API_KEY` 更换兼容服务。密钥只放环境变量，不放命令行或数据集。其他直接评测选项：`--dataset`、`--limit`、`--output`、`--judge-max-tokens`（默认 8000）、`--metric-timeout`。指标按样例串行运行，裁判采用 Instructor JSON 输出，关闭不必要的 DeepSeek thinking。

## 结果解释

报告位于 `eval/reports/`。评分成功要求 `case_errors=0`、`metric_errors=0`，且四项都有其适用样例的实际样本数。调用失败不能解释为 0 分；所有通用回答都跳过的资料指标也不能宣称它们通过了忠实度验证。

普通检索上下文通过 `/materials/search` 按同样过滤和动态 Top-K 重建，属于同一检索栈的可复现近似，不是生成模型逐字 prompt 快照；文件概述使用正文接口。报告注明 `retrieval_context_source`，引用 chunk ID 另外核对。这一差异及同模型裁判偏差均需在正式验收时考虑。

Answer Relevancy 的 diagnostics 记录原有三次裁判调用反推的问题与 noncommittal 标记，不增加调用或修改评分公式。得 0 分或波动大时可据此核对拒答判定和反推问题语言；旧报告缺少这些记录，不能事后定性为误判。

对低分问题先读原始回答：区分漏要点、错引用、真实事实错误、无关扩写、裁判误判与检查脚本误报。answer_excerpt 有长度上限，摘录末尾不完整不等于模型正文截断；应用用上游 finish_reason=length 检测真正的输出上限。修实际产品后复测，不通过降低标准、排除坏样例或覆盖旧报告来制造高分。

## 最近一轮运行（2026-09-26）

报告：`reports/chat_ragas_four_metrics_20260926_213952.json`。8 条问题、调用与指标错误均为 0，行为检查 8/8。

| 指标 | 样本数 | 均值 | 最低值 |
| --- | ---: | ---: | ---: |
| Context Precision | 6 | 1.0000 | 1.0000 |
| Context Recall | 6 | 1.0000 | 1.0000 |
| Faithfulness | 6 | 0.9206 | 0.7500 |
| Answer Relevancy | 8 | 0.7896 | 0.5549 |

资料问题相关性均值 0.8436，通用问题为 0.6277。部分裁判反推的问题是英文，相关性诊断保留原文，未改动评分。忠实度最低的隐函数求导回答包含资料条件的进一步数学推论，仍需核对归因；不能因为数学结论合理就把资料忠实度自动改成 1。

响应总耗时均值 11.14 秒、最大 33.39 秒，重建检索耗时均值 30.5 毫秒。上游未提供可观测 token 用量，不能据此计算实际费用。相比旧运行的均值变化只是本次观测，不是无随机误差的改进证明；长回答首 token 延迟和通用知识事实核验仍需继续关注。
