# 奶蛙生题失败诊断与会话用途隔离修复

日期：2026-10-19。基于当前代码、真实开发库只读账本、实际Chrome浏览器和独立PostgreSQL测试。没有发起新收费模型请求。

## 一、真实拒绝原因与证据

使用应用配置中的 `127.0.0.1:5433/kaoyan`、角色 `kaoyan`、Schema `public`，以连接默认只读并显式 `BEGIN READ ONLY` 查询生成账本与会话元数据。没有读取或输出密码/API Key。

实际最近4个生成批次为2成功、2失败，不是所有请求都失败；两条失败均为：

| 实际批次 | 时间（上海） | 模型/上限 | 原因 |
| --- | --- | --- | --- |
| `12faa4a4-e932-45fd-9707-8706babca137` | 2026-10-19 09:29 | deepseek-flash / 3000 | OUTPUT_TRUNCATED |
| `139f7869-82ed-420f-ac72-6d03ffcccaf0` | 2026-10-18 23:00 | deepseek-flash / 1800 | OUTPUT_TRUNCATED |

最新批次请求难度 improved、单选，已有126字原题，来源kind=question。不是“原题未传入”证据，也没有答案被判错的证据。两个失败都在Provider响应阶段被拒绝，未进入合格题保存。

调用链为助手确认 → `run_generation` → `generate` → `Provider.complete` → 上游 `finish_reason=length` → `AppError(answer_truncated)` → OUTPUT_TRUNCATED。`result_message` 原先只细分 provider_error，却没有解释 failures中的OUTPUT_TRUNCATED，最终显示泛化的“没有题目通过质量检查”。

另有两个实际工程问题：

- 普通问答与出题复用Provider的 reasoning_effort=low，出题没有独立传输策略；隐藏思考和JSON正文可能共同消耗有限输出额度。历史账本没有思考/正文长度，因此不能断言这两次具体各消耗多少。
- Provider先抛截断异常再返回usage，生成账本因此丢失该次请求的实际usage。两次历史usage均为空，不能把空值当作0 token或0费用。
- 有已保存参考题时，通用AI生成曾优先套用旧1800上限，而无保存参考题时为3000；同一类生成的上限不一致。

证据：`storage/quality-audits/generation-rejection-20261019/existing-batches-readonly.json`。账本仅有响应hash/状态，没有截断响应正文，无法事后补判原响应的数学正确性；测试中的合成HTTP正文不冒充这两次真实响应。

## 二、生题修复

### 传输与预算

- `backend/chat/service.py`：新增仅用于结构化出题的Provider策略。对已支持这些参数的官方DeepSeek模型，发送 thinking.disabled 和 response_format=json_object，不再同时发送reasoning_effort；普通QA和Agent策略不变，其他兼容供应商不添加未经确认的参数。
- `backend/services/question_generation.py`：配置出题Provider启用上述策略；通用出题提示压缩重复解释和错误选项长篇分析，保留关键推导；不删除题干、答案、解析。记录prompt hash、compact-json-v2交付策略、原题存在标记。
- `personal_question_service.py`、个人题路由与助手服务统一：AI generated模式无论是否有已保存参考题，都使用现有3000上限，不无限提升预算。每题仍最多一次物理Provider请求，无隐藏自动重试。
- 通过请求级ContextVar捕获Provider观察到的usage、finish_reason、正文与思考字符数，异常也计入生成账本。只记录计数/hash，不记录思考正文、上游原始错误正文或凭据。

官方参数核对：[DeepSeek思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)、[Chat Completions参数](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)。这不是已经证明关闭隐藏思考后的真实数学质量通过；仍需独立的真实模型复测。

### 稳定诊断

新增 `backend/services/generation_diagnostics.py`，按真实记录输出 `diagnostics[{code,stage,message,index}]`，覆盖输出截断、JSON/结构异常、不完整、答案/解析冲突、题型不符、知识范围不符、无法独立验证、去重、原题变化、保存权限、网络、超时、预算停止及处理异常。

