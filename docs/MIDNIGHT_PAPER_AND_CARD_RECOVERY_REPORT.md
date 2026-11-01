# 今日卷跨午夜与出题确认卡恢复修复

日期：2026-10-19。范围：现有卷的显式扩充、上海时区跨日、确认卡生命周期及实际 Windows 运行版本。不是题库审核或新的开发阶段。

## 1. 实际根因

1. `StudyPage.vue` 原先以 `status === setup` 挂载推荐知识点、范围选择和组卷表单。个人题首次加入会合法创建当天 `DailyPlan`，页面随即变为 active；虽然只有一道题，整套组卷入口却消失。这不是题目被覆盖，而是界面把“已有卷”错误等同于“不再需要组卷”。
2. `create_initial_plan` 原先拒绝任何已有的当天卷。仅恢复前端表单仍会遇到 409，因此需要显式的“扩充已有卷”分支，而不能删除旧卷或重新生成替换。
3. 浏览器可能持有昨天的 plan_id、每日助手会话和确认卡。跨日只替换助手会话、不清除确认标识，会把昨天的卡提交到今天的上下文。后端拒绝后，卡的失效状态原先未可靠持久化，历史恢复可能再次显示它。
4. 聊天创建会话与助手处理使用直接系统时钟，未与今日卷路由共用可注入的时间来源，导致跨午夜的请求与测试不能统一验证同一业务时刻。
5. 个人题生成批次保存的历史 plan_id 不能代表“已经加入今天的卷”；判断加入状态必须以当前卷实际成员为准。

## 2. 修改文件与行为

### 今日卷

- `backend/services/practice_service.py`：增加显式 `extend_existing`；与个人题追加共用事务级 advisory lock；保留既有卷和 ordinal，只在卷尾追加尚未存在的题；沿用原选题、审核与毕业策略。
- `backend/schemas/practice.py`：请求新增可选 `extend_existing=false`，旧调用的重复组卷保护不变。
- `backend/api/routes/study.py`：新增只读 `GET /api/plans/today/recommendations`；显式扩充通过现有 generate 接口完成；向昨日卷追加返回 `plan_not_today`，不把旧卷覆盖为今天。
- `backend/api/routes/personal_questions.py`、`backend/errors.py`：保留跨日错误的准确分类与恢复提示。
- `frontend/src/api/study.ts`：读取推荐视图和显式扩充参数。
- `frontend/src/pages/StudyPage.vue`：已有卷保留“追加练习题”，新增“按知识点扩充今日卷”；推荐范围需用户点击确认后追加，原题仍显示；窗口重新聚焦、页面激活及定时检查上海日期变化后重新读取今天。
- `frontend/src/product-theme.css`：扩充表单单列，不保留重复助手占位。
- `frontend/src/components/PersonalQuestionResult.vue`：使用实际当前卷成员判断加入状态，而不是沿用昨天批次的“已加入”。

### 确认卡与每日助手

- `backend/api/routes/chat.py`：会话创建和助手流式处理统一注入时间来源；历史不恢复 expired 卡。
- `backend/services/learning_assistant_service.py`：上下文空列表/缺省值归一；错误确认在回滚后将对应卡持久化为 expired；新请求可创建新卡；重放不复活失效卡。
- `backend/services/generation_conversation.py`：expired 不再算有效待确认请求。
- `frontend/src/components/LearningTaskPanel.vue`：跨日清除旧会话的确认标识；点击昨天卡不会发起生成；原要求留回输入框重新确认；失效确认不再形成循环重试。
- `frontend/src/pages/ChatPage.vue`：无效确认后恢复原要求并解除旧卡重试状态；补齐草稿恢复函数导入。

## 3. 针对性测试及真实执行结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 最终隔离 PostgreSQL/API：跨午夜、已有卷扩充、卡失效与重试 | 12 passed，0 failed，11.76s | `storage/quality-audits/midnight-final-confirmed-20261019/pytest.log` |
| 实际 Vue + 实际 API + 独立 PostgreSQL + 固定测试 Provider：保存、预览、明确加入、扩充、刷新、DB成员验证 | 1 passed，0 failed，21.5s | `storage/quality-audits/midnight-card-repair-20261019-v2/playwright.log` |
| 前端协议回归：跨午夜旧卡不提交、新卡恢复、已有卷扩充 | 最终 4 passed，0 failed，15.2s | `storage/quality-audits/midnight-final-ui-fixed-20261019/browser-artifacts/` |
| 前序相关界面协议回归 | 32 passed；之后新增午夜用例另行执行上述4项，不将其冒充整套重跑 | `storage/quality-audits/midnight-ui-20261019/browser-artifacts/` |
| 前端单元：草稿、学习上下文、个人题API、助手API | 最后执行4文件18 passed，0 failed，531ms | `npm run test:unit -- src/lib/composerDraft.test.ts src/lib/studyContext.test.ts src/api/personalQuestions.test.ts src/api/learningAssistant.test.ts` |
| 前端类型检查 | `npm run typecheck` 通过 | 本轮实际命令输出 |

新增/修改的测试：

