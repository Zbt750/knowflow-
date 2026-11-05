# 当前API契约基线：教程与后续前端优化的护栏

日期：2026-10-16。对象是**当前产品工作区**，不是旧实验或尚未完成的教学草稿。仅静态读源码及离线生成OpenAPI，未启动lifespan/HTTP服务器，未调用数据库或模型。

## 1. 基线身份与检查方式

- 当前FastAPI OpenAPI：54条路径，62个HTTP操作，80个组件Schema。
- 当前完整OpenAPI规范化SHA-256：c83c89f84a018d2d662e3d95590af9a42839973cc8b3ea7e3fd1cf0a428e6568
- frontend/openapi.json规范化SHA-256：bf825ad6e9bccdf47a1e63f38d0fdd3b00ec6243c959c4fbacaa688cb0a5ef64
- 规范化方法：json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))后UTF-8计算SHA-256。
- 离线获取方式：仅调用backend.app.create_app().openapi()；**不使用TestClient上下文、不进入lifespan**。本次还在获取进程内阻断socket连接，未发生网络/数据库连接。
- 快照不读取真实业务数据，不保存密钥；下面的default来自Schema的静态定义。
- 62个操作全部与路由源码AST对应。本文件附参数、请求/响应Schema、动态返回补充及SSE契约；不把OpenAPI未标出的字段误认作没有契约。

这是文档基线，不是本轮API运行验收；没有重新签发Core UX或真实模型通过结论。

## 2. 已发现的前端生成快照漂移

当前后端与frontend/openapi.json的路径、HTTP方法集合一致；但完整JSON有**20处Schema差异**，不是零差异。此处保留问题，不改业务代码、不刷新types.ts、不自动改前端。

| 位置 | 后端当前定义相对前端存档的差异 |
|---|---|
| AnswerSubmissionResponse | 新增question_version_id |
| AssistantRequest | 新增personal_generation_mode |
| CapabilityProfile | 新增graduation_progress |
| GeneratePlanRequest | 新增confirm_legacy_set_transition_ids |
| GraduationProgress / GraduationQuestionStatus | 新增2个Schema |
| KnowledgeNodeView | 新增graduation_set_binding_status |
| NodeAttemptView | 新增question_version_id |
| NodeQuestionView | trust默认值增加auto_review_current |
| PersonalGenerationRequest | 新增generation_mode |
| PlanItemView / PracticeItemAnswer | 各新增question_version_id |
| QuestionTrustView | 3处枚举范围扩展；新增auto_review_current/event_id/snapshot_sha256/version共4字段 |
| RecommendationItem | 新增requires_graduation_set_confirmation |

20指JSON差异路径，不是20个接口故障，也不能只看URL相同就宣称兼容全绿。上述变化主要是新增字段/枚举，但消费者是否兼容仍要看真实前端调用与类型。本轮不以静态差异推断实际运行失败。

教学以**当前后端源码和本基线**为准，不能盲用旧OpenAPI生成文件。未来获准进行类型同步时，应离线导出实际OpenAPI、检查差异、生成类型，再跑typecheck、相关单测与E2E。不能为让存档匹配而删掉后端已存在的版本/审核/题集字段。

## 3. 所有API操作索引

前端调用列相对于frontend/src/api；“相关页面”表示并非每个API都有独立client函数，不能为了凑覆盖虚构调用。完整参数边界和DTO字段在第8节。

| 方法 | URL | 路径/查询参数 | 请求体及Content-Type | 成功响应 | 当前后端入口 | 前端关联 |
|---|---|---|---|---|---|---|
| GET | /api/health | 无 | 无请求体 | 200 HealthResponse | backend/api/routes/health.py:49 · health | health.ts |
| POST | /api/chat/material-search/session | 无 | 无请求体 | 200 MaterialSearchSession | backend/api/routes/chat.py:19 · material_search_session | materialSearch.ts、chat.ts |
| PATCH | /api/chat/material-search/scope | 无 | application/json: MaterialSearchScope | 200 MaterialSearchSession | backend/api/routes/chat.py:25 · material_search_scope | materialSearch.ts、chat.ts |
| POST | /api/chat/deep-handoffs | 无 | application/json: DeepQARequest | 201 未显式约束（需看补充语义） | backend/api/routes/chat.py:45 · deep_handoff | chat.ts |
| POST | /api/chat/sessions/{session_id}/assistant:stream | path.session_id（必填）：string | application/json: AssistantRequest | 200 text/event-stream（实际路由；OpenAPI默认标注不完整） | backend/api/routes/chat.py:52 · learning_assistant | chat.ts |
| POST | /api/chat/sessions | 无 | application/json: CreateSessionRequest | 201 未显式约束（需看补充语义） | backend/api/routes/chat.py:125 · create_session | chat.ts |
| GET | /api/chat/sessions | query.mode：string 或 null | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/chat.py:143 · list_sessions | chat.ts |
| PATCH | /api/chat/sessions/{session_id} | path.session_id（必填）：string | application/json: RenameSessionRequest | 200 未显式约束（需看补充语义） | backend/api/routes/chat.py:175 · rename_session | chat.ts |
| DELETE | /api/chat/sessions/{session_id} | path.session_id（必填）：string | 无请求体 | 204 无响应体 | backend/api/routes/chat.py:183 · delete_session | chat.ts |
| GET | /api/chat/sessions/{session_id}/messages | path.session_id（必填）：string | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/chat.py:211 · list_messages | chat.ts |
| POST | /api/chat/sessions/{session_id}/answers | path.session_id（必填）：string | application/json: AskRequest | 201 未显式约束（需看补充语义） | backend/api/routes/chat.py:259 · ask | chat.ts |
| POST | /api/chat/sessions/{session_id}/answers:stream | path.session_id（必填）：string | application/json: AskRequest | 200 text/event-stream（实际路由；OpenAPI默认标注不完整） | backend/api/routes/chat.py:273 · ask_stream | chat.ts |
| POST | /api/chat/sessions/{session_id}/followup-candidates | path.session_id（必填）：string | application/json: FollowupCandidatesRequest 或 null | 200 未显式约束（需看补充语义） | backend/api/routes/chat.py:294 · followup_candidates | chat.ts |
| POST | /api/chat/sessions/{session_id}/mark-confused | path.session_id（必填）：string | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/chat.py:343 · mark_confused | chat.ts |
| GET | /api/question-availability | query.subject：string 或 null<br>query.kp_ids：string[]<br>query.exclude_kp_ids：string[]<br>query.exclude_question_ids：string[]<br>query.question_type：string 或 null<br>query.plan_id：string 或 null<br>query.limit：integer | 无请求体 | 200 QuestionAvailabilityView | backend/api/routes/study.py:106 · read_question_availability | study.ts／相关页面 |
| POST | /api/practice-items/{item_id}/recognize-work | path.item_id（必填）：string | multipart/form-data: Body_recognize_practice_work_api_practice_items__item_id__recognize_work_post | 200 RecognitionResponse | backend/api/routes/study.py:126 · recognize_practice_work | vision.ts |
| GET | /api/plans/today | 无 | 无请求体 | 200 TodaySetup 或 TodayActive | backend/api/routes/study.py:430 · read_today_plan | study.ts／相关页面 |
| POST | /api/plans/today/generate | 无 | application/json: GeneratePlanRequest | 201 TodayActive | backend/api/routes/study.py:444 · generate_today_plan | study.ts／相关页面 |
| GET | /api/plans/{plan_id}/items | path.plan_id（必填）：string | 无请求体 | 200 TodayActive | backend/api/routes/study.py:471 · read_plan_items | study.ts／相关页面 |
| POST | /api/plans/{plan_id}/questions | path.plan_id（必填）：string | application/json: AppendQuestionsRequest | 200 TodayActive | backend/api/routes/study.py:479 · append_plan_questions | study.ts／相关页面 |
| POST | /api/plans/today/exam-references | 无 | application/json: AppendExamReferencesRequest | 200 TodayActive | backend/api/routes/study.py:496 · append_today_exam_references | study.ts／相关页面 |
| GET | /api/practice-items/{item_id}/answer | path.item_id（必填）：string | 无请求体 | 200 PracticeItemAnswer | backend/api/routes/study.py:525 · read_practice_item_answer | study.ts／相关页面 |
| POST | /api/practice-items/{item_id}/answer-submissions | path.item_id（必填）：string | application/json: SubmitAnswerRequest | 200 AnswerSubmissionResponse | backend/api/routes/study.py:571 · submit_practice_answer | study.ts／相关页面 |
| GET | /api/practice-items/{item_id}/answer-submissions | path.item_id（必填）：string | 无请求体 | 200 AnswerSubmissionHistory | backend/api/routes/study.py:591 · read_practice_answer_history | study.ts／相关页面 |
| POST | /api/practice-items/{item_id}/process-reviews | path.item_id（必填）：string | application/json: ProcessReviewRequest | 200 ProcessReviewResponse | backend/api/routes/study.py:600 · review_practice_process | study.ts／相关页面 |
| GET | /api/practice-items/{item_id}/process-reviews/latest | path.item_id（必填）：string | 无请求体 | 200 ProcessReviewResponse 或 null | backend/api/routes/study.py:619 · read_latest_process_review | study.ts／相关页面 |
| POST | /api/practice-items/{item_id}/answer-reveal | path.item_id（必填）：string | 无请求体 | 200 PracticeItemAnswer | backend/api/routes/study.py:627 · reveal_practice_answer | study.ts／相关页面 |
| POST | /api/practice-items/{item_id}/self-assessments | path.item_id（必填）：string | application/json: SubmitSelfAssessmentRequest | 200 AssessmentResponse | backend/api/routes/study.py:642 · submit_self_assessment | study.ts／相关页面 |
| GET | /api/knowledge/tree | 无 | 无请求体 | 200 KnowledgeTreeResponse | backend/api/routes/study.py:691 · read_knowledge_tree | study.ts／相关页面 |
| GET | /api/learning-review-needs | query.subject：string 或 null<br>query.limit：integer | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/study.py:764 · read_learning_review_needs | study.ts／相关页面 |
| GET | /api/knowledge/lessons/{code} | path.code（必填）：string | 无请求体 | 200 KnowledgeLessonResponse | backend/api/routes/study.py:771 · read_knowledge_lesson | study.ts／相关页面 |
| GET | /api/knowledge/{kp_id} | path.kp_id（必填）：string | 无请求体 | 200 KnowledgeNodeDetail | backend/api/routes/study.py:819 · read_knowledge_node | study.ts／相关页面 |
| POST | /api/knowledge/{kp_id}/self-assessment | path.kp_id（必填）：string | application/json: NodeSelfAssessmentRequest | 200 NodeSelfAssessmentResponse | backend/api/routes/study.py:962 · submit_node_self_assessment | study.ts／相关页面 |
| POST | /api/materials | query.title（必填）：string<br>query.source_type：string | multipart/form-data: Body_upload_material_api_materials_post | 201 MaterialUploadResponse | backend/api/routes/materials.py:96 · upload_material | materials.ts（搜索另见说明） |
| GET | /api/materials | query.limit：integer<br>query.offset：integer<br>query.status：string 或 null<br>query.source_type：string 或 null<br>query.q：string 或 null | 无请求体 | 200 MaterialListResponse | backend/api/routes/materials.py:141 · list_materials | materials.ts（搜索另见说明） |
| POST | /api/materials/search | 无 | application/json: SearchRequest | 200 SearchResponse | backend/api/routes/materials.py:163 · search_materials | materials.ts（搜索另见说明） |
| GET | /api/materials/{material_id} | path.material_id（必填）：string | 无请求体 | 200 MaterialDetail | backend/api/routes/materials.py:222 · get_material | materials.ts（搜索另见说明） |
| DELETE | /api/materials/{material_id} | path.material_id（必填）：string | 无请求体 | 204 无响应体 | backend/api/routes/materials.py:278 · delete_material | materials.ts（搜索另见说明） |
| GET | /api/materials/{material_id}/content | path.material_id（必填）：string | 无请求体 | 200 MaterialContentResponse | backend/api/routes/materials.py:235 · get_material_content | materials.ts（搜索另见说明） |
| GET | /api/materials/{material_id}/chunks | path.material_id（必填）：string<br>query.limit：integer<br>query.focus_chunk_id：string 或 null | 无请求体 | 200 MaterialChunkListResponse | backend/api/routes/materials.py:241 · list_material_chunks | materials.ts（搜索另见说明） |
| POST | /api/materials/{material_id}/reindex | path.material_id（必填）：string | 无请求体 | 202 MaterialJobView | backend/api/routes/materials.py:295 · reindex_material | materials.ts（搜索另见说明） |
| POST | /api/materials/{material_id}/retry | path.material_id（必填）：string | 无请求体 | 202 MaterialJobView | backend/api/routes/materials.py:307 · retry_material | materials.ts（搜索另见说明） |
| GET | /api/settings/vision | 无 | 无请求体 | 200 VisionSettingsView | backend/api/routes/settings.py:18 · read_vision_settings | settings.ts、vision.ts |
| PUT | /api/settings/vision | header.x-settings-token：string 或 null | application/json: VisionSettingsUpdate | 200 VisionSettingsView | backend/api/routes/settings.py:24 · update_vision_settings | settings.ts、vision.ts |
| GET | /api/settings/model | 无 | 无请求体 | 200 ModelSettingsView | backend/api/routes/settings.py:36 · read_model_settings | settings.ts、vision.ts |
| PUT | /api/settings/model | header.x-settings-token：string 或 null | application/json: ModelSettingsUpdate | 200 ModelSettingsView | backend/api/routes/settings.py:43 · update_model_settings | settings.ts、vision.ts |
| POST | /api/learning-tasks/{task_id}/confirm | path.task_id（必填）：string | application/json: ConfirmTask | 200 TaskView | backend/api/routes/learning_tasks.py:13 · confirm | learningTasks.ts |
| POST | /api/learning-tasks | 无 | application/json: CreateTask | 201 TaskView | backend/api/routes/learning_tasks.py:18 · create | learningTasks.ts |
| GET | /api/learning-tasks/{task_id} | path.task_id（必填）：string | 无请求体 | 200 TaskView | backend/api/routes/learning_tasks.py:23 · read | learningTasks.ts |
| PATCH | /api/learning-tasks/{task_id} | path.task_id（必填）：string | application/json: TaskInput | 200 TaskView | backend/api/routes/learning_tasks.py:28 · modify | learningTasks.ts |
| POST | /api/learning-tasks/{task_id}/cancel | path.task_id（必填）：string | 无请求体 | 200 TaskView | backend/api/routes/learning_tasks.py:33 · cancel | learningTasks.ts |
| POST | /api/learning-tasks/{task_id}/run | path.task_id（必填）：string | 无请求体 | 200 TaskView | backend/api/routes/learning_tasks.py:38 · run | learningTasks.ts |
| GET | /api/question-bank | query.scope：string<br>query.kp_id：string 或 null<br>query.search：string<br>query.include_hidden：boolean<br>query.limit：integer<br>query.offset：integer | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/personal_questions.py:18 · read_bank | personalQuestions.ts、chat.ts |
| POST | /api/personal-questions/generate | 无 | application/json: PersonalGenerationRequest | 200 未显式约束（需看补充语义） | backend/api/routes/personal_questions.py:25 · generate_questions | personalQuestions.ts、chat.ts |
| GET | /api/personal-questions/batches/{request_key} | path.request_key（必填）：string | 无请求体 | 200 未显式约束（需看补充语义） | backend/api/routes/personal_questions.py:40 · batch_status | personalQuestions.ts、chat.ts |
| PATCH | /api/personal-questions/{question_id}/visibility | path.question_id（必填）：string | application/json: HiddenRequest | 200 未显式约束（需看补充语义） | backend/api/routes/personal_questions.py:47 · hide | personalQuestions.ts、chat.ts |
| POST | /api/personal-questions/append | 无 | application/json: PersonalAppendRequest | 200 未显式约束（需看补充语义） | backend/api/routes/personal_questions.py:56 · append | personalQuestions.ts、chat.ts |
| GET | /api/practice-requests/{request_id} | path.request_id（必填）：string | 无请求体 | 200 PracticeRequestView | backend/api/routes/practice_requests.py:33 · read | practiceRequests.ts |
| GET | /api/practice-requests | query.source_conversation_id：string 或 null | 无请求体 | 200 PracticeRequestView[] | backend/api/routes/practice_requests.py:39 · listing | practiceRequests.ts |
| POST | /api/practice-requests/{request_id}/send | path.request_id（必填）：string | application/json: SendRequest | 200 PracticeRequestView | backend/api/routes/practice_requests.py:42 · send | practiceRequests.ts |
| POST | /api/practice-requests/{request_id}/decline | path.request_id（必填）：string | 无请求体 | 200 PracticeRequestView | backend/api/routes/practice_requests.py:45 · decline | practiceRequests.ts |
| POST | /api/practice-requests/{request_id}/plan | path.request_id（必填）：string | application/json: PlanRequest | 200 PracticeProposal | backend/api/routes/practice_requests.py:48 · plan | practiceRequests.ts |

