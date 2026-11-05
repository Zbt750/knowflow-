# 奶蛙出题交互、原题上下文与回答显示修复

日期：2026-10-18

结论：本轮代码修复及离线、隔离数据库、浏览器验收通过。真实 DeepSeek 质量复测未执行。当前正式应用的 8000 后端未启用自动重载，本轮未重启它；真实页面的后端行为需要进程重启后生效。

## 已确认根因与修复

1. 原有出题识别依赖礼貌前缀和句尾“题”字，漏识别“再来一道”“这题我会了，换一道更有挑战性的”等后续请求；“难度更大”也没有被正确解析为提高难度。现在按动作、对象及上下文识别，并区分解答、讲解、库存与出题。生成解答不等于生成新题。
2. 原题只支持持久化 Question ID，聊天中粘贴的原题没有进入 PersonalGenerationRequest。现在把原始指令、原题正文、原题用户消息 ID 或 QuestionVersion 来源存到当前回复的 generation_context。确认及重试沿用这个快照；实际 Provider 请求收到 reference.statement、reference.source 和 user_requirement。
3. 两个前端都在有确认卡时拦截所有新消息。现在仅把明确的短确认回复交给确认操作，补贴原题、改变难度和新的请求可正常发送。新的生成请求会使旧卡 superseded；历史读取和 SSE 重放都过滤取消/失效卡。确认仍校验会话、知识点及学习位置，未绕过安全门。
4. 已确认且学习位置未改变的知识点可以在后续请求明确解析到同一节点时复用；发生范围变化时仍须确认。多道原题无法确定时先澄清，支持回复“第一题/第二题”，不靠模型猜选。
5. SSE 已使用增量 UTF-8 解码，不能将历史所有公式异常归因于中文拆包。本轮实际发现解析器只接受 LF 空行、不支持 CRLF/多行 data，并且把消费者异常和坏 JSON 一起吞掉。现已支持标准行边界，等待异步消息消费者；非法 UTF-8 和损坏 JSON 明确作为传输失败处理，不自动重发收费请求。
6. 数学块中被 Markdown 多转义的命名算子下标，例如 `\sum\_{n=1}`，会被当作字面下划线；现只在数学区域修复该窄范围语法，保留普通代码和 `\text{file\_name}`。另外 KaTeX 的静默红字降级没有可靠错误提示，现捕获解析失败、保留原公式并显示恢复提示。
7. 新生成题如果包含 JSON 反斜杠错误解码产生的控制字符或替换字符，会在输出校验阶段被拒绝。这是新增的防御检查；没有证据说明每一条旧历史异常都来自该原因。本轮没有清空或批量改写历史消息。

## 实际行为

流程一：先粘贴原题，再要求生成类似/变式题，后端使用可追溯的最近原题。

流程二：先要求变式但无原题，返回补充原题提示且不调用 Provider；用户贴题后继续原要求，必要时确认知识点。

流程三：做题页从 PracticeItem 进入，使用其绑定的 QuestionVersion，不把当前 Question 新版本当作历史原题。

流程四：修改待确认请求的难度或题型，形成新要求并使旧卡失效；确认不会再追加同一条用户消息。失败重试沿用请求和原题快照；重复请求不重复调用模型或保存题目。

生成成功必须来自实际生题服务返回的已保存 Question ID。普通问答不制造生成结果卡。成功后预览题目和所属节点，用户明确加入后才创建 PracticeItem；没有今日卷时保留创建确认。

## 修改文件

| 文件 | 本轮修改 |
| --- | --- |
| backend/services/personal_generation_intent.py | 动作识别、解释/出题反例、难度解析 |
| backend/services/generation_conversation.py（新增） | 可追溯原题解析、缺失原题续接、多个原题澄清、要求修改 |
| backend/services/learning_assistant_service.py | 回合上下文快照、确认生命周期、同范围确认复用、生题请求传递 |
| backend/services/personal_question_service.py | 把原题与用户要求传给实际 Provider |
| backend/services/question_generation.py | 原题约束、JSON 文本损坏校验 |
| backend/schemas/personal_questions.py | 可选的原题正文、来源和用户要求字段；无迁移 |
| backend/api/routes/chat.py | 历史返回过滤 superseded 确认卡 |
| frontend/src/components/LearningTaskPanel.vue | 允许新输入、不再被旧卡锁死、失效卡本地恢复、最终回答文本同步 |
| frontend/src/pages/ChatPage.vue | 相同确认与恢复规则 |
| frontend/src/api/chat.ts | UTF-8、LF/CRLF、多行 data、显式解析错误、异步消费 |
| frontend/src/api/personalQuestions.ts | 原题预览可选字段 |
| frontend/src/components/PersonalGenerationConfirmation.vue | 可展开查看本次变式原题 |
| frontend/src/lib/markdownMath.ts | 仅修复数学算子被多转义的下标 |
| frontend/src/components/MarkdownContent.vue | 明确公式解析失败并保留原文 |

测试及验收辅助文件：