- `tests/integration/test_midnight_plan_extension.py`：上海23:59生成、00:00加入；昨天与今天分卷；原个人题与版本保留；显式组卷追加并幂等；午夜会话日期与卡过期历史。
- `tests/integration/test_generation_card_expiry.py`：位置变化使卡持久失效；重复恢复不复活；新请求重确认；重复确认只调用一次测试Provider。
- `tests/integration/generation_journey_backend.py`、`frontend/acceptance/generation-conversation-persistence.spec.ts`：固定午夜时钟，真实持久化用户旅程。
- `frontend/e2e/generation-turn-safety.spec.ts`、`frontend/e2e/personal-question-bank.spec.ts`：实际组件点击、历史恢复、明确扩充。
- `scripts/verify_live_midnight_ui.mjs`：实际5173/8000页面复验，默认只读；确认卡验证需显式参数。

中间失败没有删除：首轮合法题夹具缺少 verified grading_config，补齐夹具后重跑；新增午夜用例暴露助手时钟不一致，修复后12项全绿；前端午夜测试原先让23:59:58在浏览器启动时自然越日，改为固定时钟后再明确推进至00:00，保留原断言。另一次命令误填不存在的测试文件，pytest未执行，未算作通过。

所有会生成题目/卷、提交业务写入的持久化回归使用自建测试 PostgreSQL（端口大于18000、专用测试库、隔离schema）。运行摘要记录原集群未触及、测试集群停止并移除。没有删除测试或新增skip。没有重跑全量后端/全站Playwright，以上不代表全量重新验收。

## 4. 实际 Windows 运行版本与浏览器复验

实际旧后端 PID17028 使用项目 Python3.12 和 `scripts/run_phase4_backend.py`，无自动重载，因此源文件修改不会自动生效。核对进程命令、manifest中的workspace、PID、module和8000监听一致后，保存日志再通过原有 `scripts/run-backend.cmd` 重启。中间 PID9440 在最后时钟修复后再次按同样方式安全重启。

最终后端 PID：**27172**。监听：**127.0.0.1:8000**，只有一个监听。Python：`C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe`。运行manifest：`tmp/dev-backend-manifests/runtime-5e8b08f301c34dd6a7d7c4697dc8698c.json`。前端5173使用本项目Vite源码。健康检查 `status=ok`、`database=connected`、`environment=dev`。

实际系统Chrome浏览器，不是静态效果图：

- 5173今日学习真实只有一道题时，打开“按知识点扩充今日卷”，看到推荐与知识范围选择，等待范围知识树实际加载。
- 刷新后入口仍可用。
- 真实卷前后均为 `8a8342ca-6cbd-4e85-8c3d-13185ccb3521`，日期2026-10-19，成员始终只有 `1b33ecb7-1fc9-4301-8a32-3ebbc9656302`。
- 最新只读复验证据：`storage/quality-audits/midnight-live-final-readonly-20261019-v2/live-browser-result.json`，errors空、writes空、model_requests=0；截图 `live-recommendation-extension.png`。
- 实际确认卡回归另见 `storage/quality-audits/midnight-live-20261019-v3/live-browser-result.json`：原要求生成卡、故意改变上下文拒绝旧卡、刷新仍expired、独立新要求产生新卡，共7项检查通过。此段是确认前置流程验证，未点击有效卡执行真实生成。

## 5. 数据与收费边界

- 真实DeepSeek请求：**0次**。配置可用与健康检查不等于真实模型质量验收。本轮未进行收费生成/回答。
- 最新午夜修复的实际页面复验为只读，未提交扩充、题目加入或答案；真实卷不变。
- 为完成上一条实际确认卡请求的浏览器复验，早期运行曾在真实应用写入测试聊天会话、用户/助手确认消息及卡expired元数据。首个探测因问答页自动恢复旧会话，在现有聊天中追加过一轮无模型确认交互；另有一次创建空测试会话后脚本失败。成功版本使用独立测试会话 `d1e089c8-df6d-45de-99bd-20f4433a4141`。这些记录保留，未删除或重置，不能把整轮称为“真实数据库零写入”。
- 未修改真实Question、QuestionVersion、PracticeItem、Attempt、LearningEvent或毕业事实；没有迁移、权限授权、题库导入、恢复或数据清理。

## 6. 用户验证与剩余边界

1. 浏览器Ctrl+F5刷新今日学习。
2. 原有题仍在；点击“按知识点扩充今日卷”。
3. 查看推荐、调整范围，再点击“确认扩充今日卷”。只有这一步才追加已有题库题目；原题不替换，重复相同选择不重复插入。
4. “追加练习题”继续可用。奶蛙生成与加入仍分离。
5. 午夜后页面在重新聚焦/激活或约15秒检查时读取新一天；过期的昨天plan_id不能追加到昨天。

已完成：问题根因修复、固定23:59/00:00隔离持久化回归、真实当前单题卷入口点击与刷新复验、实际后端更新生效。尚未执行：真实墙钟下再等一次午夜、真实DeepSeek生成质量验收、真实卷提交扩充。这些没有冒充通过；当前单题阻断组卷的界面问题已在实际浏览器验证解除。