注意：/api/materials/search是调试/检索API；当前MaterialSearch.vue的用户问答入口主要走资料会话＋answers:stream，不可把同名组件理解成只调用该搜索API。

## 4. 必须保持的实际业务契约

### 资料库

- POST /api/materials的title是**必填query参数**；source_type也是query参数，默认user。文件使用multipart/form-data的file字段。不是把title/source_type随意搬到JSON或form。
- 成功201返回MaterialUploadResponse：material、job_id、message都必填。只返回material、删除后台任务信息属于契约变化，不得作为“先简单实现”的兼容版本。
- GET /api/materials使用limit/offset分页，返回items、total、stats。前端不能用第一页items.length代替总库存，也不能偷偷改成page/page_size。
- /reindex和/retry返回202 MaterialJobView；不意味着索引已经ready。不把它改成同步完成200而不适配客户端。
- 资料详情与规范化正文/Chunk读取是不同接口，不能用服务器路径替代返回内容。
- SearchRequest包括query、top_k、candidate_k、material_ids、source_types、kp_ids。SearchHitView包括正文、出处、heading_path、kp_ids、score与可选名次；不能为了教程忽略kp_ids或额外改返回结构。
- 当前SearchResponse的公开字段中没有title_candidates、title_rank和rrf_score；内部追踪可以保留，但不能未经声明把内部调试结构当既有响应模型。

### 今日学习、作答和版本

- GET /api/plans/today返回TodaySetup或TodayActive；读推荐/恢复不能偷偷创建新卷。
- POST /api/plans/today/generate才创建，成功201；请求包括selected_kp_ids、budget与confirm_legacy_set_transition_ids。
- 作答使用/api/practice-items/{item_id}/answer-submissions，保留idempotency_key、expected_previous_attempt_id及支持的输入字段；不能改成另一套submit-answer协议。
- GET /answer为读取；POST /answer-reveal表示查看解析/答案的辅助行为。后续前端不能把有证据语义的POST改成普通GET。
- question_version_id不可为简化前端而删掉；历史PracticeItem/Attempt使用绑定版本。
- 自评、辅助正确、独立正确、毕业事实含义不变；界面不能自行计算或改写毕业结论。

### Agent与练习需求

- /learning-tasks创建请求使用goal、budget_minutes、mode、session_id、current_plan_id；budget_minutes严格整数5–240。
- 返回TaskView，不把task_id改成id；status保留created/running/ready/needs_info/answered/failed/cancelled。
- confirm必须提交64位小写十六进制draft_version；不能改为只有一个confirmed=true布尔值。
- run、confirm、cancel、modify各有真实接口。生成草案不等于确认，不得在前端收到planner事件后自动发confirm。
- practice-requests的send和plan有独立语义，前者source_conversation_id、后者study_session_id；不能把两次用户交接/确认合并为自动写入。
- 普通题目库存与个人AI生题分开。生成接口可能产生收费调用，读取页面或教程脚本不能自动触发。

### 无显式response_model的路由补充

当前部分路由使用动态dict。OpenAPI中的空schema不是允许任意破坏响应：

