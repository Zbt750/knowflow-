# 问答 RAGAS 四项评测

新增获准合成v3基线：`.\.venv-ragas\Scripts\python.exe scripts/run_isolated_chat_ragas.py --baseline-v3 --limit 16 --output eval/reports/chat-baseline-v3-20260929.json`。16个场景含2次多轮铺垫，总18次问答；使用固定四份合成资料，不放宽为任意资料上传。真实调用必须取得本轮数据与费用授权，不自动重跑整轮。首轮是带1个问答失败、2项裁判失败的诊断结果，见 `docs/rag-baseline-v3-2026-09-29.md`，不取代旧报告或宣称完整达标。

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

正式评分读取 `actual-model-evidence-v2`：在最终提示词构造处记录逐片段正文、编号、资料名和章节，按回答消息 ID 从测试消息接口取回并验证拼接校验和。缺失、旧版本、错轮次、缺块或映射不一致时该案例停止评分，不用 `/materials/search` 或正文接口重建替代。隔离启动器显式启用 `CAPTURE_TEST_EVIDENCE`；普通开发/生产服务不启用也不返回快照。失败回答快照用于诊断，不计入四指标成绩。旧近似上下文和 v1 整包 context 的成绩不是当前基线，需重新评测；同模型裁判偏差仍需人工复核。详见 `docs/actual-evidence-evaluation-2026-09-29.md`。

报告中的 `generation_trace` 关联本轮答案生成的模型、提示词版本、逐轮耗时、结束原因、错误、重试和实际用量。`token_usage` 是最后一轮用量；跨重试累计看 `observed_usage`，并核对 `total_usage_complete`，缺失不是零费用。统计不包含意图分类等辅助调用。兼容端点支持时可显式开启 `LLM_STREAM_INCLUDE_USAGE`；未观测部分不做伪估算。详见 `docs/chat-generation-observability-2026-09-29.md`。

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
# 学习任务 Agent 评测（2026-09-29）

v3 坏例定点修复使用独立 `dataset/chat_baseline_v3_1.jsonl`，原 v3 不改动。隔离启动器新增 `--baseline-v3-1`；这不是离线命令，运行前须重新限定真实调用授权与输出文件，不能覆盖历史基线。详见 `docs/rag-targeted-repairs-2026-09-29.md`。

v3.1真实首轮已完成18次问题请求；结果与补修边界见 `docs/rag-baseline-v3_1-2026-09-29.md`。后续裁判仅在既有Precision调用上附加逐片段诊断，不改变分数公式，不事后重写v3.1原始报告。

后续文件范围与事实分类离线收口见`docs/rag-followup-scope-and-comparison-2026-09-30.md`。提示词v4尚无新的真实模型成绩，不能拿v3.1分数声称其质量。

文件坏例受限复测入口为`--baseline-v3-1 --file-focus-v4 --limit 3`，固定三场景、最多4次问题请求，仍需要每轮明确授权。2026-09-30首次执行因生成端失败没有可评分回答，详见`docs/rag-file-focus-v4-2026-09-30.md`；不要自动重复运行或将未评分当成0分。

同日恢复连通后的**新授权复测**另存`reports/chat-file-focus-v4-retry-20260930.json`，三条目标回答和四项指标均完成。逐块Context Precision全为0，但诊断表明裁判把单块缺少整题其余章节判为无用，不能用该0分单独宣称检索完全失败，也不能擅自改写原评分。此后新生成的报告在这种Precision=0、Recall=1且引用落在实际证据的矛盾组合下附加`precision_conflict_review`人工复核标记，不修改分数，既有报告不回填。逐条回答、人工核对范围及跨文件截断重生成的成本见`docs/rag-file-focus-v4-retry-2026-09-30.md`。未来若改变裁判口径或证据单位，应另立基线版本。

不调用模型的生成追踪盘点可运行：