- tests/unit/test_generation_conversation_intent.py（新增）。
- tests/integration/test_generation_conversation_journey.py（新增）。
- tests/integration/generation_journey_backend.py（新增，固定 Provider，强制隔离测试库）。
- frontend/src/api/learningAssistant.test.ts。
- frontend/src/lib/markdownMath.test.ts。
- frontend/e2e/generation-turn-safety.spec.ts。
- frontend/acceptance/generation-conversation-persistence.spec.ts（新增）。
- frontend/playwright.generation.config.ts（新增）。
- scripts/run_phase45e_test_cluster.py：增加白名单内的离线验收后端与专用浏览器配置选择，不改变正式应用启动。

专用持久化浏览器用例单独运行，没有在普通套件中添加 skip 来掩盖环境依赖。

## 测试结果

| 验证范围 | passed | failed | skipped | 耗时/说明 |
| --- | ---: | ---: | ---: | --- |
| 相关后端回归（6 个文件） | 107 | 0 | 0 | 49.56 秒，真实隔离 PG + 固定 Provider |
| 最后卡片重放/原题来源定向复核 | 35 | 0 | 0 | 9.13 秒，包含上述相关用例，不能重复相加当成独立总数 |
| 最终专用持久化运行中的旅程回归 | 7 | 0 | 0 | 5.43 秒，包含上述旅程用例 |
| 双页面 UI/生题预览回归 | 31 | 0 | 0 | 35.7 秒，真实 Chrome + 接口协议夹具 |
| 实际前后端与数据库持久化浏览器验收 | 1 | 0 | 0 | 6.5 秒，未拦截 API，固定 Provider |
| 相关前端单元测试 | 22 | 0 | 0 | 4 个文件，包含逐字节 Unicode/数学 SSE、请求恢复、公式 |
| 前端类型检查及生产构建 | 通过 | — | — | vue-tsc + Vite |

本轮浏览器测试曾发现“公式错误提示没有触发”，已修复实际 KaTeX 错误捕获并重新运行完整上述 31 项。保留首次失败 trace；最终没有放宽功能要求、删除失败用例或增加跳过项。没有声称执行了全项目全量 pytest。

## 可复核的端到端证据

最终运行目录：`storage/quality-audits/generation-conversation-persistence-verified-20261018/`。

实际数据库为隔离端口 **56507**；run-summary.json 记录 original_cluster_touched=false、temporary_postgres_stopped=true、owned_temporary_data_removed=true。

浏览器真实输入：

1. “帮我生成一道难度更大一点的类似题”。
2. `当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`
3. 在确认卡选择“级数求和（隔离验收）”并确认。
4. 固定 Provider 验证收到原题、提高难度、计算题约束，返回 `\sum n^2x^n` 的完整题干、参考答案和解析。
5. 真实服务质量检查后保存并在浏览器展示预览。
6. 点击加入，刷新恢复；数据库核对同一题只有一条 PracticeItem，版本和知识节点匹配。

数据库核验（浏览器报告附件 database-proof）：

| 对象 | ID/结果 |
| --- | --- |
| Question | 58a5c11f-fae9-5404-b345-9133b0cacabf |
| QuestionVersion | aae779aa-d659-47ab-afde-a62e66ea7884 |
| KnowledgePoint | 1f109c39-a605-49e8-9bbd-f51be0059f6a |
| 加入前 PracticeItem | 0 |
| 加入后及刷新后 PracticeItem | 1 |
| bank_scope | personal |
| 正式审核事件 | 未创建 |

截图：[实际保存后、加入前预览](../storage/quality-audits/generation-conversation-persistence-verified-20261018/browser-artifacts/generation-conversation-pe-d32e0--explicit-idempotent-append/persisted-before-add.png)。

证据：[浏览器机器报告](../storage/quality-audits/generation-conversation-persistence-verified-20261018/browser-report.json)、[数据库隔离运行记录](../storage/quality-audits/generation-conversation-persistence-verified-20261018/run-summary.json)。

中文、公式及刷新截图位于 `storage/quality-audits/generation-conversation-ui-verified-20261018/browser-artifacts/`，分别有 study 和 chat 场景。

## 场景覆盖与边界

A/B/C：缺失原题、先贴题、先讨论后变式均有定向回归；D/E：旧卡、修改难度与题型、重放/幂等有 API 与 UI 验证；F/G：解释与检查思路保持 QA，有正反例及两个页面协议验证；H：错误推导/格式/空解析等拒绝保存；I/J：真实保存、预览、明确加入、版本绑定与幂等有数据库核对；K：两个入口的确认和显示协议均验证。

本轮收费模型调用 **0**，费用 **0**。固定 Provider 只能证明工程与业务流程，不能证明真实 DeepSeek 对任意原题都能产出正确变式。通用个人题的结构检查也不等于完整独立正确性证明；现有参考题标识和正式毕业隔离规则保留。真实网络、模型最新输出、跨供应商编码错误仍需独立授权的实际模型验证。

本轮没有连接或修改真实数据库 127.0.0.1:5433/kaoyan，没有迁移真实库、调整真实权限、重建题库、修改毕业规则或删除历史记录。当前 8000 端口后端 PID 17028 未使用 --reload；本轮没有重启正式进程，代码生效仍需重启该后端。