| 路由族 | 源码/前端核对出的响应关键事实 |
|---|---|
| 创建会话 | session_id、title、mode、purpose、study_date、material_scope_ids；与重命名/列表返回不能强行假定字段完全相同 |
| 会话列表 | 数组；项至少session_id/title/mode/purpose/material_scope_ids；筛选掉空会话及专用日内会话的现有语义保留 |
| 重命名会话 | session_id/title/mode；不是新建会话 |
| 消息历史 | message_id、role、content、status、citations、matched_kp及可选study_context/planner/辅助信息；从实际历史恢复，不重发模型 |
| 同步answers | message_id、answer、status、response_duration_ms、matched_kp_id/matched_kp、citations、retrieval_mode、answer_source；该同步citations卡片字段比流式卡片少，不能擅自统一删改 |
| followup-candidates | candidates数组；无当前可信归因时为空；字段包括question_id/kp_id/stem/is_variant/practice_status |
| mark-confused | kp_id、reason_code、changes_mastery:false；弱信号不冒充毕业证据 |
| question-bank | 分页items/total等由bank_rows形成；scope为public或personal、include_hidden/limit/offset等见参数索引；不能混同个人与正式题 |
| 个人题隐藏 | id、hidden；不删除历史记录 |
| 个人题批次/生成/追加 | 动态结果保留batch_id/status/message/question_ids和实际适用的追加/失败字段；不能把requested_count当成功数。当前未逐个动态键形式化，基线不伪造固定Schema |

## 5. 错误与状态码

HTTP错误统一以backend/errors.py为准：

~~~json
{"error":{"code":"validation_failed","message":"validation failed","details":[{"field":"body.question","code":"missing","message":"不能为空"}]}}
~~~

- details为可选的安全字段错误数组，不回显原始输入/密钥。
- 422当前也经validation_error_handler转换成error信封，不能照前端某条旧注释认定始终是FastAPI原生detail数组。
- 前端client.ts按code/status处理，不能把自然语言message当稳定分支条件。
- 各业务错误的状态由AppError、STATUS_BY_CODE和路由显式status_code确定。OpenAPI全局列出400/401/403/404/405/409/422/500/503，不表示每个接口都会产生每种错误。
- 204没有JSON响应体，不能前端一律response.json()。
- 流式开始前的错误走HTTP错误；开始后的错误走SSE error。HTTP200不等于任务完成。
- 设置请求的loopback/Origin/Cross-Site限制属于契约安全条件，不能为方便新前端关闭。

## 6. SSE：OpenAPI之外必须单独保护的协议

两条POST地址：
- /api/chat/sessions/{session_id}/answers:stream：AskRequest。
- /api/chat/sessions/{session_id}/assistant:stream：AssistantRequest。

实际响应Content-Type为text/event-stream，Cache-Control:no-cache、X-Accel-Buffering:no。当前OpenAPI对这两条仍默认显示200 application/json空Schema，**以实际StreamingResponse及以下事件为准**，本轮仅记录而不修改路由装饰器。

帧来自encode_sse：

~~~text
event: delta
data: {"seq":1,"text":"回答的一部分"}

~~~

JSON使用UTF-8，当前帧间以空行分隔。前端必须增量解码、缓冲拆包/合包和最后尾帧；中止不是自动重发POST的理由。

| 事件 | 当前数据/处理约定 |
|---|---|
| route | assistant能力路由对象；含实际route.public_dict字段，不等于已创建计划 |
| meta | message_id；按分支可附retrieval_mode/retrieved_count/timing/capability/task_id/replayed等。不是每分支相同字段 |
| status | message等运行提示，不当作回答正文 |
| delta | text、通常seq；replace:true时替换而不是拼接，可能附recovering |
| citations | citations数组；卡片含label、chunk_id、material_id、material_title、heading_path、ordinal、preview |
| planner | TaskView，并可能有qa_handoff；展示草案/状态，不自动确认 |
| practice_request | 真实练习需求对象；前端保存id并走后续确认/交接 |
| personal_generation | 实际GenerationResult，区分成功、部分成功和失败 |
| information_source / web_sources | 来源提示/实际来源数组；不能假装全部来自用户资料 |
| done | message_id/answer/citations等终态数据；按分支还可有status/answer_source/matched_kp/usage/timings等，不能假定每支全有 |
| error | code/message，按分支可有retryable/message_id；结束失败，不改写成completed |

普通资料回答常见meta→delta*→citations→done，但assistant的路由/任务/生题分支不是固定同一顺序。不能为了新UI把所有分支强制改成同一事件序列。失败/预算停止/截断不能变成done成功。

## 7. 前端落点与变更门禁

- api/client.ts：相对/api、错误信封、JSON/form上传、取消；不计算毕业状态。
- api/chat.ts：streamChatAnswer的POST fetch流读取及会话API。
- api/materials.ts、materialSearch.ts：资料接口、范围与日内会话。
- api/study.ts：今日学习、提交、解析、自评与知识树。
- api/learningTasks.ts、practiceRequests.ts：草案/版本确认、用户交接。
- api/personalQuestions.ts：归属、隐藏、追加；生成链另有assistant入口。
- api/vision.ts、settings.ts、health.ts：对应辅助入口，不为教程新增收费调用。
- 页面对应ChatPage.vue、MaterialsPage.vue、MaterialSearch.vue、StudyPage.vue、LearningTaskPanel.vue等，以当前调用为准。

每章必须标“本节是否修改API契约：否/是”，默认否。若是，先标[API CONTRACT CHANGE]，同时维护后端、OpenAPI、前端API/类型、相关单测、E2E与教程迁移说明；本轮并未批准任何变更。

## 8. DTO字段快照

以下为当前80个Schema的结构快照：去除展示用title/description/examples，保留字段名、类型、required、默认、枚举、边界、额外字段策略与引用。它是护栏附录，不是让学生逐行背诵。

<details>
<summary>AnswerSubmissionHistory</summary>

~~~json
{
  "properties": {
    "practice_item_id": {
      "type": "string",
      "format": "uuid"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/AnswerSubmissionResponse"
      },
      "type": "array"
    },
    "legacy_self_report_count": {
      "type": "integer",
      "default": 0
    }
  },
  "type": "object",
  "required": [
    "practice_item_id",
    "items"
  ]
}
~~~

</details>

<details>
<summary>AnswerSubmissionResponse</summary>

~~~json
{
  "properties": {
    "attempt_id": {
      "type": "string",
      "format": "uuid"
    },
    "practice_item_id": {
      "type": "string",
      "format": "uuid"
    },
    "question_version_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "result": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    },
    "method": {
      "type": "string"
    },
    "assisted": {
      "type": "boolean"
    },
    "submitted_at": {
      "type": "string"
    },
    "raw_answer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "selected_option": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "confidence": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "assessment_basis": {
      "type": "string",
      "default": "legacy_self_reported"
    },
    "mastery_assessment_basis": {
      "type": "string",
      "default": "legacy_self_reported"
    },
    "state": {
      "type": "string",
      "default": "unseen"
    },
    "mastery_reason": {
      "type": "string",
      "default": "answer_recorded_only"
    },
    "effective_confirmation_count": {
      "type": "integer",
      "default": 0
    },
    "basis_changed": {
      "type": "boolean",
      "default": false
    },
    "attempt_number": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "previous_attempt_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "sequence_category": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "first_independent_correct",
            "self_corrected",
            "correct_after_ungraded",
            "hint_assisted_correct",
            "solution_assisted_correct",
            "process_review_assisted_correct",
            "repeat_correct",
            "independent_retest_correct",
            "independent_correct_history_unknown",
            "low_confidence_correct",
            "incorrect",
            "unable_to_grade",
            "ai_consistent_correct_nonconfirming",
            "ai_consistent_wrong_nonconfirming"
          ]
        },
        {
          "type": "null"
        }
      ]
    },
    "assistance_level": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "none",
            "hint_1",
            "hint_2",
            "process_review",
            "solution"
          ]
        },
        {
          "type": "null"
        }
      ]
    },
    "can_retry": {
      "type": "boolean",
      "default": false
    },
    "reference_result": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "right",
            "wrong",
            "unknown"
          ]
        },
        {
          "type": "null"
        }
      ]
    },
    "feedback_notice": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "attempt_id",
    "practice_item_id",
    "result",
    "reason",
    "method",
    "assisted",
    "submitted_at"
  ]
}
~~~

</details>

<details>
<summary>AppendExamReferencesRequest</summary>

~~~json
{
  "properties": {
    "reference_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "minItems": 1
    }
  },
  "type": "object",
  "required": [
    "reference_ids"
  ]
}
~~~

</details>

<details>
<summary>AppendQuestionsRequest</summary>

~~~json
{
  "properties": {
    "question_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "minItems": 1
    }
  },
  "type": "object",
  "required": [
    "question_ids"
  ]
}
~~~

</details>

<details>
<summary>AskRequest</summary>

~~~json
{
  "properties": {
    "question": {
      "type": "string",
      "maxLength": 4000,
      "minLength": 1
    }
  },
  "type": "object",
  "required": [
    "question"
  ]
}
~~~

</details>

<details>
<summary>AssessmentResponse</summary>

~~~json
{
  "properties": {
    "practice_item_id": {
      "type": "string",
      "format": "uuid"
    },
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "state": {
      "type": "string"
    },
    "reason_code": {
      "type": "string"
    },
    "effective_confirmation_count": {
      "type": "integer"
    },
    "manual_credit_count": {
      "type": "integer"
    },
    "next_review_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "practice_item_id",
    "kp_id",
    "state",
    "reason_code",
    "effective_confirmation_count",
    "manual_credit_count"
  ]
}
~~~

</details>

<details>
<summary>AssistantRequest</summary>

~~~json
{
  "properties": {
    "question": {
      "type": "string",
      "maxLength": 4000,
      "minLength": 1
    },
    "study_context": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/StudyContext"
        },
        {
          "type": "null"
        }
      ]
    },
    "qa_action": {
      "type": "string",
      "enum": [
        "auto",
        "hint_1",
        "hint_2",
        "solution",
        "process_review"
      ],
      "default": "auto"
    },
    "request_key": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "retry_of_message_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "current_work": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4000
        },
        {
          "type": "null"
        }
      ]
    },
    "personal_generation_mode": {
      "type": "string",
      "enum": [
        "ai_generated",
        "ai_enhanced",
        "deterministic_fast"
      ],
      "default": "ai_generated"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "question"
  ]
}
~~~

</details>

<details>
<summary>AvailabilityNode</summary>