```powershell
.\.venv-ragas\Scripts\python.exe scripts/analyze_chat_generation_reports.py eval/reports/chat-baseline-v3_1-20260929.json eval/reports/chat-file-focus-v4-retry-20260930.json
```

只打印汇总元数据，不打印问题、回答或上下文；只分析显式传入的文件。失败报告中恢复到的生成追踪也计入。输出上限、网络重试、最终用量须分开看，且不同提示词版本不能直接当成同一线上样本。四份隔离报告的盘点与结论见`docs/chat-output-limit-offline-audit-2026-09-30.md`。

跨文件预算的单例探索入口为 `--baseline-v3-1 --cross-file-budget 4000 --limit 1` 或将预算换为 `6000`，每次仅固定一条跨文件问题请求，仍须限定实际模型调用授权；参数只覆盖隔离后端首轮预算。2026-09-30两档各一次、均未截断，原始报告与人工结论见`docs/chat-cross-file-budget-pair-2026-09-30.md`。该单例不是稳定性或成本改善证明，不应据此改全局预算。

默认 `python scripts/run_learning_agent_eval.py` 只验证隔离数据、工具协议和报告。经明确授权后加 `--live --allow-synthetic-data --limit 8`，使用当前配置模型跑同一组固定合成场景。它不发送私人资料、不写开发今日卷；报告逐场景保存于 `eval/reports/learning-agent-*.json`。

通过率是任务约束检查，不是 RAGAS 或教学质量分。真实工具、最终草案、失败与重试、usage、耗时供人工复核。详见 `docs/learning-agent-evaluation-2026-09-29.md`。原有问答四项评测继续保留。

扩展场景使用 `python scripts/run_learning_agent_eval.py --suite extended --limit 4`，覆盖连续修改、无上下文指代、父节点与排除范围、题数不足。多次修改的每个阶段都记录并核验；四场景最多六次任务，任务内可能有多次模型调用。真实调用须重新核对授权范围。结果与已知语义失败见 `docs/learning-agent-extended-evaluation-2026-09-29.md`。

`python scripts/compare_learning_planners.py` 在相同隔离数据上对照协议Agent与复用现有缺口选择器的规则适配方案，不收费、不写今日卷。规则使用人工定位关键词、Agent使用替身，不是自然语言理解/真实教学效果对比。详见 `docs/learning-agent-finalization-and-comparison-2026-09-29.md`。

## 当前 RAG Baseline 的 P0 冻结（2026-10-01）

P6 上下文相关性离线对照可运行 `python scripts/probe_context_relevance.py --output eval/reports/<新目录>/calibration.json`。使用本地真实缓存embedding、16个固定合成样例与章节标签；不调用LLM/裁判或读写数据库、拒绝覆盖报告。对照结果同时保留无关块和漏失章节，不将章节覆盖当成RAGAS Recall，不在生产中启用实验阈值。标签为助手复核非独立人工真值，完整边界见 [P6校准记录](../docs/rag-p6-context-calibration-2026-10-01.md)。

新措辞与长段落固定验证使用 `python scripts/validate_context_relevance.py --output eval/reports/<新目录>/validation.json`。18个新样例保留原五策略，增查跨chunk的必要条件和反例；不能因标题仍在就认定覆盖完整。复现和两批一起作取舍见 [P6验证记录](../docs/rag-p6-context-validation-2026-10-01.md)。仍无模型/裁判/数据库调用，旧报告不得覆盖。

实际问答准备链路已支持受控 `CHAT_CONTEXT_SCREENING=off|shadow|filter`，默认off；shadow不改变上下文，filter只作用于受支持普通检索，文件/综合/降级/重排绕过。当前快照附仅计数诊断，评测manifest记模式与策略版本，不与旧结果混算。开关未在私人.env启用；真实问答/裁判调用仍须明确授权，详情见 [P6受控筛选](../docs/rag-p6-controlled-screening-2026-10-02.md)。