- 顶层SSE保留兼容的personal_generation_failed，额外附带诊断列表；不会将上游原始异常文本暴露给用户。
- JSON/Pydantic失败提取白名单校验标识，不保存失败输入或栈信息。
- 原有批次GET与聊天历史GET在读取时解释旧失败记录，不更新历史行。
- 新增前端 `GenerationFailureNotice.vue`，今日助手和问答使用同一诊断显示；刷新后仍有错误码/阶段与恢复说明。
- 失败批次重复读取/同一请求重放不重新调用模型；若主动提交新请求，明确说明会产生新调用。

质量门保持：截断内容不尝试拼成完整题、不保存；错误答案和解析冲突继续拒绝；不把REVIEW/UNSUPPORTED改成PASS。通用节点的既有REFERENCE_SAVED仍只是结构检查后的个人参考练习，不是独立正确性认证、不获得公共正式题或毕业证据。

## 三、会话隔离实际现状与修复

只读会话审计见 `existing-sessions-readonly.json`：

- 当天助手 `3995be84-91e0-4a0d-9dd7-e4076f15697a` 为purpose=study、surface=study；其他日期的今日助手同样是study。
- 独立问答为purpose=qa、surface=chat；用户主动深入问答的交接记录带qa_handoff，属于真正QA。
- `d1e089c8-df6d-45de-99bd-20f4433a4141`、`97c99c06-8969-42ca-824f-ca8526bca1f5` 两条出题标题QA来自上一轮浏览器探测，不是今日助手把自己的会话ID改成QA。这是此前验收留下的真实聊天记录，未删除、未改归属。

当前代码原本已排除study，不能虚构为“完全没有purpose字段”。本轮补齐两个真实隔离边界：

1. 服务端列表支持明确purpose查询，普通历史默认只允许qa/materials，而不是排除几个已知内部类型后放行其余类型。问答页的列表、首次恢复、路由恢复明确请求purpose=qa，不能被其他用途的会话干扰。
2. 今日助手原先直接信任localStorage里的会话ID并恢复任意该ID消息。现在必须通过服务端study查询核对用途和上海日期，错误/过期指针不再复用，原会话及消息不删除。随后需要新请求时仍创建独立study会话。

仍共享原ChatSession/ChatMessage表，不新增表或迁移。study恢复端点可明确查询study；问答列表不是前端拿到混合数据再隐藏。消息、卡、重试标识继续归属各自session。无法可靠归属的旧QA记录继续保留，不能仅凭标题或“出题”关键词删除。

## 四、修改文件

业务后端：

- `backend/chat/service.py`
- `backend/services/question_generation.py`
- `backend/services/personal_question_service.py`
- `backend/services/generation_diagnostics.py`（新增）
- `backend/services/learning_assistant_service.py`
- `backend/api/routes/personal_questions.py`
- `backend/api/routes/chat.py`

前端：

- `frontend/src/api/chat.ts`
- `frontend/src/api/personalQuestions.ts`
- `frontend/src/components/GenerationFailureNotice.vue`（新增）
- `frontend/src/components/LearningTaskPanel.vue`
- `frontend/src/pages/ChatPage.vue`

测试与证据脚本：

- `tests/unit/test_generation_rejection_diagnostics.py`
- `tests/integration/test_generation_rejection_persistence.py`
- `tests/integration/test_chat_session_purpose_isolation.py`
- `tests/integration/generation_journey_backend.py`
- `frontend/src/api/personalQuestions.test.ts`
- `frontend/e2e/generation-turn-safety.spec.ts`
- `frontend/acceptance/generation-conversation-persistence.spec.ts`
- `frontend/playwright.generation.config.ts`
- `scripts/run_phase45e_test_cluster.py`
- `scripts/audit_generation_rejections.py`、`scripts/verify_live_generation_diagnostics.mjs`

## 五、实际测试结果

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 生成诊断、旧生成质量回归、Provider兼容、通用节点、原题上下文和确认恢复 | 105 passed，0 failed，18.11s；此轮在随后用途隔离修改之前 | `confirmed/pytest.log` |
| 隔离用途、拒绝持久化、确认重试和诊断回归 | 28 passed，0 failed，8.83s | `session-confirmed/pytest.log` |
| 最后真实API/PG隔离用途与拒绝持久化 | 7 passed，0 failed，4.69s | `verified-journeys/pytest.log` |
| Chrome＋实际前后端＋隔离PG：3条持久化旅程 | 3 passed，0 failed，15.0s | `verified-journeys/playwright.log` |
| 前端协议：午夜旧卡、两个入口失效卡恢复、中文公式刷新 | 5 passed，0 failed，6.4s | 本轮定向Playwright；截图/trace目录`protocol/browser-artifacts` |
| 前端API/助手回合单元测试 | 16 passed，0 failed，297ms | 本轮vitest实际输出 |
| 前端typecheck | 通过 | 本轮vue-tsc实际输出 |