~~~json
{
  "properties": {
    "kp_id": {
      "type": "string"
    },
    "code": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "subject": {
      "type": "string"
    },
    "path": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "active_question_count": {
      "type": "integer"
    },
    "practice_eligible_count": {
      "type": "integer"
    },
    "available_to_append_count": {
      "type": "integer"
    },
    "already_in_plan_count": {
      "type": "integer"
    },
    "previously_attempted_count": {
      "type": "integer"
    },
    "unused_count": {
      "type": "integer"
    },
    "reference_count": {
      "type": "integer"
    },
    "candidate_count": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "candidate_inventory_status": {
      "type": "string"
    },
    "blocking_reasons": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "question_provenance_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "answer_provenance_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "grading_capability_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "evidence_capability_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "evidence_pool_status": {
      "type": "string",
      "enum": [
        "SUFFICIENT",
        "INSUFFICIENT",
        "UNKNOWN"
      ],
      "default": "UNKNOWN"
    },
    "evidence_pool_reasons": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "verified_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "distinct_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "unattempted_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "variation_objective_question_count": {
      "type": "integer",
      "default": 0
    }
  },
  "type": "object",
  "required": [
    "kp_id",
    "code",
    "name",
    "subject",
    "path",
    "active_question_count",
    "practice_eligible_count",
    "available_to_append_count",
    "already_in_plan_count",
    "previously_attempted_count",
    "unused_count",
    "reference_count",
    "candidate_inventory_status"
  ]
}
~~~

</details>

<details>
<summary>Body_recognize_practice_work_api_practice_items__item_id__recognize_work_post</summary>

~~~json
{
  "properties": {
    "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream"
    },
    "consent": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "file"
  ]
}
~~~

</details>

<details>
<summary>Body_upload_material_api_materials_post</summary>

~~~json
{
  "properties": {
    "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream"
    }
  },
  "type": "object",
  "required": [
    "file"
  ]
}
~~~

</details>

<details>
<summary>CapabilityDimension</summary>

~~~json
{
  "properties": {
    "key": {
      "type": "string"
    },
    "label": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "not_verified",
        "limited_evidence",
        "independent_evidence",
        "needs_retest"
      ]
    },
    "status_label": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    },
    "evidence_scope": {
      "type": "string",
      "enum": [
        "final_answer",
        "process"
      ]
    },
    "online_question_count": {
      "type": "integer"
    },
    "reliable_grading_question_count": {
      "type": "integer"
    },
    "independent_question_count": {
      "type": "integer"
    },
    "independent_question_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array"
    },
    "pending_review_question_count": {
      "type": "integer"
    },
    "recent_attempt_count": {
      "type": "integer"
    },
    "recent_assisted_attempt_count": {
      "type": "integer"
    },
    "recent_ungraded_attempt_count": {
      "type": "integer"
    },
    "observed_skill_tags": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "type": "object",
  "required": [
    "key",
    "label",
    "status",
    "status_label",
    "reason",
    "evidence_scope",
    "online_question_count",
    "reliable_grading_question_count",
    "independent_question_count",
    "pending_review_question_count",
    "recent_attempt_count",
    "recent_assisted_attempt_count",
    "recent_ungraded_attempt_count"
  ]
}
~~~

</details>

<details>
<summary>CapabilityProfile</summary>

~~~json
{
  "properties": {
    "version": {
      "type": "string",
      "default": "capability-evidence-v1"
    },
    "mapping_version": {
      "type": "string",
      "default": "question-type-role-v1"
    },
    "dimensions": {
      "items": {
        "$ref": "#/components/schemas/CapabilityDimension"
      },
      "type": "array"
    },
    "history_truncated": {
      "type": "boolean",
      "default": false
    },
    "confirmation_lookup_truncated": {
      "type": "boolean",
      "default": false
    },
    "excluded_confirmation_count": {
      "type": "integer",
      "default": 0
    },
    "unmapped_pending_review_count": {
      "type": "integer",
      "default": 0
    },
    "learning_progress": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/LearningProgress"
        },
        {
          "type": "null"
        }
      ]
    },
    "post_graduation": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/PostGraduationPractice"
        },
        {
          "type": "null"
        }
      ]
    },
    "graduation_progress": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/GraduationProgress"
        },
        {
          "type": "null"
        }
      ]
    },
    "note": {
      "type": "string",
      "default": "按题型与学习角色描述当前证据，不代表全面掌握；最终答案正确不证明推导或程序过程正确。"
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>ChunkPreviewView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "ordinal": {
      "type": "integer"
    },
    "heading_path": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "char_count": {
      "type": "integer"
    },
    "preview": {
      "type": "string"
    },
    "kp_hint_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "id",
    "ordinal",
    "heading_path",
    "char_count",
    "preview"
  ]
}
~~~

</details>

<details>
<summary>ConfirmTask</summary>

~~~json
{
  "properties": {
    "draft_version": {
      "type": "string",
      "maxLength": 64,
      "minLength": 64,
      "pattern": "^[0-9a-f]+$"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "draft_version"
  ]
}
~~~

</details>

<details>
<summary>CreateSessionRequest</summary>

~~~json
{
  "properties": {
    "title": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "default": "新对话"
    },
    "mode": {
      "type": "string",
      "enum": [
        "builtin",
        "user"
      ],
      "default": "builtin"
    },
    "purpose": {
      "type": "string",
      "enum": [
        "qa",
        "materials",
        "study"
      ],
      "default": "qa"
    },
    "material_scope_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 8
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>CreateTask</summary>

~~~json
{
  "properties": {
    "goal": {
      "type": "string",
      "maxLength": 1200,
      "minLength": 2
    },
    "budget_minutes": {
      "type": "integer",
      "maximum": 240,
      "minimum": 5
    },
    "mode": {
      "type": "string",
      "const": "builtin",
      "default": "builtin"
    },
    "session_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "current_plan_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "goal",
    "budget_minutes"
  ]
}
~~~

</details>

<details>
<summary>DeepQARequest</summary>

~~~json
{
  "properties": {
    "source_session_id": {
      "type": "string",
      "format": "uuid"
    },
    "study_context": {
      "$ref": "#/components/schemas/StudyContext"
    },
    "learning_problem": {
      "type": "string",
      "maxLength": 1200,
      "minLength": 1
    },
    "request_key": {
      "type": "string",
      "format": "uuid"
    }
  },
  "type": "object",
  "required": [
    "source_session_id",
    "study_context",
    "learning_problem",
    "request_key"
  ]
}
~~~

</details>

<details>
<summary>ErrorBody</summary>

~~~json
{
  "properties": {
    "code": {
      "type": "string"
    },
    "message": {
      "type": "string"
    },
    "details": {
      "anyOf": [
        {
          "items": {
            "$ref": "#/components/schemas/ValidationDetail"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "code",
    "message"
  ]
}
~~~

</details>

<details>
<summary>ErrorResponse</summary>

~~~json
{
  "properties": {
    "error": {
      "$ref": "#/components/schemas/ErrorBody"
    }
  },
  "type": "object",
  "required": [
    "error"
  ]
}
~~~

</details>

<details>
<summary>ExamQuestionReferenceView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "subject": {
      "type": "string"
    },
    "year": {
      "type": "integer"
    },
    "question_number": {
      "type": "integer"
    },
    "topic_label": {
      "type": "string"
    },
    "source_topic_label": {
      "type": "string"
    },
    "question_source_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "topic_source_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "local_folder": {
      "type": "string"
    },
    "source_note": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "id",
    "subject",
    "year",
    "question_number",
    "topic_label",
    "source_topic_label",
    "local_folder",
    "source_note"
  ]
}
~~~

</details>

<details>
<summary>FollowupCandidatesRequest</summary>

~~~json
{
  "properties": {
    "message_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>GapItemView</summary>

~~~json
{
  "properties": {
    "key": {
      "type": "string"
    },
    "label": {
      "type": "string"
    },
    "current": {
      "type": "integer"
    },
    "required": {
      "type": "integer"
    },
    "satisfied": {
      "type": "boolean"
    }
  },
  "type": "object",
  "required": [
    "key",
    "label",
    "current",
    "required",
    "satisfied"
  ]
}
~~~

</details>

<details>
<summary>GeneratePlanRequest</summary>

~~~json
{
  "properties": {
    "selected_kp_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "minItems": 1
    },
    "confirm_legacy_set_transition_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array"
    },
    "budget": {
      "type": "string",
      "pattern": "^(light|standard|deep)$",
      "default": "standard"
    }
  },
  "type": "object",
  "required": [
    "selected_kp_ids"
  ]
}
~~~

</details>

<details>
<summary>GenerationTarget</summary>

~~~json
{
  "properties": {
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "question_type": {
      "type": "string",
      "enum": [
        "single_choice",
        "fill_blank"
      ],
      "default": "single_choice"
    },
    "count": {
      "type": "integer",
      "maximum": 5,
      "minimum": 1,
      "default": 3
    },
    "difficulty": {
      "type": "string",
      "enum": [
        "basic",
        "improved",
        "comprehensive"
      ],
      "default": "basic"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "kp_id"
  ]
}
~~~

</details>

<details>
<summary>GraduationProgress</summary>

~~~json
{
  "properties": {
    "version": {
      "type": "string",
      "const": "frozen_question_set_v1",
      "default": "frozen_question_set_v1"
    },
    "configured": {
      "type": "boolean",
      "default": false
    },
    "graduated": {
      "type": "boolean",
      "default": false
    },
    "graduated_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "completed_question_count": {
      "type": "integer",
      "default": 0
    },
    "required_question_count": {
      "type": "integer",
      "default": 0
    },
    "questions": {
      "items": {
        "$ref": "#/components/schemas/GraduationQuestionStatus"
      },
      "type": "array"
    },
    "note": {
      "type": "string",
      "default": "题目进度只汇总该节点冻结的公共正式题；新题和个人 AI 题不会自动加入。"
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>GraduationQuestionStatus</summary>

~~~json
{
  "properties": {
    "question_id": {
      "type": "string",
      "format": "uuid"
    },
    "ordinal": {
      "type": "integer"
    },
    "status": {
      "type": "string",
      "enum": [
        "NOT_STARTED",
        "IN_PROGRESS",
        "COMPLETED"
      ]
    }
  },
  "type": "object",
  "required": [
    "question_id",
    "ordinal",
    "status"
  ]
}
~~~

</details>

<details>
<summary>HealthResponse</summary>

~~~json
{
  "properties": {
    "status": {
      "type": "string"
    },
    "database": {
      "type": "string"
    },
    "environment": {
      "type": "string",
      "enum": [
        "dev",
        "test",
        "prod"
      ]
    },
    "retrieval": {
      "type": "string",
      "default": "unknown"
    },
    "retrieval_reason": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "worker": {
      "type": "string",
      "default": "unknown"
    },
    "llm_configured": {
      "type": "boolean",
      "default": false
    },
    "llm_model": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "status",
    "database",
    "environment"
  ]
}
~~~

</details>

<details>
<summary>HiddenRequest</summary>

~~~json
{
  "properties": {
    "hidden": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "hidden"
  ]
}
~~~

</details>

<details>
<summary>KnowledgeLessonResponse</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "code": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "subject": {
      "type": "string"
    },
    "is_assessable": {
      "type": "boolean"
    },
    "breadcrumbs": {
      "items": {
        "$ref": "#/components/schemas/LessonBreadcrumb"
      },
      "type": "array"
    },
    "markdown": {
      "type": "string"
    },
    "question_count": {
      "type": "integer"
    },
    "practice_eligible_question_count": {
      "type": "integer",
      "default": 0
    }
  },
  "type": "object",
  "required": [
    "id",
    "code",
    "name",
    "subject",
    "is_assessable",
    "breadcrumbs",
    "markdown",
    "question_count"
  ]
}
~~~

</details>

<details>
<summary>KnowledgeNodeDetail</summary>

~~~json
{
  "properties": {
    "node": {
      "$ref": "#/components/schemas/KnowledgeNodeView"
    },
    "questions": {
      "items": {
        "$ref": "#/components/schemas/NodeQuestionView"
      },
      "type": "array"
    },
    "attempts": {
      "items": {
        "$ref": "#/components/schemas/NodeAttemptView"
      },
      "type": "array"
    },
    "exam_references": {
      "items": {
        "$ref": "#/components/schemas/ExamQuestionReferenceView"
      },
      "type": "array",
      "default": []
    },
    "lesson_available": {
      "type": "boolean",
      "default": false
    },
    "materials_ready": {
      "type": "boolean",
      "default": false
    },
    "capability_profile": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/CapabilityProfile"
        },
        {
          "type": "null"
        }
      ]
    },
    "personal_questions": {
      "additionalProperties": true,
      "type": "object",
      "default": {}
    }
  },
  "type": "object",
  "required": [
    "node",
    "questions",
    "attempts"
  ]
}
~~~

</details>

<details>
<summary>KnowledgeNodeView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "code": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "subject": {
      "type": "string"
    },
    "ordinal": {
      "type": "integer"
    },
    "is_assessable": {
      "type": "boolean"
    },
    "is_reference_only": {
      "type": "boolean",
      "default": false
    },
    "online_question_count": {
      "type": "integer",
      "default": 0
    },
    "practice_eligible_question_count": {
      "type": "integer",
      "default": 0
    },
    "blocked_active_question_count": {
      "type": "integer",
      "default": 0
    },
    "evidence_pool_status": {
      "type": "string",
      "enum": [
        "SUFFICIENT",
        "INSUFFICIENT",
        "UNKNOWN"
      ],
      "default": "UNKNOWN"
    },
    "evidence_pool_reasons": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "verified_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "distinct_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "unattempted_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "variation_objective_question_count": {
      "type": "integer",
      "default": 0
    },
    "summary": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "post_graduation": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/PostGraduationPractice"
        },
        {
          "type": "null"
        }
      ]
    },
    "post_graduation_review_count": {
      "type": "integer",
      "default": 0
    },
    "learning_goal": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "state": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "assessment_basis": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "pending_review_count": {
      "type": "integer",
      "default": 0
    },
    "next_review_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "mastered_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "node_self_grade": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "manual_credit_count": {
      "type": "integer",
      "default": 0
    },
    "effective_confirmation_count": {
      "type": "integer",
      "default": 0
    },
    "has_real_variant": {
      "type": "boolean",
      "default": false
    },
    "first_confirmed_on": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "last_confirmed_on": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "day_span": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "gap_items": {
      "items": {
        "$ref": "#/components/schemas/GapItemView"
      },
      "type": "array",
      "default": []
    },
    "next_step": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "required_question_types": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "policy_version": {
      "type": "integer",
      "default": 1
    },
    "graduation_set_binding_status": {
      "type": "string",
      "enum": [
        "unstarted",
        "legacy_history_unbound",
        "bound"
      ],
      "default": "unstarted"
    },
    "required_question_origins": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "excluded_question_types": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "required_skill_tags": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "children": {
      "items": {
        "$ref": "#/components/schemas/KnowledgeNodeView"
      },
      "type": "array",
      "default": []
    }
  },
  "type": "object",
  "required": [
    "id",
    "code",
    "name",
    "subject",
    "ordinal",
    "is_assessable"
  ]
}
~~~