真实对照入口 `--context-screening-p6 off|filter` 固定数学追问/408缺页，每分支最多3次问题请求，要求v3.1/limit2/新输出文件，拒绝其他付费范围混用。实际快照模式与计数必须通过评分前校验；仅有入口不代表已授权调用。预算、限制及本轮94条离线回归见 [P6对照入口](../docs/rag-p6-screening-eval-entry-2026-10-02.md)。

获准的两分支真实对照已完成（6问题/16指标），预算用完不能自动重跑。原件及坏例见 [P6真实对照审阅](../docs/rag-p6-screening-live-review-2026-10-02.md)。`scripts/compare_screening_reports.py` 仅离线检查版本/配置/范围与实际快照，输出另存、拒绝覆盖，不调用模型或重评分；不以片段减少或Precision高分判定回答正确。

随后针对数学方向矛盾和背景定义误贴来源，普通问答 Prompt 升为 `chat-evidence-v7`，补合并条件措辞与逐事实引用边界；旧 v6 对照原件保持不变，不能改标为 v7。135 条定点离线回归、1327 条完整后端回归通过（0失败/错误/跳过），无新增真实调用；修复后模型质量未验证，详见 [P6方向与来源修复](../docs/rag-p6-source-direction-2026-10-02.md)。

随后经确认，v7/off 仅两目标加一次铺垫完成 3 请求、8 指标，无整轮重跑。数学原答案方向一致（F=1/AR=.7409），408 仍混合背景定义附 C1（F=.6667/AR=.9670）；各 12 块仅 1 块被判有用，P≈1/R=1 不作为全局质量通过。观测生成含铺垫 9985 tokens、不含裁判，原低分/诊断不改；清理 schema 0，详情见 [v7 真实复核](../docs/rag-p6-source-direction-live-review-2026-10-02.md)。不与 v6 混算，授权已用完，P6 尚未整体完成。

本轮继续进行无需付费的工程收口，普通 Prompt 升为 v8，补“资料与背景分句”，防止同一句/列表/表格混用引用。139 专项、1331 后端全量、35 前端单测、typecheck/build、36路径 OpenAPI 校验通过；五份历史报告的8个实际快照只读校验有效，不回填成 v8。真实质量仍待授权复测和独立审核，详见 [P6 离线收口清单](../docs/rag-p6-offline-closeout-2026-10-02.md)。

同批完整浏览器回归128通过、0跳过/失败/flaky，生成JSON原件另存，测试后端已回收。使用离线模型替身，不以E2E全绿替代v8真实回答质量；本轮未新增付费问答或裁判。

当前版本条件与历史结果的兼容性审计见 [P0基线收口](../docs/current-rag-baseline-p0-2026-10-01.md)。v3.1全量与后续v4/v5定点报告分开保留，不拼接不同Prompt的均值，不删除Precision0/失败/慢例。随后获准的当前v5+比较首轮6000完整16例实测已另存，详见 [P0实测冻结版](../docs/current-rag-baseline-measured-2026-10-01.md)。原预审包不回填。

`python scripts/freeze_current_rag_baseline.py --output-dir eval/reports/<新冻结目录>` **只做离线归档**：复用manifest、实际快照校验与逐例追踪统计，不创建Provider/embedding/DB engine，不调用RAGAS。原报告与源码/合成数据归档在本地Git忽略目录，拒绝覆盖旧冻结目录；不归档密钥、开发数据或私人资料。两份checkpoint经逐例相等核验后排除重复计数。辅助内容复核不替代独立真人审核。

`scripts/seal_current_rag_baseline.py` 只离线封装已完成实测与既有预审原件，拒绝checkpoint、筛掉场景、超出授权问题数、变动生成源码/Prompt/数据/配置或篡改评分快照。当前16目标+2铺垫完成18次问题、57个指标作业，无请求/指标错误；F .9418 / AR .7371 / P .7381 / R .9762。这不是全业务质量通过证明。单列生成耗时/usage、逐块正判比例（仅诊断、不改分数）及Codex辅助复核，独立人工仍pending；P0后停止。