以上有重复范围，不能相加宣称唯一测试总数；没有全量重跑。最终上述定向测试无新增skip。

浏览器3条旅程实际点击了：

1. 今日助手提出更难类似题 → 卡持久化 → 刷新恢复 → 问答列表无该study会话 → 问答新建并发送 → 与助手不同ID → 置顶 → 重命名 → 刷新恢复 → 返回今日助手旧卡仍在 → 删除测试QA而study不受影响。删除只发生在专用隔离测试库。
2. 相同真实用户措辞 → 截断测试Provider → 显示output_truncated及模型输出阶段 → 无预览 → 刷新诊断仍在。不是DeepSeek实测。
3. 请求变式 → 补充原题 → 明确确认节点 → 合格固定响应 → Question/QuestionVersion实际入库与预览 → 加入前0个PracticeItem → 点击确认后1个且版本正确 → 重复恢复不重复插入 → 扩充今日卷仍保留原题。

中间失败保留：初始类型不符夹具同时带非法选项，修正为合法但题型不符的响应以准确测试该分支；新建对话按钮定位改用真实title；新浏览器用例共享测试库需要显式新建对话而不是继承上个用例；并行测试5174代理复用冲突改为专用临时前端端口，并仅在测试环境精确允许这个Origin，没有关闭CSRF/来源检查。被中断的测试与Origin未配置时的403均未计入通过。

## 六、实际Windows运行与真实页面

核对旧PID34788的命令、manifest、workspace、8000监听一致，保存旧manifest和日志后，使用原项目`scripts/run-backend.cmd`安全重启，未操作其他进程、PostgreSQL或权限。

最终PID：**36400**，**127.0.0.1:8000**单监听。Python3.12：`C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe`。运行manifest：`tmp/dev-backend-manifests/runtime-6f2c233a777045e0ad16dac5ac1eea2d.json`。应用加载本地配置，安全核对模型deepseek-flash、官方Provider；未打印密钥。

实际5173/8000系统Chrome只读复验：

- 服务端study/qa查询ID无交集。
- 今日助手恢复现有真实失败批次，显示截断错误码、阶段和“不是已判定答案错误”；刷新仍正常。
- 实际问答侧栏与服务端QA列表数量一致，study会话不出现，刷新保持。
- 健康检查ok/database connected；pageerror为空；真实业务写入0，真实模型请求0。

证据：`storage/quality-audits/generation-rejection-20261019/live-readonly/result.json`，截图`actual-study-truncation-diagnostic.png`和`actual-qa-separate-history.png`。

## 七、剩余限制与结论

- **会话用途隔离已在独立持久化用户旅程及实际页面中验证。** 不会自动删除既有QA历史，包括旧验收记录和用户主动深入问答记录。
- **真实失败类型已确认，截断诊断、传输策略、预算一致性及账本修复已部署。** 但本轮未获新的付费金额预算，没有发送真实DeepSeek请求，不能宣称修复后的真实生成成功率或数学质量验收已通过。
- 历史截断响应正文/usage缺失不可逆，未伪造历史响应或费用。今后异常也保留usage与有限诊断。
- 关闭结构化出题的隐藏思考不是降低质量检查；真实模型可能仍产生错题或长输出，仍会被拒绝并解释原因。验证模型效果需要用户手动测试或另行明确预算后进行少量真实调用。
- 真实数据库本轮只读，没有写入聊天或学习记录、权限变更、迁移、题库导入或清理；所有新增/删除测试记录均在专用测试库，摘要确认测试集群已停止并移除，原集群未触及。
- 用户需要Ctrl+F5刷新，已保存的旧QA会话不会凭空消失。若仍出现异常，错误码和阶段可直接定位，不再需要反复猜测提示词。