</details>

<details>
<summary>KnowledgeTreeResponse</summary>

~~~json
{
  "properties": {
    "nodes": {
      "items": {
        "$ref": "#/components/schemas/KnowledgeNodeView"
      },
      "type": "array"
    }
  },
  "type": "object",
  "required": [
    "nodes"
  ]
}
~~~

</details>

<details>
<summary>LearningProgress</summary>

~~~json
{
  "properties": {
    "version": {
      "type": "string",
      "const": "learning_progress_v1",
      "default": "learning_progress_v1"
    },
    "status": {
      "type": "string",
      "enum": [
        "NOT_STARTED",
        "PRACTICING",
        "NEEDS_CONSOLIDATION",
        "IMPROVING",
        "RETEST_RECOMMENDED",
        "STABLE_PRACTICE"
      ]
    },
    "label": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    },
    "reliability_note": {
      "type": "string"
    },
    "next_action": {
      "type": "string",
      "enum": [
        "read_lesson",
        "practice",
        "consolidate",
        "delayed_retest",
        "validate_with_other_questions",
        "spaced_review"
      ]
    },
    "next_step": {
      "type": "string"
    },
    "limitations": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "observed_attempt_count": {
      "type": "integer",
      "default": 0
    },
    "distinct_question_count": {
      "type": "integer",
      "default": 0
    },
    "assisted_correct_question_count": {
      "type": "integer",
      "default": 0
    },
    "reference_wrong_count": {
      "type": "integer",
      "default": 0
    },
    "reliable_wrong_count": {
      "type": "integer",
      "default": 0
    },
    "unknown_count": {
      "type": "integer",
      "default": 0
    },
    "history_truncated": {
      "type": "boolean",
      "default": false
    },
    "strict_graduation_unchanged": {
      "type": "boolean",
      "default": true
    }
  },
  "type": "object",
  "required": [
    "status",
    "label",
    "reason",
    "reliability_note",
    "next_action",
    "next_step"
  ]
}
~~~

</details>

<details>
<summary>LessonBreadcrumb</summary>

~~~json
{
  "properties": {
    "code": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "code",
    "name"
  ]
}
~~~

</details>

<details>
<summary>MaterialChunkListResponse</summary>

~~~json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/ChunkPreviewView"
      },
      "type": "array"
    },
    "total": {
      "type": "integer"
    }
  },
  "type": "object",
  "required": [
    "items",
    "total"
  ]
}
~~~

</details>

<details>
<summary>MaterialContentResponse</summary>

~~~json
{
  "properties": {
    "title": {
      "type": "string"
    },
    "text": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "title"
  ]
}
~~~

</details>

<details>
<summary>MaterialDetail</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "title": {
      "type": "string"
    },
    "source_type": {
      "type": "string"
    },
    "original_filename": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "status": {
      "type": "string"
    },
    "file_size": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "active_index_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "last_error_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "chunk_count": {
      "type": "integer",
      "default": 0
    },
    "latest_job": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/MaterialJobView"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "id",
    "title",
    "source_type",
    "status",
    "created_at",
    "updated_at"
  ]
}
~~~

</details>

<details>
<summary>MaterialJobView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "job_type": {
      "type": "string"
    },
    "status": {
      "type": "string"
    },
    "attempts": {
      "type": "integer"
    },
    "max_attempts": {
      "type": "integer"
    },
    "error_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "result_index_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "type": "object",
  "required": [
    "id",
    "job_type",
    "status",
    "attempts",
    "max_attempts",
    "created_at"
  ]
}
~~~

</details>

<details>
<summary>MaterialListResponse</summary>

~~~json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/MaterialView"
      },
      "type": "array"
    },
    "total": {
      "type": "integer"
    },
    "stats": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object"
    }
  },
  "type": "object",
  "required": [
    "items",
    "total",
    "stats"
  ]
}
~~~

</details>

<details>
<summary>MaterialSearchScope</summary>

~~~json
{
  "properties": {
    "session_id": {
      "type": "string",
      "format": "uuid"
    },
    "scope_mode": {
      "type": "string",
      "enum": [
        "all",
        "selected"
      ],
      "default": "all"
    },
    "selected_file_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 8
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "session_id"
  ]
}
~~~

</details>

<details>
<summary>MaterialSearchSession</summary>

~~~json
{
  "properties": {
    "session_id": {
      "type": "string",
      "format": "uuid"
    },
    "title": {
      "type": "string"
    },
    "mode": {
      "type": "string",
      "const": "user"
    },
    "purpose": {
      "type": "string",
      "const": "material_search"
    },
    "study_date": {
      "type": "string"
    },
    "scope_mode": {
      "type": "string",
      "enum": [
        "all",
        "selected"
      ]
    },
    "selected_file_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array"
    }
  },
  "type": "object",
  "required": [
    "session_id",
    "title",
    "mode",
    "purpose",
    "study_date",
    "scope_mode",
    "selected_file_ids"
  ]
}
~~~

</details>

<details>
<summary>MaterialUploadResponse</summary>

~~~json
{
  "properties": {
    "material": {
      "$ref": "#/components/schemas/MaterialView"
    },
    "job_id": {
      "type": "string",
      "format": "uuid"
    },
    "message": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "material",
    "job_id",
    "message"
  ]
}
~~~

</details>

<details>
<summary>MaterialView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "title": {
      "type": "string"
    },
    "source_type": {
      "type": "string"
    },
    "original_filename": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "status": {
      "type": "string"
    },
    "file_size": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "active_index_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "last_error_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "type": "object",
  "required": [
    "id",
    "title",
    "source_type",
    "status",
    "created_at",
    "updated_at"
  ]
}
~~~

</details>

<details>
<summary>ModelSettingsUpdate</summary>

