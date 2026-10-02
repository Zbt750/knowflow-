# P6 第二批：明确知识追问的检索对象补全

## 原因与取舍

原 `math-followup` 问题是“刚才那个反例左右导数各是多少？它证明了哪个方向不能反过来？”，前一轮用户问“解释可导与连续的关系以及|x|的反例”。生成 Prompt 已有历史预算，但混合检索只使用当前问题，遗漏真正对象；不能指望回答模型从历史中补回根本没有优先召回的正文。

增加 `backend/chat/query_context.py`，不重做三路召回、不加模型 rewrite、不扩大 top-k、不修改普通 Prompt、评分或归因阈值：

- 仅对明确起头的知识追问（例如“刚才那个反例”“这个结论”“这一步”）补入最近一条具体用户问题。
- 只查最近一条用户消息，沿用当前会话；不读取模型答案猜事实，不遍历很久以前的历史。
- 当前问句最多180字符、前一问最多240字符；超限不裁碎句、不强行补全。
- 新话题、显式转题、文件名/资料/章节请求、前一问含糊、问候或重复问句均保留原查询；文件解析继续由已有文件范围逻辑负责。
- 不穿过“继续”“刚才那个呢”等不明确前一轮，去更早历史强行找主题。首版不承诺多跳指代或任意语义消歧。
- 关闭历史预算时不补全；有明确文件范围时不使用这个知识追问分支。
- 补全只用于 embedding、BM25、标题召回与重排查询。当前问句仍原样交给回答模型，候选/片段预算仍按原规则。
- 可确定的补全不额外调用分类模型；没有新增外部调用。

受控 Actual Context Snapshot 增加可选 `retrieval_query_context`，记录版本 `bounded-previous-user-v1`、来源 current_only/previous_user_question 和使用轮数；不记录原问题或历史正文。证据块/引用/证据哈希规则不变，快照v2仍可读取旧报告。这个辅助字段不是对历史正文的额外签名。

## 本地真实 embedding 对照

`scripts/probe_followup_retrieval.py` 固定只读取原数学与408两份合成讲义，正式标题树/分块、真实本地 BGE、小型内存向量库、原 BM25/标题检索与 RRF。没有数据库连接、LLM、裁判或模型下载；不导入开发资料。报告拒绝覆盖。

```powershell
.\.venv-ragas\Scripts\python.exe scripts/probe_followup_retrieval.py --output eval/reports/rag-p6-followup-20261001/local-fusion-probe-v1.json
```

这是**重排前候选融合探测**，不是完整 Chat API、RAGAS 或最终 Context 的验收。

| 查询 | 第一名 | 第二名 | 极限与连续向量相似度 |
|---|---|---|---:|
| 原追问 | 洛必达条件与反例 | 极限与连续 | 0.58379 |
| 加最近用户问题 | 极限与连续 | 洛必达条件与反例 | 0.76397 |

本地真实 embedding `BAAI/bge-small-zh-v1.5` 复现了原候选排序错误并观测到目标升首位。它只证明这个固定合成样例的候选变化；其他数学/408追问是否提升需扩大离线案例，最终回答是否准确需获准真实问答。

洛必达等无关候选仍存在，没有筛掉坏例，也没有用这个单例证明所有上下文已精确。先记录结果，不引入未经校准的全局 cosine/RRF 阈值。

## 测试与版本

新增22条测试：原数据集问题、转题/文件/长文本、前一轮含糊或无效、不回看旧主题、历史预算开关、检索实际收到补全查询、回答仍收到原问句、模式过滤、用户模式不归因、实际证据辅助诊断不含正文。

- 问答相关专项 **119 passed**。
- 后端全量 **1220 passed / 0 failed / 0 errors / 0 skipped**，170.223秒，包含上一批受限评测/忠实度诊断测试。
- `git diff --check` 通过。
- 本轮外部生成模型和 RAGAS 调用均 **0**。未改前端，未重跑前端E2E，不引用旧成绩作本轮结果。
- 身份核验后开发后端已重启加载本批代码，launcher38740 / listener25208；health ok / database connected / retrieval ready / worker running。PG37008和前端40928未动，未发送开发库问答。

报告与 SHA256：

- `eval/reports/rag-p6-followup-20261001/local-fusion-probe-v1.json`：`dd2e2a57b68cf40edbb85f807ca21bdf3c139d9205652fcedda5b19f1032af25`
- `eval/reports/rag-p6-followup-20261001/backend-junit.xml`：`cc7829540ea4db584643a586619d2b250ad51f4b78f14b26c9e191aa65642188`
- `backend/chat/service.py`：`4f06794b16fb3bd7be7d9e4a98932a947b06f1447a120ad03f36de60366bb750`
- `backend/chat/query_context.py`：`7f8a8417ac1035d2a0cedc47e88554c306977b012de0826412627c523ebbb574`
- `backend/chat/evidence.py`：`f3320fcc33ac5db396add9ef01bbea3cc9f018d09f37a44ebd0cea285c49f735`

工作区仍有既有未提交修改，HEAD为 `c841adbbddf82c5da3103474e63d7889afaf9c7f`；上述文件哈希及探测记录限定本次证据，不把HEAD单独称完整运行版本。原P0/上一批真实报告不改。

## 未完成与下一步

本次没有证明“不能反过来”的语言表达已纠正，没有新的忠实度分数或完整回答判定。上一批 E/F/G 的0.8182与Precision冲突仍保留，也不能凭本批查询补全改写旧分。

当前P6仍未完成：普通知识上下文冗余、跨文件比较冗余、通用参考时态、多跳指代与低忠实度逐声明分析。下一次真实补证可仅用原 `math-followup` 场景，一条铺垫+一条目标，最多2次问答及目标四项裁判，利用已补的声明诊断；需新确认，失败不自动重跑。不为新分数重复跑完整基线。
