# P6：命题方向与引用边界的定点修复

## 原因和范围

上一轮真实 off/filter 对照两份数学追问答案都将“连续⇒可导这个方向不能反过来成立”与随后正确的原命题/逆命题列表并列。Faithfulness 都为 1，仍不能证明表述一致。408 答案还把讲义未显式展开的 TLB 背景定义附上 C1；其中部分低分也可能包含裁判对合理改述、组织措辞的过严判断。原答案、低分与 NLI 诊断全部保留，不重评分或修改合成讲义来提高指标。

本轮不增加检索量、不调整筛选阈值、不调用模型/裁判、不改 Agent，不进行通用数学语义自动改写。只修改普通问答提示词并验证已有来源隔离链路。

## 修改

- 普通问答 Prompt 从 `chat-evidence-v6` 升为 `chat-evidence-v7`。学习任务 Agent 的 `learning-task-v7` 是另一条版本线，没有改动。
- 命题方向触发补齐“必要充分”“充分必要”“充要”。要求先明确原命题 P⇒Q，再明确逆命题 Q⇒P，最后说明反例否定的对象；Q 真且 P 假否定 Q⇒P，不否定 P⇒Q。
- 明确禁止把逆命题称为“不能反过来成立”的对象。必要/充分条件须按方向说明，不用预写某一道题的答案代替通用规则。
- 两种资料模式共享引用支持边界：引用支持相邻的具体事实，允许忠实改述及有明确资料前提的推导，不允许仅因同主题就为外部定义、机制或条件贴引用。
- 确有必要的背景补充放末尾 `## 通用知识参考`，声明不是文件内容且不附 C 编号。不需要背景时不强制新增段落；不能用常识猜文件。
- 复用已有完成处理：通用参考段编号不会保存成来源卡，完成帧与历史答案一致。没有增加模型判断调用，也没有静默删改数学结论。

## 版本证据

工作区基于 HEAD `c841adbbddf82c5da3103474e63d7889afaf9c7f`，包含大量既有未提交修改；HEAD 不是本次源码快照。以下 SHA256 固定本轮涉及的生成代码：

| 文件 | SHA256 |
|---|---|
| backend/chat/service.py | 5c593884bbcd6f28dfa49688fc13c7e27bcb69e3b0d856c7805f99a0ce8e0ee6 |
| backend/chat/call_trace.py | 42bd5d7d5e730f0f15ebc642ccdd16a0fe9524055e645e22c1d4ea435ae8e0ad |

历史对照仍属于 v6，不可改标为 v7 或混入 v7 指标均值。原件校验未变：

- `eval/reports/rag-p6-screening-live-20261002/off.json`：45973f362e052bd1a8e7d9cf8392ce209d2e87ac51fc9946958e7136b3004941。
- `eval/reports/rag-p6-screening-live-20261002/filter.json`：a80cea4cc47bf082f1af11464e5e36b130e886b36d621089071038f5e135390a。

Actual Context Snapshot 格式、dataset、retrieval/rerank/context 参数、模型配置均未在本轮调整；受控筛选默认仍为 off，私人 .env 未修改。

## 离线验收和限制

定点测试 135 条，0 failed/error/skipped，报告 `eval/reports/rag-p6-source-direction-20261002/targeted-junit.xml`。新增测试覆盖合并条件措辞、两种资料模式的来源约束，以及不同层级通用参考标题的真实 SSE 完成和数据库保存。沿用实际上下文、调用追踪、通用参考与问答流程回归。

复现（Windows）：

```powershell
$env:KAOYAN_MANAGED_PG_TEST_BIN='C:\Program Files\PostgreSQL\18\bin'
.\.venv-ragas\Scripts\python.exe -m pytest tests/unit/test_chat_direction_contract.py tests/unit/test_chat_retrieval_intent.py tests/unit/test_chat_call_trace.py tests/unit/test_actual_chat_evidence.py tests/integration/test_chat_stream.py tests/integration/test_chat_flow.py -q
```

测试使用隔离测试库和离线 Provider 替身，不发送私人资料、不写开发学习记录。Prompt 断言证明约束实际注入，SSE 测试证明来源段落隔离和持久化；它们都不证明真实模型必然遵循，不能将旧版本高分当成修复后质量证据。

最终完整后端回归 **1327 passed，0 failed/error/skipped**，JUnit 时间 164.952 秒。报告 `eval/reports/rag-p6-source-direction-20261002/full-junit.xml`，SHA256 `d6010639cf33f3bb23f07eba100f7eb530ec2445b93683214e856bf0e2ad6c99`。使用上述环境变量后执行 `python -m pytest -q --junitxml=<新报告路径>` 可复现。本轮未修改前端，不将后端回归称为浏览器实测；收尾只读探测未发现 8000/5173 的监听进程，没有宣称开发服务已加载 v7。

本轮真实模型/裁判调用为 0。v7 的命题方向一致性和逐事实引用仍待受限真实复测，独立学科人工审核仍 pending。P6 尚不能宣告全部完成；不自动进入知识资产最终收口或安装包路线。