~~~json
{
  "properties": {
    "base_url": {
      "type": "string",
      "maxLength": 500,
      "minLength": 1
    },
    "model": {
      "type": "string",
      "maxLength": 120,
      "minLength": 1
    },
    "api_key": {
      "anyOf": [
        {
          "type": "string",
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ]
    },
    "clear_key": {
      "type": "boolean",
      "default": false
    },
    "max_output_tokens": {
      "type": "integer",
      "maximum": 32768,
      "minimum": 256,
      "default": 4000
    },
    "timeout_seconds": {
      "type": "number",
      "maximum": 180,
      "minimum": 5,
      "default": 60
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "base_url",
    "model"
  ]
}
~~~

</details>

<details>
<summary>ModelSettingsView</summary>

~~~json
{
  "properties": {
    "base_url": {
      "type": "string"
    },
    "model": {
      "type": "string"
    },
    "key_configured": {
      "type": "boolean"
    },
    "max_output_tokens": {
      "type": "integer"
    },
    "timeout_seconds": {
      "type": "number"
    },
    "csrf_token": {
      "type": "string"
    },
    "storage_warning": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "base_url",
    "model",
    "key_configured",
    "max_output_tokens",
    "timeout_seconds",
    "csrf_token"
  ]
}
~~~

</details>

<details>
<summary>NodeAttemptView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "question_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_version_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "exam_reference_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_stem": {
      "type": "string"
    },
    "self_grade": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "objective_result": {
      "type": "string"
    },
    "result_state": {
      "type": "string"
    },
    "reason_code": {
      "type": "string"
    },
    "submitted_at": {
      "type": "string"
    },
    "raw_answer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "grading_evidence": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "id",
    "question_stem",
    "self_grade",
    "objective_result",
    "result_state",
    "reason_code",
    "submitted_at"
  ]
}
~~~

</details>

<details>
<summary>NodeQuestionView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "bank_scope": {
      "type": "string",
      "enum": [
        "public",
        "personal"
      ],
      "default": "public"
    },
    "question_type": {
      "type": "string"
    },
    "difficulty": {
      "type": "string"
    },
    "is_variant": {
      "type": "boolean"
    },
    "stem": {
      "type": "string"
    },
    "options": {
      "anyOf": [
        {
          "additionalProperties": {
            "type": "string"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "question_source": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/QuestionSourceView"
        },
        {
          "type": "null"
        }
      ]
    },
    "trust": {
      "$ref": "#/components/schemas/QuestionTrustView",
      "default": {
        "bank_scope": "public",
        "question_provenance": "legacy_unknown",
        "content_trust": "unreviewed",
        "source_status": "unknown",
        "answer_provenance": "unknown",
        "answer_reliability": "unknown",
        "mapping_status": "unknown",
        "source_attestation_current": false,
        "answer_attestation_current": false,
        "answer_verification_current": false,
        "auto_review_current": false,
        "practice_eligible": false,
        "grading_capability": "unsupported",
        "evidence_capability": "self_report_only",
        "blocking_reasons": [],
        "objective_feedback_eligible": false
      }
    }
  },
  "type": "object",
  "required": [
    "id",
    "question_type",
    "difficulty",
    "is_variant",
    "stem",
    "kp_id"
  ]
}
~~~

</details>

<details>
<summary>NodeSelfAssessmentRequest</summary>

~~~json
{
  "properties": {
    "self_grade": {
      "type": "string"
    },
    "idempotency_key": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "self_grade",
    "idempotency_key"
  ]
}
~~~

</details>

<details>
<summary>NodeSelfAssessmentResponse</summary>

~~~json
{
  "properties": {
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "state": {
      "type": "string"
    },
    "reason_code": {
      "type": "string"
    },
    "effective_confirmation_count": {
      "type": "integer"
    },
    "manual_credit_count": {
      "type": "integer"
    },
    "next_review_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "kp_id",
    "state",
    "reason_code",
    "effective_confirmation_count",
    "manual_credit_count"
  ]
}
~~~

</details>

<details>
<summary>PersonalAppendRequest</summary>

~~~json
{
  "properties": {
    "plan_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 5,
      "minItems": 1
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "question_ids"
  ]
}
~~~

</details>

<details>
<summary>PersonalGenerationRequest</summary>

~~~json
{
  "properties": {
    "request_key": {
      "type": "string",
      "format": "uuid"
    },
    "generation_mode": {
      "type": "string",
      "enum": [
        "ai_generated",
        "ai_enhanced",
        "deterministic_fast"
      ],
      "default": "ai_generated"
    },
    "targets": {
      "items": {
        "$ref": "#/components/schemas/GenerationTarget"
      },
      "type": "array",
      "maxItems": 5,
      "minItems": 1
    },
    "surface": {
      "type": "string",
      "enum": [
        "study",
        "chat",
        "knowledge"
      ],
      "default": "chat"
    },
    "plan_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "append_to_today": {
      "type": "boolean",
      "default": false
    },
    "reference_question_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_key",
    "targets"
  ]
}
~~~

</details>

<details>
<summary>PlanItemView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "ordinal": {
      "type": "integer"
    },
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "kp_name": {
      "type": "string"
    },
    "question_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_version_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_source": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/QuestionSourceView"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_trust": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/QuestionTrustView"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_type": {
      "type": "string"
    },
    "question_role": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": "basic"
    },
    "difficulty": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "stem": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "options": {
      "anyOf": [
        {
          "additionalProperties": {
            "type": "string"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "skill_tags": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "is_variant": {
      "type": "boolean",
      "default": false
    },
    "estimated_minutes": {
      "type": "integer",
      "default": 5
    },
    "completed": {
      "type": "boolean"
    },
    "completed_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "latest_self_grade": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "is_review": {
      "type": "boolean",
      "default": false
    },
    "is_external_reference": {
      "type": "boolean",
      "default": false
    },
    "exam_reference": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/ExamQuestionReferenceView"
        },
        {
          "type": "null"
        }
      ]
    },
    "answer_submission": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/AnswerSubmissionResponse"
        },
        {
          "type": "null"
        }
      ]
    },
    "answer_grading_method": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "id",
    "ordinal",
    "kp_id",
    "kp_name",
    "question_type",
    "completed"
  ]
}
~~~

</details>

<details>
<summary>PlanRequest</summary>

~~~json
{
  "properties": {
    "study_session_id": {
      "type": "string",
      "format": "uuid"
    }
  },
  "type": "object",
  "required": [
    "study_session_id"
  ]
}
~~~

</details>

<details>
<summary>PostGraduationPractice</summary>

~~~json
{
  "properties": {
    "version": {
      "type": "string",
      "const": "post-graduation-practice-v1",
      "default": "post-graduation-practice-v1"
    },
    "applicable": {
      "type": "boolean",
      "default": false
    },
    "status": {
      "type": "string",
      "enum": [
        "NOT_APPLICABLE",
        "INSUFFICIENT",
        "GOOD",
        "CONSOLIDATE",
        "REVIEW"
      ]
    },
    "label": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    },
    "next_action": {
      "type": "string"
    },
    "foundation_unchanged": {
      "type": "boolean",
      "default": true
    },
    "graduated_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "last_reliable_practice_at": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "observed_attempt_count": {
      "type": "integer",
      "default": 0
    },
    "reliable_attempt_count": {
      "type": "integer",
      "default": 0
    },
    "distinct_question_count": {
      "type": "integer",
      "default": 0
    },
    "independent_correct_count": {
      "type": "integer",
      "default": 0
    },
    "independent_wrong_count": {
      "type": "integer",
      "default": 0
    },
    "assisted_correct_count": {
      "type": "integer",
      "default": 0
    },
    "excluded_attempt_count": {
      "type": "integer",
      "default": 0
    },
    "history_truncated": {
      "type": "boolean",
      "default": false
    },
    "evidence_summary": {
      "type": "string",
      "default": ""
    },
    "limitations": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "type": "object",
  "required": [
    "status",
    "label",
    "reason",
    "next_action"
  ]
}
~~~

</details>

<details>
<summary>PracticeItemAnswer</summary>

~~~json
{
  "properties": {
    "practice_item_id": {
      "type": "string",
      "format": "uuid"
    },
    "question_id": {
      "type": "string",
      "format": "uuid"
    },
    "question_version_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "stem": {
      "type": "string"
    },
    "options": {
      "anyOf": [
        {
          "additionalProperties": {
            "type": "string"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "correct_answer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "explanation": {
      "type": "string"
    },
    "question_type": {
      "type": "string"
    },
    "grading_mode": {
      "type": "string"
    },
    "question_trust": {
      "$ref": "#/components/schemas/QuestionTrustView"
    },
    "answer_notice": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "practice_item_id",
    "question_id",
    "stem",
    "explanation",
    "question_type",
    "grading_mode",
    "question_trust",
    "answer_notice"
  ]
}
~~~

</details>

<details>
<summary>PracticeProposal</summary>

~~~json
{
  "properties": {
    "request": {
      "$ref": "#/components/schemas/PracticeRequestView"
    },
    "task": {
      "$ref": "#/components/schemas/TaskView"
    }
  },
  "type": "object",
  "required": [
    "request",
    "task"
  ]
}
~~~

</details>

<details>
<summary>PracticeRequestView</summary>

~~~json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "status": {
      "type": "string",
      "enum": [
        "draft",
        "pending",
        "planning",
        "proposed",
        "accepted",
        "declined",
        "expired",
        "failed"
      ]
    },
    "source_conversation_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "source_message_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "user_request": {
      "type": "string"
    },
    "details": {
      "additionalProperties": true,
      "type": "object"
    },
    "planner_task_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "daily_plan_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "error_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "expires_at": {
      "type": "string",
      "format": "date-time"
    },
    "handled_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "id",
    "status",
    "source_conversation_id",
    "source_message_id",
    "user_request",
    "details",
    "planner_task_id",
    "daily_plan_id",
    "error_code",
    "created_at",
    "expires_at",
    "handled_at"
  ]
}
~~~

</details>

<details>
<summary>ProcessReviewRequest</summary>

~~~json
{
  "properties": {
    "idempotency_key": {
      "type": "string",
      "maxLength": 100,
      "minLength": 8
    },
    "work_text": {
      "type": "string",
      "maxLength": 4000,
      "minLength": 10
    },
    "subjective_kind": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "concept",
            "algorithm"
          ]
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "idempotency_key",
    "work_text"
  ]
}
~~~

</details>

<details>
<summary>ProcessReviewResponse</summary>

~~~json
{
  "properties": {
    "review_id": {
      "type": "string",
      "format": "uuid"
    },
    "practice_item_id": {
      "type": "string",
      "format": "uuid"
    },
    "review_kind": {
      "type": "string",
      "enum": [
        "calculation",
        "proof",
        "concept",
        "algorithm"
      ]
    },
    "feedback": {
      "type": "string"
    },
    "reviewed_at": {
      "type": "string"
    },
    "changes_mastery": {
      "type": "boolean",
      "default": false
    },
    "is_final_grade": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "review_id",
    "practice_item_id",
    "review_kind",
    "feedback",
    "reviewed_at"
  ]
}
~~~

</details>

<details>
<summary>QuestionAvailabilityView</summary>

~~~json
{
  "properties": {
    "subject": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "scope_node_ids": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "excluded_node_ids": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "excluded_question_ids": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "question_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "current_plan_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "active_question_count": {
      "type": "integer"
    },
    "practice_eligible_count": {
      "type": "integer"
    },
    "available_to_append_count": {
      "type": "integer"
    },
    "already_in_plan_count": {
      "type": "integer"
    },
    "previously_attempted_count": {
      "type": "integer"
    },
    "unused_count": {
      "type": "integer"
    },
    "reference_count": {
      "type": "integer"
    },
    "candidate_count": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "candidate_inventory_status": {
      "type": "string"
    },
    "blocked_question_count": {
      "type": "integer"
    },
    "blocking_reasons": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "question_provenance_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "answer_provenance_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "grading_capability_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "evidence_capability_counts": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "evidence_pool_sufficient_node_count": {
      "type": "integer",
      "default": 0
    },
    "evidence_pool_insufficient_node_count": {
      "type": "integer",
      "default": 0
    },
    "evidence_pool_unknown_node_count": {
      "type": "integer",
      "default": 0
    },
    "eligible_nodes": {
      "items": {
        "$ref": "#/components/schemas/AvailabilityNode"
      },
      "type": "array",
      "default": []
    },
    "node_list_truncated": {
      "type": "boolean",
      "default": false
    },
    "inventory_note": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "active_question_count",
    "practice_eligible_count",
    "available_to_append_count",
    "already_in_plan_count",
    "previously_attempted_count",
    "unused_count",
    "reference_count",
    "candidate_inventory_status",
    "blocked_question_count",
    "inventory_note"
  ]
}
~~~

</details>

<details>
<summary>QuestionSourceView</summary>

~~~json
{
  "properties": {
    "source_type": {
      "type": "string",
      "enum": [
        "exam",
        "mock",
        "original",
        "unknown"
      ],
      "default": "unknown"
    },
    "year": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "question_number": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "paper_title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "subject": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "content_status": {
      "type": "string",
      "enum": [
        "reviewed",
        "source_transcribed",
        "unknown"
      ],
      "default": "unknown"
    },
    "edition": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>QuestionTrustView</summary>

~~~json
{
  "properties": {
    "bank_scope": {
      "type": "string",
      "default": "public"
    },
    "question_provenance": {
      "type": "string",
      "enum": [
        "real_exam",
        "trusted_practice",
        "ai_generated_practice",
        "legacy_unknown"
      ],
      "default": "legacy_unknown"
    },
    "content_trust": {
      "type": "string",
      "enum": [
        "unreviewed",
        "needs_review",
        "source_attested",
        "verified",
        "auto_verified"
      ],
      "default": "unreviewed"
    },
    "source_status": {
      "type": "string",
      "enum": [
        "verified",
        "traceable",
        "needs_review",
        "unknown",
        "not_applicable"
      ],
      "default": "unknown"
    },
    "answer_provenance": {
      "type": "string",
      "enum": [
        "verified_reference",
        "human_verified",
        "ai_generated",
        "server_generated",
        "legacy_transcription",
        "unknown",
        "auto_verified"
      ],
      "default": "unknown"
    },
    "answer_reliability": {
      "type": "string",
      "enum": [
        "verified",
        "ai_generated_consistent",
        "ai_disagreement",
        "model_generated",
        "unverified",
        "unknown"
      ],
      "default": "unknown"
    },
    "mapping_status": {
      "type": "string",
      "default": "unknown"
    },
    "source_attestation_current": {
      "type": "boolean",
      "default": false
    },
    "answer_attestation_current": {
      "type": "boolean",
      "default": false
    },
    "answer_verification_current": {
      "type": "boolean",
      "default": false
    },
    "answer_verification_type": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "verified_reference",
            "human_verified",
            "auto_verified"
          ]
        },
        {
          "type": "null"
        }
      ]
    },
    "answer_verification_event_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "auto_review_current": {
      "type": "boolean",
      "default": false
    },
    "auto_review_event_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "auto_review_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "auto_review_snapshot_sha256": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "practice_eligible": {
      "type": "boolean",
      "default": false
    },
    "grading_capability": {
      "type": "string",
      "enum": [
        "deterministic",
        "final_answer_limited",
        "process_review_only",
        "unsupported"
      ],
      "default": "unsupported"
    },
    "evidence_capability": {
      "type": "string",
      "default": "self_report_only"
    },
    "answer_comparison_method": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "verified_grading_method": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "blocking_reasons": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "teaching_use": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "objective_feedback_eligible": {
      "type": "boolean",
      "default": false
    },
    "presentation_label": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "explanation_label": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "teaching_rule_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object"
}
~~~

</details>

<details>
<summary>RecognitionResponse</summary>

~~~json
{
  "properties": {
    "text": {
      "type": "string",
      "maxLength": 4000
    },
    "model": {
      "type": "string"
    },
    "duration_ms": {
      "type": "integer"
    },
    "usage": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "requires_confirmation": {
      "type": "boolean",
      "default": true
    },
    "changes_mastery": {
      "type": "boolean",
      "default": false
    },
    "image_stored": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "text",
    "model",
    "duration_ms"
  ]
}
~~~

</details>

<details>
<summary>RecommendationItem</summary>

~~~json
{
  "properties": {
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "name": {
      "type": "string"
    },
    "state": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    },
    "next_step": {
      "type": "string",
      "default": ""
    },
    "missing_types": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "default": []
    },
    "requires_graduation_set_confirmation": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "kp_id",
    "name",
    "state",
    "reason"
  ]
}
~~~

</details>

<details>
<summary>RenameSessionRequest</summary>

~~~json
{
  "properties": {
    "title": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1
    }
  },
  "type": "object",
  "required": [
    "title"
  ]
}
~~~

</details>

<details>
<summary>SearchHitView</summary>

~~~json
{
  "properties": {
    "chunk_id": {
      "type": "string",
      "format": "uuid"
    },
    "material_id": {
      "type": "string",
      "format": "uuid"
    },
    "material_title": {
      "type": "string"
    },
    "source_type": {
      "type": "string"
    },
    "index_version": {
      "type": "string"
    },
    "ordinal": {
      "type": "integer"
    },
    "content": {
      "type": "string"
    },
    "heading_path": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "kp_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array"
    },
    "score": {
      "type": "number"
    },
    "vector_rank": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "keyword_rank": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "rerank_score": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "chunk_id",
    "material_id",
    "material_title",
    "source_type",
    "index_version",
    "ordinal",
    "content",
    "heading_path",
    "kp_ids",
    "score"
  ]
}
~~~

</details>

<details>
<summary>SearchRequest</summary>

~~~json
{
  "properties": {
    "query": {
      "type": "string",
      "maxLength": 500,
      "minLength": 1
    },
    "top_k": {
      "type": "integer",
      "maximum": 20,
      "minimum": 1,
      "default": 6
    },
    "candidate_k": {
      "type": "integer",
      "maximum": 50,
      "minimum": 1,
      "default": 20
    },
    "material_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string",
            "format": "uuid"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ]
    },
    "source_types": {
      "anyOf": [
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ]
    },
    "kp_ids": {
      "anyOf": [
        {
          "items": {
            "type": "string",
            "format": "uuid"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "query"
  ]
}
~~~

</details>

<details>
<summary>SearchResponse</summary>

~~~json
{
  "properties": {
    "query": {
      "type": "string"
    },
    "hits": {
      "items": {
        "$ref": "#/components/schemas/SearchHitView"
      },
      "type": "array"
    },
    "degraded": {
      "type": "boolean",
      "default": false
    },
    "degraded_reasons": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "vector_candidates": {
      "type": "integer",
      "default": 0
    },
    "keyword_candidates": {
      "type": "integer",
      "default": 0
    },
    "reranked": {
      "type": "boolean",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "query",
    "hits"
  ]
}
~~~

</details>

<details>
<summary>SendRequest</summary>

~~~json
{
  "properties": {
    "source_conversation_id": {
      "type": "string",
      "format": "uuid"
    }
  },
  "type": "object",
  "required": [
    "source_conversation_id"
  ]
}
~~~

</details>

<details>
<summary>StudyContext</summary>

~~~json
{
  "properties": {
    "version": {
      "type": "string",
      "const": "study-context-v1",
      "default": "study-context-v1"
    },
    "surface": {
      "type": "string",
      "enum": [
        "study",
        "chat",
        "knowledge",
        "materials"
      ],
      "default": "chat"
    },
    "subject": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 80
        },
        {
          "type": "null"
        }
      ]
    },
    "knowledge_node_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 8
    },
    "question_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "attempt_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "daily_plan_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "practice_item_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "material_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "chunk_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "conversation_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "task_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "origin": {
      "type": "string",
      "enum": [
        "navigation",
        "practice",
        "knowledge",
        "material",
        "conversation"
      ],
      "default": "conversation"
    },
    "generated_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "type": "object"
}
~~~

</details>

<details>
<summary>SubmitAnswerRequest</summary>

~~~json
{
  "properties": {
    "idempotency_key": {
      "type": "string",
      "maxLength": 100,
      "minLength": 8
    },
    "raw_answer": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4000
        },
        {
          "type": "null"
        }
      ]
    },
    "selected_option": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 8
        },
        {
          "type": "null"
        }
      ]
    },
    "confidence": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(certain|uncertain|guess|no_idea)$"
        },
        {
          "type": "null"
        }
      ]
    },
    "expected_previous_attempt_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "idempotency_key"
  ]
}
~~~

</details>

<details>
<summary>SubmitSelfAssessmentRequest</summary>

~~~json
{
  "properties": {
    "self_grade": {
      "type": "string",
      "pattern": "^(mastered|partial|not_mastered|skip)$"
    },
    "idempotency_key": {
      "type": "string",
      "minLength": 8
    },
    "raw_answer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "selected_option": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 8
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "self_grade",
    "idempotency_key"
  ]
}
~~~

</details>

<details>
<summary>TaskInput</summary>

~~~json
{
  "properties": {
    "goal": {
      "type": "string",
      "maxLength": 1200,
      "minLength": 2
    },
    "budget_minutes": {
      "type": "integer",
      "maximum": 240,
      "minimum": 5
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "goal",
    "budget_minutes"
  ]
}
~~~

</details>

<details>
<summary>TaskView</summary>

~~~json
{
  "properties": {
    "task_id": {
      "type": "string",
      "format": "uuid"
    },
    "session_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "goal": {
      "type": "string"
    },
    "budget_minutes": {
      "type": "integer"
    },
    "status": {
      "type": "string",
      "enum": [
        "created",
        "running",
        "ready",
        "needs_info",
        "answered",
        "failed",
        "cancelled"
      ]
    },
    "trace": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "draft": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "message": {
      "type": "string"
    },
    "error_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "metrics": {
      "additionalProperties": true,
      "type": "object"
    },
    "draft_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "type": "object",
  "required": [
    "task_id",
    "session_id",
    "goal",
    "budget_minutes",
    "status",
    "trace",
    "draft",
    "message",
    "error_code",
    "metrics"
  ]
}
~~~

</details>

<details>
<summary>TodayActive</summary>

~~~json
{
  "properties": {
    "status": {
      "type": "string"
    },
    "plan_id": {
      "type": "string",
      "format": "uuid"
    },
    "study_date": {
      "type": "string"
    },
    "completed_count": {
      "type": "integer"
    },
    "total_count": {
      "type": "integer"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/PlanItemView"
      },
      "type": "array"
    },
    "focus_item_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ]
    },
    "summary_kps": {
      "items": {
        "$ref": "#/components/schemas/TodaySummaryKp"
      },
      "type": "array"
    },
    "type_summary": {
      "additionalProperties": {
        "type": "integer"
      },
      "type": "object",
      "default": {}
    },
    "estimated_minutes": {
      "type": "integer",
      "default": 0
    },
    "remaining_minutes": {
      "type": "integer",
      "default": 0
    }
  },
  "type": "object",
  "required": [
    "status",
    "plan_id",
    "study_date",
    "completed_count",
    "total_count",
    "items",
    "summary_kps"
  ]
}
~~~

</details>

<details>
<summary>TodaySetup</summary>

~~~json
{
  "properties": {
    "status": {
      "type": "string",
      "default": "setup"
    },
    "study_date": {
      "type": "string"
    },
    "recommendations": {
      "items": {
        "$ref": "#/components/schemas/RecommendationItem"
      },
      "type": "array"
    }
  },
  "type": "object",
  "required": [
    "study_date",
    "recommendations"
  ]
}
~~~

</details>

<details>
<summary>TodaySummaryKp</summary>

~~~json
{
  "properties": {
    "kp_id": {
      "type": "string",
      "format": "uuid"
    },
    "name": {
      "type": "string"
    },
    "completed_count": {
      "type": "integer"
    },
    "total_count": {
      "type": "integer"
    }
  },
  "type": "object",
  "required": [
    "kp_id",
    "name",
    "completed_count",
    "total_count"
  ]
}
~~~

</details>

<details>
<summary>ValidationDetail</summary>

~~~json
{
  "properties": {
    "field": {
      "type": "string"
    },
    "code": {
      "type": "string"
    },
    "message": {
      "type": "string"
    }
  },
  "type": "object",
  "required": [
    "field",
    "code",
    "message"
  ]
}
~~~

</details>

<details>
<summary>VisionSettingsUpdate</summary>

~~~json
{
  "properties": {
    "base_url": {
      "type": "string",
      "maxLength": 500,
      "minLength": 1
    },
    "model": {
      "type": "string",
      "maxLength": 120,
      "minLength": 1
    },
    "api_key": {
      "anyOf": [
        {
          "type": "string",
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ]
    },
    "clear_key": {
      "type": "boolean",
      "default": false
    },
    "max_output_tokens": {
      "type": "integer",
      "maximum": 32768,
      "minimum": 256,
      "default": 4000
    },
    "timeout_seconds": {
      "type": "number",
      "maximum": 180,
      "minimum": 5,
      "default": 60
    },
    "reuse_chat_model": {
      "type": "boolean",
      "default": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "base_url",
    "model"
  ]
}
~~~

</details>

<details>
<summary>VisionSettingsView</summary>

~~~json
{
  "properties": {
    "base_url": {
      "type": "string"
    },
    "model": {
      "type": "string"
    },
    "key_configured": {
      "type": "boolean"
    },
    "max_output_tokens": {
      "type": "integer"
    },
    "timeout_seconds": {
      "type": "number"
    },
    "csrf_token": {
      "type": "string"
    },
    "storage_warning": {
      "type": "boolean",
      "default": false
    },
    "reuse_chat_model": {
      "type": "boolean"
    },
    "configured": {
      "type": "boolean"
    }
  },
  "type": "object",
  "required": [
    "base_url",
    "model",
    "key_configured",
    "max_output_tokens",
    "timeout_seconds",
    "csrf_token",
    "reuse_chat_model",
    "configured"
  ]
}
~~~

</details>

## 9. 来源指纹与本轮限制

下表是本轮用于契约核对的36份源码/已有存档指纹，非Git提交证明。重新生成时还应比较语义，不以hash不同自动认定破坏。

| 文件 | SHA-256 |
|---|---|
| backend/api/routes/chat.py | d061e4f7b62916e5eb4f7fe0a536c3da8234345b1fcf90a3261ebc474b9ada7c |
| backend/api/routes/health.py | 1df05e505d05a4812a7c6ec18790c3b17e99481967cff2534e876982115f2318 |
| backend/api/routes/learning_tasks.py | 400cfbffa8067a76f5021ae01d6146fecbfce660d677f5d4dd73477d033c5b14 |
| backend/api/routes/materials.py | 5f1fcf42376862a55eb88e32a213e4124d26fc229f8441b8d7c4eb995ff1692f |
| backend/api/routes/personal_questions.py | 6c6801a3fc1a559ea43bbcad0d2727134aae6f094f48b47b79cf150fd68c0128 |
| backend/api/routes/practice_requests.py | 99c5f25234e667109b2ec0ae9b0a8cf3398a6e4a475e6893fc92e1f369aa1b0f |
| backend/api/routes/settings.py | 6d62d6f93891fd991af24f46b62516bf27e9c8164b8582ff41a24f99a29050f4 |
| backend/api/routes/study.py | 36ba2892bee8f9ffe553254498bf6eb187d5ac863181794cd0bba1f759b493f9 |
| backend/api/routes/__init__.py | 23bc8246d2b28b656654d07b4cd15a67de5093f208a04699a2d0234c5d926d41 |
| backend/schemas/capability.py | 29af2027fadb5fd9238e92333ffcb1fbf2712a685bb58d654982f58fdd1635cc |
| backend/schemas/knowledge.py | dbe401e099377cfde3f5bbfdf415d327245fc742d90bdd15250f5f8f6cd5a7e5 |
| backend/schemas/learning_assistant.py | bd27d8be35fdde778458615485a565d22a841c9166fbdf2912e07df090094671 |
| backend/schemas/learning_task.py | 3e4360cbaf9f9d47bc3906720833c94e1c7328ea6f1d9fec1c2fec3f38316829 |
| backend/schemas/materials.py | fe12f9eb9aaa928f0c129875e0220ebc43cbf6f377ce364b840c71a6f0de7568 |
| backend/schemas/material_search.py | 48dd36a9d0934105f592b3d10c09ca72a85ef7ff610904c64df07c10ae05a6cb |
| backend/schemas/personal_questions.py | 52892e4f3b7814ceaebcadc926268281858426de5137200eb579556ed8ded398 |
| backend/schemas/practice.py | 377fc54c1b587676459649b9db36ca9ea0d32bea730ea34cc51772af473707ed |
| backend/schemas/question_source.py | 936eaf2b877564c46e35d3febc0fc306d3e528e31e7f6481d4fcd9c9ebc820cc |
| backend/schemas/question_trust.py | 7f77d2dd5813a932fe19f0356acffa6a624a71113c73e176f2dc724dc29f0e82 |
| backend/schemas/__init__.py | a45c954bb0eb2b3bedf253bb3dffb9ebac880fcbf0d5b5e8dc07d2dbc1d0758c |
| frontend/src/api/chat.ts | 0a08258145f4868bfd55e05d3e2d01936aa35027ab79044a81b7f44ba9bceecf |
| frontend/src/api/client.ts | 157aea0d59bebf2fa3f556a9259f2405d098fb75fb4637c5a50dbfe7918a814c |
| frontend/src/api/health.ts | 691ab4e309911162f0711e7c32c0a8d1951063a491cf6b8101f3bb3ad68c888a |
| frontend/src/api/learningTasks.ts | 7d78d2838ecc8aa3bef7b6c0d3edca32283a983057f442ef9bb806de0e093568 |
| frontend/src/api/materials.ts | 33baaae1660d5c22fc31d4dd65217cef36ea950184f7980fc27375bebe6b21fb |
| frontend/src/api/materialSearch.ts | 7cc965bead062369e571936f964bf7db507515926b7879ba7656a6da346868e3 |
| frontend/src/api/personalQuestions.ts | de1ea83ed587190f478c414a8c57425fcae8c8c27d67e57d8825f486a0fd3328 |
| frontend/src/api/practiceRequests.ts | b553694f7592acd54faa401f0a559988d9bfc993156ffd9442df0fccf1af2c14 |
| frontend/src/api/settings.ts | 2171c44089147820cbfa38695c9e3fb52b0165872d728e109ff8184b496522ad |
| frontend/src/api/study.ts | 36bc9f550f0a226e773c9df6323474a59bd89cbdf677964986e9e8221cd4ed96 |
| frontend/src/api/types.ts | f1acf970edab2765cbecd8c08cbcfcf841cc956f6e341acb6e72664c3c134452 |
| frontend/src/api/vision.ts | 87f36bcc470182f5d8ef6bc66d9989c11bce4912889b64d496cd8c439118360a |
| backend/errors.py | 8777707c7e05c91113699fd7469646f4274fbadaed72b85fabd8ff59e7cacb00 |
| backend/chat/service.py | e20782824bee9b0482b0482c24543d2c49bc21223d5104076dd5e8ba0f4a718f |
| backend/services/learning_assistant_service.py | 0bc8b8b25bc71dd13c992ca91170aa7ef872a4e0704ea26c72810724a7e7fce2 |
| frontend/openapi.json | cb9aac2ab524e30d614038ca7d10afab3385fa7444b2cc907b10d7e960f9265e |

本轮仅离线检查：未访问真实库/隔离库，未执行迁移、运行API、浏览器或真实AI验收。先前样章任务启动的专属59316集群已按正常流程关闭；先前迁移尝试连接超时，未成功执行，未将它计为验收通过。新样章草稿不纳入这份产品契约基线，也未发布为合格教程检查点。
